"""观众弹幕连接器（T3）：可插拔的弹幕源采集连接器。

提供：
- ``DanmakuConnector``：基类（running 标志 + 后台 asyncio task + start/stop）。
- ``RdfConnector``：通用 WebSocket 文本行弹幕源（``username: message`` 或 JSON）。
- ``BilibiliConnector``：bilibili 弹幕源的最小兼容实现（带断线重连）。
- ``create_connector``：工厂，按 ``source_config.type``（none|rdf|bilibili）分发。

用法（互动协调器 toggle_audience 内部装配）::

    connector = create_connector(source_config, on_danmaku=async_cb)
    await connector.start()   # 后台采集
    await connector.stop()    # 取消后台 task

``on_danmaku`` 为 ``async (userid, username, text) -> None`` 回调。
消费端（协调器）负责把弹幕投递进互动房间消息流。
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable, Dict, Optional

import websockets

logger = logging.getLogger(__name__)

# 弹幕回调类型：async (userid, username, text) -> None
DanmakuCallback = Callable[[str, str, str], Awaitable[None]]


def _parse_danmaku_line(raw) -> Optional[tuple]:
    """解析单条弹幕行，返回 (userid, username, text)；解析失败返回 None。

    支持两种格式：
    - JSON：``{"user"|"username", "msg"|"text", "userid"|"uid"?}``
    - 文本行：``username: message``
    """
    stripped = (raw or "").strip()
    if not stripped:
        return None

    if stripped.startswith("{"):
        try:
            obj = json.loads(stripped)
        except (ValueError, TypeError):
            obj = None
        if isinstance(obj, dict):
            text = obj.get("msg") or obj.get("text") or obj.get("message")
            if text:
                userid = str(obj.get("userid") or obj.get("uid") or "")
                username = str(obj.get("username") or obj.get("user") or "")
                return (userid, username, str(text))
        return None

    # 文本行：username: message
    if ":" in stripped:
        name, _, content = stripped.partition(":")
        if content.strip():
            return ("", name.strip(), content.strip())
    return None


class DanmakuConnector:
    """弹幕连接器基类。

    子类实现 ``_parse_line`` 或直接复用基类。基类负责连接生命周期
    （后台 task、running 标志、start/stop 取消兜底、断线重连）。
    """

    MAX_RECONNECT: int = 5  # 断线指数退避重连次数上限

    def __init__(self, url: str, on_danmaku: Optional[DanmakuCallback] = None):
        self.url = url
        self.on_danmaku = on_danmaku
        self.running: bool = False
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """启动后台采集 task（幂等：已在运行则不重复启动）。"""
        if self.running:
            return
        self.running = True
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """停止后台采集 task，取消未完成的连接循环（含异常兜底）。"""
        if not self.running:
            return
        self.running = False
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # 取消/中途异常均吞掉
                pass
        self._task = None

    # ---------------------------------------------------------------- 连接循环
    async def _run(self) -> None:
        """后台主循环：连接 → 逐行读取解析回调 → 断线指数退避重连。"""
        attempt = 0
        while self.running:
            try:
                ws = await websockets.connect(
                    self.url,
                    max_size=None,
                    ping_interval=20,
                    ping_timeout=10,
                )
            except Exception as e:  # 连接失败：退避重试
                logger.warning("弹幕连接器连接失败 %s: %s", self.url, e)
                attempt += 1
                if attempt >= self.MAX_RECONNECT:
                    logger.error("弹幕连接器连续重连失败，退出 %s", self.url)
                    break
                await asyncio.sleep(min(2 ** attempt, 30))
                continue
            attempt = 0
            try:
                async for raw in ws:
                    if not self.running:
                        break
                    await self._dispatch(raw)
            except asyncio.CancelledError:
                raise  # 转发取消，交由 stop() 兜底
            except Exception as e:  # 读取中断：尝试重连
                logger.warning("弹幕连接器读取中断 %s: %s", self.url, e)
            finally:
                try:
                    await ws.close()
                except Exception:  # 关闭失败忽略
                    pass
        self.running = False

    async def _dispatch(self, raw) -> None:
        """解析一行并触发 on_danmaku 回调（回调异常不阻断主循环）。"""
        parsed = self._parse_line(raw)
        if parsed is None:
            return
        userid, username, text = parsed
        if self.on_danmaku is None:
            return
        try:
            await self.on_danmaku(userid, username, text)
        except Exception as e:  # 回调失败仅记录，不阻断采集
            logger.warning("弹幕回调失败: %s", e)

    def _parse_line(self, raw) -> Optional[tuple]:
        """解析单行弹幕；默认走通用解析，子类可覆写。"""
        return _parse_danmaku_line(raw)


class RdfConnector(DanmakuConnector):
    """通用 WebSocket 文本行弹幕连接器（rdf 弹幕源）。

    连接 ``websocket_url``（缺省由工厂按 host/port 构造），逐行读取文本。
    """


class BilibiliConnector(RdfConnector):
    """bilibili 直播弹幕连接器（最小兼容）。

    注：bilibili 专有二进制协议未实现端到端解析，仅按文本/JSON 行做最小兼容。
    建议使用 rdf/通用文本源（配 websocket_url 指向第三方转换网关）。
    自带断线重连（指数退避，最多 ``MAX_RECONNECT`` 次）。
    """


def create_connector(
    source_config: Optional[Dict[str, Any]],
    on_danmaku: Optional[DanmakuCallback] = None,
) -> Optional[DanmakuConnector]:
    """按配置创建弹幕连接器实例。

    Args:
        source_config: 弹幕源配置 dict（含 type/host/port/room_id/websocket_url）。
        on_danmaku: 弹幕回调 async (userid, username, text) -> None。

    Returns:
        对应类型的连接器；``type=="none"`` 返回 None；未知类型抛 ValueError。
    """
    cfg = source_config or {}
    typ = cfg.get("type", "none")

    if typ == "none":
        return None
    if typ == "rdf":
        url = cfg.get("websocket_url") or _default_host_port_url(cfg)
        return RdfConnector(url, on_danmaku)
    if typ == "bilibili":
        url = cfg.get("websocket_url") or _default_bilibili_url(cfg)
        return BilibiliConnector(url, on_danmaku)
    raise ValueError(f"未知弹幕源类型: {typ!r}（支持 none|rdf|bilibili）")


def _default_host_port_url(cfg: Dict[str, Any]) -> str:
    """由 host/port 构造默认 ws 地址。"""
    host = cfg.get("host") or "127.0.0.1"
    port = cfg.get("port") or 8080
    return f"ws://{host}:{port}"


def _default_bilibili_url(cfg: Dict[str, Any]) -> str:
    """由 host/port/room_id 构造 bilibili 默认 ws 地址。"""
    host = cfg.get("host") or "127.0.0.1"
    port = cfg.get("port") or 8080
    room_id = cfg.get("room_id") or ""
    query = f"?room_id={room_id}" if room_id else ""
    return f"ws://{host}:{port}{query}"