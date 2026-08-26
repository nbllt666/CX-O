"""通用工具函数——共享 HTTP 客户端、深度合并、有界 IO 执行器等跨模块复用能力。"""
import asyncio
import json
import logging
import os
import socket
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx


def iso_now() -> str:
    """返回 ISO 8601 带时区（UTC）时间戳。"""
    return datetime.now(timezone.utc).isoformat()


def new_uuid() -> str:
    """生成 UUID v4 字符串。"""
    return str(uuid.uuid4())


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """递归合并两个字典，嵌套字典按 key 逐层合并，override 覆盖 base。"""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def format_messages_for_summary(messages: List[Dict], max_content_length: int = 500) -> str:
    """将消息列表格式化为「序号 角色: 内容」多行文本，超长内容截断。"""
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
    """获取模块级共享的 httpx.AsyncClient 单例（惰性创建，禁用系统代理）。"""
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
            transport=httpx.AsyncHTTPTransport(
                socket_options=[(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)],
            ),
        )
    return _shared_http_client


async def close_shared_http_client():
    """关闭共享 HTTP 客户端并置空，供服务关闭时调用。"""
    global _shared_http_client
    if _shared_http_client:
        await _shared_http_client.aclose()
        _shared_http_client = None


# ============================================================================
# 统一并发原语（语音链路多会话并发治理模块，供 ASR / TTS / 声纹等复用）
# - make_semaphore      : 统一 in-flight 信号量；count<=0 时不限（零侵入默认）
# - make_bounded_queue  : 有界 asyncio.Queue；maxsize<=0 时不限（兼容既有无界默认）
#
# 调用点统一走 acquire/release 或 async with，无论“有信号量”还是“占位不限”，
# 语义都一致：locked()==True 表示当前不可再进入（供“丢弃”模式用）。
# ============================================================================


class _AlwaysAvailable:
    """占位信号量：acquire/release 为空操作、locked() 恒 False，等效“不限并发”。

    使调用点无需为“未配置信号量”分支各自兜底；任何 count 取值（含 0/None）
    下 acquire / release / locked / async with 语义都成立。
    """

    def locked(self) -> bool:
        return False

    async def acquire(self) -> None:
        return None

    def release(self) -> None:
        return None

    async def __aenter__(self) -> "_AlwaysAvailable":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


def make_semaphore(count: Optional[int]):
    """创建统一 in-flight 信号量；``count`` 为 None/<=0 时返回不限并发的占位信号量。

    Args:
        count: 并发上限；None/<=0 表示不限制（保持默认行为零侵入）。

    Returns:
        ``asyncio.Semaphore`` 或 ``_AlwaysAvailable``（不限并发）。
    """
    if count is None or count <= 0:
        return _AlwaysAvailable()
    return asyncio.Semaphore(count)


def make_bounded_queue(maxsize: Optional[int]) -> asyncio.Queue:
    """创建 asyncio 队列；``maxsize`` 为 None/<=0 时返回无界队列（兼容既有默认）。

    Args:
        maxsize: 队列有界上限；None/<=0 表示无界（保持默认行为零侵入）。

    Returns:
        ``asyncio.Queue``；消费者慢于生产者时，有界队列的 ``put`` 会自然背压，
        避免无界堆积。
    """
    if maxsize is None or maxsize <= 0:
        return asyncio.Queue()
    return asyncio.Queue(maxsize=int(maxsize))


async def retry_with_backoff(
    func,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    service_name: str = "Service",
    *args,
    **kwargs
):
    """带指数退避的异步请求重试包装器，对连接/超时/5xx 错误按约定次数重试。"""
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


# ============================================================================
# 有界 IO 执行器
# ----------------------------------------------------------------------------
# 供 async 热路径把同步 sqlite/文件 IO/CPU 段移出事件循环。这是一个进程级共享、
# 有界（并发上限可配置）的线程池。默认行为零侵入：io_pool_size<=0 时按
# min(32, (os.cpu_count() or 4) + 4) 自动取值，不改变既有并发上限。
# ============================================================================

_io_executor: Optional[ThreadPoolExecutor] = None


def get_io_executor() -> ThreadPoolExecutor:
    """获取模块级惰性构造的有界 IO 线程池执行器（单例）。

    池大小取 ``config.executor.io_pool_size``；当该值 <=0（含默认 0）时
    自动回退到 ``min(32, (os.cpu_count() or 4) + 4)``，保持默认行为零侵入。

    Returns:
        共享的 ``concurrent.futures.ThreadPoolExecutor`` 实例。
    """
    global _io_executor
    if _io_executor is None:
        from server.config import get_config

        size = get_config().executor.io_pool_size
        if not size or size <= 0:
            size = min(32, (os.cpu_count() or 4) + 4)
        _io_executor = ThreadPoolExecutor(max_workers=size, thread_name_prefix="cxo-io")
    return _io_executor


def shutdown_io_executor() -> None:
    """关闭有界 IO 线程池（同步，等待在途任务完成），幂等。

    供服务关闭流程调用。用 try…finally 保证在执行器本就不可用时也不抛异常。
    """
    global _io_executor
    ex = _io_executor
    _io_executor = None
    if ex is None:
        return
    try:
        ex.shutdown(wait=True)
    except Exception as e:  # 关闭失败不影响进程退出
        logging.getLogger(__name__).warning(f"关闭 IO 执行器失败: {e}")
    finally:
        pass


async def run_io(func, *args, **kwargs):
    """在共享有界 IO 线程池中异步执行同步函数，返回其结果。

    把阻塞调用（同步 sqlite / 文件 IO / CPU 段）移出事件循环，避免卡住
    asyncio 事件循环。支持位置与关键字参数；内部以闭包转发，线程安全。

    Args:
        func: 需在 IO 线程池执行的同步可调用对象（可为绑定方法）。
        *args / **kwargs: 传给 func 的参数。

    Returns:
        func 的返回值。
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        get_io_executor(), lambda: func(*args, **kwargs)
    )
