"""通用工具函数——共享 HTTP 客户端、深度合并等跨模块复用能力。"""
import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

import httpx


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def format_messages_for_summary(messages: List[Dict], max_content_length: int = 500) -> str:
    lines = []
    for i, msg in enumerate(messages, 1):
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if len(content) > max_content_length:
            content = content[:max_content_length] + "..."
        lines.append(f"[{i}] {role}: {content}")
    return "\n".join(lines)


def _strip_trailing_commas(s: str) -> str:
    """移除对象/数组中的尾随逗号（字符串感知，不破坏字符串内逗号）。

    仅在 json.loads 直接失败时调用，用于处理 LLM 输出的 `{"a": 1,}` 这类噪声。
    """
    out = []
    in_str = False
    escape = False
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        if escape:
            out.append(ch)
            escape = False
            i += 1
            continue
        if in_str:
            out.append(ch)
            if ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
            i += 1
            continue
        if ch == ",":
            j = i + 1
            while j < n and s[j].isspace():
                j += 1
            if j < n and s[j] in "}]":
                i += 1  # 尾随逗号：跳过
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def extract_json(text: Any, default: Any = None) -> Any:
    """从文本中提取并解析 JSON 对象或数组。

    统一处理 LLM 输出的常见噪声：markdown 代码栅栏、前后缀说明文字、
    括号不平衡、尾随逗号等。解析失败返回 default。

    Args:
        text: 含 JSON 的字符串（或已是可解析值）
        default: 解析失败时的回退值

    Returns:
        解析后的 JSON 值；失败返回 default。
    """
    if text is None:
        return default
    if not isinstance(text, str):
        return text
    s = text.strip()
    if not s:
        return default

    # 剥 markdown 代码栅栏
    if s.startswith("```"):
        s = s.strip("`")
        s = s[4:].strip() if s[:4].lower() == "json" else s

    # 直接解析
    try:
        return json.loads(s)
    except (ValueError, TypeError):
        pass

    # 括号平衡提取最外层 JSON 对象/数组（逐字符扫描，正确处理字符串内括号）
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start = s.find(open_ch)
        if start == -1:
            continue
        depth = 0
        in_str = False
        escape = False
        for i in range(start, len(s)):
            ch = s[i]
            if escape:
                escape = False
                continue
            if in_str:
                if ch == "\\":
                    escape = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == open_ch:
                depth += 1
            elif ch == close_ch:
                depth -= 1
                if depth == 0:
                    sub = s[start : i + 1]
                    try:
                        return json.loads(sub)
                    except (ValueError, TypeError):
                        # 尾随逗号等噪声：清理后重试
                        try:
                            return json.loads(_strip_trailing_commas(sub))
                        except (ValueError, TypeError):
                            break
    return default


_shared_http_client: Optional[httpx.AsyncClient] = None


def get_shared_http_client() -> httpx.AsyncClient:
    global _shared_http_client
    if _shared_http_client is None:
        # 显式禁用 Windows 系统代理检测（trust_env=False + proxy=None）
        # 不依赖 main.py 的 monkey-patch（某些导入顺序下 patch 可能未生效）
        # 实测：仅 trust_env=False 仍耗时 7.8s（httpx 内部代理检测残留）；
        # 必须同时 proxy=None 才能降到 ~10ms（与 requests 一致）
        _shared_http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=120.0, write=120.0, pool=10.0),
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10, keepalive_expiry=30.0),
            trust_env=False,
            proxy=None,
        )
    return _shared_http_client


async def close_shared_http_client():
    global _shared_http_client
    if _shared_http_client:
        await _shared_http_client.aclose()
        _shared_http_client = None


async def retry_with_backoff(
    func,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    service_name: str = "Service",
    *args,
    **kwargs
):
    last_exception = None
    for attempt in range(max_retries):
        try:
            return await func(*args, **kwargs)
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout, httpx.ConnectTimeout) as e:
            last_exception = e
            if attempt < max_retries - 1:
                delay = min(base_delay * (2 ** attempt), max_delay)
                logging.getLogger(__name__).warning(f"{service_name} request failed (attempt {attempt + 1}/{max_retries}): {e}. Retrying in {delay:.1f}s...")
                await asyncio.sleep(delay)
            else:
                logging.getLogger(__name__).error(f"{service_name} request failed after {max_retries} attempts: {e}")
                raise
        except httpx.HTTPStatusError as e:
            if e.response.status_code >= 500 and attempt < max_retries - 1:
                delay = min(base_delay * (2 ** attempt), max_delay)
                logging.getLogger(__name__).warning(f"{service_name} server error (attempt {attempt + 1}/{max_retries}): {e}. Retrying in {delay:.1f}s...")
                await asyncio.sleep(delay)
            else:
                raise
        except Exception as e:
            logging.getLogger(__name__).error(f"Unexpected error in {service_name} request: {e}")
            raise
    if last_exception:
        raise last_exception
