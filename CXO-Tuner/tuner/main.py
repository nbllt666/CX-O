"""CXO-Tuner 独立后台微调服务 FastAPI 入口。

启动：uvicorn tuner.main:app --host 0.0.0.0 --port 8300
lifespan 阶段初始化 DatasetStore / AdapterStore / Collector 并挂到 app.state。
"""
from __future__ import annotations

import logging
import os
import threading
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI

from tuner.api.routes import router
from tuner.config import TunerConfig, load_config
from tuner.core.adapter_store.store import AdapterStore
from tuner.core.collector import Collector
from tuner.core.collector.cleaner import FeedbackCleaner
from tuner.core.collector.dataset import DatasetStore
from tuner.core.judge.dpo_builder import DpoBuilder
from tuner.core.judge.judge_engine import JudgeEngine
from tuner.core.scheduler import IdleScheduler, OnlineDpo
from tuner.core.trainer.qlora_trainer import QLoRATrainer, is_training_in_progress
from tuner.core.trainer.store import TrainerJobStore
from tuner.core.trainer.train_job import InvalidTransitionError, TrainJob

logger = logging.getLogger("cxo_tuner")

# 闲时调度后台线程 tick 间隔（秒）（可调）
_SCHEDULER_TICK_INTERVAL = 60.0


def create_app(config: Optional[TunerConfig] = None) -> FastAPI:
    """应用工厂。config 为 None 时使用 load_config()（含 auto_fill）。

    磁盘组件（DatasetStore/AdapterStore）仅在 lifespan 启动时创建，import 阶段零副作用，
    便于测试注入临时数据目录。
    """
    resolved = config if config is not None else load_config()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        dataset_store = DatasetStore(resolved.dataset_dir)
        adapter_store = AdapterStore(resolved.lora_dir)
        cleaner = FeedbackCleaner()
        collector = Collector(cleaner, dataset_store)
        trainer_store = TrainerJobStore(os.path.join(resolved.dataset_dir, "train_jobs"))
        trainer = QLoRATrainer(resolved, trainer_store, dataset_store=dataset_store)

        # H15b：服务重启恢复——上一进程崩溃/重启时遗留的 status=="running" 任务实际已无人
        # 执行，若不清理将永久停留在 running（僵尸任务），且 is_training_in_progress 语义
        # 与之矛盾、UI 无法重试。启动时统一标记 failed 并强制落盘。
        _stale_running = [
            stale for stale in trainer_store.all() if stale.status == "running"
        ]
        for stale in _stale_running:
            try:
                stale.fail("service restarted mid-training")
            except InvalidTransitionError:  # pragma: no cover —— all() 刚过滤过，防御兜底
                continue
            trainer_store.update(stale, force=True)
        if _stale_running:
            logger.warning("服务重启恢复：已将 %d 个遗留 running 训练任务标记为 failed", len(_stale_running))

        dpo_builder = DpoBuilder(dataset_store, JudgeEngine(resolved))
        app.state.config = resolved
        app.state.dataset_store = dataset_store
        app.state.adapter_store = adapter_store
        app.state.cleaner = cleaner
        app.state.collector = collector
        app.state.trainer_store = trainer_store
        app.state.trainer = trainer
        app.state.dpo_builder = dpo_builder

        def _trigger_train() -> None:
            """闲时触发一次训练：创建 TrainJob 并在后台线程运行（复用 /train/trigger 路径）。"""
            job = TrainJob(status="idle", base_model=resolved.base_model)
            trainer_store.create(job)
            threading.Thread(target=trainer.run, args=(job.job_id,), daemon=True).start()

        # 闲时调度：仅当 scheduler.enabled 时挂载（instances 自身不独占后台线程）
        scheduler = None
        scheduler_stop = None
        scheduler_thread = None
        # 在线 DPO 为实验性（默认关闭），仅在状态注册开关，不默认启动
        online_dpo = OnlineDpo(resolved.online_dpo)
        if resolved.scheduler.enabled:
            scheduler = IdleScheduler(
                config=resolved.scheduler,
                dataset_store=dataset_store,
                trigger=_trigger_train,
                trainer_store=trainer_store,
            )

            def _scheduler_loop() -> None:
                while not scheduler_stop.is_set():
                    try:
                        scheduler.tick()
                    except Exception as exc:  # noqa: BLE001 —— 调度失败仅告警，不中断服务
                        logger.warning("闲时调度 tick 异常: %s", exc)
                    scheduler_stop.wait(_SCHEDULER_TICK_INTERVAL)

            scheduler_stop = threading.Event()
            scheduler_thread = threading.Thread(
                target=_scheduler_loop, name="idle-scheduler", daemon=True
            )
            scheduler_thread.start()
            logger.info(
                "闲时调度已启动: idle=[%s,%s) min_dataset_size=%d",
                resolved.scheduler.idle_start,
                resolved.scheduler.idle_end,
                resolved.scheduler.min_dataset_size,
            )

        app.state.scheduler = scheduler
        app.state.online_dpo = online_dpo
        app.state._scheduler_stop = scheduler_stop
        app.state._scheduler_thread = scheduler_thread

        logger.info("CXO-Tuner 组件初始化完成: dataset_dir=%s lora_dir=%s", resolved.dataset_dir, resolved.lora_dir)
        try:
            yield
        finally:
            if scheduler_stop is not None:
                scheduler_stop.set()
            if scheduler_thread is not None:
                scheduler_thread.join(timeout=5.0)

    app = FastAPI(title="CXO-Tuner", version="1.0.0", lifespan=lifespan)
    app.state.config = resolved
    app.include_router(router)
    return app


# uvicorn 目标：tuner.main:app
app = create_app()