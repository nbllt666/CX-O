"""
服务生命周期管理
提供统一的服务初始化和关闭辅助函数，消除重复的异常处理与日志模式
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


async def init_service(
    name: str,
    factory: Callable[..., Any],
    *,
    logger_: Optional[logging.Logger] = None,
    args: tuple = (),
    kwargs: Optional[dict] = None,
) -> Optional[Any]:
    """
    通用的服务初始化辅助函数，统一异常处理与日志格式。

    Args:
        name: 服务中文名称，用于日志（如 "记忆管理器"）
        factory: 服务工厂函数（同步或异步）
        logger_: 日志记录器，默认使用模块级 logger
        args: 传给 factory 的位置参数
        kwargs: 传给 factory 的关键字参数

    Returns:
        初始化成功返回服务实例，失败返回 None
    """
    log = logger_ or logger
    kwargs = kwargs or {}
    try:
        if asyncio.iscoroutinefunction(factory):
            instance = await factory(*args, **kwargs)
        else:
            instance = factory(*args, **kwargs)
        log.info(f"{name}已启动")
        return instance
    except Exception as e:
        log.warning(f"{name}启动失败: {e}")
        return None


async def shutdown_service(
    name: str,
    coro_or_fn: Callable[..., Any],
    *,
    logger_: Optional[logging.Logger] = None,
    args: tuple = (),
    kwargs: Optional[dict] = None,
) -> None:
    """
    通用的服务关闭辅助函数，统一异常处理与日志格式。

    Args:
        name: 服务中文名称，用于日志（如 "图数据库"）
        coro_or_fn: 关闭函数（同步或异步）
        logger_: 日志记录器
        args: 传给关闭函数的位置参数
        kwargs: 传给关闭函数的关键字参数
    """
    log = logger_ or logger
    kwargs = kwargs or {}
    try:
        if asyncio.iscoroutinefunction(coro_or_fn):
            await coro_or_fn(*args, **kwargs)
        else:
            coro_or_fn(*args, **kwargs)
        log.info(f"{name}已关闭")
    except Exception as e:
        log.warning(f"{name}关闭失败: {e}")
