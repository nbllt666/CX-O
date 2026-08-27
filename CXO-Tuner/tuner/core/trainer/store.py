"""TrainerJobStore：训练任务存储（内存 + JSON 持久化）。

- 内存索引：按 job_id 快速读写，线程安全（threading.Lock）。
- 磁盘持久化：jobs_dir 下每个 job 一个 <job_id>.json，写时全量快照。
  H15a 修复：
    1. 原子写——先写临时文件再 os.replace 替换，进程崩溃不再留下半截 JSON；
    2. 写盘节流——训练回调每个 log step 全量持久化的高频路径按时间间隔节流
      （默认 <2s 跳过写盘），但状态转换点（status 与上次落盘不同）始终立即落盘。
- 进程重启后可加载既有 job 快照，latest() 返回最近创建的 job。
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Dict, List, Optional

from tuner.core.trainer.train_job import TrainJob

logger = logging.getLogger("cxo_tuner.trainer.store")

#: 相邻两次成功写盘的最小间隔（秒）。间隔内的高频 update 跳过磁盘写入（内存仍最新），
#: 但 status 发生变化时无条件落盘，保证状态转换点不丢。
_PERSIST_MIN_INTERVAL_SEC = 2.0


class TrainerJobStore:
    def __init__(self, jobs_dir: str) -> None:
        self.jobs_dir = os.path.abspath(jobs_dir)
        os.makedirs(self.jobs_dir, exist_ok=True)
        self._lock = threading.Lock()
        self._jobs: Dict[str, TrainJob] = {}
        self._last_persist_ts: Dict[str, float] = {}       # job_id -> 上次成功写盘时刻(monotonic)
        self._last_persisted_status: Dict[str, str] = {}   # job_id -> 上次成功落盘的 status
        self._load_existing()

    # -- 磁盘 ------------------------------------------------------------------
    def _path(self, job_id: str) -> str:
        return os.path.join(self.jobs_dir, f"{job_id}.json")

    def _load_existing(self) -> None:
        try:
            entries = os.listdir(self.jobs_dir)
        except OSError:
            return
        for name in entries:
            if not name.endswith(".json"):
                continue
            path = os.path.join(self.jobs_dir, name)
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                job = TrainJob.from_dict(data)
                self._jobs[job.job_id] = job
            except Exception as exc:  # noqa: BLE001 —— 单个损坏快照不影响其余历史加载
                logger.warning("加载训练任务快照失败（可能为崩溃残留半截 JSON，已跳过）: %s err=%s",
                               path, exc)
                continue

    def _persist(self, job: TrainJob, *, force: bool = False) -> None:
        """原子 + 节流地持久化单个 job 快照。

        - force=True 或 status 较上次落盘发生变化时无条件写盘（状态转换点必须落盘）；
        - 其余高频调用（如每 log step 回调）在 <_PERSIST_MIN_INTERVAL_SEC 内跳过，
          内存态保持最新，后续非节流窗口的更新会带上全部进展落盘。
        """
        if not force and self._last_persisted_status.get(job.job_id) == job.status:
            last = self._last_persist_ts.get(job.job_id)
            if last is not None and (time.monotonic() - last) < _PERSIST_MIN_INTERVAL_SEC:
                return  # 节流窗口内：跳过本次写盘（状态未变化，内存已更新）
        path = self._path(job.job_id)
        tmp_path = f"{path}.tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(job.to_dict(), fh, ensure_ascii=False, indent=2)
            # H15a：临时文件写完整后原子替换，任何进程崩溃点都不会留下半截 JSON
            os.replace(tmp_path, path)
        except OSError:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass
            return  # 持久化失败不影响内存态返回
        self._last_persist_ts[job.job_id] = time.monotonic()
        self._last_persisted_status[job.job_id] = job.status

    # -- 对外读写 ---------------------------------------------------------------
    def create(self, job: TrainJob) -> TrainJob:
        with self._lock:
            self._jobs[job.job_id] = job
            self._persist(job, force=True)
        return job

    def update(self, job: TrainJob, *, force: bool = False) -> None:
        """更新内存态并按节流策略落盘。force=True 强制立即落盘（用于状态转换点）。"""
        with self._lock:
            self._jobs[job.job_id] = job
            self._persist(job, force=force)

    def get(self, job_id: str) -> Optional[TrainJob]:
        with self._lock:
            return self._jobs.get(job_id)

    def latest(self) -> Optional[TrainJob]:
        with self._lock:
            if not self._jobs:
                return None
            return max(self._jobs.values(), key=lambda j: j.created_at)

    def all(self) -> List[TrainJob]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda j: j.created_at)