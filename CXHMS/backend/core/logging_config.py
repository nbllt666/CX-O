"""
结构化日志配置模块
提供统一的日志格式和结构化日志支持
"""

import json
import logging
import logging.handlers
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


class StructuredLogFormatter(logging.Formatter):
    """结构化日志格式化器

    输出JSON格式的日志，便于日志收集和分析
    """

    def __init__(self, include_extra: bool = True):
        super().__init__()
        self.include_extra = include_extra

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "thread": record.thread,
            "process": record.process,
        }

        # 添加异常信息
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # 添加额外字段
        if self.include_extra:
            for key, value in record.__dict__.items():
                if key not in {
                    "name",
                    "msg",
                    "args",
                    "levelname",
                    "levelno",
                    "pathname",
                    "filename",
                    "module",
                    "exc_info",
                    "exc_text",
                    "stack_info",
                    "lineno",
                    "funcName",
                    "created",
                    "msecs",
                    "relativeCreated",
                    "thread",
                    "threadName",
                    "processName",
                    "process",
                    "message",
                }:
                    try:
                        # 尝试序列化，如果失败则转为字符串
                        json.dumps({key: value})
                        log_data[key] = value
                    except (TypeError, ValueError):
                        log_data[key] = str(value)

        return json.dumps(log_data, ensure_ascii=False, default=str)


class ColoredConsoleFormatter(logging.Formatter):
    """带颜色的控制台日志格式化器"""

    COLORS = {
        "DEBUG": "\033[36m",  # Cyan
        "INFO": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[35m",  # Magenta
        "RESET": "\033[0m",
    }

    def __init__(self, fmt: str = None, datefmt: str = None):
        super().__init__(fmt, datefmt)
        self.use_colors = sys.platform != "win32" or "ANSICON" in os.environ

    def format(self, record: logging.LogRecord) -> str:
        if self.use_colors:
            color = self.COLORS.get(record.levelname, self.COLORS["RESET"])
            reset = self.COLORS["RESET"]
            record.levelname = f"{color}{record.levelname}{reset}"

        return super().format(record)


def setup_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
    structured: bool = False,
    console_colors: bool = True,
) -> logging.Logger:
    """设置日志配置

    Args:
        level: 日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: 日志文件路径
        max_bytes: 单个日志文件最大大小
        backup_count: 备份文件数量
        structured: 是否使用结构化日志格式
        console_colors: 控制台是否使用颜色

    Returns:
        根日志记录器
    """
    import os

    # 获取日志级别
    log_level = getattr(logging, level.upper(), logging.INFO)

    # 配置根日志记录器
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # 清除现有处理器
    root_logger.handlers.clear()

    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)

    if structured:
        console_formatter = StructuredLogFormatter()
    else:
        if console_colors:
            console_formatter = ColoredConsoleFormatter(
                fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        else:
            console_formatter = logging.Formatter(
                fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )

    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # 文件处理器
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
        )
        file_handler.setLevel(log_level)

        if structured:
            file_formatter = StructuredLogFormatter()
        else:
            file_formatter = logging.Formatter(
                fmt="%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )

        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)

    return root_logger


def get_logger(name: str) -> logging.Logger:
    """获取日志记录器

    Args:
        name: 日志记录器名称

    Returns:
        日志记录器
    """
    return logging.getLogger(name)


class LogContext:
    """日志上下文管理器

    用于添加上下文信息到日志记录

    示例:
        with LogContext(request_id="123", user_id="456"):
            logger.info("处理请求")
    """

    _context_data: Dict[str, Any] = {}

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.previous_context = {}

    def __enter__(self):
        self.previous_context = LogContext._context_data.copy()
        LogContext._context_data.update(self.kwargs)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        LogContext._context_data = self.previous_context
        return False

    @classmethod
    def get_context(cls) -> Dict[str, Any]:
        """获取当前上下文"""
        return cls._context_data.copy()

    @classmethod
    def clear_context(cls):
        """清除上下文"""
        cls._context_data.clear()


class ContextualLogger:
    """上下文感知日志记录器

    自动添加上下文信息到日志记录
    """

    def __init__(self, name: str):
        self.logger = logging.getLogger(name)

    def _log_with_context(self, level: int, msg: str, *args, **kwargs):
        """记录带上下文的日志"""
        # 添加上下文信息
        context = LogContext.get_context()
        if context:
            extra = kwargs.get("extra", {})
            extra.update(context)
            kwargs["extra"] = extra

        self.logger.log(level, msg, *args, **kwargs)

    def debug(self, msg: str, *args, **kwargs):
        self._log_with_context(logging.DEBUG, msg, *args, **kwargs)

    def info(self, msg: str, *args, **kwargs):
        self._log_with_context(logging.INFO, msg, *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs):
        self._log_with_context(logging.WARNING, msg, *args, **kwargs)

    def error(self, msg: str, *args, **kwargs):
        self._log_with_context(logging.ERROR, msg, *args, **kwargs)

    def critical(self, msg: str, *args, **kwargs):
        self._log_with_context(logging.CRITICAL, msg, *args, **kwargs)

    def exception(self, msg: str, *args, **kwargs):
        """记录异常信息"""
        kwargs["exc_info"] = True
        self._log_with_context(logging.ERROR, msg, *args, **kwargs)


def get_contextual_logger(name: str) -> ContextualLogger:
    """获取上下文感知日志记录器

    Args:
        name: 日志记录器名称

    Returns:
        上下文感知日志记录器
    """
    return ContextualLogger(name)
