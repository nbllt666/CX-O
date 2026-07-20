import asyncio
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
