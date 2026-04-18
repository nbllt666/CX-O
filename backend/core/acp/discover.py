import asyncio
import json
import socket
from datetime import datetime
from typing import Any, Dict, List, Optional

from backend.core.logging_config import get_contextual_logger

from .manager import ACPAgentInfo, ACPManager

logger = get_contextual_logger(__name__)


class ACPLanDiscovery:
    def __init__(
        self,
        acp_manager: ACPManager,
        broadcast_port: int = 9998,
        discovery_port: int = 9999,
        broadcast_address: str = "255.255.255.255",
        interval: int = 30,
    ):
        self.acp_manager = acp_manager
        self.broadcast_port = broadcast_port
        self.discovery_port = discovery_port
        self.broadcast_address = broadcast_address
        self.interval = interval

        self._running = False
        self._broadcast_socket = None
        self._discovery_socket = None
        self._task = None

    async def start(self):
        if self._running:
            return

        self._running = True

        try:
            self._broadcast_socket = socket.socket(
                socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP
            )
            self._broadcast_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            self._broadcast_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._broadcast_socket.settimeout(1)

            self._discovery_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._discovery_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._discovery_socket.bind(("", self.discovery_port))
            self._discovery_socket.settimeout(1)

            self._task = asyncio.create_task(self._discovery_loop())
            logger.info(
                f"局域网发现服务已启动: discovery_port={self.discovery_port}, broadcast_port={self.broadcast_port}"
            )
        except Exception as e:
            logger.error(f"启动局域网发现服务失败: {e}")
            await self.stop()
            raise

    async def stop(self):
        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        if self._broadcast_socket:
            self._broadcast_socket.close()
        if self._discovery_socket:
            self._discovery_socket.close()

        logger.info("局域网发现服务已停止")

    async def _discovery_loop(self):
        while self._running:
            try:
                await self._broadcast_presence()
                await self._scan_network()
            except Exception as e:
                logger.warning(f"发现循环异常: {e}")

            await asyncio.sleep(self.interval)

    async def _broadcast_presence(self):
        if not self._broadcast_socket:
            return

        try:
            agent_info = self.acp_manager._local_agent_id
            agent_name = self.acp_manager._local_agent_name

            message = {
                "type": "ACP_BEACON",
                "agent_id": agent_info,
                "agent_name": agent_name,
                "timestamp": datetime.now().isoformat(),
                "version": "1.0.0",
                "capabilities": ["memory", "tools", "chat"],
                "port": self.discovery_port,
            }

            self._broadcast_socket.sendto(
                json.dumps(message).encode(), (self.broadcast_address, self.broadcast_port)
            )
        except Exception as e:
            logger.warning(f"广播失败: {e}")

    async def _scan_network(self):
        if not self._discovery_socket:
            return

        found_agents = []

        for _ in range(5):
            try:
                self._discovery_socket.setblocking(False)
                await asyncio.sleep(0.1)
                data, addr = self._discovery_socket.recvfrom(4096)
                message = json.loads(data.decode())

                if message.get("type") == "ACP_BEACON":
                    agent = ACPAgentInfo(
                        id=message.get("agent_id", ""),
                        name=message.get("agent_name", ""),
                        host=addr[0],
                        port=message.get("port", 0),
                        status="online",
                        version=message.get("version", "1.0.0"),
                        capabilities=message.get("capabilities", []),
                        last_seen=message.get("timestamp", datetime.now().isoformat()),
                    )

                    if agent.id and agent.id != self.acp_manager._local_agent_id:
                        await self.acp_manager.register_agent(agent)
                        found_agents.append(agent)
            except BlockingIOError:
                continue
            except Exception as e:
                break

        if found_agents:
            logger.info(f"发现 {len(found_agents)} 个Agents")

    async def discover_once(self, timeout: float = 5.0) -> List[Dict]:
        agents = []

        async def receive_with_timeout():
            found = []
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("", self.discovery_port))
            sock.settimeout(timeout)

            end_time = asyncio.get_event_loop().time() + timeout

            while asyncio.get_event_loop().time() < end_time:
                try:
                    data, addr = sock.recvfrom(4096)
                    message = json.loads(data.decode())

                    if message.get("type") == "ACP_BEACON":
                        agent = ACPAgentInfo(
                            id=message.get("agent_id", ""),
                            name=message.get("agent_name", ""),
                            host=addr[0],
                            port=message.get("port", 0),
                            status="online",
                            version=message.get("version", "1.0.0"),
                            capabilities=message.get("capabilities", []),
                            last_seen=message.get("timestamp", datetime.now().isoformat()),
                        )

                        if agent.id and agent.id != self.acp_manager._local_agent_id:
                            await self.acp_manager.register_agent(agent)
                            found.append(agent.to_dict())
                except socket.timeout:
                    break
                except Exception as e:
                    break

            sock.close()
            return found

        agents = await receive_with_timeout()
        return agents

    async def get_local_ip(self) -> str:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    def get_status(self) -> Dict:
        return {
            "running": self._running,
            "broadcast_port": self.broadcast_port,
            "discovery_port": self.discovery_port,
            "broadcast_address": self.broadcast_address,
            "interval": self.interval,
        }
