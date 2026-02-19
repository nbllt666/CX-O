from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.core.exceptions import ToolError
from backend.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)

router = APIRouter()


class ToolRegisterRequest(BaseModel):
    """工具注册请求"""

    name: str
    description: str
    parameters: Dict
    enabled: bool = True
    version: str = "1.0.0"
    category: str = "general"
    tags: List[str] = []
    examples: List[str] = []
    # 前端兼容字段
    type: Optional[str] = None  # 映射到 category
    icon: Optional[str] = None  # 可选图标
    config: Optional[Dict] = None  # 额外配置


class ToolCallRequest(BaseModel):
    """工具调用请求"""

    name: str
    arguments: Dict = {}


class MCPServerAddRequest(BaseModel):
    """MCP服务器添加请求"""

    name: str
    command: str
    args: List[str] = []
    env: Dict = {}


class MCPServerStartRequest(BaseModel):
    """MCP服务器启动请求"""

    name: str


class MCPServerStopRequest(BaseModel):
    """MCP服务器停止请求"""

    name: str


class MCPToolCallRequest(BaseModel):
    """MCP工具调用请求"""

    server_name: str
    tool_name: str
    arguments: Dict = {}


@router.get("/tools")
async def list_tools(
    enabled_only: bool = True, include_builtin: bool = False, category: str = None
):
    """列出工具"""
    from backend.core.tools.registry import BUILTIN_TOOL_NAMES, tool_registry

    try:
        tools = tool_registry.list_tools_dict(enabled_only, include_builtin)

        # 按 category 过滤
        if category:
            tools = {k: v for k, v in tools.items() if v.get("category") == category}

        # 添加 type 字段（用于前端兼容）
        for name, tool in tools.items():
            if name in BUILTIN_TOOL_NAMES:
                tool["type"] = "builtin"
            elif tool.get("category") == "mcp":
                tool["type"] = "mcp"
            else:
                tool["type"] = "custom"
            tool["status"] = "active" if tool.get("enabled", True) else "inactive"

        stats = tool_registry.get_tool_stats()
        return {"status": "success", "tools": tools, "statistics": stats}
    except ToolError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"列出工具失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.post("/tools")
async def register_tool(request: ToolRegisterRequest):
    from backend.core.tools.registry import tool_registry

    try:
        # 处理前端 type 字段映射到 category
        category = request.category
        if request.type and request.type != request.category:
            # 如果提供了 type 且与 category 不同，使用 type 作为 category
            if request.type in ["mcp", "native", "custom", "builtin"]:
                category = request.type

        tool_registry.register(
            name=request.name,
            description=request.description,
            parameters=request.parameters,
            enabled=request.enabled,
            version=request.version,
            category=category,
            tags=request.tags,
            examples=request.examples,
        )
        return {"status": "success", "message": f"工具 {request.name} 注册成功"}
    except ToolError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"注册工具失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.get("/tools/stats")
async def get_tool_stats():
    from backend.core.tools.registry import BUILTIN_TOOL_NAMES, tool_registry

    try:
        stats = tool_registry.get_tool_stats()

        # 计算 MCP 和原生工具数量
        mcp_tools = 0
        native_tools = 0
        for tool in tool_registry.list_tools(enabled_only=False):
            if tool.category == "mcp":
                mcp_tools += 1
            elif tool.name in BUILTIN_TOOL_NAMES:
                native_tools += 1
            else:
                native_tools += 1

        # 添加前端需要的字段名
        stats["active_tools"] = stats.get("enabled_tools", 0)
        stats["mcp_tools"] = mcp_tools
        stats["native_tools"] = native_tools

        return {"status": "success", "statistics": stats}
    except ToolError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"获取工具统计失败: {e}", exc_info=True)
        import traceback

        logger.error(f"详细堆栈: {traceback.format_exc()}")
        return {
            "status": "success",
            "statistics": {
                "total_tools": 0,
                "enabled_tools": 0,
                "active_tools": 0,
                "disabled_tools": 0,
                "mcp_tools": 0,
                "native_tools": 0,
                "total_calls": 0,
                "by_category": {},
                "top_tools": [],
            },
        }


@router.post("/tools/call")
async def call_tool(request: ToolCallRequest):
    """调用工具"""
    from backend.core.tools.registry import tool_registry

    try:
        result = tool_registry.call_tool(request.name, request.arguments)
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    except ToolError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"调用工具失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


class ToolTestRequest(BaseModel):
    """工具测试请求"""

    arguments: Dict = {}


@router.post("/tools/{name}/test")
async def test_tool(name: str, request: ToolTestRequest):
    """测试工具"""
    from backend.core.tools.registry import tool_registry

    try:
        tool = tool_registry.get_tool(name)
        if not tool:
            raise HTTPException(status_code=404, detail=f"工具 {name} 不存在")

        result = tool_registry.call_tool(name, request.arguments)
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error", "调用失败"))

        return {
            "status": "success",
            "tool_name": name,
            "arguments": request.arguments,
            "result": result.get("result"),
            "message": f"工具 {name} 测试成功",
        }
    except ToolError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"测试工具失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"测试失败: {str(e)}")


@router.get("/tools/openai")
async def get_openai_functions(enabled_only: bool = True):
    """获取OpenAI格式的工具列表"""
    from backend.core.tools.registry import tool_registry

    try:
        functions = tool_registry.list_openai_functions(enabled_only)
        return {"status": "success", "functions": functions}
    except ToolError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"获取OpenAI工具失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.post("/tools/export")
async def export_tools():
    from backend.core.tools.registry import tool_registry

    try:
        tools = tool_registry.export_tools()
        return {"status": "success", "tools": tools, "total": len(tools)}
    except ToolError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"导出工具失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.post("/tools/import")
async def import_tools(tools: List[Dict]):
    from backend.core.tools.registry import tool_registry

    try:
        count = tool_registry.import_tools(tools)
        return {"status": "success", "message": f"成功导入 {count} 个工具", "count": count}
    except ToolError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"导入工具失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.get("/tools/mcp/servers")
async def get_mcp_servers():
    from backend.api.app import get_mcp_manager

    try:
        mcp_mgr = get_mcp_manager()
        servers = await mcp_mgr.list_servers()
        stats = mcp_mgr.get_stats()
        return {"status": "success", "servers": servers, "statistics": stats}
    except ToolError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"获取MCP服务器失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.post("/tools/mcp/servers")
async def add_mcp_server(request: MCPServerAddRequest):
    from backend.api.app import get_mcp_manager

    try:
        mcp_mgr = get_mcp_manager()
        server = await mcp_mgr.add_server(
            name=request.name, command=request.command, args=request.args, env=request.env
        )
        return {
            "status": "success",
            "server": server,
            "message": f"MCP服务器 {request.name} 已添加",
        }
    except ToolError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"添加MCP服务器失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.delete("/tools/mcp/servers/{name}")
async def remove_mcp_server(name: str):
    from backend.api.app import get_mcp_manager

    try:
        mcp_mgr = get_mcp_manager()
        success = await mcp_mgr.remove_server(name)
        if not success:
            raise HTTPException(status_code=404, detail="服务器不存在")
        return {"status": "success", "message": f"MCP服务器 {name} 已删除"}
    except ToolError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"删除MCP服务器失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.post("/tools/mcp/servers/start")
async def start_mcp_server(request: MCPServerStartRequest):
    from backend.api.app import get_mcp_manager

    try:
        mcp_mgr = get_mcp_manager()
        success = await mcp_mgr.start_server(request.name)
        if not success:
            raise HTTPException(status_code=400, detail="启动失败")
        return {"status": "success", "message": f"MCP服务器 {request.name} 已启动"}
    except ToolError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"启动MCP服务器失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.post("/tools/mcp/servers/stop")
async def stop_mcp_server(request: MCPServerStopRequest):
    from backend.api.app import get_mcp_manager

    try:
        mcp_mgr = get_mcp_manager()
        success = await mcp_mgr.stop_server(request.name)
        if not success:
            raise HTTPException(status_code=400, detail="停止失败")
        return {"status": "success", "message": f"MCP服务器 {request.name} 已停止"}
    except ToolError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"停止MCP服务器失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.get("/tools/mcp/servers/{name}/health")
async def check_mcp_server_health(name: str):
    from backend.api.app import get_mcp_manager

    try:
        mcp_mgr = get_mcp_manager()
        health = await mcp_mgr.check_health(name)
        return {"status": "success", "server": name, "healthy": health}
    except ToolError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"检查MCP服务器健康状态失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.get("/tools/mcp/servers/{name}/tools")
async def get_mcp_server_tools(name: str):
    from backend.api.app import get_mcp_manager

    try:
        mcp_mgr = get_mcp_manager()
        tools = await mcp_mgr.list_server_tools(name)
        return {"status": "success", "server": name, "tools": tools}
    except ToolError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"获取MCP服务器工具失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.post("/tools/mcp/call")
async def call_mcp_tool(request: MCPToolCallRequest):
    from backend.api.app import get_mcp_manager

    try:
        mcp_mgr = get_mcp_manager()
        result = await mcp_mgr.call_tool(
            server_name=request.server_name,
            tool_name=request.tool_name,
            arguments=request.arguments,
        )
        return {"status": "success", "result": result}
    except ToolError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"调用MCP工具失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.post("/tools/mcp/sync")
async def sync_mcp_tools():
    from backend.api.app import get_mcp_manager

    try:
        mcp_mgr = get_mcp_manager()
        count = await mcp_mgr.sync_all_tools()
        return {"status": "success", "message": f"同步了 {count} 个MCP工具", "count": count}
    except ToolError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"同步MCP工具失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.get("/tools/plugins")
async def get_plugins():
    from backend.core.tools import tool_registry

    try:
        tools = tool_registry.list_tools_dict(enabled_only=False)
        return {"status": "success", "plugins": tools, "total": len(tools)}
    except Exception as e:
        return {
            "status": "success",
            "plugins": [],
            "total": 0,
            "message": f"插件功能暂不可用: {str(e)}",
        }


# 这些路由必须放在最后，因为它们使用路径参数
@router.get("/tools/{name}")
async def get_tool(name: str):
    from backend.core.tools.registry import tool_registry

    try:
        tool = tool_registry.get_tool(name)
        if not tool:
            raise HTTPException(status_code=404, detail="工具不存在")

        return {"status": "success", "tool": tool.to_dict()}
    except ToolError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"获取工具失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.delete("/tools/{name}")
async def delete_tool(name: str):
    from backend.core.tools.registry import tool_registry

    try:
        success = tool_registry.delete_tool(name)
        if not success:
            raise HTTPException(status_code=404, detail="工具不存在")

        return {"status": "success", "message": f"工具 {name} 已删除"}
    except ToolError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"删除工具失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")
