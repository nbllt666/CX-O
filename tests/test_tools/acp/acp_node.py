"""ACP 独立节点

整合 UDP 发现 + 消息服务器 + 消息客户端，
作为完整独立的 ACP Agent 运行，不依赖主系统 REST API 中转消息。

职责：
- 启动/停止独立 ACP 节点
- 维护本地消息历史
- 点对点消息发送（直接 HTTP 调用目标 Agent）
- 主系统消息发送（通过 /acp/receive 端点）
- 已知 Agent 列表管理
- 统计信息
"""
import threading
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from .message_client import MessageClient
from .message_server import MessageServer
from .udp_discovery import UDPDiscovery


class ACPNode:
    """独立 ACP 节点

    作为独立 ACP Agent 运行，拥有自己的 agent_id，
    可被其他 ACP Agent 发现，可与其他 ACP Agent 点对点通信。
    """

    def __init__(
        self,
        agent_id: str,
        agent_name: str,
        http_host: str = "0.0.0.0",
        http_port: int = 8505,
        capabilities: Optional[List[str]] = None,
        broadcast_port: int = 9998,
        discovery_port: int = 9999,
        broadcast_address: str = "255.255.255.255",
        discovery_interval: int = 10,
    ) -> None:
        self.agent_id = agent_id
        self.agent_name = agent_name
        self.http_host = http_host
        self.http_port = http_port
        self.capabilities = capabilities or ["chat"]

        self._lock = threading.Lock()
        self._messages: List[Dict[str, Any]] = []
        self._known_agents: Dict[str, Dict[str, Any]] = {}
        self._running = False

        self._discovery = UDPDiscovery(
            agent_id=agent_id,
            agent_name=agent_name,
            http_port=http_port,
            capabilities=self.capabilities,
            broadcast_port=broadcast_port,
            discovery_port=discovery_port,
            broadcast_address=broadcast_address,
            interval=discovery_interval,
            on_agent_discovered=self._on_agent_discovered,
        )

        self._server = MessageServer(
            agent_id=agent_id,
            agent_name=agent_name,
            host=http_host,
            http_port=http_port,
            capabilities=self.capabilities,
            on_message_received=self._on_message_received,
        )

        self._client = MessageClient(timeout=5.0)

    def start(self) -> Dict[str, Any]:
        """启动独立 ACP 节点

        Returns:
            启动结果 {"success": bool, "error": str}
        """
        if self._running:
            return {"success": True, "error": "节点已在运行"}

        try:
            self._server.start()
        except Exception as exc:
            return {"success": False, "error": f"消息服务器启动失败: {exc}"}

        try:
            self._discovery.start()
        except Exception as exc:
            self._server.stop()
            return {"success": False, "error": f"UDP 发现服务启动失败: {exc}"}

        self._running = True
        return {"success": True, "error": ""}

    def stop(self) -> None:
        """停止独立 ACP 节点"""
        self._running = False
        self._discovery.stop()
        self._server.stop()
        self._client.close()

    def is_running(self) -> bool:
        return self._running

    def _on_agent_discovered(self, agent_info: Dict[str, Any]) -> None:
        """UDP 发现新 Agent 的回调"""
        with self._lock:
            existing = self._known_agents.get(agent_info["id"], {})
            if existing.get("is_main_system"):
                agent_info["is_main_system"] = True
            self._known_agents[agent_info["id"]] = agent_info

    def _on_message_received(self, message: Dict[str, Any]) -> None:
        """消息服务器接收消息的回调"""
        with self._lock:
            message["is_sent"] = False
            self._messages.append(message)

    def list_known_agents(self) -> List[Dict[str, Any]]:
        """返回已知 Agent 列表"""
        with self._lock:
            return list(self._known_agents.values())

    def get_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """获取指定 Agent 信息"""
        with self._lock:
            return self._known_agents.get(agent_id)

    def discover_once(self, timeout: float = 5.0) -> List[Dict[str, Any]]:
        """主动发现一次

        在广播本地 BEACON 之前，先尝试触发已知主系统立即广播 BEACON，
        实现双向触发加速发现。主系统未启动或调用失败时静默忽略。
        """
        self._trigger_main_system_discover()

        result = self._discovery.discover_once(timeout=timeout)
        with self._lock:
            for agent in result:
                existing = self._known_agents.get(agent["id"], {})
                if existing.get("is_main_system"):
                    agent["is_main_system"] = True
                self._known_agents[agent["id"]] = agent
        return result

    def _trigger_main_system_discover(self) -> None:
        """触发已知主系统立即广播 BEACON

        查找 self._known_agents 中标记为 is_main_system 的 agent，
        通过 HTTP POST /api/acp/discover 触发主系统立即广播。失败静默。
        """
        with self._lock:
            main_system = None
            for agent in self._known_agents.values():
                if agent.get("is_main_system"):
                    main_system = agent
                    break

        if not main_system:
            return

        host = main_system.get("host", "")
        port = main_system.get("port", 0)
        if not host or not port:
            return

        try:
            url = f"http://{host}:{port}/api/acp/discover"
            self._client._client.post(url, json={}, timeout=2.0)
        except Exception:
            pass

    def send_message(
        self,
        to_agent_id: str,
        content: Dict[str, Any],
        msg_type: str = "chat",
    ) -> Dict[str, Any]:
        """向指定 Agent 发送消息（点对点）

        自动查找目标 Agent 的 host:port，通过 HTTP 直接投递。
        若目标为主系统且未在已知列表中，需调用方先调用 register_main_system 注册。

        Args:
            to_agent_id: 接收方 Agent ID
            content: 消息内容
            msg_type: 消息类型

        Returns:
            发送结果 {"success": bool, "error": str, "message": dict}
        """
        target = self.get_agent(to_agent_id)
        if not target:
            return {"success": False, "error": f"未知 Agent: {to_agent_id}"}

        host = target.get("host", "")
        port = target.get("port", 0)
        if not host or not port:
            return {"success": False, "error": f"Agent {to_agent_id} 缺少 host/port 信息"}

        result = self._client.send_message(
            target_host=host,
            target_port=int(port),
            from_agent_id=self.agent_id,
            from_agent_name=self.agent_name,
            to_agent_id=to_agent_id,
            content=content,
            msg_type=msg_type,
        )

        if result.get("success"):
            with self._lock:
                msg = result["message"].copy()
                msg["is_sent"] = True
                self._messages.append(msg)

        return result

    def send_to_main_system(
        self,
        main_system_host: str,
        main_system_port: int,
        main_system_agent_id: str,
        content: Dict[str, Any],
        msg_type: str = "chat",
    ) -> Dict[str, Any]:
        """向主系统发送消息（通过 /acp/receive 端点）

        Args:
            main_system_host: 主系统主机
            main_system_port: 主系统 HTTP 端口
            main_system_agent_id: 主系统的 Agent ID
            content: 消息内容
            msg_type: 消息类型

        Returns:
            发送结果
        """
        result = self._client.send_to_main_system(
            main_system_host=main_system_host,
            main_system_port=main_system_port,
            from_agent_id=self.agent_id,
            from_agent_name=self.agent_name,
            to_agent_id=main_system_agent_id,
            content=content,
            msg_type=msg_type,
            from_host=self.http_host if self.http_host != "0.0.0.0" else self.get_local_ip(),
            from_port=self.http_port,
        )

        if result.get("success"):
            with self._lock:
                msg = result["message"].copy()
                msg["is_sent"] = True
                self._messages.append(msg)

        return result

    def register_main_system(
        self,
        main_system_host: str,
        main_system_port: int,
        main_system_agent_id: str = "",
        main_system_agent_name: str = "Main System",
    ) -> Dict[str, Any]:
        """手动注册主系统为已知 Agent

        Args:
            main_system_host: 主系统主机
            main_system_port: 主系统 HTTP 端口
            main_system_agent_id: 主系统 Agent ID（若为空则尝试通过 /api/acp/stats 获取）
            main_system_agent_name: 主系统 Agent 名称

        Returns:
            注册结果
        """
        if not main_system_agent_id:
            # 尝试从主系统 ACP stats 获取真实 agent_id
            try:
                stats_resp = self._client._client.get(
                    f"http://{main_system_host}:{main_system_port}/api/acp/stats"
                )
                if stats_resp.status_code == 200:
                    stats_data = stats_resp.json()
                    stats = stats_data.get("statistics", {})
                    if stats.get("local_agent_id"):
                        main_system_agent_id = stats["local_agent_id"]
                    if stats.get("local_agent_name"):
                        main_system_agent_name = stats["local_agent_name"]
            except Exception:
                pass

            # 仍为空则使用回退 ID
            if not main_system_agent_id:
                main_system_agent_id = f"main-{main_system_host}-{main_system_port}"

        agent_info = {
            "id": main_system_agent_id,
            "name": main_system_agent_name,
            "host": main_system_host,
            "port": main_system_port,
            "status": "online",
            "version": "1.0.0",
            "capabilities": ["memory", "tools", "chat"],
            "last_seen": datetime.now().isoformat(),
            "is_main_system": True,
        }

        with self._lock:
            self._known_agents[main_system_agent_id] = agent_info

        return {"success": True, "agent": agent_info}

    def get_messages(
        self,
        agent_id: Optional[str] = None,
        group_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """获取消息历史

        Args:
            agent_id: 筛选与指定 Agent 的对话（双向）
            group_id: 筛选指定群组的消息
            limit: 返回消息数量上限

        Returns:
            消息列表（按时间正序）
        """
        with self._lock:
            messages = list(self._messages)

        if agent_id:
            messages = [
                m for m in messages
                if m.get("from_agent_id") == agent_id or m.get("to_agent_id") == agent_id
            ]
        if group_id:
            messages = [m for m in messages if m.get("to_group_id") == group_id]

        try:
            messages = sorted(messages, key=lambda m: m.get("timestamp", ""))
        except Exception:
            pass

        return messages[-limit:] if limit > 0 else messages

    def get_statistics(self) -> Dict[str, Any]:
        """获取本节点统计信息"""
        with self._lock:
            total_messages = len(self._messages)
            sent_messages = sum(1 for m in self._messages if m.get("is_sent"))
            received_messages = total_messages - sent_messages
            known_agents_count = len(self._known_agents)

        return {
            "local_agent_id": self.agent_id,
            "local_agent_name": self.agent_name,
            "http_port": self.http_port,
            "running": self._running,
            "total_agents": known_agents_count,
            "total_messages": total_messages,
            "messages_sent": sent_messages,
            "messages_received": received_messages,
            "discovery_status": self._discovery.get_status(),
            "server_status": self._server.get_status(),
        }

    def get_local_ip(self) -> str:
        """获取本机 IP"""
        return self._discovery.get_local_ip()

    def health_check_agent(self, agent_id: str) -> Dict[str, Any]:
        """健康检查指定 Agent"""
        target = self.get_agent(agent_id)
        if not target:
            return {"success": False, "error": f"未知 Agent: {agent_id}"}
        return self._client.health_check(target.get("host", ""), int(target.get("port", 0)))
