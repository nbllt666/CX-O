"""CX-O-Autonomy 安全层——AuditStore 审计日志存储。

以 JSONL（追加行）方式持久化自主行动审计条目，对齐
public/schema/autonomy_audit.schema.json：
- 必填字段 timestamp / action，缺失时拒绝写入（抛 ValueError）；
- result 枚举 success/failed/blocked/skipped，非法值拒绝；
- cost_tokens 必须为非负整数。

默认路径：server/autonomy/data/audit_logs.jsonl（path 缺省基于 __file__ 绝对路径解析）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

# 默认存储路径：本文件位于 server/autonomy/safety/，parent.parent = server/autonomy
DEFAULT_STORE_PATH = str(Path(__file__).resolve().parent.parent / "data" / "audit_logs.jsonl")

# 对齐 autonomy_audit.schema.json 的 result 枚举
AUDIT_RESULTS = ("success", "failed", "blocked", "skipped")


class AuditStore:
    """审计日志存储（JSONL 追加写，对齐 autonomy_audit.schema.json）。"""

    def __init__(self, path: Optional[str] = None) -> None:
        self.path = path or DEFAULT_STORE_PATH

    def _validate(self, entry: Dict[str, Any]) -> None:
        """校验必要字段与取值，违反时抛 ValueError。"""
        if not isinstance(entry, dict):
            raise TypeError(f"审计条目必须为 dict，收到 {type(entry).__name__}")
        if not entry.get("timestamp"):
            raise ValueError("审计条目缺少必填字段 timestamp")
        if not entry.get("action"):
            raise ValueError("审计条目缺少必填字段 action")
        if "result" in entry and entry["result"] not in AUDIT_RESULTS:
            raise ValueError(f"result 非法值 {entry['result']!r}，可选 {AUDIT_RESULTS}")
        if "cost_tokens" in entry:
            ct = entry["cost_tokens"]
            if not isinstance(ct, int) or isinstance(ct, bool) or ct < 0:
                raise ValueError(f"cost_tokens 必须为非负整数，收到 {ct!r}")

    def append(self, entry: Dict[str, Any]) -> str:
        """校验并追加一条审计日志（JSONL 行），返回写入路径。"""
        self._validate(entry)
        path = Path(self.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return str(path)

    def list(self, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
        """返回审计条目分页列表 {"items": [...], "total": int}。

        按写入顺序返回；limit 为 None 时返回全部；损坏行自动跳过。
        """
        items: List[Dict[str, Any]] = []
        path = Path(self.path)
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        items.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue  # 跳过损坏行
        total = len(items)
        if limit is None:
            sliced = items[offset:]
        else:
            sliced = items[offset: offset + limit]
        return {"items": sliced, "total": total}

    def clear(self) -> None:
        """清空全部审计日志。"""
        path = Path(self.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("")
