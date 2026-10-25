"""Training shutdown/deadline regressions without starting engines or processes."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from modelstation import main
from modelstation.api import sovits_svc as api
from modelstation.services import melotts_trainer as mt
from modelstation.services import sovits_svc_trainer as svc
from modelstation.services.training_mutex import (
    TRAINING_MELOTTS, current_training, reset_registry, try_begin_training,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("first_fails", [False, True])
async def test_lifespan_awaits_both_trainers(monkeypatch, first_fails):
    first = AsyncMock(side_effect=RuntimeError("failed") if first_fails else None)
    second = AsyncMock()
    monkeypatch.setattr(api, "_trainer_instance", SimpleNamespace(stop_training=first))
    monkeypatch.setattr(mt, "_trainer_instance", SimpleNamespace(stop_training=second))
    async with main.lifespan(None):
        first.assert_not_awaited()
    first.assert_awaited_once()
    second.assert_awaited_once()


class HangingStream:
    def __init__(self, fail=False):
        self.fail = fail
        self.readers = 0

    async def readline(self):
        self.readers += 1
        try:
            if self.fail:
                raise OSError("broken log pipe")
            await asyncio.Event().wait()
        finally:
            self.readers -= 1


class HangingProcess:
    def __init__(self, fail=False):
        self.pid = 999999
        self.stdout = HangingStream(fail)
        self.stderr = HangingStream()
        self.returncode = None
        self.terminated = False
        self.exited = asyncio.Event()
        self.waiters = 0

    async def wait(self):
        self.waiters += 1
        try:
            await self.exited.wait()
            return self.returncode
        finally:
            self.waiters -= 1

    def terminate(self):
        self.terminated = True
        self.returncode = -15
        self.exited.set()

    kill = terminate


@pytest.mark.asyncio
@pytest.mark.parametrize("engine", ["svc", "melo"])
@pytest.mark.parametrize("failure", ["timeout", "stream_error", "cancel"])
async def test_monitor_bounds_pipe_reads_and_cleans_tasks(monkeypatch, tmp_path, engine, failure):
    module = svc if engine == "svc" else mt
    monkeypatch.setattr(module, "_TRAIN_MONITOR_TIMEOUT", 0.02)
    monkeypatch.setattr(module, "_TRAIN_STOP_WAIT_TIMEOUT", 0.02)
    proc = HangingProcess(fail=failure == "stream_error")
    updates = []
    reset_registry()
    mt.reset_train_status()
    if engine == "svc":
        trainer = svc.SoVITSSVCTrainer(output_dir=str(tmp_path))
        monitor = trainer._monitor_training(1, lambda **kw: updates.append(kw), proc=proc)
    else:
        trainer = mt.MeloTTSTrainer(str(tmp_path), str(tmp_path), str(tmp_path))
        assert try_begin_training(TRAINING_MELOTTS, "test")[0]
        monitor = trainer._monitor_training("test", "output", 1, proc)
    task = asyncio.create_task(monitor)
    try:
        if failure == "cancel":
            await asyncio.sleep(0.005)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            await asyncio.wait_for(task, 1.0)
            final = updates[-1] if engine == "svc" else mt.get_train_status()
            assert final["status"] == "failed"
            assert ("超时" if failure == "timeout" else "broken log pipe") in final["message"]
        assert proc.terminated
        assert proc.stdout.readers == proc.stderr.readers == proc.waiters == 0
        assert current_training() is None
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        reset_registry()
        mt.reset_train_status()


@pytest.mark.asyncio
async def test_sovits_epoch_parsed_from_log_file(monkeypatch, tmp_path):
    """引擎 epoch 日志只落 train.log 文件（get_logger 仅 FileHandler）→ 监控从文件尾部解析并回调真实 epoch"""
    log_dir = tmp_path / "logs" / "mymodel"
    log_dir.mkdir(parents=True)
    (log_dir / "train.log").write_text(
        "2026-10-18\tINFO\t====> Epoch: 7, cost 1.00 s\n", encoding="utf-8"
    )
    monkeypatch.setattr(svc, "_EPOCH_FILE_POLL_SECONDS", 0.02)
    # HangingProcess 流永不 EOF：监控 gather 依赖超时收尾，缩短以匹配测试节奏
    monkeypatch.setattr(svc, "_TRAIN_MONITOR_TIMEOUT", 0.3)
    proc = HangingProcess()
    updates: list[dict] = []
    trainer = svc.SoVITSSVCTrainer(output_dir=str(tmp_path), so_vits_svc_dir=str(tmp_path))
    monitor = trainer._monitor_training(
        10, lambda **kw: updates.append(kw), proc=proc, output_name="mymodel"
    )
    task = asyncio.create_task(monitor)
    try:
        await asyncio.sleep(0.1)
        # stdout/stderr 未输出任何 epoch 行，epoch 只能来自 train.log 文件解析
        assert any(u.get("epoch") == 7 for u in updates), f"updates={updates}"
        proc.terminate()  # returncode=-15 → 监控按异常退出收尾并回填终态
        await asyncio.wait_for(task, 1.0)
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        reset_registry()
        mt.reset_train_status()
    final = updates[-1]
    assert final["status"] == "failed"
    assert final["epoch"] == 7  # 终态回填的 epoch 取文件解析值，而非 0
