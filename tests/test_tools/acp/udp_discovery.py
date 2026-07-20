"""ACP 独立 UDP 发现模块

基于主系统 backend/core/acp/discover.py 的协议格式，
实现独立的 UDP BEACON 广播与接收，作为独立 ACP 节点的发现层。

协议约定：
- BEACON 广播端口 9998（发送）
- BEACON 接收端口 9999（接收）
- BEACON 格式与主系统兼容，port 字段表示 HTTP 消息服务器端口
"""
import json
import socket
import threading
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional


BEACON_TYPE = "ACP_BEACON"
DEFAULT_BROADCAST_PORT = 9998
DEFAULT_DISCOVERY_PORT = 9999
DEFAULT_BROADCAST_ADDR = "255.255.255.255"
DEFAULT_INTERVAL = 10  # 秒


class UDPDiscovery:
    """独立 UDP 发现服务

    负责广播本地 Agent 的 BEACON，并接收其他 Agent 的 BEACON。
    发现的其他 Agent 通过回调通知上层。
    """

    def __init__(
        self,
        agent_id: str,
        agent_name: str,
        http_port: int,
        capabilities: List[str],
        broadcast_port: int = DEFAULT_BROADCAST_PORT,
        discovery_port: int = DEFAULT_DISCOVERY_PORT,
        broadcast_address: str = DEFAULT_BROADCAST_ADDR,
        interval: int = DEFAULT_INTERVAL,
        on_agent_discovered: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        self.agent_id = agent_id
        self.agent_name = agent_name
        self.http_port = http_port
        self.capabilities = list(capabilities)
        self.broadcast_port = broadcast_port
        self.discovery_port = discovery_port
        self.broadcast_address = broadcast_address
        self.interval = interval
        self.on_agent_discovered = on_agent_discovered

        self._running = False
        self._broadcast_thread: Optional[threading.Thread] = None
        self._listen_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        self._broadcast_socket: Optional[socket.socket] = None
        self._listen_socket: Optional[socket.socket] = None

        self._known_agents: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def start(self) -> None:
        """启动 UDP 发现服务（广播 + 监听）"""
        if self._running:
            return
        self._running = True
        self._stop_event.clear()

        self._broadcast_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self._broadcast_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self._broadcast_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        self._listen_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self._listen_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._listen_socket.bind(("", self.discovery_port))
        except OSError as exc:
            raise RuntimeError(
                f"无法绑定 UDP 发现端口 {self.discovery_port}: {exc}。"
                f"可能主系统已占用该端口，请在独立模式下确保端口可用。"
            ) from exc
        self._listen_socket.settimeout(1.0)

        self._broadcast_thread = threading.Thread(target=self._broadcast_loop, daemon=True)
        self._listen_thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._broadcast_thread.start()
        self._listen_thread.start()

    def stop(self) -> None:
        """停止 UDP 发现服务"""
        self._running = False
        self._stop_event.set()

        if self._broadcast_socket:
            try:
                self._broadcast_socket.close()
            except Exception:
                pass
            self._broadcast_socket = None

        if self._listen_socket:
            try:
                self._listen_socket.close()
            except Exception:
                pass
            self._listen_socket = None

        if self._broadcast_thread:
            self._broadcast_thread.join(timeout=2.0)
            self._broadcast_thread = None

        if self._listen_thread:
            self._listen_thread.join(timeout=2.0)
            self._listen_thread = None

    def _build_beacon(self) -> bytes:
        message = {
            "type": BEACON_TYPE,
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "timestamp": datetime.now().isoformat(),
            "version": "1.0.0",
            "capabilities": self.capabilities,
            "port": self.http_port,
        }
        return json.dumps(message).encode("utf-8")

    def _broadcast_loop(self) -> None:
        while self._running and not self._stop_event.is_set():
            try:
                if self._broadcast_socket:
                    payload = self._build_beacon()
                    # 发送目标端口 = 监听端口 = discovery_port（9999），
                    # 保证两端绑定同一端口的 socket 都能收到广播包副本
                    self._broadcast_socket.sendto(
                        payload, (self.broadcast_address, self.discovery_port)
                    )
            except Exception:
                pass
            self._stop_event.wait(self.interval)

    def _listen_loop(self) -> None:
        while self._running and not self._stop_event.is_set():
            try:
                if not self._listen_socket:
                    break
                try:
                    data, addr = self._listen_socket.recvfrom(4096)
                except socket.timeout:
                    continue
                except OSError:
                    break

                try:
                    message = json.loads(data.decode("utf-8"))
                except Exception:
                    continue

                if message.get("type") != BEACON_TYPE:
                    continue

                agent_id = message.get("agent_id", "")
                if not agent_id or agent_id == self.agent_id:
                    continue

                agent_info = {
                    "id": agent_id,
                    "name": message.get("agent_name", ""),
                    "host": addr[0],
                    "port": message.get("port", 0),
                    "status": "online",
                    "version": message.get("version", "1.0.0"),
                    "capabilities": message.get("capabilities", []),
                    "last_seen": message.get("timestamp", datetime.now().isoformat()),
                }

                with self._lock:
                    is_new = agent_id not in self._known_agents
                    self._known_agents[agent_id] = agent_info

                if is_new and self.on_agent_discovered:
                    try:
                        self.on_agent_discovered(agent_info)
                    except Exception:
                        pass
            except Exception:
                continue

    def list_known_agents(self) -> List[Dict[str, Any]]:
        """返回已知 Agent 列表"""
        with self._lock:
            return list(self._known_agents.values())

    def get_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """获取指定 Agent 信息"""
        with self._lock:
            return self._known_agents.get(agent_id)

    def discover_once(self, timeout: float = 5.0) -> List[Dict[str, Any]]:
        """主动发现一次：广播 BEACON 并等待响应

        在独立节点已启动的情况下，此方法触发一次额外广播并等待 timeout 秒收集响应。
        """
        if not self._broadcast_socket:
            return []

        try:
            payload = self._build_beacon()
            self._broadcast_socket.sendto(
                payload, (self.broadcast_address, self.discovery_port)
            )
        except Exception:
            pass

        end_time = time.time() + timeout
        while time.time() < end_time:
            self._stop_event.wait(0.5)

        return self.list_known_agents()

    def get_local_ip(self) -> str:
        """获取本机 IP 地址"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    def get_status(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "http_port": self.http_port,
            "broadcast_port": self.broadcast_port,
            "discovery_port": self.discovery_port,
            "known_agents_count": len(self._known_agents),
        }
