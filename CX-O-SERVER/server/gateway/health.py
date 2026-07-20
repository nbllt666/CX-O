"""
健康检查模块
"""
from __future__ import annotations

import time
from typing import Any
from dataclasses import dataclass


@dataclass
class ServiceHealth:
    name: str
    status: str = "unknown"
    last_check: float = 0
    latency_ms: float = 0
    error: str = ""


class HealthChecker:
    def __init__(self):
        self._services: dict[str, ServiceHealth] = {}
        self._check_interval = 30
        self._running = False

    def register_service(self, name: str):
        self._services[name] = ServiceHealth(name=name)

    def update_status(self, name: str, status: str, latency_ms: float = 0, error: str = ""):
        if name in self._services:
            self._services[name].status = status
            self._services[name].last_check = time.time()
            self._services[name].latency_ms = latency_ms
            self._services[name].error = error

    def get_status(self, name: str) -> dict[str, Any] | None:
        if name in self._services:
            s = self._services[name]
            return {
                "name": s.name,
                "status": s.status,
                "last_check": s.last_check,
                "latency_ms": s.latency_ms,
                "error": s.error
            }
        return None

    def get_all_status(self) -> dict[str, Any]:
        return {
            "services": {name: self.get_status(name) for name in self._services},
            "timestamp": time.time()
        }

    def is_healthy(self, name: str) -> bool:
        if name not in self._services:
            return False
        return self._services[name].status == "healthy"

    def all_healthy(self) -> bool:
        return all(self.is_healthy(name) for name in self._services)


health_checker = HealthChecker()
