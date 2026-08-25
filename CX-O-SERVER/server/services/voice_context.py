"""语音链路上下文（contextvars）：把当前语音会话的 client_id 传给工具执行。

不同客户端连接 = 不同 asyncio task = 不同 context，天然隔离；无语音上下文
（如文本聊天）读到默认 "default"。
"""
from __future__ import annotations

import contextvars
from typing import Optional

_active_client_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "voice_client_id", default="default"
)


def set_active_client_id(client_id: str) -> contextvars.Token:
    """设置当前 task 的语音 client_id，返回 token 供复位。"""
    return _active_client_id.set(client_id)


def reset_active_client_id(token: contextvars.Token) -> None:
    """复位语音 client_id（一般无需手动调用，task 消亡即回收）。"""
    _active_client_id.reset(token)


def get_active_client_id() -> str:
    """读取当前 task 的语音 client_id（默认 "default"）。"""
    return _active_client_id.get()