"""文档处理模块。

迁移自 CXHMS: backend/core/document/
包含：
- parser: 文档解析（PDF/Word/TXT/Markdown）
- memory: DocumentMemoryManager（文档元数据 + 永久记忆持久化）
"""

from server.core.document.memory import DocumentMemoryManager
from server.core.document.parser import (
    MAX_DOCUMENT_SIZE,
    parse_attachment,
    parse_attachments,
    parse_data_uri,
    parse_document,
)

__all__ = [
    "DocumentMemoryManager",
    "MAX_DOCUMENT_SIZE",
    "parse_attachment",
    "parse_attachments",
    "parse_data_uri",
    "parse_document",
]
