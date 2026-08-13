"""CXFC 插件发现——探测局域网内可用的 CXFC 插件服务。"""
import asyncio
import json
import socket
from typing import List, Dict, Any, Optional

from server.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)


class CXFCDiscovery:
    """CXFC 插件发现器，通过 UDP 广播宣告自身存在并监听局域网内的插件信标，维护已发现插件列表。"""

    def __init__(
        self,
        broadcast_port: int = 9997,
        discovery_port: int = 9996,
        broadcast_address: str = "255.255.255.255",
        interval: int = 30,
    ):
        self.broadcast_port = broadcast_port
        self.discovery_port = discovery_port
        self.broadcast_address = broadcast_address
        self.interval = interval
        self._broadcast_socket: Optional[socket.socket] = None
        self._discovery_socket: Optional[socket.socket] = None
        self._running = False
        self._discovered: List[Dict[str, Any]] = []
        self._task: Optional[asyncio.Task] = None

    async def start_discovery(
        self,
        local_name: str = "CX-O",
        local_port: int = 8000,
        capabilities: List[str] = None,
    ):
        if self._running:
            return

        self._running = True

        try:
            self._broadcast_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            self._broadcast_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            self._broadcast_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._broadcast_socket.settimeout(1)

            self._discovery_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._discovery_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._discovery_socket.bind(("", self.discovery_port))
            self._discovery_socket.settimeout(1)

            self._task = asyncio.create_task(
                self._discovery_loop(local_name, local_port, capabilities or [])
            )
            logger.info(
                f"CXFC 发现服务已启动: discovery_port={self.discovery_port}, broadcast_port={self.broadcast_port}"
            )
        except Exception as e:
            logger.error(f"启动 CXFC 发现服务失败: {e}")
            await self.stop_discovery()
            raise

    async def _discovery_loop(self, local_name: str, local_port: int, capabilities: List[str]):
        while self._running:
            try:
                await self._broadcast_presence(local_name, local_port, capabilities)
                await self._scan_network()
            except Exception as e:
                logger.warning(f"CXFC 发现循环异常: {e}")

            await asyncio.sleep(self.interval)

    async def _broadcast_presence(self, name: str, port: int, capabilities: List[str]):
        if not self._broadcast_socket:
            return

        try:
            beacon = json.dumps({
                "type": "CXFC_BEACON",
                "name": name,
                "port": port,
                "capabilities": capabilities,
                "version": "1.0.0",
            })
            self._broadcast_socket.sendto(
                beacon.encode(), (self.broadcast_address, self.broadcast_port)
            )
        except Exception as e:
            logger.debug(f"CXFC 广播失败: {e}")

    async def _scan_network(self):
        if not self._discovery_socket:
            return

        found = []
        for _ in range(5):
            try:
                self._discovery_socket.setblocking(False)
                await asyncio.sleep(0.1)
                data, addr = self._discovery_socket.recvfrom(4096)
                beacon = json.loads(data.decode())

                if beacon.get("type") == "CXFC_BEACON":
                    found.append({
                        "host": addr[0],
                        "port": beacon.get("port", 0),
                        "name": beacon.get("name", ""),
                        "capabilities": beacon.get("capabilities", []),
                        "version": beacon.get("version", ""),
                    })
            except BlockingIOError:
                continue
            except Exception:
                break

        if found:
            self._discovered = found
            logger.info(f"CXFC 发现 {len(found)} 个插件")

    async def scan_network(self) -> List[Dict[str, Any]]:
        found = []
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", self.discovery_port))
        sock.settimeout(2.0)

        for _ in range(5):
            try:
                data, addr = sock.recvfrom(4096)
                beacon = json.loads(data.decode())
                if beacon.get("type") == "CXFC_BEACON":
                    found.append({
                        "host": addr[0],
                        "port": beacon.get("port", 0),
                        "name": beacon.get("name", ""),
                        "capabilities": beacon.get("capabilities", []),
                        "version": beacon.get("version", ""),
                    })
            except socket.timeout:
                break
            except Exception:
                continue

        sock.close()
        return found

    def get_discovered(self) -> List[Dict[str, Any]]:
        """返回当前已发现的插件列表。"""
        return self._discovered

    async def stop_discovery(self):
        """停止发现循环，取消后台任务并关闭广播与监听套接字。"""
        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        if self._broadcast_socket:
            self._broadcast_socket.close()
            self._broadcast_socket = None
        if self._discovery_socket:
            self._discovery_socket.close()
            self._discovery_socket = None

        logger.info("CXFC 发现服务已停止")
