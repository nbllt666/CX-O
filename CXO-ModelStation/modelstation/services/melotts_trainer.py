"""
MeloTTS 微调训练器（子进程模式，与 sovits_svc_trainer.py 同构）

change-id: extend-modelstation-standalone-melotts-datasets（spec「MeloTTS 微调训练」）。

同构点（对照 sovits_svc_trainer.SoVITSSVCTrainer）：
- 单例：api 层经 get_trainer() 复用同一实例（本模块提供默认工厂）；
- _train_status 模块级 dict：task_id / status(idle|busy_starting|running|completed|
  failed|stopped) / progress / epoch / total_epochs / message；
- asyncio 后台监控任务解析子进程输出更新进度；stop 为 terminate→kill 链路；
- CWD 免疫：全部路径经 config 绝对值注入，子进程 cwd 固定为引擎 melo 目录
  （train.py / preprocess_text.py 依赖 CWD=engine_dir/melo 导入顶层模块，实码约束），
  数据/产物路径全部以绝对路径传入子进程。

MeloTTS 官方训练链路（engines/MeloTTS 实码结论，本 trainer 的调用依据）：
  1) melo/preprocess_text.py（click CLI）：
     输入 metadata 四列 `utt|spk|language|text`，BERT/音素化后输出七列
     `utt|spk|language|text|phones|tones|word2ph` cleaned 文件，并按
     --val-per-spk/--max-val-total 重切 train/val + 产出 config.json（spk2id 等）
     至 dirname(metadata)；本 trainer 以 --val-per-spk 0 --max-val-total 0
     让全部清洗结果进 train.list，再按 prep 的切分重分（保留 95/5 决定权）。
  2) melo/train.py（train.sh 经 torchrun 启动）：
     `train.py --c <config> --model <name>`；必需 env LOCAL_RANK（torchrun 注入；
     本 trainer 以等价单进程 env:// 注入 LOCAL_RANK/RANK/WORLD_SIZE/MASTER_*）；
     hps.model_dir 硬编码 `./logs/<model>`（相对 CWD）→ 产物 G_*.pth/D_*.pth
     落盘 engine_dir/melo/logs/<output_name>/，训练完成后由本 trainer 拷贝至
     models_dir/<output_name>/（spec 训练产物落盘约定）。
  3) 进度日志行：`Train Epoch: N [..%]` / `====> Epoch: N`（train.py 实码）。

训练互斥：与 sovits 共享 training_mutex 原语（同一时间仅一个训练任务）；
所有出口（监控收尾 / stop / start 异常）释放互斥（end_training 幂等）。

部署要求：单 worker（uvicorn --workers 1）。
GPU 依赖：MeloTTS preprocess_text.py 的 clean_text_bert 固定 cuda:0、train.py
强制 .cuda()——训练链路需 GPU 环境（未就绪时报错含 setup 指引）。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from modelstation.services.training_mutex import (
    TRAINING_MELOTTS,
    current_training,
    end_training,
    try_begin_training,
)

logger = logging.getLogger(__name__)

_OUTPUT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")

# 官方 preprocess_text.py 清洗步骤超时（秒）：BERT 逐条推理，长清单耗时显著
_PREPROCESS_SUBPROCESS_TIMEOUT = 3600.0
# 训练监控超时（秒）：训练通常耗时数小时，与 sovits trainer 对齐取 7 天
_TRAIN_MONITOR_TIMEOUT = 7 * 24 * 3600.0
_TRAIN_STOP_WAIT_TIMEOUT = 10.0
# melo 包导入试探超时（秒）（与 tools/setup_engines.py 校验一致）
_IMPORT_PROBE_TIMEOUT = 120.0

# 训练进度估算：完全解析不到 epoch 日志行时按已运行时长估算（每 epoch 估 60s，
# message 注明估算语义），progress 封顶 0.95（避免虚报完成）
_ESTIMATED_SECONDS_PER_EPOCH = 60.0
_ESTIMATE_INTERVAL_SECONDS = 30.0

# train.py 实码日志行格式（utils.get_logger 经 StreamHandler 输出）：
#   "Train Epoch: 12 [34%]"（logger.info）/ "====> Epoch: 12"（epoch 收尾）
_EPOCH_PATTERN = re.compile(r"(?:Train Epoch|====> Epoch):\s*(\d+)")


class MelottsEngineNotReadyError(RuntimeError):
    """MeloTTS 引擎未就绪（目录缺失 / melo 包不可导入）。message 含修复指引。"""


class TrainingInProgressError(RuntimeError):
    """训练互斥冲突（本地已在训练或跨类型占用）。attributes: current。"""

    def __init__(self, message: str, current: Optional[dict] = None):
        super().__init__(message)
        self.current = dict(current) if current else current_training()


def _now_iso() -> str:
    """本地时区 ISO8601 时间戳（秒级）"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _sanitize_output_name(name: str) -> str:
    """校验 output_name 仅由字母/数字/下划线/连字符组成，防止目录穿越。"""
    base = os.path.basename(name or "")
    if not base or not _OUTPUT_NAME_PATTERN.match(base):
        raise ValueError(
            f"Invalid output_name: {name!r}. "
            "Only letters, digits, underscore and hyphen are allowed and path separators are forbidden."
        )
    return base


def _pick_free_port() -> int:
    """挑选本机空闲端口（gloo init_method=env:// 的 MASTER_PORT）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


async def _wait_for_subprocess_exit(process: asyncio.subprocess.Process, timeout: float) -> bool:
    """等待子进程退出；超时则先 terminate 再 kill，返回是否主动 kill。"""
    try:
        await asyncio.wait_for(process.wait(), timeout=timeout)
        return False
    except asyncio.TimeoutError:
        logger.warning(f"Subprocess (pid={process.pid}) did not exit within {timeout}s; terminating")
        try:
            process.terminate()
        except ProcessLookupError:
            return True
        try:
            await asyncio.wait_for(process.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.error(f"Subprocess (pid={process.pid}) did not exit after terminate; killing")
            try:
                process.kill()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                pass
        return True


# ---------------------------------------------------------------------------
# 模块级训练状态（与 api/sovits_svc.py 的 _train_status 同形状）
# ---------------------------------------------------------------------------
_train_status: dict = {
    "task_id": None,
    "status": "idle",
    "progress": 0.0,
    "epoch": 0,
    "total_epochs": 0,
    "message": "",
}


def get_train_status() -> dict:
    """训练状态只读快照（API /status 消费入口）。"""
    return dict(_train_status)


def _update_train_status(**kwargs) -> None:
    """按白名单键更新模块级训练状态。"""
    for k, v in kwargs.items():
        if k in _train_status:
            _train_status[k] = v


def reset_train_status() -> None:
    """复位训练状态（测试专用）。"""
    _update_train_status(
        task_id=None, status="idle", progress=0.0, epoch=0, total_epochs=0, message=""
    )


class MeloTTSTrainer:
    """MeloTTS 子进程训练器（官方两步链路：preprocess_text.py → train.py）。"""

    def __init__(
        self,
        engine_dir: str,
        training_data_dir: str,
        models_dir: str,
        python_path: str = "python",
        language: str = "ZH",
        base_checkpoint: str = "",
    ):
        self._engine_dir = Path(engine_dir)
        self._training_data_dir = Path(training_data_dir)
        self._models_dir = Path(models_dir)
        self._python_path = python_path
        self._language = language
        self._base_checkpoint = base_checkpoint
        self._process: Optional[asyncio.subprocess.Process] = None
        self._monitor_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # 路径与就绪校验
    # ------------------------------------------------------------------
    @property
    def engine_dir(self) -> Path:
        return self._engine_dir

    @property
    def melo_dir(self) -> Path:
        """官方脚本工作目录（train.py / preprocess_text.py 的 CWD，实码约束）。"""
        return self._engine_dir / "melo"

    async def _probe_melo_import(self) -> None:
        """父进程试探 melo 包可导入（engines/MeloTTS 内执行 python -c "import melo"）。

        与 tools/setup_engines.py verify_melotts_import 同口径。
        Raises:
            MelottsEngineNotReadyError: 导入失败/超时（message 含依赖安装与 setup 指引）
        """
        args = [self._python_path, "-c", "import melo"]
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self._engine_dir),
            )
        except (OSError, ValueError) as exc:
            raise MelottsEngineNotReadyError(
                f"MeloTTS python 环境不可用（python_path={self._python_path!r}）: {exc}。"
                "请检查 config.melotts.python_path 或执行 tools/setup_engines.py --clone-melotts"
            )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=_IMPORT_PROBE_TIMEOUT
            )
        except asyncio.TimeoutError:
            await _wait_for_subprocess_exit(proc, _TRAIN_STOP_WAIT_TIMEOUT)
            raise MelottsEngineNotReadyError(
                "MeloTTS 导入校验超时（120s）；请先运行 tools/setup_engines.py 检查环境，"
                "或在 engines/MeloTTS 安装依赖（pip install -e .）"
            )
        if proc.returncode != 0:
            tail = (stderr or b"").decode("utf-8", errors="replace").strip().splitlines()
            last_err = tail[-1] if tail else "<无 stderr>"
            raise MelottsEngineNotReadyError(
                f"MeloTTS 训练管线不可导入（exit={proc.returncode}）: {last_err}。"
                "修复指引: 在 engines/MeloTTS 安装依赖（pip install -e . 或 "
                "pip install -r requirements.txt）；引擎缺失时执行 "
                "tools/setup_engines.py --clone-melotts"
            )

    async def check_ready(self) -> None:
        """训练前就绪校验：引擎目录/关键脚本存在 + melo 包可导入。

        Raises:
            MelottsEngineNotReadyError: 任一校验失败（message 含
                tools/setup_engines.py --clone-melotts 指引，spec 冻结）
        """
        melo = self.melo_dir
        checks = [
            ("MeloTTS 引擎根目录", self._engine_dir),
            ("MeloTTS melo 包目录", melo),
            ("MeloTTS 训练入口 melo/train.py", melo / "train.py"),
            ("MeloTTS 预处理脚本 melo/preprocess_text.py", melo / "preprocess_text.py"),
            ("MeloTTS 基础配置 melo/configs/config.json", melo / "configs" / "config.json"),
        ]
        missing = [f"{desc}: {path}" for desc, path in checks if not path.exists()]
        if missing:
            raise MelottsEngineNotReadyError(
                "MeloTTS 引擎未就绪，缺失: " + "; ".join(missing) + "。"
                "修复指引: 执行 tools/setup_engines.py --clone-melotts 克隆官方仓库"
                "（详见 CXO-ModelStation/DEPLOY.md）"
            )
        await self._probe_melo_import()

    # ------------------------------------------------------------------
    # 子进程执行
    # ------------------------------------------------------------------
    async def _run_subprocess(
        self, args: list[str], cwd: Path, timeout: float
    ) -> tuple[int, str, str]:
        """执行短生命周期子进程（官方 preprocess_text.py 清洗步骤）。"""
        logger.info(f"Running subprocess: {' '.join(args)} (cwd={cwd})")
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd),
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.error(f"Subprocess timeout after {timeout}s: {' '.join(args)}")
            await _wait_for_subprocess_exit(proc, _TRAIN_STOP_WAIT_TIMEOUT)
            raise RuntimeError(
                f"Subprocess timed out after {timeout}s: {' '.join(args)}"
            )
        return (
            proc.returncode if proc.returncode is not None else -1,
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
        )

    async def _spawn_train(
        self, args: list[str], cwd: Path, env: dict
    ) -> asyncio.subprocess.Process:
        """启动训练子进程（独立方法便于测试注入 mock 进程）。"""
        return await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd),
            env=env,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
        )

    # ------------------------------------------------------------------
    # prep 产物定位与官方清洗结果重分
    # ------------------------------------------------------------------
    def _find_latest_prep(self) -> dict:
        """取最近一次 prep 的 manifest_prep.json（训练 filelist 来源）。

        Raises:
            FileNotFoundError: 无 prep 产物时（message 含 preprocess 指引）
        """
        from modelstation.services.melotts_dataset_prep import find_latest_prep

        return find_latest_prep(str(self._training_data_dir))

    def _resplit_cleaned(self, work_dir: Path, prep_info: dict) -> tuple[int, int, int]:
        """按 prep 的切分对官方清洗结果重分 train.list / val.list。

        preprocess_text.py 以 --val-per-spk 0 运行后全部清洗行落在
        official_train.list；本方法按行首列（音频路径）对照 prep 的
        train.txt/val.txt 成员关系重分，保留 prep 的 95/5 切分决定权；
        官方清洗失败跳过的行自然缺席，按 dropped 计数。

        Returns:
            (train_count, val_count, dropped_count)
        """
        cleaned_path = work_dir / "official_train.list"
        cleaned_lines = [
            line.strip()
            for line in cleaned_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

        def _first_col(path: Path) -> set[str]:
            if not path.is_file():
                return set()
            return {
                line.strip().split("|")[0]
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            }

        train_paths = _first_col(Path(prep_info["train_file"]))
        val_paths = _first_col(Path(prep_info["val_file"]))

        train_out: list[str] = []
        val_out: list[str] = []
        dropped = 0
        for line in cleaned_lines:
            utt = line.split("|")[0]
            if utt in train_paths:
                train_out.append(line)
            elif utt in val_paths:
                val_out.append(line)
            else:
                # 官方清洗失败跳过（preprocess_text.py "err!" 路径）或路径不匹配
                dropped += 1
        if not train_out:
            raise RuntimeError(
                "MeloTTS 官方清洗结果为空（train.list 无条目）；"
                "请检查数据集文本与语言配置（language）是否匹配 MeloTTS 支持的语言"
            )
        (work_dir / "train.list").write_text(
            "\n".join(train_out) + "\n", encoding="utf-8"
        )
        (work_dir / "val.list").write_text(
            "\n".join(val_out) + "\n", encoding="utf-8"
        )
        logger.info(
            "MeloTTS 清洗结果重分: train=%d val=%d dropped=%d (work_dir=%s)",
            len(train_out), len(val_out), dropped, work_dir,
        )
        return len(train_out), len(val_out), dropped

    def _write_train_config(
        self,
        config_path: Path,
        *,
        train_list: Path,
        val_list: Path,
        epochs: int,
        batch_size: int,
        learning_rate: float,
    ) -> None:
        """改写官方 preprocess_text.py 产出的 config.json 超参并落盘训练工作目录。

        字段名以 engines/MeloTTS/melo/configs/config.json 与
        melo/preprocess_text.py（spk2id/training_files/validation_files）实码为准：
        train.epochs / train.batch_size / train.learning_rate /
        data.training_files / data.validation_files（绝对路径注入，CWD 免疫）。
        """
        if not config_path.is_file():
            raise RuntimeError(
                f"官方 preprocess_text.py 未产出 config.json: {config_path}"
            )
        config = json.loads(config_path.read_text(encoding="utf-8"))
        train_section = config.get("train") if isinstance(config, dict) else None
        data_section = config.get("data") if isinstance(config, dict) else None
        if not isinstance(train_section, dict) or not isinstance(data_section, dict):
            raise RuntimeError(f"config.json 结构异常（缺 train/data 段）: {config_path}")
        train_section["epochs"] = int(epochs)
        train_section["batch_size"] = int(batch_size)
        train_section["learning_rate"] = float(learning_rate)
        data_section["training_files"] = str(train_list.resolve())
        data_section["validation_files"] = str(val_list.resolve())
        config_path.write_text(
            json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _collect_outputs(self, output_name: str) -> Path:
        """训练完成后收集产物：engine logs/<name> → models_dir/<name>。

        train.py 将产物硬编码落盘 ./logs/<model>（相对 melo CWD，实码约束），
        spec 约定训练产物落盘 models_dir/<output_name>/，此处搬运。
        """
        src = self.melo_dir / "logs" / output_name
        dst = self._models_dir / output_name
        dst.mkdir(parents=True, exist_ok=True)
        if not src.is_dir():
            raise RuntimeError(
                f"训练子进程 exit=0 但引擎日志目录不存在: {src}（无产物可收集）"
            )
        for pattern in ("G_*.pth", "D_*.pth", "DUR_*.pth", "config.json"):
            for f in src.glob(pattern):
                shutil.copy2(f, dst / f.name)
        if not list(dst.glob("G_*.pth")):
            raise RuntimeError(
                f"训练完成但未在 {src} 找到 G_*.pth 产物；请检查训练日志"
            )
        return dst

    # ------------------------------------------------------------------
    # 训练主流程
    # ------------------------------------------------------------------
    async def start_training(
        self,
        epochs: int = 10000,
        batch_size: int = 6,
        learning_rate: float = 3e-4,
        output_name: Optional[str] = None,
        language: Optional[str] = None,
        base_checkpoint: Optional[str] = None,
    ) -> str:
        """启动 MeloTTS 微调训练，返回 task_id。

        链路：本地运行检查 → 就绪校验 → 跨类型互斥 → 官方 preprocess_text.py
        （BERT/音素化）→ 按 prep 切分重分 → 改写训练 config → train.py 子进程
        → 后台监控。

        Raises:
            TrainingInProgressError: 本地已在训练或跨类型互斥占用（409 语义）
            MelottsEngineNotReadyError: 引擎未就绪（含 setup 指引）
            FileNotFoundError: 无 prep 产物（含 preprocess 指引）
            RuntimeError / ValueError: 清洗失败 / 切分异常 / 参数非法
        """
        if self._process is not None and self._process.returncode is None:
            raise TrainingInProgressError("训练已在进行，请先停止当前训练")

        if not int(epochs) >= 1:
            raise ValueError(f"epochs must be >= 1, got: {epochs}")
        if not int(batch_size) >= 1:
            raise ValueError(f"batch_size must be >= 1, got: {batch_size}")
        if not float(learning_rate) > 0:
            raise ValueError(f"learning_rate must be > 0, got: {learning_rate}")

        task_id = str(uuid.uuid4())
        if output_name:
            output_name = _sanitize_output_name(output_name)
        else:
            output_name = f"melotts_{task_id[:8]}"

        # 就绪校验（spec：引擎缺失/依赖缺失时明确报错含 setup 指引；互斥之前执行）
        await self.check_ready()

        # 跨类型训练互斥（同一时间仅一个训练任务；409 语义由 API 层映射）
        ok, current = try_begin_training(TRAINING_MELOTTS, task_id)
        if not ok:
            holder = current or {}
            raise TrainingInProgressError(
                "训练任务正在进行中"
                f"（类型: {holder.get('owner_type')}, task_id: {holder.get('task_id')}）",
                current=holder,
            )

        try:
            _update_train_status(
                task_id=task_id,
                status="busy_starting",
                progress=0.0,
                epoch=0,
                total_epochs=int(epochs),
                message="训练启动中（数据清洗/配置生成）",
            )

            prep_info = self._find_latest_prep()
            work_dir = Path(prep_info.get("output_dir") or Path(prep_info["prep_manifest_file"]).parent)
            metadata_file = Path(prep_info["metadata_file"])
            if not metadata_file.is_file():
                raise FileNotFoundError(
                    f"prep 产出的 metadata.list 不存在: {metadata_file}（请重新 preprocess）"
                )

            melo_dir = self.melo_dir
            out_path = self._models_dir / output_name
            out_path.mkdir(parents=True, exist_ok=True)

            # Step 1: 官方 preprocess_text.py（BERT/音素化；CWD=engine_dir/melo 实码约束）
            # --val-per-spk 0 --max-val-total 0：全部清洗行进 official_train.list，
            # 切分决定权保留在 prep 的 95/5（_resplit_cleaned 按路径成员重分）
            rc, stdout, stderr = await self._run_subprocess(
                [
                    self._python_path,
                    "preprocess_text.py",
                    "--metadata", str(metadata_file.resolve()),
                    "--config_path", str((melo_dir / "configs" / "config.json").resolve()),
                    "--train-path", str((work_dir / "official_train.list").resolve()),
                    "--val-path", str((work_dir / "official_val.list").resolve()),
                    "--cleaned-path", str((work_dir / "cleaned.list").resolve()),
                    "--val-per-spk", "0",
                    "--max-val-total", "0",
                ],
                cwd=melo_dir,
                timeout=_PREPROCESS_SUBPROCESS_TIMEOUT,
            )
            if rc != 0:
                raise RuntimeError(
                    f"MeloTTS preprocess_text.py 失败（exit={rc}）: {stderr[-2000:]}"
                )

            # Step 2: 按 prep 切分重分官方清洗结果
            train_count, val_count, dropped = self._resplit_cleaned(work_dir, prep_info)

            # Step 3: 改写训练 config（filelist 绝对路径 + 超参注入，落盘训练工作目录）
            config_path = work_dir / "config.json"
            self._write_train_config(
                config_path,
                train_list=work_dir / "train.list",
                val_list=work_dir / "val.list",
                epochs=epochs,
                batch_size=batch_size,
                learning_rate=learning_rate,
            )

            # 训练元数据落盘（复现用：请求参数 / 产物映射 / prep 来源）
            effective_base_ckpt = base_checkpoint if base_checkpoint else self._base_checkpoint
            train_meta = {
                "task_id": task_id,
                "output_name": output_name,
                "epochs": int(epochs),
                "batch_size": int(batch_size),
                "learning_rate": float(learning_rate),
                "language": language or self._language,
                "base_checkpoint": effective_base_ckpt or "",
                "prep_info": prep_info,
                "train_count": train_count,
                "val_count": val_count,
                "dropped_in_clean": dropped,
                "config_file": str(config_path.resolve()),
                # train.py 硬编码 ./logs/<model>（相对 melo CWD）→ 训练后拷贝至 models_dir
                "engine_logs_dir": str((melo_dir / "logs" / output_name).resolve()),
                "models_output_dir": str(out_path.resolve()),
                "created_at": _now_iso(),
            }
            (work_dir / "train_meta.json").write_text(
                json.dumps(train_meta, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            # Step 4: train.py 子进程（单进程 env:// 等价 torchrun 单卡启动）
            env = {
                **os.environ,
                "LOCAL_RANK": "0",
                "RANK": "0",
                "WORLD_SIZE": "1",
                "MASTER_ADDR": "127.0.0.1",
                "MASTER_PORT": str(_pick_free_port()),
            }
            args = [
                self._python_path,
                "train.py",
                "--c", str(config_path.resolve()),
                "--model", output_name,
            ]
            if effective_base_ckpt:
                # get_hparams 支持 --pretrain_G（train.py: hps.pretrain_G = args or 官方默认下载）
                args += ["--pretrain_G", str(effective_base_ckpt)]

            logger.info(
                "Starting MeloTTS training: %s (output=%s, epochs=%d, batch=%d, lr=%g)",
                task_id, output_name, epochs, batch_size, learning_rate,
            )
            proc = await self._spawn_train(args, cwd=melo_dir, env=env)
            self._process = proc
            self._monitor_task = asyncio.create_task(
                self._monitor_training(
                    task_id=task_id,
                    output_name=output_name,
                    total_epochs=int(epochs),
                    proc=proc,
                )
            )
            _update_train_status(status="running", message="训练进行中")
            return task_id
        except BaseException as exc:
            # 启动失败/异常：释放互斥（幂等）+ 状态复位，允许后续重试
            end_training(TRAINING_MELOTTS)
            _update_train_status(status="idle", message=f"训练启动失败: {exc}")
            raise

    # ------------------------------------------------------------------
    # 监控
    # ------------------------------------------------------------------
    async def _read_stream(self, stream, on_line) -> None:
        """逐行读取子进程流；stream 为 None（测试桩）时直接返回。"""
        if stream is None:
            return
        while True:
            line = await stream.readline()
            if not line:
                break
            on_line(line.decode("utf-8", errors="replace").strip())

    async def _monitor_training(
        self,
        task_id: str,
        output_name: str,
        total_epochs: int,
        proc: asyncio.subprocess.Process,
    ) -> None:
        """后台监控：解析 epoch 日志行更新进度；收尾校验产物并释放互斥。"""
        started_at = asyncio.get_running_loop().time()
        current_epoch = 0
        epoch_seen = False

        def _process_line(line_str: str) -> None:
            nonlocal current_epoch, epoch_seen
            if not line_str:
                return
            match = _EPOCH_PATTERN.search(line_str)
            if match:
                current_epoch = int(match.group(1))
                epoch_seen = True
                progress = min(current_epoch / total_epochs, 1.0) if total_epochs > 0 else 0.0
                _update_train_status(
                    epoch=current_epoch,
                    progress=progress,
                    message=line_str[:300],
                )
            else:
                _update_train_status(message=line_str[:300])

        async def _time_based_estimator() -> None:
            """无法解析 epoch 日志时按已运行时长估算进度（message 注明估算）。"""
            while not done_event.is_set():
                await asyncio.sleep(_ESTIMATE_INTERVAL_SECONDS)
                if epoch_seen or proc.returncode is not None:
                    continue
                elapsed = asyncio.get_running_loop().time() - started_at
                estimated = min(
                    elapsed / max(total_epochs * _ESTIMATED_SECONDS_PER_EPOCH, 1.0),
                    0.95,
                )
                _update_train_status(
                    progress=estimated,
                    message=f"（按已运行时长估算进度，未解析到 epoch 日志）已运行 {elapsed:.0f}s",
                )

        done_event = asyncio.Event()
        estimator_task = asyncio.create_task(_time_based_estimator())
        try:
            stdout_task = asyncio.create_task(self._read_stream(proc.stdout, _process_line))
            stderr_task = asyncio.create_task(self._read_stream(proc.stderr, _process_line))
            await asyncio.gather(stdout_task, stderr_task)

            # 等待子进程退出，超时主动 kill（对齐 sovits trainer）
            try:
                await asyncio.wait_for(proc.wait(), timeout=_TRAIN_MONITOR_TIMEOUT)
            except asyncio.TimeoutError:
                logger.error(
                    f"Training monitor wait timeout after {_TRAIN_MONITOR_TIMEOUT}s; killing process"
                )
                await _wait_for_subprocess_exit(proc, _TRAIN_STOP_WAIT_TIMEOUT)

            returncode = proc.returncode if proc.returncode is not None else -1
            if returncode == 0:
                try:
                    dst = self._collect_outputs(output_name)
                    _update_train_status(
                        status="completed",
                        progress=1.0,
                        message=f"训练完成，产物已收集至 {dst}",
                    )
                    logger.info("MeloTTS training completed: task_id=%s", task_id)
                except Exception as exc:
                    _update_train_status(
                        status="failed",
                        message=f"训练子进程正常退出但产物收集失败: {exc}",
                    )
                    logger.error("MeloTTS output collection failed: %s", exc)
            else:
                _update_train_status(
                    status="failed",
                    message=f"训练子进程异常退出（exit={returncode}）",
                )
                logger.error(
                    "MeloTTS training failed: task_id=%s exit=%s", task_id, returncode
                )
        except asyncio.CancelledError:
            # stop 路径取消监控：状态由 stop_training 收尾，此处仅传播取消
            raise
        finally:
            done_event.set()
            estimator_task.cancel()
            # 所有出口释放互斥（end_training 幂等；仅持有者匹配时生效）
            end_training(TRAINING_MELOTTS)

    # ------------------------------------------------------------------
    # 停止 / 模型列表
    # ------------------------------------------------------------------
    async def stop_training(self) -> None:
        """停止训练：terminate→kill 链路（对齐 sovits trainer）；所有出口释放互斥。"""
        if self._process is not None and self._process.returncode is None:
            try:
                self._process.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(self._process.wait(), timeout=_TRAIN_STOP_WAIT_TIMEOUT)
            except asyncio.TimeoutError:
                logger.warning(
                    f"Training process did not exit after terminate; killing "
                    f"(pid={self._process.pid})"
                )
                try:
                    self._process.kill()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(
                        self._process.wait(), timeout=_TRAIN_STOP_WAIT_TIMEOUT
                    )
                except asyncio.TimeoutError:
                    logger.error(
                        f"Training process still alive after kill (pid={self._process.pid})"
                    )
        if self._monitor_task is not None and not self._monitor_task.done():
            self._monitor_task.cancel()
            # join 已取消的监控任务：其 finally 已释放互斥，此处等待收尾完成
            done, _ = await asyncio.wait([self._monitor_task])
            for task in done:
                if task.cancelled():
                    continue
                exc = task.exception()
                if exc:
                    logger.debug(f"训练监控任务异常退出: {exc}")
        self._process = None
        self._monitor_task = None
        _update_train_status(status="stopped", message="训练已停止")
        # stop 出口释放互斥（幂等：monitor finally 已释放时此处无害）
        end_training(TRAINING_MELOTTS)
        logger.info("MeloTTS training stopped")

    def list_models(self) -> list[dict]:
        """列出已训练模型（形状与 sovits /models 同构：name/path/created/g_model/d_model）。"""
        models = []
        if self._models_dir.exists():
            for d in self._models_dir.iterdir():
                if d.is_dir():
                    g_files = sorted(d.glob("G_*.pth"), key=lambda p: p.stat().st_mtime)
                    d_files = sorted(d.glob("D_*.pth"), key=lambda p: p.stat().st_mtime)
                    if g_files or d_files:
                        models.append({
                            "name": d.name,
                            "path": str(d),
                            "created": d.stat().st_mtime,
                            "g_model": str(g_files[-1]) if g_files else None,
                            "d_model": str(d_files[-1]) if d_files else None,
                        })
        models.sort(key=lambda m: m["created"], reverse=True)
        return models


# ---------------------------------------------------------------------------
# 默认单例工厂（api 层复用入口；同 sovits get_sovits_trainer 模式）
# ---------------------------------------------------------------------------
_trainer_instance: Optional[MeloTTSTrainer] = None
_trainer_kwargs_hash: Optional[str] = None


def _hash_kwargs(kwargs: dict) -> str:
    import hashlib

    payload = json.dumps(kwargs, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def get_trainer() -> MeloTTSTrainer:
    """按 settings.melotts 冻结字段构造/复用 trainer 单例。

    配置变化且无运行中训练时自动重建（melotts trainer 不持有
    跨请求内存状态——prep 产物全部落盘，重建安全）；有运行中训练时
    保留旧实例（防止丢失运行中子进程句柄）。
    """
    global _trainer_instance, _trainer_kwargs_hash
    from modelstation.config import get_settings

    settings = get_settings()
    melotts_cfg = getattr(settings, "melotts", None)
    if melotts_cfg is None:
        raise RuntimeError("melotts 配置段未就绪（依赖 config.py 落地）")
    kwargs = {
        "engine_dir": melotts_cfg.engine_dir,
        "training_data_dir": melotts_cfg.training_data_dir,
        "models_dir": melotts_cfg.models_dir,
        "python_path": melotts_cfg.python_path,
        "language": melotts_cfg.language,
        "base_checkpoint": melotts_cfg.base_checkpoint,
    }
    new_hash = _hash_kwargs(kwargs)
    busy = _trainer_instance is not None and (
        _trainer_instance._process is not None
        and _trainer_instance._process.returncode is None
    )
    if _trainer_instance is None or (_trainer_kwargs_hash != new_hash and not busy):
        from modelstation.services.melotts_trainer import MeloTTSTrainer

        _trainer_instance = MeloTTSTrainer(**kwargs)
        _trainer_kwargs_hash = new_hash
    return _trainer_instance


def reset_trainer() -> None:
    """重置 trainer 单例（测试专用）。"""
    global _trainer_instance, _trainer_kwargs_hash
    _trainer_instance = None
    _trainer_kwargs_hash = None
