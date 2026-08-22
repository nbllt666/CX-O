"""tuner.core.trainer：QLoRA 训练引擎（Unsloth）。

组成：
  - train_job.py      TrainJob 训练任务状态机（idle/running/completed/failed）
  - store.py          TrainerJobStore 任务存储（内存 + JSON 持久化）
  - anchors.py        锚点样本加载与 DPO 数据混合
  - qlora_trainer.py  QLoRA 训练引擎（懒加载 unsloth，资源限制，DPO+锚点 SFT 混合损失）

约定：unsloth/trl/torch 等重型依赖仅在训练真正执行时懒加载；模块导入零副作用，
便于离线测试通过 monkeypatch 注入假 run 而不触发真实 import / 不占用 GPU。
"""
from tuner.core.trainer.train_job import TrainJob
from tuner.core.trainer.store import TrainerJobStore
from tuner.core.trainer.anchors import load_anchor_samples, sample_anchor_subset
from tuner.core.trainer.qlora_trainer import QLoRATrainer, apply_resource_caps

__all__ = [
    "TrainJob",
    "TrainerJobStore",
    "load_anchor_samples",
    "sample_anchor_subset",
    "QLoRATrainer",
    "apply_resource_caps",
]