import json
import socket
import threading
from typing import Any, Dict, List, Optional

from server.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)


class ServiceDiscovery:
    def __init__(self, multicast_group: str = "224.0.0.1", port: int = 5000):
        self.multicast_group = multicast_group
        self.port = port
        self._services: Dict[str, Dict] = {}
        self._lock = threading.Lock()
        self._running = False

    def register_service(self, service_name: str, host: str, port: int, metadata: Dict = None):
        with self._lock:
            self._services[service_name] = {
                "name": service_name,
                "host": host,
                "port": port,
                "metadata": metadata or {},
            }
            logger.info(f"服务已注册: {service_name} at {host}:{port}")

    def unregister_service(self, service_name: str):
        with self._lock:
            if service_name in self._services:
                del self._services[service_name]
                logger.info(f"服务已注销: {service_name}")

    def discover_service(self, service_name: str) -> Optional[Dict]:
        return self._services.get(service_name)

    def list_services(self) -> List[Dict]:
        with self._lock:
            return list(self._services.values())

    def discover_all(self) -> List[Dict]:
        return self.list_services()

    def start_multicast_discovery(self):
        self._running = True
        logger.info(f"多播服务发现已启动: group={self.multicast_group}, port={self.port}")

    def stop_multicast_discovery(self):
        self._running = False
        logger.info("多播服务发现已停止")