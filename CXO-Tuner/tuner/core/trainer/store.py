"""TrainerJobStore：训练任务存储（内存 + JSON 持久化）。

- 内存索引：按 job_id 快速读写，线程安全（threading.Lock）。
- 磁盘持久化：jobs_dir 下每个 job 一个 <job_id>.json，写时全量快照。
- 进程重启后可加载既有 job 快照，latest() 返回最近创建的 job。
"""
from __future__ import annotations

import json
import os
import threading
from typing import Dict, List, Optional

from tuner.core.trainer.train_job import TrainJob


class TrainerJobStore:
    def __init__(self, jobs_dir: str) -> None:
        self.jobs_dir = os.path.abspath(jobs_dir)
        os.makedirs(self.jobs_dir, exist_ok=True)
        self._lock = threading.Lock()
        self._jobs: Dict[str, TrainJob] = {}
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
            except Exception:
                continue

    def _persist(self, job: TrainJob) -> None:
        path = self._path(job.job_id)
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(job.to_dict(), fh, ensure_ascii=False, indent=2)
        except OSError:
            pass  # 持久化失败不影响内存态返回

    # -- 对外读写 ---------------------------------------------------------------
    def create(self, job: TrainJob) -> TrainJob:
        with self._lock:
            self._jobs[job.job_id] = job
            self._persist(job)
        return job

    def update(self, job: TrainJob) -> None:
        with self._lock:
            self._jobs[job.job_id] = job
            self._persist(job)

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