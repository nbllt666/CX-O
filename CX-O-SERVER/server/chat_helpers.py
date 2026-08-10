"""聊天公共助手：跨 HTTP 路由与 WebSocket 处理器共享的 Agent 解析与 LLM 客户端选择。

收敛自 server/api/routers/chat.py 与 server/handlers/chat.py 的重复实现，
消除两个入口对 Agent 配置解析与 LLM 客户端选择的重复逻辑与行为漂移。
"""
import logging

logger = logging.getLogger(__name__)


def get_agent_config(agent_id: str) -> dict:
    """按 agent_id 查找 Agent 配置，不存在时返回 None。"""
    from server.api.routers.agents import _load_agents

    agents = _load_agents()
    return next((a for a in agents if a["id"] == agent_id), None)


def get_llm_client_for_agent(agent_config: dict):
    """按 Agent 配置获取 LLM 客户端。

    - model 为 main/summary/memory 类型 → 从 model_router 获取对应客户端
    - model 为具体模型名 → 基于 main 客户端 host 创建 OllamaClient
    - 处理失败 → 回退到全局 llm_client
    """
    from server.dependencies import get_llm_client, get_model_router

    model = agent_config.get("model", "main")

    try:
        model_router = get_model_router()

        if model.lower() in ["main", "summary", "memory"]:
            client = model_router.get_client(model.lower())
            if client:
                return client
        else:
            main_client = model_router.get_client("main")
            if main_client:
                from server.core.llm.client import OllamaClient

                return OllamaClient(
                    host=main_client.host,
                    model=model,
                    temperature=agent_config.get("temperature", 0.7),
                    max_tokens=agent_config.get("max_tokens", 4096),
                )
    except Exception as e:
        logger.warning(f"Failed to create client for model {model}: {e}")

    return get_llm_client()


def get_tools_for_agent(agent_config) -> list:
    """按 Agent 配置收集可注入 LLM 的工具列表（内置工具 + 主模型工具）。

    收敛自 server/handlers/chat.py 的 _get_tools_for_agent，供 HTTP 聊天、WebSocket
    聊天与 ACP 自动回复共享，避免 core.acp.manager 对 handler 层的跨层依赖。
    """
    from server.core.tools import tool_registry
    from server.core.tools.builtin import get_builtin_tools

    builtin_tools = get_builtin_tools()

    EXCLUDED_CATEGORIES = {"summary"}
    main_tool_names = {
        "write_long_term_memory", "search_all_memories", "call_assistant",
        "set_alarm", "mono", "write_permanent_memory",
        "acp_list_agents", "acp_connect", "acp_disconnect",
        "acp_send_message", "acp_create_group", "acp_join_group", "acp_leave_group",
    }
    main_tools = []
    for tool_name in main_tool_names:
        tool = tool_registry.get_tool(tool_name)
        if tool and tool.enabled and tool.category not in EXCLUDED_CATEGORIES:
            main_tools.append(tool.to_openai_function())

    return builtin_tools + main_tools