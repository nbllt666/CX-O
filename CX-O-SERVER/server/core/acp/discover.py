"""ACP 局域网发现——通过 UDP 广播发现局域网络内其他 ACP Agent。"""
import asyncio
import json
import socket
import time
from datetime import datetime
from typing import Dict, List, Tuple

from server.core.logging_config import get_contextual_logger

from .manager import ACPAgentInfo, ACPManager

logger = get_contextual_logger(__name__)


def _recv_beacons_sync(sock, timeout: float) -> List[Tuple[dict, tuple]]:
    """discover_once 的同步收包辅助（仅供 asyncio.to_thread 调度）。

    在超时窗口内循环阻塞 recvfrom，收集所有成功解析的信标消息，返回
    ``[(message_dict, (host, port)), ...]``。语义对齐旧实现：
    - ``socket.timeout`` → 停止收包（超时 break）；
    - 其他收包/解析异常 → 停止收包（旧实现 ``except Exception: break``）；
    - 非 ACP_BEACON 消息照常收集，由 async 侧过滤。
    阻塞式 recvfrom 不得直接运行在事件循环线程上（无信标时最长冻结 5s）。
    """
    collected: List[Tuple[dict, tuple]] = []
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        try:
            data, addr = sock.recvfrom(4096)
        except socket.timeout:
            break
        except Exception:
            break

        try:
            message = json.loads(data.decode())
        except Exception:
            break

        collected.append((message, addr))

    return collected


class ACPLanDiscovery:
    """ACP 局域网发现器，通过 UDP 广播宣告本机 Agent 并监听局域网信标，将发现的 Agent 注册到管理器中。"""

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

        # 可注入的 socket 工厂：默认创建真实 UDP socket。
        # 测试通过覆写为 FakeSocket 工厂实现隔离，避免 monkeypatch 全局
        # socket.socket（Windows ProactorEventLoop 依赖该类型做 isinstance 判断，
        # 全局替换会破坏事件循环自读通道导致协程悬挂）。
        self._socket_factory = socket.socket

    async def start(self):
        """启动发现服务：创建广播/监听 UDP socket 并启动后台发现循环。"""
        if self._running:
            return

        self._running = True

        try:
            self._broadcast_socket = self._socket_factory(
                socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP
            )
            self._broadcast_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            self._broadcast_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._broadcast_socket.settimeout(1)

            self._discovery_socket = self._socket_factory(socket.AF_INET, socket.SOCK_DGRAM)
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
        """停止发现服务：置停运行标记并取消后台发现循环任务。"""
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

            # #21（CX-O问题汇总报告补充批注）: 旧实现 sendto(broadcast_port) 而监听
            # bind(discovery_port)，默认 9998/9999 错位致对端无人监听 9998、UDP 发现失效。
            # 广播目标改为对端实际监听端口 discovery_port（BEACON 携带的 port 字段不变）。
            self._broadcast_socket.sendto(
                json.dumps(message).encode(), (self.broadcast_address, self.discovery_port)
            )
        except Exception as e:
            logger.warning(f"广播失败: {e}")

    async def _scan_network(self):
        if not self._discovery_socket:
            return

        found_agents = []
        local_agent_id = self.acp_manager._local_agent_id

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

                    if agent.id and agent.id != local_agent_id:
                        # M-C 修复: 对比已注册四元组（host/port/version/id），
                        # 无实质变化不重复 register_agent、不触发全量 YAML 落盘。
                        # 注意：仅在锁内做快照比对，注册放锁外——asyncio.Lock
                        # 不可重入，锁内再走 register_agent 会自死锁。
                        async with self.acp_manager._lock:
                            existing = self.acp_manager.agents.get(agent.id)
                            if existing is None:
                                need_register = True
                            else:
                                quad_existing = (
                                    existing.host,
                                    existing.port,
                                    existing.version,
                                    existing.id,
                                )
                                quad_new = (agent.host, agent.port, agent.version, agent.id)
                                need_register = quad_existing != quad_new
                        if need_register:
                            await self.acp_manager.register_agent(agent, persist=False)
                            found_agents.append(agent)
            except BlockingIOError:
                continue
            except Exception:
                break

        if found_agents:
            # 单次落盘：避免每发现一个 agent 触发一次全量 YAML 重写
            await self.acp_manager._save_data()
            logger.info(f"发现 {len(found_agents)} 个Agents")

    async def discover_once(self, timeout: float = 5.0) -> List[Dict]:
        """执行一次主动发现：在指定超时窗口内监听局域网信标，返回发现的 Agent 字典列表。

        M-C 修复: 发现端口被后台发现服务占用时不再回退随机端口盲听（收不到
        定向广播 → 恒空扫描假象），改为抛 RuntimeError 让调用方得 503 类明确错误。
        线程卸载修复: 阻塞 recvfrom 收包段整体经 asyncio.to_thread 在工作线程
        执行（_recv_beacons_sync），无信标时事件循环不再被冻结最长 5s；
        本 async 函数只做 socket 准备、to_thread 调度与结果组装。
        """
        agents: List[Dict] = []

        sock = self._socket_factory(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("", self.discovery_port))
            sock.settimeout(timeout)

            # 阻塞收包段整体卸载到工作线程，返回 [(message, addr), ...]
            received = await asyncio.to_thread(_recv_beacons_sync, sock, timeout)

            found: List[Dict] = []
            for message, addr in received:
                if message.get("type") != "ACP_BEACON":
                    continue

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
                    await self.acp_manager.register_agent(agent, persist=False)
                    found.append(agent.to_dict())

            if found:
                # 单次落盘：避免每个 agent 触发一次全量 YAML 重写
                await self.acp_manager._save_data()

            agents = found
            return agents
        except OSError as exc:
            # M-C 修复: 固定发现端口已被占用（后台发现服务运行中）→ 明确报错，
            # 不再回退随机端口造成恒空扫描的假象。
            raise RuntimeError(
                f"discovery port {self.discovery_port} occupied by background service"
            ) from exc
        finally:
            # 泄漏兜底：任何路径（含 raise）都确保关闭本次临时 socket
            try:
                sock.close()
            except Exception:
                pass

    async def get_local_ip(self) -> str:
        """获取本机局域网 IP，失败时回退到 127.0.0.1。"""
        try:
            s = self._socket_factory(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    def get_status(self) -> Dict:
        """返回发现服务的运行状态与网络端口配置。"""
        return {
            "running": self._running,
            "broadcast_port": self.broadcast_port,
            "discovery_port": self.discovery_port,
            "broadcast_address": self.broadcast_address,
            "interval": self.interval,
        }
