import json
import logging
import logging.handlers
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


class StructuredLogFormatter(logging.Formatter):
    def __init__(self, include_extra: bool = True):
        super().__init__()
        self.include_extra = include_extra

    def format(self, record: logging.LogRecord) -> str:
        log_data = {"timestamp": datetime.utcnow().isoformat() + "Z", "level": record.levelname, "logger": record.name,
                   "message": record.getMessage(), "module": record.module, "function": record.funcName,
                   "line": record.lineno, "thread": record.thread, "process": record.process}
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        if self.include_extra:
            for key, value in record.__dict__.items():
                if key not in {"name", "msg", "args", "levelname", "levelno", "pathname", "filename", "module",
                              "exc_info", "exc_text", "stack_info", "lineno", "funcName", "created", "msecs",
                              "relativeCreated", "thread", "threadName", "processName", "process", "message"}:
                    try:
                        json.dumps({key: value})
                        log_data[key] = value
                    except (TypeError, ValueError):
                        log_data[key] = str(value)
        return json.dumps(log_data, ensure_ascii=False, default=str)


class ColoredConsoleFormatter(logging.Formatter):
    COLORS = {"DEBUG": "\033[36m", "INFO": "\033[32m", "WARNING": "\033[33m", "ERROR": "\033[31m", "CRITICAL": "\033[35m", "RESET": "\033[0m"}

    def __init__(self, fmt: str = None, datefmt: str = None):
        super().__init__(fmt, datefmt)
        self.use_colors = sys.platform != "win32" or "ANSICON" in os.environ

    def format(self, record: logging.LogRecord) -> str:
        if self.use_colors:
            color = self.COLORS.get(record.levelname, self.COLORS["RESET"])
            reset = self.COLORS["RESET"]
            record.levelname = f"{color}{record.levelname}{reset}"
        return super().format(record)


def setup_logging(level: str = "INFO", log_file: Optional[str] = None, max_bytes: int = 10 * 1024 * 1024,
                 backup_count: int = 5, structured: bool = False, console_colors: bool = True) -> logging.Logger:
    log_level = getattr(logging, level.upper(), logging.INFO)
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    if structured:
        console_formatter = StructuredLogFormatter()
    else:
        if console_colors:
            console_formatter = ColoredConsoleFormatter(fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
        else:
            console_formatter = logging.Formatter(fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")
        file_handler.setLevel(log_level)
        if structured:
            file_formatter = StructuredLogFormatter()
        else:
            file_formatter = logging.Formatter(fmt="%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)
    return root_logger


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


class LogContext:
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
        return cls._context_data.copy()

    @classmethod
    def clear_context(cls):
        cls._context_data.clear()


class ContextualLogger:
    def __init__(self, name: str):
        self.logger = logging.getLogger(name)

    def _log_with_context(self, level: int, msg: str, *args, **kwargs):
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
        kwargs["exc_info"] = True
        self._log_with_context(logging.ERROR, msg, *args, **kwargs)


def get_contextual_logger(name: str) -> ContextualLogger:
    return ContextualLogger(name)