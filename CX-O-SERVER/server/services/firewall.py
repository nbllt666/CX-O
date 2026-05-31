"""
弹幕防火墙
"""
import asyncio
import json
import logging
import re
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class FirewallConfig:
    enabled: bool = True
    max_messages_per_second: float = 5.0
    max_messages_per_minute: int = 100
    duplicate_threshold: int = 3
    duplicate_window_seconds: int = 30
    min_message_length: int = 1
    max_message_length: int = 500
    blocked_patterns: list[str] = field(default_factory=list)
    blocked_users: list[str] = field(default_factory=list)
    keyword_filter_enabled: bool = True
    rate_limit_enabled: bool = True
    duplicate_filter_enabled: bool = True
    length_filter_enabled: bool = True
    user_filter_enabled: bool = True
    pattern_filter_enabled: bool = True


@dataclass
class FilterResult:
    allowed: bool
    reason: str = ""
    filtered_content: str = ""
    original_content: str = ""


class FirewallService:
    _instance = None

    def __init__(self):
        self.config = FirewallConfig()
        self._context_manager: Any = None
        self._message_timestamps: deque = deque(maxlen=1000)
        self._user_message_counts: dict[str, deque] = {}
        self._recent_messages: deque = deque(maxlen=100)
        self._compiled_patterns: list[re.Pattern] = []
        self._keyword_cache: set[str] = set()
        self._filter_callback: Optional[Callable] = None

    @classmethod
    def get_instance(cls) -> "FirewallService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def set_context_manager(self, context_manager: Any):
        self._context_manager = context_manager

    def set_config(self, config: dict):
        if "enabled" in config:
            self.config.enabled = config["enabled"]
        if "max_messages_per_second" in config:
            self.config.max_messages_per_second = config["max_messages_per_second"]
        if "max_messages_per_minute" in config:
            self.config.max_messages_per_minute = config["max_messages_per_minute"]
        if "duplicate_threshold" in config:
            self.config.duplicate_threshold = config["duplicate_threshold"]
        if "duplicate_window_seconds" in config:
            self.config.duplicate_window_seconds = config["duplicate_window_seconds"]
        if "min_message_length" in config:
            self.config.min_message_length = config["min_message_length"]
        if "max_message_length" in config:
            self.config.max_message_length = config["max_message_length"]
        if "blocked_patterns" in config:
            self.config.blocked_patterns = config["blocked_patterns"]
            self._compile_patterns()
        if "blocked_users" in config:
            self.config.blocked_users = config["blocked_users"]
        if "keyword_filter_enabled" in config:
            self.config.keyword_filter_enabled = config["keyword_filter_enabled"]
        if "rate_limit_enabled" in config:
            self.config.rate_limit_enabled = config["rate_limit_enabled"]
        if "duplicate_filter_enabled" in config:
            self.config.duplicate_filter_enabled = config["duplicate_filter_enabled"]
        if "length_filter_enabled" in config:
            self.config.length_filter_enabled = config["length_filter_enabled"]
        if "user_filter_enabled" in config:
            self.config.user_filter_enabled = config["user_filter_enabled"]
        if "pattern_filter_enabled" in config:
            self.config.pattern_filter_enabled = config["pattern_filter_enabled"]

    def _compile_patterns(self):
        self._compiled_patterns = []
        for pattern_str in self.config.blocked_patterns:
            try:
                self._compiled_patterns.append(re.compile(pattern_str))
            except re.error as e:
                logger.error(f"Invalid pattern '{pattern_str}': {e}")

    def filter_message(self, content: str, user_id: str = "", username: str = "") -> FilterResult:
        if not self.config.enabled:
            return FilterResult(
                allowed=True,
                filtered_content=content,
                original_content=content
            )

        original_content = content

        if self.config.length_filter_enabled:
            if len(content) < self.config.min_message_length:
                return FilterResult(
                    allowed=False,
                    reason=f"Message too short (min: {self.config.min_message_length})",
                    original_content=original_content
                )
            if len(content) > self.config.max_message_length:
                return FilterResult(
                    allowed=False,
                    reason=f"Message too long (max: {self.config.max_message_length})",
                    original_content=original_content
                )

        if self.config.user_filter_enabled and user_id:
            if user_id in self.config.blocked_users:
                return FilterResult(
                    allowed=False,
                    reason=f"User blocked: {user_id}",
                    original_content=original_content
                )

        if self.config.rate_limit_enabled:
            now = time.time()
            self._message_timestamps.append(now)

            recent_count = sum(
                1 for t in self._message_timestamps
                if now - t < 1.0
            )
            if recent_count > self.config.max_messages_per_second:
                return FilterResult(
                    allowed=False,
                    reason="Rate limit exceeded (per second)",
                    original_content=original_content
                )

            if user_id:
                expired_users = [
                    uid for uid, timestamps in self._user_message_counts.items()
                    if not timestamps or now - timestamps[-1] > 60.0
                ]
                for uid in expired_users:
                    del self._user_message_counts[uid]

                if user_id not in self._user_message_counts:
                    self._user_message_counts[user_id] = deque(maxlen=100)
                self._user_message_counts[user_id].append(now)

                user_recent = sum(
                    1 for t in self._user_message_counts[user_id]
                    if now - t < 60.0
                )
                if user_recent > self.config.max_messages_per_minute:
                    return FilterResult(
                        allowed=False,
                        reason=f"User rate limit exceeded: {user_id}",
                        original_content=original_content
                    )

        if self.config.duplicate_filter_enabled:
            now = time.time()
            duplicate_count = sum(
                1 for msg in self._recent_messages
                if msg["content"] == content and now - msg["time"] < self.config.duplicate_window_seconds
            )
            if duplicate_count >= self.config.duplicate_threshold:
                return FilterResult(
                    allowed=False,
                    reason="Duplicate message",
                    original_content=original_content
                )

            self._recent_messages.append({"content": content, "time": now})

        if self.config.pattern_filter_enabled:
            for pattern in self._compiled_patterns:
                if pattern.search(content):
                    return FilterResult(
                        allowed=False,
                        reason=f"Blocked pattern matched",
                        original_content=original_content
                    )

        if self.config.keyword_filter_enabled and self._keyword_cache:
            for keyword in self._keyword_cache:
                if keyword in content.lower():
                    return FilterResult(
                        allowed=False,
                        reason=f"Blocked keyword: {keyword}",
                        original_content=original_content
                    )

        return FilterResult(
            allowed=True,
            filtered_content=content,
            original_content=original_content
        )

    def add_keyword(self, keyword: str):
        self._keyword_cache.add(keyword.lower())

    def remove_keyword(self, keyword: str):
        self._keyword_cache.discard(keyword.lower())

    def get_stats(self) -> dict:
        return {
            "enabled": self.config.enabled,
            "keywords_count": len(self._keyword_cache),
            "patterns_count": len(self._compiled_patterns),
            "blocked_users_count": len(self.config.blocked_users),
            "recent_messages_tracked": len(self._recent_messages)
        }


def get_firewall_service() -> FirewallService:
    return FirewallService.get_instance()
