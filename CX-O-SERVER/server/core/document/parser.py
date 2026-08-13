"""文档解析器模块。

迁移自 CXHMS: backend/core/document/parser.py
支持从 AnythingLLM attachments 的 data URI 格式解析文档内容为纯文本。
支持格式：PDF、Word(.docx)、TXT、Markdown。

AnythingLLM attachments 格式：
    {"name": "doc.pdf", "mime": "application/anythingllm-document", "contentString": "data:application/pdf;base64,..."}

图片附件（mime: image/*）不在此模块处理，直接传递给 LLM 的 images 参数。
"""

import base64
import io
import logging
import os
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# 单文件大小上限（10MB），防止内存溢出
MAX_DOCUMENT_SIZE = 10 * 1024 * 1024

IMAGE_MIME_PREFIX = "image/"


def parse_data_uri(content_string: str) -> Tuple[str, bytes]:
    """解析 data URI 格式，返回 (mime_type, raw_bytes)。

    Args:
        content_string: data URI 格式字符串，如 "data:application/pdf;base64,JVBERi0xLjQ..."

    Returns:
        (mime_type, raw_bytes): MIME 类型和原始字节内容

    Raises:
        ValueError: 格式无效或超过大小限制
    """
    if not content_string or not content_string.startswith("data:"):
        raise ValueError("contentString 必须是 data URI 格式（以 'data:' 开头）")

    # 解析 data URI: data:<mime>;base64,<payload>
    header, _, payload = content_string.partition(",")
    if not payload:
        raise ValueError("data URI 缺少 payload 部分")

    # 提取 mime 类型
    # header 格式: data:<mime>;base64 或 data:<mime>
    mime_part = header[5:]  # 去掉 "data:"
    mime_type = "application/octet-stream"
    is_base64 = True

    if ";" in mime_part:
        parts = mime_part.split(";")
        mime_type = parts[0]
        is_base64 = "base64" in parts
    else:
        mime_type = mime_part

    # 解码
    if is_base64:
        try:
            raw_bytes = base64.b64decode(payload)
        except Exception as e:
            raise ValueError(f"base64 解码失败: {e}")
    else:
        raw_bytes = payload.encode("utf-8")

    # 大小限制
    if len(raw_bytes) > MAX_DOCUMENT_SIZE:
        raise ValueError(
            f"文档大小 {len(raw_bytes)} 字节超过限制 {MAX_DOCUMENT_SIZE} 字节（10MB）"
        )

    return mime_type, raw_bytes


def _infer_mime_from_name(name: str) -> str:
    """从文件名推断 MIME 类型。"""
    ext = os.path.splitext(name)[1].lower()
    return {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".doc": "application/msword",
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".markdown": "text/markdown",
    }.get(ext, "application/octet-stream")


def parse_document(name: str, mime: str, raw_bytes: bytes) -> str:
    """根据 mime 类型解析文档为纯文本。

    Args:
        name: 文件名（用于推断格式，当 mime 为 application/anythingllm-document 时）
        mime: MIME 类型
        raw_bytes: 原始字节内容

    Returns:
        解析后的纯文本

    Raises:
        ValueError: 不支持的格式或解析失败
    """
    # AnythingLLM 统一标记，需从文件名推断真实格式
    if mime == "application/anythingllm-document":
        mime = _infer_mime_from_name(name)
        logger.info(f"从文件名推断 MIME: {name} -> {mime}")

    if mime == "application/pdf":
        return _parse_pdf(raw_bytes)
    elif mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return _parse_docx(raw_bytes)
    elif mime == "application/msword":
        # .doc 格式（旧版 Word），python-docx 不支持，返回提示
        return f"[不支持解析旧版 .doc 格式: {name}]"
    elif mime in ("text/plain", "text/markdown"):
        return _parse_text(raw_bytes)
    else:
        raise ValueError(f"不支持的文档 MIME 类型: {mime}")


def _parse_pdf(raw_bytes: bytes) -> str:
    """解析 PDF 文档为纯文本。"""
    try:
        from pypdf import PdfReader
    except ImportError:
        raise ValueError("pypdf 未安装，无法解析 PDF。请运行: pip install pypdf")

    try:
        reader = PdfReader(io.BytesIO(raw_bytes))
        texts = []
        for page in reader.pages:
            text = page.extract_text() or ""
            if text:
                texts.append(text)
        return "\n\n".join(texts) if texts else "[PDF 无可提取文本]"
    except Exception as e:
        raise ValueError(f"PDF 解析失败: {e}")


def _parse_docx(raw_bytes: bytes) -> str:
    """解析 Word .docx 文档为纯文本。"""
    try:
        from docx import Document
    except ImportError:
        raise ValueError("python-docx 未安装，无法解析 .docx。请运行: pip install python-docx")

    try:
        doc = Document(io.BytesIO(raw_bytes))
        texts = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n".join(texts) if texts else "[Word 文档无可提取文本]"
    except Exception as e:
        raise ValueError(f"Word 文档解析失败: {e}")


def _parse_text(raw_bytes: bytes) -> str:
    """解析纯文本/Markdown 文档。"""
    try:
        return raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return raw_bytes.decode("gbk")
        except UnicodeDecodeError:
            return raw_bytes.decode("utf-8", errors="replace")


def is_image_attachment(mime: str) -> bool:
    """判断是否为图片附件。"""
    return mime.startswith(IMAGE_MIME_PREFIX)


def parse_attachment(attachment: dict) -> Tuple[Optional[str], Optional[str]]:
    """解析单个附件，返回 (text_content, image_data_url)。

    对于文档附件：返回 (解析后的文本, None)
    对于图片附件：返回 (None, contentString)（直接传递给 LLM）

    Args:
        attachment: AnythingLLM attachment 对象，包含 name、mime、contentString

    Returns:
        (text_content, image_data_url): 文档返回文本，图片返回 data URL

    Raises:
        ValueError: 解析失败
    """
    name = attachment.get("name", "unknown")
    mime = attachment.get("mime", "")
    content_string = attachment.get("contentString", "")

    if not content_string:
        raise ValueError(f"附件 '{name}' 缺少 contentString")

    # 解析 data URI
    actual_mime, raw_bytes = parse_data_uri(content_string)

    # 图片附件：直接返回 data URL
    if is_image_attachment(mime) or is_image_attachment(actual_mime):
        return None, content_string

    # 文档附件：解析为文本
    text = parse_document(name, actual_mime, raw_bytes)
    return text, None


def parse_attachments(attachments: list) -> Tuple[str, list]:
    """解析附件列表，返回 (combined_text, image_urls)。

    Args:
        attachments: AnythingLLM attachments 列表

    Returns:
        (combined_text, image_urls): 合并后的文档文本 + 图片 data URL 列表
    """
    if not attachments:
        return "", []

    texts = []
    images = []
    errors = []

    for i, att in enumerate(attachments):
        try:
            text, image_url = parse_attachment(att)
            if text:
                name = att.get("name", f"document-{i}")
                texts.append(f"--- {name} ---\n{text}")
            if image_url:
                images.append(image_url)
        except ValueError as e:
            name = att.get("name", f"attachment-{i}")
            errors.append(f"[附件 '{name}' 解析失败: {e}]")
            logger.warning(f"附件解析失败: {name} - {e}")

    combined_text = "\n\n".join(texts) if texts else ""
    if errors:
        # 解析错误也作为文本返回，让 LLM 知道
        error_text = "\n".join(errors)
        combined_text = f"{combined_text}\n\n{error_text}" if combined_text else error_text

    return combined_text, images
