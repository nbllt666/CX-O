"""SQLite 指标库 + run 生命周期状态机。

库文件: {data_dir}/evalkit.db
run 状态机（单向终态）: running → passed | failed | judge_unavailable | error
非法转换抛 ValueError。
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from evalkit import report

RUNNING = "running"
TERMINAL_STATUSES = ("passed", "failed", "judge_unavailable", "error")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    suite TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    finished_at TEXT,
    config_snapshot TEXT,
    metrics_summary TEXT,
    error TEXT
)
"""


class EvalStore:
    """runs 表访问层（线程安全：runner 后台线程与 API 线程共用）。"""

    def __init__(self, data_dir: str):
        self.data_dir = report.resolve_data_dir(data_dir)
        os.makedirs(self.data_dir, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(
            os.path.join(self.data_dir, "evalkit.db"), check_same_thread=False
        )
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute(_SCHEMA)
            self._conn.commit()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def create_run(
        self, run_id: str, suite: str, config_snapshot: Optional[Dict[str, Any]] = None
    ) -> None:
        """插入新 run，初始状态 running。config_snapshot 必须为已剥离 key 的安全 dict。"""
        with self._lock:
            self._conn.execute(
                "INSERT INTO runs (run_id, suite, status, created_at, config_snapshot) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    run_id,
                    suite,
                    RUNNING,
                    self._now(),
                    json.dumps(config_snapshot or {}, ensure_ascii=False),
                ),
            )
            self._conn.commit()

    def finish_run(
        self,
        run_id: str,
        status: str,
        metrics_summary: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        """终态化 run。当前必须为 running 且 status 为四个终态之一，非法转换抛 ValueError。"""
        if status not in TERMINAL_STATUSES:
            raise ValueError(
                f"非法终态 status={status!r}，允许值: {TERMINAL_STATUSES}"
            )
        with self._lock:
            row = self._conn.execute(
                "SELECT status FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if row is None:
                raise ValueError(f"run 不存在: {run_id}")
            if row["status"] != RUNNING:
                raise ValueError(
                    f"run {run_id} 当前状态为 {row['status']!r}（非 running），禁止二次终态化"
                )
            self._conn.execute(
                "UPDATE runs SET status = ?, finished_at = ?, metrics_summary = ?, error = ? "
                "WHERE run_id = ?",
                (
                    status,
                    self._now(),
                    json.dumps(metrics_summary, ensure_ascii=False)
                    if metrics_summary is not None
                    else None,
                    error,
                    run_id,
                ),
            )
            self._conn.commit()

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """单 run 详情；不存在返回 None。JSON 字段自动反序列化。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        return self._row_to_dict(row) if row is not None else None

    def list_runs(self) -> List[Dict[str, Any]]:
        """run 列表（created_at 倒序，同刻按插入序倒序兜底）。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM runs ORDER BY created_at DESC, rowid DESC"
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        d = dict(row)
        for field in ("config_snapshot", "metrics_summary"):
            raw = d.get(field)
            if raw:
                d[field] = json.loads(raw)
            else:
                d[field] = {} if field == "config_snapshot" else None
        return d

    def save_run_artifacts(self, run_id: str, detail: Dict[str, Any]) -> str:
        """写 run 明细 {data_dir}/runs/{run_id}/detail.json，返回文件路径。"""
        return report.write_detail_json(self.data_dir, run_id, detail)

    def get_report_path(self, run_id: str) -> str:
        """返回 {data_dir}/runs/{run_id}/report.md 约定路径（不必存在）。"""
        return report.report_path(self.data_dir, run_id)

    def close(self) -> None:
        with self._lock:
            self._conn.close()
