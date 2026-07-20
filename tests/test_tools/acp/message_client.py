"""ACP 独立消息发送客户端

基于 httpx 同步客户端实现点对点消息发送，作为独立 ACP 节点的消息发送层。

职责：
- 向目标 Agent 的 POST /acp/message 端点投递消息
- 健康检查目标 Agent
- 获取目标 Agent 信息
"""
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

import httpx


class MessageClient:
    """点对点消息发送客户端"""

    def __init__(self, timeout: float = 5.0) -> None:
        self.timeout = timeout
        # trust_env=False + proxy=None：禁用 Windows IE 注册表代理检测
        # （与 tests/test_tools/common/api_client.py 和 server/main.py 入口 monkey-patch 对齐）
        # 详见 .trae/documents/20260719_模块0_CXFC路由注入修复.md 第五章
        self._client = httpx.Client(timeout=timeout, trust_env=False, proxy=None)

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass

    def _base_url(self, host: str, port: int) -> str:
        return f"http://{host}:{port}"

    def send_message(
        self,
        target_host: str,
        target_port: int,
        from_agent_id: str,
        from_agent_name: str,
        to_agent_id: str,
        content: Dict[str, Any],
        msg_type: str = "chat",
        to_group_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """向目标 Agent 发送消息

        Args:
            target_host: 目标 Agent 主机
            target_port: 目标 Agent HTTP 端口
            from_agent_id: 发送方 Agent ID
            from_agent_name: 发送方 Agent 名称
            to_agent_id: 接收方 Agent ID
            content: 消息内容
            msg_type: 消息类型
            to_group_id: 群组 ID（群消息时使用）

        Returns:
            目标 Agent 的响应
        """
        message = {
            "id": str(uuid.uuid4()),
            "msg_type": msg_type,
            "from_agent_id": from_agent_id,
            "from_agent_name": from_agent_name,
            "to_agent_id": to_agent_id,
            "to_group_id": to_group_id,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            "metadata": {},
        }

        url = f"{self._base_url(target_host, target_port)}/acp/message"
        try:
            resp = self._client.post(url, json=message)
            if resp.status_code < 200 or resp.status_code >= 300:
                return {
                    "success": False,
                    "error": f"HTTP {resp.status_code}: {resp.text[:200]}",
                }
            return {"success": True, "response": resp.json(), "message": message}
        except httpx.ConnectError as exc:
            return {"success": False, "error": f"连接失败: {exc}"}
        except httpx.TimeoutException as exc:
            return {"success": False, "error": f"请求超时: {exc}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def send_to_main_system(
        self,
        main_system_host: str,
        main_system_port: int,
        from_agent_id: str,
        from_agent_name: str,
        to_agent_id: str,
        content: Dict[str, Any],
        msg_type: str = "chat",
        from_host: str = "",
        from_port: int = 0,
    ) -> Dict[str, Any]:
        """向主系统发送消息（通过主系统的 /acp/receive 端点）

        Args:
            main_system_host: 主系统主机
            main_system_port: 主系统 HTTP 端口
            from_agent_id: 发送方 Agent ID
            from_agent_name: 发送方 Agent 名称
            to_agent_id: 接收方 Agent ID（主系统的 agent_id）
            content: 消息内容
            msg_type: 消息类型
            from_host: 发送方 HTTP 主机（用于主系统回送消息）
            from_port: 发送方 HTTP 端口（用于主系统回送消息）

        Returns:
            主系统的响应
        """
        message = {
            "id": str(uuid.uuid4()),
            "msg_type": msg_type,
            "from_agent_id": from_agent_id,
            "from_agent_name": from_agent_name,
            "to_agent_id": to_agent_id,
            "to_group_id": None,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            "metadata": {
                "from_host": from_host,
                "from_port": from_port,
            },
        }

        url = f"{self._base_url(main_system_host, main_system_port)}/api/acp/receive"
        try:
            resp = self._client.post(url, json=message)
            if resp.status_code < 200 or resp.status_code >= 300:
                return {
                    "success": False,
                    "error": f"HTTP {resp.status_code}: {resp.text[:200]}",
                }
            return {"success": True, "response": resp.json(), "message": message}
        except httpx.ConnectError as exc:
            return {"success": False, "error": f"连接失败: {exc}"}
        except httpx.TimeoutException as exc:
            return {"success": False, "error": f"请求超时: {exc}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def health_check(self, host: str, port: int) -> Dict[str, Any]:
        """检查目标 Agent 健康状态"""
        url = f"{self._base_url(host, port)}/acp/health"
        try:
            resp = self._client.get(url)
            if resp.status_code < 200 or resp.status_code >= 300:
                return {"success": False, "error": f"HTTP {resp.status_code}"}
            return {"success": True, "info": resp.json()}
        except httpx.ConnectError as exc:
            return {"success": False, "error": f"连接失败: {exc}"}
        except httpx.TimeoutException as exc:
            return {"success": False, "error": f"请求超时: {exc}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def get_agent_info(self, host: str, port: int) -> Dict[str, Any]:
        """获取目标 Agent 信息"""
        url = f"{self._base_url(host, port)}/acp/info"
        try:
            resp = self._client.get(url)
            if resp.status_code < 200 or resp.status_code >= 300:
                return {"success": False, "error": f"HTTP {resp.status_code}"}
            return {"success": True, "info": resp.json()}
        except httpx.ConnectError as exc:
            return {"success": False, "error": f"连接失败: {exc}"}
        except httpx.TimeoutException as exc:
            return {"success": False, "error": f"请求超时: {exc}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}
