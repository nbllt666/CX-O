"""聊天公共助手：跨 HTTP 路由与 WebSocket 处理器共享的 Agent 解析与 LLM 客户端选择。

收敛自 server/api/routers/chat.py 与 server/handlers/chat.py 的重复实现，
消除两个入口对 Agent 配置解析与 LLM 客户端选择的重复逻辑与行为漂移。
"""
import logging
import threading
from typing import Dict, Optional

from server.core.utils import run_io

logger = logging.getLogger(__name__)

# A1: MemoryRouter 惰性共享缓存（按 memory_manager 身份分键）。
# 原实现每条消息新建 MemoryRouter，其 __init__ 重建 Settings()（加载全量配置）、
# DecayCalculator 与 HybridSearch，纯浪费且拖慢聊天热路径。状态共享安全性：
# route() 路径对 self.config / self.decay_calculator / self.hybrid_search 仅读不写
# （config 仅 set_config 可变，本共享入口从不调用；DecayCalculator 为纯计算器；
# HybridSearch 每次调用无请求态字段），可安全跨协程复用。
_router_cache: Dict[int, object] = {}
_router_cache_lock = threading.Lock()


def get_shared_memory_router(memory_mgr):
    """获取与 memory_mgr 绑定的共享 MemoryRouter 单例（不存在则惰性创建）。"""
    from server.core.memory.router import MemoryRouter

    key = id(memory_mgr)
    router = _router_cache.get(key)
    if router is not None:
        return router
    with _router_cache_lock:
        router = _router_cache.get(key)
        if router is None:
            # 必须透传 manager 的向量组件：MemoryRouter 缺省 vector_store/embedding_model
            # 均为 None → hybrid_search 不启用 → chat 链路回退 SQLite LIKE 检索
            # （全包含匹配），自然语言提问命中不了记忆 → 注入为空。
            # rag/search 端点独立走向量检索故能命中，与 chat 链路形成"检索到但没注入"的
            # 断裂（EvalKit memory_decay 实测发现的根因，2026-09-12）。
            router = MemoryRouter(
                memory_manager=memory_mgr,
                vector_store=getattr(memory_mgr, "_vector_store", None),
                embedding_model=getattr(memory_mgr, "_embedding_model", None),
            )
            _router_cache[key] = router
    return router


def get_agent_config(agent_id: str) -> dict:
    """按 agent_id 查找 Agent 配置，不存在时返回 None。"""
    from server.api.routers.agents import _load_agents

    agents = _load_agents()
    return next((a for a in agents if a["id"] == agent_id), None)


async def get_agent_config_async(agent_id: str) -> Optional[dict]:
    """按 agent_id 查找 Agent 配置的异步版本（文件读取移入有界 IO 池）。

    与 ``get_agent_config`` 行为一致，仅供 async 热路径使用。
    """
    from server.api.routers.agents import _load_agents

    agents = await run_io(_load_agents)
    return next((a for a in agents if a["id"] == agent_id), None)


async def retrieve_memory_context(
    agent_config: dict,
    memory_mgr,
    user_message: str,
    session_id: str,
) -> Optional[str]:
    """按 Agent 配置检索记忆并格式化为上下文注入字符串。

    收敛自 server/handlers/chat.py、server/api/routers/chat.py（chat/chat_stream）
    与 server/core/websocket/handlers.py（chat/chat_stream）四处重复实现，消除
    MemoryRouter 初始化与记忆注入格式化的重复逻辑。未启用记忆 / 无记忆时返回 None。
    """
    if not agent_config.get("use_memory", True) or not memory_mgr:
        return None

    from server.config import get_settings

    # A1: 改用共享单例，避免每条消息重建 MemoryRouter（Settings/DecayCalculator/
    # HybridSearch 初始化开销）
    router = get_shared_memory_router(memory_mgr)
    routing_result = await router.route(
        query=user_message,
        session_id=session_id,
        scene_type=agent_config.get("memory_scene", "chat"),
        agent_id=agent_config.get("id"),
    )
    if not routing_result.memories:
        return None

    limit = get_settings().config.limits.memory.inject_memories_count
    injected = routing_result.memories[:limit]
    # 注入现场日志（排障用）：条数 + 每条综合分/时间分/内容头，观察"该忘的忘"是否传导
    logger.info(
        "[EVAL-INJECT] agent=%s candidates=%s inject=%s limit=%s detail=%s",
        agent_config.get("id"),
        len(routing_result.memories),
        len(injected),
        limit,
        [
            (
                m.get("final_score"),
                (m.get("component_scores") or {}).get("time"),
                str(m.get("content"))[:10],
            )
            for m in injected
        ],
    )
    return "\n".join([f"- {m['content']}" for m in injected])


def ensure_agent_session(context_mgr, agent_id: str, agent_name: str) -> str:
    """为 Agent 获取或创建默认会话（agent-chats 工作区）。

    会话 ID 约定为 ``agent-{agent_id}``。收敛自 server/handlers/chat.py、
    server/api/routers/chat.py 与 server/api/routers/anythingllm.py 的重复
    ensure_session 样板。返回会话 ID。
    """
    return context_mgr.ensure_session(
        f"agent-{agent_id}",
        workspace_id="agent-chats",
        title=f"{agent_name} 的对话",
        metadata={"agent_id": agent_id},
    )


async def ensure_agent_session_async(context_mgr, agent_id: str, agent_name: str) -> str:
    """异步取 get-or-create 会话（ensure_session 的同步 sqlite 移入有界 IO 池）。

    与 ``ensure_agent_session`` 返回语义一致（返回会话 ID），供异步路由热路径调用。
    """
    return await run_io(
        context_mgr.ensure_session,
        f"agent-{agent_id}",
        workspace_id="agent-chats",
        title=f"{agent_name} 的对话",
        metadata={"agent_id": agent_id},
    )


def get_llm_client_for_agent(agent_config: dict):
    """按 Agent 配置获取 LLM 客户端。

    - model 为 main/summary/memory 类型 → 从 model_router 获取对应客户端
    - model 为具体模型名 → 基于 main 客户端 host 经 LLMFactory.create_client
      创建/复用缓存实例（缓存键含 provider/model/host/temperature/max_tokens）
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
                # P5: 改经 LLMFactory 缓存复用——旧实现每请求直接新建
                # OllamaClient 造成实例churn；工厂缓存键并入 host/model/
                # temperature/max_tokens，不同 host 或采样参数不会互串缓存
                from server.core.llm.client import LLMFactory

                return LLMFactory.create_client(
                    "ollama",
                    host=main_client.host,
                    model=model,
                    temperature=agent_config.get("temperature", 0.7),
                    max_tokens=agent_config.get("max_tokens", 4096),
                )
    except Exception as e:
        logger.warning(f"Failed to create client for model {model}: {e}")

    return get_llm_client()


def get_tools_for_agent() -> list:
    """收集可注入 LLM 的工具列表（内置工具 + 主模型工具 + CXFC 插件工具）。

    收敛自 server/handlers/chat.py 的 _get_tools_for_agent，供 HTTP 聊天、WebSocket
    聊天与 ACP 自动回复共享，避免 core.acp.manager 对 handler 层的跨层依赖。
    内置工具的 OpenAI 定义本身由 get_builtin_tools() 内部 lru_cache，此处不再整体
    缓存——工具注册表是运行期可变状态，整体缓存会读入陈旧工具集，且单条消息仅
    需 14 次 get_tool 查询，相对 LLM 调用耗时可忽略。

    额外追加 category='cxfc' 的已注册工具，使语音 / 普通聊天均能选择 CXFC 工具
    （电脑控制、自主系统等），与"全部工具"口径一致。
    """
    from server.core.tools import tool_registry
    from server.core.tools.builtin import get_builtin_tools

    builtin_tools = get_builtin_tools()

    EXCLUDED_CATEGORIES = {"summary"}
    main_tool_names = {
        "write_long_term_memory", "search_all_memories", "call_assistant",
        "set_alarm", "mono", "write_permanent_memory",
        # per-agent 预设工具（快捷指令：情感TTS预设/动作预设）
        "save_emotion_preset", "save_action_preset", "list_presets", "delete_preset",
        "acp_list_agents", "acp_connect", "acp_disconnect",
        "acp_send_message", "acp_create_group", "acp_join_group", "acp_leave_group",
        "register_voiceprint",
    }
    main_tools = []
    for tool_name in main_tool_names:
        tool = tool_registry.get_tool(tool_name)
        if tool and tool.enabled and tool.category not in EXCLUDED_CATEGORIES:
            main_tools.append(tool.to_openai_function())

    # CXFC 插件工具（category='cxfc'），如 computer_control / autonomy_*，
    # 均在运行期由 CXFCManager 注册；此处全量透传，使 LLM 能选中并（经异步执行器）执行。
    try:
        cxfc_tools = tool_registry.list_openai_functions(category="cxfc")
    except Exception:
        cxfc_tools = []

    return builtin_tools + main_tools + cxfc_tools
