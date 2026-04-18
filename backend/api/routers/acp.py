import uuid
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.core.exceptions import ACPError
from backend.core.logging_config import get_contextual_logger

router = APIRouter()
logger = get_contextual_logger(__name__)


class ACPDiscoverRequest(BaseModel):
    """ACP发现请求"""

    timeout: float = 5.0


class ACPConnectRequest(BaseModel):
    """ACP连接请求"""

    agent_id: str
    host: str
    port: int


class ACPGroupCreateRequest(BaseModel):
    """ACP群组创建请求"""

    name: str
    description: str = ""
    max_members: int = 50


class ACPGroupJoinRequest(BaseModel):
    """ACP群组加入请求"""

    group_id: str


class ACPGroupLeaveRequest(BaseModel):
    """ACP群组退出请求"""

    group_id: str


class ACPSendMessageRequest(BaseModel):
    """ACP发送消息请求"""

    to_agent_id: Optional[str] = None
    to_group_id: Optional[str] = None
    content: Dict
    msg_type: str = "chat"


@router.post("/acp/discover")
async def discover_agents(request: ACPDiscoverRequest = None):
    """发现Agents"""
    from backend.api.app import get_acp_manager
    from backend.core.acp.discover import ACPLanDiscovery

    try:
        acp_mgr = get_acp_manager()
        discovery = ACPLanDiscovery(acp_mgr=acp_mgr)
        agents = await discovery.discover_once(timeout=request.timeout if request else 5.0)
        return {
            "status": "success",
            "agents": agents,
            "scanned_count": len(agents),
            "message": f"发现 {len(agents)} 个Agents",
        }
    except ACPError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"发现Agents失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.get("/acp/agents")
async def list_agents(online_only: bool = False):
    from backend.api.app import get_acp_manager

    try:
        acp_mgr = get_acp_manager()
        agents = await acp_mgr.list_agents(online_only=online_only)
        return {"status": "success", "agents": agents, "total": len(agents)}
    except Exception as e:
        logger.error(f"列出Agents失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.post("/acp/connect")
async def connect_to_agent(request: ACPConnectRequest):
    from backend.api.app import get_acp_manager
    from backend.core.acp.manager import ACPConnectionInfo

    try:
        acp_mgr = get_acp_manager()

        connection = ACPConnectionInfo(
            id=str(uuid.uuid4()),
            local_agent_id=acp_mgr._local_agent_id,
            remote_agent_id=request.agent_id,
            remote_agent_name="Remote Agent",
            host=request.host,
            port=request.port,
            status="connecting",
            connected_at=datetime.now().isoformat(),
        )

        await acp_mgr.create_connection(connection)

        return {
            "status": "success",
            "connection": connection.to_dict(),
            "message": "连接请求已发送",
        }
    except Exception as e:
        logger.error(f"连接Agent失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.delete("/acp/connect/{connection_id}")
async def disconnect_from_agent(connection_id: str):
    from backend.api.app import get_acp_manager

    try:
        acp_mgr = get_acp_manager()
        success = await acp_mgr.delete_connection(connection_id)

        if not success:
            raise HTTPException(status_code=404, detail="连接不存在")

        return {"status": "success", "message": "连接已断开"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"断开连接失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.get("/acp/connections")
async def list_connections(local_only: bool = True):
    """列出连接"""
    from backend.api.app import get_acp_manager

    try:
        acp_mgr = get_acp_manager()
        connections = await acp_mgr.list_connections(local_only=local_only)
        return {"status": "success", "connections": connections, "total": len(connections)}
    except ACPError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"列出连接失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.post("/acp/groups")
async def create_group(request: ACPGroupCreateRequest):
    """创建群组"""
    from backend.api.app import get_acp_manager
    from backend.core.acp.group import ACPGroupManager

    try:
        acp_mgr = get_acp_manager()
        group_mgr = ACPGroupManager(acp_mgr)

        group = await group_mgr.create_group(
            name=request.name,
            description=request.description,
            creator_id=acp_mgr._local_agent_id,
            creator_name=acp_mgr._local_agent_name,
            max_members=request.max_members,
        )

        return {"status": "success", "group": group.to_dict(), "message": "群组创建成功"}
    except ACPError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"创建群组失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.get("/acp/groups")
async def list_groups():
    from backend.api.app import get_acp_manager
    from backend.core.acp.group import ACPGroupManager

    try:
        acp_mgr = get_acp_manager()
        group_mgr = ACPGroupManager(acp_mgr)
        groups = await group_mgr.list_groups()

        return {"status": "success", "groups": groups, "total": len(groups)}
    except Exception as e:
        logger.error(f"列出群组失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.post("/acp/groups/{group_id}/join")
async def join_group(group_id: str):
    from backend.api.app import get_acp_manager
    from backend.core.acp.group import ACPGroupManager

    try:
        acp_mgr = get_acp_manager()
        group_mgr = ACPGroupManager(acp_mgr)

        success = await group_mgr.join_group(
            group_id=group_id,
            agent_id=acp_mgr._local_agent_id,
            agent_name=acp_mgr._local_agent_name,
        )

        if not success:
            raise HTTPException(status_code=400, detail="加入群组失败")

        return {"status": "success", "message": "已加入群组"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"加入群组失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.post("/acp/groups/{group_id}/leave")
async def leave_group(group_id: str):
    from backend.api.app import get_acp_manager
    from backend.core.acp.group import ACPGroupManager

    try:
        acp_mgr = get_acp_manager()
        group_mgr = ACPGroupManager(acp_mgr)

        success = await group_mgr.leave_group(group_id=group_id, agent_id=acp_mgr._local_agent_id)

        if not success:
            raise HTTPException(status_code=400, detail="退出群组失败")

        return {"status": "success", "message": "已退出群组"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"退出群组失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.post("/acp/send")
async def send_message(request: ACPSendMessageRequest):
    from backend.api.app import get_acp_manager
    from backend.core.acp.manager import ACPMessageInfo

    try:
        acp_mgr = get_acp_manager()

        message = ACPMessageInfo(
            id=str(uuid.uuid4()),
            msg_type=request.msg_type,
            from_agent_id=acp_mgr._local_agent_id,
            from_agent_name=acp_mgr._local_agent_name,
            to_agent_id=request.to_agent_id,
            to_group_id=request.to_group_id,
            content=request.content,
            timestamp=datetime.now().isoformat(),
            is_sent=True,
        )

        await acp_mgr.send_message(message)

        return {"status": "success", "message_id": message.id, "message": "消息已发送"}
    except Exception as e:
        logger.error(f"发送消息失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.post("/acp/send/group")
async def send_group_message(group_id: str, content: Dict):
    from backend.api.app import get_acp_manager
    from backend.core.acp.group import ACPGroupManager

    try:
        acp_mgr = get_acp_manager()
        group_mgr = ACPGroupManager(acp_mgr)

        message = await group_mgr.broadcast_to_group(
            group_id=group_id,
            from_agent_id=acp_mgr._local_agent_id,
            from_agent_name=acp_mgr._local_agent_name,
            content=content,
        )

        return {"status": "success", "message_id": message.id, "message": "群消息已发送"}
    except Exception as e:
        logger.error(f"发送群消息失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.get("/acp/messages")
async def get_messages(
    agent_id: Optional[str] = None, group_id: Optional[str] = None, limit: int = 50
):
    from backend.api.app import get_acp_manager

    try:
        acp_mgr = get_acp_manager()
        messages = await acp_mgr.get_messages(
            target_id=agent_id or "", group_id=group_id, limit=limit
        )

        return {"status": "success", "messages": messages, "total": len(messages)}
    except Exception as e:
        logger.error(f"获取消息失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.get("/acp/stats")
async def get_acp_stats():
    from backend.api.app import get_acp_manager

    try:
        acp_mgr = get_acp_manager()
        stats = await acp_mgr.get_statistics()

        return {"status": "success", "statistics": stats}
    except Exception as e:
        logger.error(f"获取ACP统计失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")
