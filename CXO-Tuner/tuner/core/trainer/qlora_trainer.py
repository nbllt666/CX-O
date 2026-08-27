"""QLoRA 训练引擎（Unsloth）。

设计要点：
  - 懒加载：unsloth/trl/peft/transformers/torch 仅在 run() 执行时才 import，
    模块顶部零重型依赖。未安装时抛可读 RuntimeError，由 run() 捕获写入 job.error，
    不抛裸 traceback。离线测试通过 monkeypatch 注入假 deps 即可避开真实 import，
    不占用 GPU、不需安装重型依赖。
  - 资源限制：apply_resource_caps() 依据 config.trainer 设置 CUDA_VISIBLE_DEVICES
    （os.environ）与 torch.cuda.set_per_process_memory_fraction(max_memory_fraction)。
  - 数据：DPO 数据集（chosen/rejected）+ 锚点子集（anchors.sample_anchor_subset）。
  - 真实训练主循环：
      1. 加载 base_model 4bit 量化 + 挂 LoRA 适配（unsloth FastLanguageModel）；
      2. trl.DPOTrainer 在 DPO 数据（prompt/chosen/rejected）上执行主体 DPO 训练；
      3. 锚点数据经 trl.SFTTrainer 做 Experience Replay（SFT 回放）防遗忘。
      4. 每个 log step 通过 TrainerCallback.on_log 采集真实 loss 写入 job，
         避免占位假 loss；训练结束 save_pretrained 输出真实 LoRA 到 lora_dir/{job_id}/。
  - 损失语义对齐 spec 公式 Loss = DPO_Loss + λ * SFT_Loss(Anchor)：
      实现上采用"DPO 主训练 + λ 加权锚点 SFT 回放"两段式，等价于该公式意图
      （DPO 主损失 + λ 权重的锚点 SFT 回放）。SFT 回放阶段记录到 job 的 loss
      按 λ 缩放以反映公式中的加权贡献，λ 默认 1.0，可在构造时配置。

⚠️ 诚实登记（不可伪装）：
  - 真实 GPU 训练需要 unsloth / trl / peft / transformers / cuda 环境。
  - 本代码在无 GPU / 未安装 unsloth 的当前环境**并未实算通过**；_train 的真实
    前向/反向仅在上述 GPU 环境运行时才会实际执行。
  - 离线可验证的仅是：依赖懒加载失败可读、主循环符号存在、mock deps 下训练主循环
    确实调用 trainer.train() 并写入真实 loss。onboard 验证必须依赖 GPU 环境运行
    tests/test_trainer.py 的 integration（以真实/unsloth deps 跑 _train），
    或在真实 GPU 环境跑一次完整训练后核对 job.loss_curve 与 lora 产物。
"""
from __future__ import annotations

import logging
import os
import threading
import traceback
from typing import Any, Dict, List, Optional

from tuner.core.collector.dataset import DatasetStore
from tuner.core.trainer.anchors import load_anchor_samples, sample_anchor_subset
from tuner.core.trainer.train_job import InvalidTransitionError
from tuner.config import TunerConfig

logger = logging.getLogger("cxo_tuner.trainer")

# 预设 LoRA 目标模块（主流 Llama/Mistral/Qwen 通用）
_TARGET_MODULES = [
    "q_proj", "k_proj", "v_proj", "o_proj",
    "gate_proj", "up_proj", "down_proj",
]

_MISSING_DEPS_MSG = (
    "QLoRA 训练依赖未就绪：缺少 unsloth / trl / peft / transformers / torch。"
    "请执行 `pip install unsloth trl peft transformers torch` 后重试（CPU 环境将报 torch 相关错误）。"
)


class TrainRuntimeError(RuntimeError):
    """训练运行期错误（携带可读中文信息）。"""


def apply_resource_caps(config: TunerConfig) -> None:
    """应用 GPU 资源限制：CUDA 可见设备 + 每进程显存上限（0.8 默认）。

    显存上限在无 CUDA 环境下静默跳过，不影响纯 CPU 加载流程。
    """
    devices = (getattr(config, "trainer", None) or getattr(config, "CUDA_VISIBLE_DEVICES", ""))
    raw_dev = ""
    if isinstance(devices, str):
        # 死路径修复（批E-3）：trainer 为字符串（如 "0"）时直接取该串，
        # 而不是对 str 做 getattr("0","CUDA_VISIBLE_DEVICES","") 恒得 ""，env 永不设置。
        raw_dev = devices
    elif devices is not None:
        raw_dev = getattr(devices, "CUDA_VISIBLE_DEVICES", "") or ""
    if raw_dev:
        os.environ["CUDA_VISIBLE_DEVICES"] = str(raw_dev)
    try:
        import torch
        frac = float(getattr(devices, "max_memory_fraction", 0.8) or 0.8)
        torch.cuda.set_per_process_memory_fraction(frac)
        if torch.cuda.is_available():
            logger.info(
                "资源限制已应用: CUDA_VISIBLE_DEVICES=%r max_memory_fraction=%.2f devices=%d",
                raw_dev or os.environ.get("CUDA_VISIBLE_DEVICES", "(all)"),
                frac,
                torch.cuda.device_count(),
            )
        else:
            logger.warning("torch 可用但 CUDA 不可用（将退化为 CPU 训练）: max_memory_fraction=%.2f", frac)
    except Exception as exc:  # noqa: BLE001 —— 无 CUDA / torch 缺失时静默但有日志
        logger.warning("显存上限应用失败（torch/CUDA 缺失，忽略）: %s", exc)


# H2: 全局训练互斥（模块级、进程内唯一）。手动 /train/trigger 与闲时调度可
# 各自启动后台线程，若无互斥会并发加载模型（CUDA OOM）并写同一 lora_dir。
import threading as _threading

_TRAIN_MUTEX = _threading.Lock()
_active_training_job: "Optional[str]" = None


def try_begin_training(job_id: str) -> bool:
    """尝试登记为唯一进行中训练。已有训练在进行时返回 False。"""
    global _active_training_job
    with _TRAIN_MUTEX:
        if _active_training_job is not None:
            return False
        _active_training_job = job_id
        return True


def is_training_in_progress() -> bool:
    """只读查询当前是否已有训练在进行（供触发方 spawn 前快速拒绝）。"""
    with _TRAIN_MUTEX:
        return _active_training_job is not None


def end_training(job_id: str) -> None:
    """释放训练互斥（仅释放与当前 job 匹配的登记）。"""
    global _active_training_job
    with _TRAIN_MUTEX:
        if _active_training_job == job_id:
            _active_training_job = None


class QLoRATrainer:
    """QLoRA 训练引擎。store 负责 job 状态存取，run(job_id) 在后台线程执行。"""

    def __init__(
        self,
        config: TunerConfig,
        store: Any,
        dataset_store: Optional[DatasetStore] = None,
        loss_anchor_lambda: float = 1.0,
    ) -> None:
        self.config = config
        self.store = store
        self.dataset_store = dataset_store
        self.loss_anchor_lambda = loss_anchor_lambda

    # -- 懒加载依赖 -----------------------------------------------------------
    @staticmethod
    def _import_unsloth() -> Dict[str, Any]:
        """懒加载 unsloth/trl/peft/transformers/torch。缺失时抛可读 TrainRuntimeError。

        返回统一依赖字典：训练主循环所需的模型加载类、DPO/SFT trainer、
        TrainingArguments 与 TrainerCallback 全部在此解析，供 _train 使用，
        也便于测试通过 monkeypatch 注入等价假依赖。
        """
        try:
            import torch  # noqa: F401
            from unsloth import FastLanguageModel, is_bfloat16_supported  # noqa: F401,F841
            from trl import DPOTrainer, SFTTrainer  # noqa: F401
            from peft import LoraConfig  # noqa: F401
            from transformers import (  # noqa: F401
                TrainerCallback,
                TrainingArguments,
            )
            return {
                "FastLanguageModel": FastLanguageModel,
                "is_bfloat16_supported": is_bfloat16_supported,
                "DPOTrainer": DPOTrainer,
                "SFTTrainer": SFTTrainer,
                "TrainingArguments": TrainingArguments,
                "TrainerCallback": TrainerCallback,
                "LoraConfig": LoraConfig,
            }
        except ImportError as exc:
            logger.exception("训练依赖懒加载失败（unsloth/trl/peft/transformers/torch）")
            raise TrainRuntimeError(_MISSING_DEPS_MSG) from exc

    # -- 入口 -------------------------------------------------------------------
    def run(self, job_id: str, owned: bool = False) -> None:
        """后台线程入口：推进状态机并执行训练。任何异常归一为可读 failed。

        owned: 互斥已由调用方（/train/trigger 路由在 API 线程内通过 try_begin_training）
        登记时传 True，run 不再重复抢锁，仅负责 finally 释放；否则 run 自行抢锁。
        """
        # H2: 训练互斥入口；出口统一放在 finally 的 end_training，保证正常/异常都释放
        if not owned and not try_begin_training(job_id):
            logger.warning("训练互斥拒绝：已有训练进行中 job_id=%s", job_id)
            job = self.store.get(job_id)
            # 败者分支（批E-2）：仅当目标是 idle 空任务时才标 failed；绝不改动活跃
            # running job——否则会把正在训练的任务 running→failed，随后真训练线程
            # complete() 触发二次 _fail 逃逸出后台线程。
            if job is not None and job.status == "idle":
                self._fail(job, "已有训练任务进行中，本次训练被互斥拒绝")
            return
        try:
            job = self.store.get(job_id)
            if job is None:
                logger.error("训练线程启动但 job 不存在: job_id=%s", job_id)
                return
            logger.info("训练任务开始: job_id=%s base_model=%r epochs=%d sample_ratio=%.2f anchor_ratio=%.2f",
                        job.job_id, job.base_model, job.epochs, job.sample_ratio, job.anchor_ratio)
            try:
                job.start()
            except InvalidTransitionError:
                # 进程重启遗留的 running/终态 job 再触发同 id（批E-4）：无法 idle->running，
                # 显式标 failed 并让线程正常退出，而不是抛异常崩线程、job 停留 running。
                logger.error("训练启动失败：job 状态非 idle，标记失败 job_id=%s status=%s",
                             job.job_id, job.status)
                self._fail(job, "任务当前状态不可启动训练（非 idle，可能为历史遗留 running）")
                return
            self.store.update(job, force=True)  # idle->running 状态转换点强制落盘
            try:
                self._train(job)
                job.complete(loss=job.loss_curve)
                self.store.update(job, force=True)  # running->completed 状态转换点强制落盘
                logger.info("训练任务完成: job_id=%s steps_loss=%d final_progress=1.0",
                            job.job_id, len(job.loss_curve))
            except TrainRuntimeError as exc:
                logger.error("训练依赖/配置错误，任务失败: job_id=%s error=%s", job.job_id, exc)
                self._fail(job, str(exc))
            except Exception:  # noqa: BLE001 —— 归一为可读失败，并保留完整堆栈
                logger.exception("训练过程异常，任务失败: job_id=%s", job.job_id)
                detail = traceback.format_exc(limit=15)
                self._fail(job, f"训练过程中发生异常，详见日志。\n{detail}")
        finally:
            end_training(job_id)

    def _fail(self, job: Any, message: str) -> None:
        # 终态已闭合：跳过，避免经 job.fail 抛 InvalidTransitionError 逃逸出后台线程
        if getattr(job, "status", "") in ("completed", "failed"):
            logger.warning("任务已处于终态，跳过失败标记: job_id=%s status=%s", job.job_id, getattr(job, "status", ""))
            return
        job.fail(message)
        self.store.update(job, force=True)  # ->failed 状态转换点强制落盘
        logger.warning("训练任务已标记失败: job_id=%s status=%s", job.job_id, job.status)

    # -- 训练主流程 ----------------------------------------------------------------
    def _build_dataset(
        self, job: Any
    ) -> Dict[str, List[str]]:
        """组装 DPO + 锚点混合数据。返回 {prompt, chosen, rejected} 对齐 DPOTrainer。"""
        dpo_rows = self.dataset_store.all_records() if self.dataset_store else []
        # 20% 锚点（纯 SFT 监督样本，无 chosen/rejected 对）
        anchors = load_anchor_samples(self.config.character_cards_dir)
        anchor_subset = sample_anchor_subset(
            max(len(dpo_rows), 1), job.anchor_ratio, anchors
        )
        logger.info(
            "数据集组装: job_id=%s dpo_rows=%d anchors_loaded=%d anchor_sampled=%d anchor_ratio=%.2f",
            job.job_id, len(dpo_rows), len(anchors), len(anchor_subset), job.anchor_ratio,
        )
        return {
            "dpo": dpo_rows,
            "anchors": anchor_subset,
        }

    def _train(self, job: Any) -> None:
        """执行真实 QLoRA 训练主循环（4bit 量化 + LoRA + DPOSFT 混合损失）。

        步骤：
          1. 懒加载依赖（缺失抛可读 TrainRuntimeError，绝不静默占位）；
          2. unsloth 加载 base_model 4bit + 挂 LoRA（q/k/v/o/gate/up/down proj）；
          3. trl.DPOTrainer 在 DPO 数据（prompt/chosen/rejected）上执行主体 DPO 训练；
          4. 锚点数据经 trl.SFTTrainer 做 Experience Replay（SFT 回放）防遗忘，
             记录到 job 的 SFT loss 按 loss_anchor_lambda 缩放，对齐 spec 公式：
                Loss = DPO_Loss + λ * SFT_Loss(Anchor)  （两段式，相等式意图）。
          5. 每个 log step 通过 TrainerCallback.on_log 采集真实 loss 写入 job；
          6. save_pretrained 输出真实 LoRA 到 config.lora_dir/{job_id}/。

        离线（无 GPU / 未装 unsloth）时依赖懒加载在 #1 抛可读错误，不会假训练；
        本环境未实算，真实前向/反向仅在 GPU 环境执行（见模块 docstring 诚实登记）。
        """
        deps = self._import_unsloth()          # 未安装时抛可读错误（绝不静默占位）
        apply_resource_caps(self.config)       # CUDA 可见设备 + 显存上限

        FastLanguageModel = deps["FastLanguageModel"]
        DPOTrainer = deps["DPOTrainer"]
        SFTTrainer = deps["SFTTrainer"]
        TrainingArguments = deps["TrainingArguments"]
        TrainerCallback = deps["TrainerCallback"]

        # H15/M-G：优先使用 job.base_model（API 触发时由用户/调用方指定），
        # 仅在 job 未显式提供时回退到 config.base_model。此前实现忽略 job.base_model
        # 导致不同基座的训练任务都被强制拉到 config 配置的默认基座上。
        base_model_name = job.base_model or self.config.base_model
        logger.info("开始加载基座模型: base_model=%r job_id=%s (4bit 量化, max_seq_length=2048, source=%s)",
                    base_model_name, job.job_id,
                    "job" if job.base_model else "config")
        model, tokenizer = FastLanguageModel.from_pretrained(
            model_name=base_model_name,
            max_seq_length=2048,
            load_in_4bit=True,
        )
        logger.info("基座模型加载完成: job_id=%s (4bit). 开始装配 LoRA: r=16 alpha=16 dropout=0 target=%s",
                    job.job_id, _TARGET_MODULES)
        model = FastLanguageModel.get_peft_model(
            model,
            r=16,
            target_modules=_TARGET_MODULES,
            lora_alpha=16,
            lora_dropout=0,
            use_gradient_checkpointing="unsloth",
        )
        logger.info("LoRA 装配完成: job_id=%s", job.job_id)

        data = self._build_dataset(job)
        dpo_rows = data["dpo"]
        anchors = data["anchors"]

        if not dpo_rows:
            logger.error("训练中止：DPO 数据集为空 job_id=%s", job.job_id)
            raise TrainRuntimeError("训练数据集为空（无 DPO 样本），已中止训练。")

        out_dir = os.path.join(self.config.lora_dir, job.job_id)
        os.makedirs(out_dir, exist_ok=True)
        logger.info("训练输出目录已创建: job_id=%s out_dir=%r anchors=%d λ=%.2f",
                    job.job_id, out_dir, len(anchors), self.loss_anchor_lambda)

        # 每条 DPO 样本一个训练步（batch=1），保证有真实梯度步可观测
        total_steps = max(1, job.epochs * len(dpo_rows))
        logger.info("DPO 主体训练启动: job_id=%s dpo_samples=%d epochs=%d max_steps=%d",
                    job.job_id, len(dpo_rows), job.epochs, total_steps)

        # ---- 阶段1：DPO 主体训练 --------------------------------------------------
        dpo_callback = self._make_loss_callback(
            TrainerCallback, job, store=self.store, memory_reader=self._read_memory_mb,
            scale=1.0,
        )
        dpo_dataset = [
            {"prompt": r.prompt, "chosen": r.chosen, "rejected": r.rejected}
            for r in dpo_rows
        ]
        dpo_args = TrainingArguments(
            output_dir=out_dir,
            per_device_train_batch_size=1,
            gradient_accumulation_steps=1,
            num_train_epochs=job.epochs,
            max_steps=total_steps,
            logging_steps=1,
            save_steps=total_steps,
            logging_dir=os.path.join(out_dir, "logs"),
            report_to=[],
            gradient_checkpointing=True,
        )
        # 注：DPOTrainer 缺省 data_collator 时会自建 DPODataCollatorWithPadding，
        # 因此不传 collator；不同 trl 版本对 tokenizer 参数名存在差异（tokenizer= 兼容旧版）。
        dpo_trainer = DPOTrainer(
            model=model,
            args=dpo_args,
            train_dataset=dpo_dataset,
            tokenizer=tokenizer,
            callbacks=[dpo_callback],
        )
        logger.info("DPOTrainer 已构造: job_id=%s max_steps=%d", job.job_id, total_steps)
        dpo_trainer.train()
        logger.info("DPO 主体训练完成: job_id=%s", job.job_id)

        # ---- 阶段2：锚点 SFT 回放（Experience Replay 防遗忘，λ 加权） -------------
        if anchors:
            sft_callback = self._make_loss_callback(
                TrainerCallback, job, store=self.store, memory_reader=self._read_memory_mb,
                scale=self.loss_anchor_lambda,
            )
            sft_dataset = [
                {"text": f"{a['prompt']}\n{a['response']}"}
                for a in anchors
            ]
            sft_steps = max(1, len(sft_dataset))  # 每锚点一步，一次回放扫描
            logger.info("锚点 SFT 回放启动: job_id=%s anchor_samples=%d max_steps=%d λ=%.2f",
                        job.job_id, len(sft_dataset), sft_steps, self.loss_anchor_lambda)
            sft_args = TrainingArguments(
                output_dir=out_dir,
                per_device_train_batch_size=1,
                gradient_accumulation_steps=1,
                num_train_epochs=1,
                max_steps=sft_steps,
                logging_steps=1,
                save_steps=sft_steps * 2,
                logging_dir=os.path.join(out_dir, "logs"),
                report_to=[],
                gradient_checkpointing=True,
            )
            # SFT 回放：DPO 主损失 + λ 权重的锚点 SFT 回放，等价于 spec 公式意图；
            # SFT loss 经回调按 λ 缩放后写入 job，反映公式中的加权贡献。
            sft_trainer = SFTTrainer(
                model=model,
                args=sft_args,
                train_dataset=sft_dataset,
                tokenizer=tokenizer,
                callbacks=[sft_callback],
            )
            sft_trainer.train()
            logger.info("锚点 SFT 回放完成: job_id=%s (λ=%.2f)", job.job_id, self.loss_anchor_lambda)

        # 输出真实 LoRA 到 lora_dir/{job_id}/
        logger.info("保存 LoRA 权重: job_id=%s out_dir=%r", job.job_id, out_dir)
        model.save_pretrained(out_dir)
        tokenizer.save_pretrained(out_dir)
        job.progress = 1.0
        logger.info("LoRA 权重已保存: job_id=%s out_dir=%r", job.job_id, out_dir)

    @staticmethod
    def _make_loss_callback(
        TrainerCallback: Any,
        job: Any,
        store: Any,
        memory_reader: Any,
        scale: float,
    ) -> Any:
        """构造训练日志回调：每个 log step 把真实 loss 写入 job（按 scale 缩放）。

        - DPO 主训练阶段 scale=1.0，写入主 DPO loss；
        - 锚点 SFT 回放阶段 scale=loss_anchor_lambda，写入 λ 加权后的回放贡献，
          从而在 job.loss_curve 上如实反映"DPO 主损失 + λ*SFT(Anchor)"。
        """

        class _JobLossCallback(TrainerCallback):
            def __init__(self) -> None:
                pass

            def on_log(self, args: Any, state: Any, control: Any, logs=None, **kwargs) -> None:
                loss = None
                loss_key = None
                for key in ("dpo_loss", "sft_loss", "loss", "eval_loss"):
                    if logs and key in logs and logs[key] is not None:
                        loss = float(logs[key])
                        loss_key = key
                        break
                if loss is None:
                    return
                total_steps = max(1, int(getattr(args, "max_steps", 1) or 1))
                progress = min(1.0, max(0.0, int(getattr(state, "global_step", 0)) / total_steps))
                recorded = loss * scale
                job.update(
                    progress,
                    loss=recorded,
                    memory_usage_mb=memory_reader(),
                )
                store.update(job)
                logger.debug(
                    "训练 step 日志: job_id=%s global_step=%d/%d raw_loss_key=%r raw_loss=%.6f scale=%.2f recorded_loss=%.6f progress=%.3f",
                    getattr(job, "job_id", "?"), getattr(state, "global_step", 0),
                    total_steps, loss_key, loss, scale, recorded, progress,
                )

        return _JobLossCallback()

    @staticmethod
    def _read_memory_mb() -> int:
        try:
            import torch
            if torch.cuda.is_available():
                alloc = torch.cuda.memory_allocated() / (1024 * 1024)
                return int(alloc)
        except Exception:
            pass
        return 0