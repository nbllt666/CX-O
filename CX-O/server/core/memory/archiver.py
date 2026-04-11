from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from server.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)


@dataclass
class ArchiveRule:
    name: str
    condition: str
    action: str
    enabled: bool = True


@dataclass
class ArchivedMemory:
    memory_id: int
    archived_at: str = field(default_factory=lambda: datetime.now().isoformat())
    archive_reason: str = ""
    archive_location: str = ""


class MemoryArchiver:
    def __init__(self, storage_path: str = "data/archives"):
        self.storage_path = storage_path
        self._archives: Dict[int, ArchivedMemory] = {}
        self._rules: List[ArchiveRule] = []

    def add_archive_rule(self, rule: ArchiveRule):
        self._rules.append(rule)
        logger.info(f"添加归档规则: {rule.name}")

    def archive_memory(self, memory_id: int, reason: str = "") -> ArchivedMemory:
        archived = ArchivedMemory(memory_id=memory_id, archive_reason=reason)
        self._archives[memory_id] = archived
        logger.info(f"记忆已归档: memory_id={memory_id}, reason={reason}")
        return archived

    def restore_memory(self, memory_id: int) -> bool:
        if memory_id in self._archives:
            del self._archives[memory_id]
            logger.info(f"记忆已恢复: memory_id={memory_id}")
            return True
        return False

    def get_archived_memories(self) -> List[ArchivedMemory]:
        return list(self._archives.values())

    def is_archived(self, memory_id: int) -> bool:
        return memory_id in self._archives