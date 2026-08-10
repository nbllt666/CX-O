"""
server/core/logging_config.py 回归测试
结构化日志格式化器、彩色控制台格式化器、日志配置、上下文日志门面
"""
import json
import logging
import sys

import pytest

from server.core.logging_config import (
    ColoredConsoleFormatter,
    ContextualLogger,
    LogContext,
    StructuredLogFormatter,
    get_contextual_logger,
    get_logger,
    setup_logging,
)


def _make_record(msg="hello", level=logging.INFO, name="test"):
    return logging.LogRecord(
        name=name,
        level=level,
        pathname=__file__,
        lineno=42,
        msg=msg,
        args=(),
        exc_info=None,
    )


class TestStructuredLogFormatter:
    def test_basic_fields(self):
        fmt = StructuredLogFormatter()
        out = json.loads(fmt.format(_make_record("hello")))
        assert out["message"] == "hello"
        assert out["level"] == "INFO"
        assert out["logger"] == "test"
        assert out["module"] == "test_logging_config"
        assert "timestamp" in out
        assert out["line"] == 42

    def test_exc_info_included(self):
        fmt = StructuredLogFormatter()
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            record = logging.LogRecord(
                name="t", level=logging.ERROR, pathname=__file__, lineno=1,
                msg="err", args=(), exc_info=sys.exc_info(),
            )
        out = json.loads(fmt.format(record))
        assert "RuntimeError: boom" in out["exception"]

    def test_extra_fields_serialized(self):
        fmt = StructuredLogFormatter()
        record = _make_record()
        record.custom_key = "custom_value"
        record.another = 123
        out = json.loads(fmt.format(record))
        assert out["custom_key"] == "custom_value"
        assert out["another"] == 123

    def test_non_serializable_extra_falls_back_to_str(self):
        fmt = StructuredLogFormatter()
        record = _make_record()
        record.obj = object()  # 不可 JSON 序列化
        out = json.loads(fmt.format(record))
        assert out["obj"] == str(record.obj)

    def test_include_extra_false_omits_extra(self):
        fmt = StructuredLogFormatter(include_extra=False)
        record = _make_record()
        record.custom_key = "custom_value"
        out = json.loads(fmt.format(record))
        assert "custom_key" not in out


class TestColoredConsoleFormatter:
    def test_color_applied_when_use_colors(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        formatter = ColoredConsoleFormatter(fmt="%(levelname)s")
        record = _make_record(level=logging.INFO)
        expected = "\033[32mINFO\033[0m"
        assert formatter.format(record) == expected

    def test_no_color_on_windows_without_ansicon(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.delenv("ANSICON", raising=False)
        formatter = ColoredConsoleFormatter(fmt="%(levelname)s")
        record = _make_record(level=logging.INFO)
        assert formatter.format(record) == "INFO"

    def test_unknown_level_uses_reset_color(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        formatter = ColoredConsoleFormatter(fmt="%(levelname)s")
        record = _make_record(level=logging.DEBUG)
        assert formatter.format(record) == "\033[36mDEBUG\033[0m"


class TestLogContext:
    def test_enter_exit_restores(self):
        assert LogContext.get_context() == {}
        with LogContext(request_id="r1", user_id="u1"):
            assert LogContext.get_context() == {"request_id": "r1", "user_id": "u1"}
            with LogContext(trace="t1"):
                assert LogContext.get_context() == {
                    "request_id": "r1", "user_id": "u1", "trace": "t1",
                }
            # 内层退出后还原
            assert LogContext.get_context() == {"request_id": "r1", "user_id": "u1"}
        # 外层退出后清空
        assert LogContext.get_context() == {}

    def test_get_context_returns_copy(self):
        with LogContext(x=1):
            ctx = LogContext.get_context()
            ctx["x"] = 999
            assert LogContext.get_context() == {"x": 1}

    def test_clear_context(self):
        LogContext._context_data.update({"a": 1})
        LogContext.clear_context()
        assert LogContext.get_context() == {}


class TestContextualLogger:
    def test_injects_context_into_extra(self, caplog):
        logger = ContextualLogger("ctx_test")
        with LogContext(request_id="abc"):
            with caplog.at_level(logging.INFO, logger="ctx_test"):
                logger.info("msg")
        # 底部 logger 用标准 logging 记录，extra 会带上 request_id
        assert any(r.request_id == "abc" for r in caplog.records)

    def test_no_context_does_not_add_extra(self, caplog):
        logger = ContextualLogger("ctx_test2")
        with caplog.at_level(logging.INFO, logger="ctx_test2"):
            logger.info("plain")
        assert all(not hasattr(r, "request_id") for r in caplog.records)

    def test_log_levels_dispatch(self, caplog):
        logger = ContextualLogger("ctx_test3")
        with caplog.at_level(logging.DEBUG, logger="ctx_test3"):
            logger.debug("d")
            logger.warning("w")
            logger.error("e")
            logger.critical("c")
        levels = {r.levelname for r in caplog.records}
        assert {"DEBUG", "WARNING", "ERROR", "CRITICAL"} <= levels

    def test_exception_sets_excinfo(self, caplog):
        logger = ContextualLogger("ctx_test4")
        try:
            raise ValueError("v")
        except ValueError:
            with caplog.at_level(logging.ERROR, logger="ctx_test4"):
                logger.exception("boom")
        assert any(r.exc_info and r.exc_info[1] for r in caplog.records)


class TestSetupLogging:
    def test_returns_root_logger_and_sets_level(self):
        root = setup_logging(level="DEBUG")
        assert root is logging.getLogger()
        assert root.level == logging.DEBUG

    def test_clears_existing_handlers(self):
        root = logging.getLogger()
        root.handlers.clear()
        root.addHandler(logging.StreamHandler())
        before = len(root.handlers)
        setup_logging(level="INFO")
        assert len(root.handlers) == 1  # 仅 console handler
        assert before == 1

    def test_console_handler_structured(self):
        setup_logging(level="INFO", structured=True)
        root = logging.getLogger()
        console = next(h for h in root.handlers if isinstance(h, logging.StreamHandler))
        assert isinstance(console.formatter, StructuredLogFormatter)

    def test_console_handler_colored(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        setup_logging(level="INFO", structured=False, console_colors=True)
        root = logging.getLogger()
        console = next(h for h in root.handlers if isinstance(h, logging.StreamHandler))
        assert isinstance(console.formatter, ColoredConsoleFormatter)

    def test_file_handler_created_with_parent_dirs(self, tmp_path):
        log_file = str(tmp_path / "nested" / "app.log")
        setup_logging(level="INFO", log_file=log_file)
        root = logging.getLogger()
        file_handler = next(
            (h for h in root.handlers if isinstance(h, logging.handlers.RotatingFileHandler)),
            None,
        )
        assert file_handler is not None
        assert file_handler.baseFilename.replace("\\", "/") == log_file.replace("\\", "/")
        # 父目录被创建
        assert (tmp_path / "nested").is_dir()

    def test_file_handler_structured_formatter(self, tmp_path):
        setup_logging(level="INFO", log_file=str(tmp_path / "app.log"), structured=True)
        root = logging.getLogger()
        file_handler = next(
            (h for h in root.handlers if isinstance(h, logging.handlers.RotatingFileHandler)),
            None,
        )
        assert isinstance(file_handler.formatter, StructuredLogFormatter)


def test_get_logger_returns_named_logger():
    assert get_logger("my.logger").name == "my.logger"


def test_get_contextual_logger_returns_contextual():
    assert isinstance(get_contextual_logger("x"), ContextualLogger)