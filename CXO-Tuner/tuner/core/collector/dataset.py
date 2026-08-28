"""DatasetStore：偏好/DPO 数据集存储与聚合统计。

存储：SQLite（dataset.db，数据目录下）为默认后端；也可在构造时指定 storage="json"
以 JSON 文件落盘。记录结构对齐 cxo_tuner_dpo_dataset.schema.json。
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from tuner.models import DatasetStats

_SOURCE_ALL = ("live_danmaku", "judge", "distillation")


@dataclass
class DpoRecord:
    """一条 DPO 风格数据集记录（对齐 cxo_tuner_dpo_dataset.schema.json）。"""

    id: str
    fingerprint: str
    prompt: str
    chosen: str
    rejected: str
    source: str
    anchor: bool
    quality_score: Optional[float]
    session_id: Optional[str]
    created_at: str
    judge_model: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class DatasetStore:
    """数据集存储。storage: "sqlite" | "json"。"""

    def __init__(self, dataset_dir: str, storage: str = "sqlite") -> None:
        self.dataset_dir = os.path.abspath(dataset_dir)
        self._storage = storage.lower()
        os.makedirs(self.dataset_dir, exist_ok=True)
        self._lock = threading.Lock()
        if self._storage == "sqlite":
            self._db_path = os.path.join(self.dataset_dir, "dataset.db")
            self._init_sqlite()
        else:
            self._json_path = os.path.join(self.dataset_dir, "dataset.json")

    # -- sqlite 后端 ------------------------------------------------------
    def _init_sqlite(self) -> None:
        # check_same_thread=False：Starlette/FastAPI 将同步端点跑在线程池线程，
        # 连接在 lifespan 线程创建。所有访问已由 self._lock 串行化保护。
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS records (
                id          TEXT PRIMARY KEY,
                fingerprint TEXT NOT NULL UNIQUE,
                prompt      TEXT NOT NULL,
                chosen      TEXT NOT NULL,
                rejected    TEXT NOT NULL,
                source      TEXT NOT NULL,
                anchor      INTEGER NOT NULL DEFAULT 0,
                quality_score REAL,
                session_id  TEXT,
                created_at  TEXT NOT NULL,
                judge_model TEXT,
                metadata    TEXT
            )
            """
        )
        # 兼容旧库：为存量 dataset.db 补充新增列（新列不存在时 ALTER 幂等成功）
        for _col, _ctype in (("judge_model", "TEXT"), ("metadata", "TEXT")):
            try:
                self._conn.execute(f"ALTER TABLE records ADD COLUMN {_col} {_ctype}")
            except sqlite3.OperationalError:
                pass  # 列已存在
        self._conn.commit()

    def close(self) -> None:
        """释放 sqlite 连接。json 后端无线程安全连接需要，调用方按需在生命周期结束处调用。"""
        with self._lock:
            conn = getattr(self, "_conn", None)
            if conn is not None:
                try:
                    conn.close()
                except sqlite3.Error:
                    pass
                self._conn = None

    # -- 写 -----------------------------------------------------------------
    def add_record(
        self,
        *,
        fingerprint: str,
        prompt: str,
        chosen: str,
        rejected: str,
        source: str,
        anchor: bool = False,
        quality_score: Optional[float] = None,
        session_id: Optional[str] = None,
        created_at: Optional[str] = None,
        judge_model: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> DpoRecord:
        rec = DpoRecord(
            id=uuid4().hex,
            fingerprint=fingerprint,
            prompt=prompt,
            chosen=chosen,
            rejected=rejected,
            source=source,
            anchor=anchor,
            quality_score=quality_score,
            session_id=session_id,
            created_at=created_at or _now_iso(),
            judge_model=judge_model,
            metadata=metadata,
        )
        with self._lock:
            if self._storage == "sqlite":
                try:
                    self._conn.execute(
                        "INSERT INTO records (id, fingerprint, prompt, chosen, rejected, source, anchor, quality_score, session_id, created_at, judge_model, metadata) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            rec.id,
                            rec.fingerprint,
                            rec.prompt,
                            rec.chosen,
                            rec.rejected,
                            rec.source,
                            1 if rec.anchor else 0,
                            rec.quality_score,
                            rec.session_id,
                            rec.created_at,
                            rec.judge_model,
                            json.dumps(rec.metadata, ensure_ascii=False) if rec.metadata is not None else None,
                        ),
                    )
                    self._conn.commit()
                except sqlite3.IntegrityError:
                    # fingerprint UNIQUE 冲突：find_by_fingerprint 预检与 INSERT 非原子，
                    # 并发下会抛 IntegrityError。归一为「已存在」，返回库里既有记录而非冒泡 500。
                    self._conn.rollback()
                    row = self._conn.execute(
                        "SELECT id, fingerprint, prompt, chosen, rejected, source, anchor, quality_score, session_id, created_at, judge_model, metadata "
                        "FROM records WHERE fingerprint = ?",
                        (rec.fingerprint,),
                    ).fetchone()
                    if row:
                        return self._row_to_record(row)
                    return rec  # 冲突但查无记录（并发下被删除的极端情况），返回本构造记录避免断裂
            else:
                rows = self._load_json()
                rows.append(self._to_dict_internal(rec))
                self._save_json(rows)
        return rec

    def find_by_fingerprint(self, fingerprint: str) -> Optional[DpoRecord]:
        with self._lock:
            if self._storage == "sqlite":
                cur = self._conn.execute(
                    "SELECT id, fingerprint, prompt, chosen, rejected, source, anchor, quality_score, session_id, created_at, judge_model, metadata "
                    "FROM records WHERE fingerprint = ?",
                    (fingerprint,),
                )
                row = cur.fetchone()
                return self._row_to_record(row) if row else None
            rows = self._load_json()
            for r in rows:
                if r.get("fingerprint") == fingerprint:
                    return self._dict_to_record(r)
            return None

    def count(self) -> int:
        return self.get_stats().total

    def get_stats(self) -> DatasetStats:
        with self._lock:
            if self._storage == "sqlite":
                total = self._conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
                breakdown: Dict[str, int] = {
                    src: 0 for src in _SOURCE_ALL
                }
                for src, cnt in self._conn.execute(
                    "SELECT source, COUNT(*) FROM records GROUP BY source"
                ):
                    breakdown[src] = cnt
                anchor_count = self._conn.execute(
                    "SELECT COUNT(*) FROM records WHERE anchor = 1"
                ).fetchone()[0]
            else:
                rows = self._load_json()
                total = len(rows)
                breakdown = {src: 0 for src in _SOURCE_ALL}
                anchor_count = 0
                for r in rows:
                    src = r.get("source")
                    if src in breakdown:
                        breakdown[src] += 1
                    if r.get("anchor"):
                        anchor_count += 1
        total = int(total)
        if total > 0:
            positive_ratio = 1.0  # 每条记录包含 1 个正样本（chosen）
            negative_ratio = 1.0  # 每条记录包含 1 个负样本（rejected）
        else:
            positive_ratio = 0.0
            negative_ratio = 0.0
        return DatasetStats(
            total=total,
            source_breakdown=breakdown,
            positive_ratio=positive_ratio,
            negative_ratio=negative_ratio,
            anchor_count=int(anchor_count),
        )

    def all_records(self) -> List[DpoRecord]:
        with self._lock:
            if self._storage == "sqlite":
                rows = self._conn.execute(
                    "SELECT id, fingerprint, prompt, chosen, rejected, source, anchor, quality_score, session_id, created_at, judge_model, metadata "
                    "FROM records"
                ).fetchall()
                return [self._row_to_record(r) for r in rows]
            rows = self._load_json()
            return [self._dict_to_record(r) for r in rows]

    # -- 内部工具 -------------------------------------------------------------
    @staticmethod
    def _row_to_record(row: Any) -> DpoRecord:
        metadata = None
        raw_meta = row[11] if len(row) > 11 else None
        if isinstance(raw_meta, str):
            try:
                metadata = json.loads(raw_meta)
            except json.JSONDecodeError:
                metadata = None
        return DpoRecord(
            id=row[0],
            fingerprint=row[1],
            prompt=row[2],
            chosen=row[3],
            rejected=row[4],
            source=row[5],
            anchor=bool(row[6]),
            quality_score=row[7],
            session_id=row[8],
            created_at=row[9],
            judge_model=row[10] if len(row) > 10 else None,
            metadata=metadata,
        )

    @staticmethod
    def _dict_to_record(r: Dict[str, Any]) -> DpoRecord:
        return DpoRecord(
            id=r["id"],
            fingerprint=r["fingerprint"],
            prompt=r["prompt"],
            chosen=r["chosen"],
            rejected=r["rejected"],
            source=r["source"],
            anchor=bool(r.get("anchor")),
            quality_score=r.get("quality_score"),
            session_id=r.get("session_id"),
            created_at=r["created_at"],
            judge_model=r.get("judge_model"),
            metadata=r.get("metadata"),
        )

    @staticmethod
    def _to_dict_internal(rec: DpoRecord) -> Dict[str, Any]:
        return {
            "id": rec.id,
            "fingerprint": rec.fingerprint,
            "prompt": rec.prompt,
            "chosen": rec.chosen,
            "rejected": rec.rejected,
            "source": rec.source,
            "anchor": rec.anchor,
            "quality_score": rec.quality_score,
            "session_id": rec.session_id,
            "created_at": rec.created_at,
            "judge_model": rec.judge_model,
            "metadata": rec.metadata,
        }

    def _load_json(self) -> List[Dict[str, Any]]:
        if os.path.isfile(self._json_path):
            try:
                with open(self._json_path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                return data if isinstance(data, list) else []
            except Exception:
                return []
        return []

    def _save_json(self, rows: List[Dict[str, Any]]) -> None:
        # H15a 同款原子写（参照 trainer/store.py）：先写临时文件再 os.replace 原子替换，
        # 任何进程崩溃点都不会留下半截 JSON（读侧 _load_json 遇损坏会静默回落空列表）。
        tmp_path = f"{self._json_path}.tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(rows, fh, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._json_path)
        except OSError:
            # 写失败时清理残留临时文件后原样抛出（保持写失败可感知语义）
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass
            raise