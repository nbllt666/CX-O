"""备份单元枚举与同步策略注册。

unit enum: memory / persona / config / graph / session / autonomy / vector
strategy:  memory, session        -> incremental
          persona, config         -> incremental
          graph, autonomy         -> snapshot
          vector                  -> rebuild（接收端本地重建，不跨机同步）
"""
from __future__ import annotations

from dataclasses import dataclass

UNIT_REGISTRY: dict[str, str] = {
    "memory": "incremental",
    "session": "incremental",
    "persona": "incremental",
    "config": "incremental",
    "ref_audio": "incremental",
    "graph": "snapshot",
    "autonomy": "snapshot",
    "vector": "rebuild",
}


@dataclass
class BackupUnit:
    """对齐 public/schema/cluster_backup_unit.schema.json。"""

    unit: str = ""
    strategy: str = "incremental"
    last_applied_seq: int = 0

    def describe(self) -> dict:
        return {"unit": self.unit, "strategy": self.strategy}


def describe(unit: str) -> dict:
    """返回 {unit, strategy}。未注册单元默认 incremental。"""
    strategy = UNIT_REGISTRY.get(unit, "incremental")
    return {"unit": unit, "strategy": strategy}