"""服务依赖容器——集中管理各服务单例的初始化、持有与访问，作为全局服务状态注册表。"""
import threading
from typing import Optional, Any, Dict

from fastapi import HTTPException, Request
from fastapi import Depends


class ServiceState:
    def __init__(self):
        self.memory_manager = None
        self.async_memory_manager = None
        self.context_manager = None
        self.acp_manager = None
        self.llm_client = None
        self.secondary_router = None
        self.decay_batch_processor = None
        self.mcp_manager = None
        self.model_router = None
        self.asr_service = None
        self.tts_service = None
        self.graph_database = None
        self.graph_store = None
        self.cxfc_manager: Optional[Any] = None
        # DocumentMemoryManager（迁移自 CXHMS Phase 2：AnythingLLM Document API 兼容端点）
        self.document_memory_manager: Optional[Any] = None


_service_state: Optional[ServiceState] = None


def set_service_state(state: ServiceState):
    global _service_state
    _service_state = state


def get_service_state(request: Request) -> ServiceState:
    return request.app.state.services


def _is_depends_marker(obj) -> bool:
    """检查 obj 是否是 FastAPI Depends 标记对象。

    FastAPI 的 ``Depends`` 是函数，调用后返回 ``fastapi.dependencies.models.Depends``
    类的实例。直接调用 getter（如 ``get_memory_manager()``）时，``state`` 默认参数
    就是这个 Depends 实例，此时应回退到全局 ``_service_state``。

    用类型名称检查避免直接导入内部类，保持跨 FastAPI 版本兼容。
    """
    return type(obj).__name__ == "Depends"


def _resolve_state(state=None) -> ServiceState:
    # state 为 None 或 FastAPI Depends 占位对象（直接调用 getter 时默认参数）
    # → 从全局 _service_state 获取
    if state is None or _is_depends_marker(state):
        if _service_state is not None:
            return _service_state
        raise RuntimeError("Service state not initialized. Call set_service_state() first.")
    # 正确类型 → 直接返回
    if isinstance(state, ServiceState):
        return state
    # 非 ServiceState 非 None 非 Depends → 类型错误，不应静默回退到全局
    # B11 修复: 原实现将任意非 ServiceState 对象回退到全局，掩盖调用方传入错误类型的 bug
    raise TypeError(
        f"Expected ServiceState or None, got {type(state).__name__}. "
        "Direct calls should pass state=None to use the global state."
    )


def get_memory_manager(state: ServiceState = Depends(get_service_state)):
    state = _resolve_state(state)
    if state.memory_manager is None:
        raise HTTPException(status_code=503, detail="记忆服务不可用")
    return state.memory_manager


def get_async_memory_manager(state: ServiceState = Depends(get_service_state)):
    state = _resolve_state(state)
    if state.async_memory_manager is None:
        raise HTTPException(status_code=503, detail="异步记忆服务不可用")
    return state.async_memory_manager


def get_context_manager(state: ServiceState = Depends(get_service_state)):
    state = _resolve_state(state)
    if state.context_manager is None:
        raise HTTPException(status_code=503, detail="上下文服务不可用")
    return state.context_manager


def get_acp_manager(state: ServiceState = Depends(get_service_state)):
    state = _resolve_state(state)
    if state.acp_manager is None:
        raise HTTPException(status_code=503, detail="ACP服务不可用")
    return state.acp_manager


def get_llm_client(state: ServiceState = Depends(get_service_state)):
    state = _resolve_state(state)
    if state.llm_client is None:
        raise HTTPException(status_code=503, detail="LLM服务不可用")
    return state.llm_client


def get_secondary_router(state: ServiceState = Depends(get_service_state)):
    state = _resolve_state(state)
    if state.secondary_router is None:
        raise HTTPException(status_code=503, detail="副模型路由器不可用")
    return state.secondary_router


def get_decay_batch_processor(state: ServiceState = Depends(get_service_state)):
    state = _resolve_state(state)
    if state.decay_batch_processor is None:
        raise HTTPException(status_code=503, detail="批量衰减处理器不可用")
    return state.decay_batch_processor


def get_mcp_manager(state: ServiceState = Depends(get_service_state)):
    state = _resolve_state(state)
    if state.mcp_manager is None:
        raise HTTPException(status_code=503, detail="MCP管理器不可用")
    return state.mcp_manager


def get_model_router(state: ServiceState = Depends(get_service_state)):
    state = _resolve_state(state)
    if state.model_router is None:
        raise HTTPException(status_code=503, detail="模型路由器不可用")
    return state.model_router


def get_asr_service(state: ServiceState = Depends(get_service_state)):
    state = _resolve_state(state)
    if state.asr_service is None:
        raise HTTPException(status_code=503, detail="ASR服务不可用")
    return state.asr_service


def get_tts_service(state: ServiceState = Depends(get_service_state)):
    state = _resolve_state(state)
    if state.tts_service is None:
        raise HTTPException(status_code=503, detail="TTS服务不可用")
    return state.tts_service


def get_graph_database(agent_id: str = "default", state: ServiceState = Depends(get_service_state)):
    """按 agent_id 获取图数据库实例（按需创建）。

    迁移自 CXHMS：使用 per-agent 注册表 + 双重检查锁实现线程安全的按需创建。
    - agent_id="default" 时返回默认实例
    - 其他 agent_id 时返回该 agent 专属实例
    - 首次访问触发 GraphDatabase.initialize()
    - 保留 CX-O 原有 state.graph_database 兼容性（默认 agent 写回 state）

    详见 .trae/documents/20260720_模块0_从CXHMS迁移图数据库.md
    """
    _resolve_state(state)
    gdb = _get_or_create_graph_database(agent_id)
    # 默认 agent 同步写入 state.graph_database 以兼容旧调用方
    if agent_id == "default" and state.graph_database is None:
        state.graph_database = gdb
    return gdb


def get_graph_store(agent_id: str = "default", state: ServiceState = Depends(get_service_state)):
    """按 agent_id 获取图存储实例（按需创建）。

    迁移自 CXHMS：依赖 _get_or_create_graph_store 实现 per-agent 隔离。
    默认 agent 同步写入 state.graph_store 以兼容旧调用方。
    """
    _resolve_state(state)
    store = _get_or_create_graph_store(agent_id)
    # 默认 agent 同步写入 state.graph_store 以兼容旧调用方
    if agent_id == "default" and state.graph_store is None:
        state.graph_store = store
    return store


# ---- per-agent 图数据库/图存储注册表（迁移自 CXHMS） ----
_graph_databases: Dict[str, Any] = {}
_graph_stores: Dict[str, Any] = {}
# 用可重入锁：_get_or_create_graph_store 持锁调用 _get_or_create_graph_database
# 会再次获取同一锁，非可重入锁（threading.Lock）会导致同线程死锁。
_graph_registry_lock = threading.RLock()


def _get_or_create_graph_database(agent_id: str = "default"):
    """按 agent_id 获取或按需创建 GraphDatabase 实例。

    使用双重检查锁（double-checked locking）避免并发请求时重复初始化。
    GraphDatabase 构造时通过 agent_id 隔离底层 SQLite 文件与 Weaviate collection。
    """
    if agent_id not in _graph_databases:
        with _graph_registry_lock:
            if agent_id not in _graph_databases:
                from server.core.graph import GraphDatabase

                gdb = GraphDatabase(agent_id=agent_id)
                gdb.initialize()
                _graph_databases[agent_id] = gdb
    return _graph_databases[agent_id]


def _get_or_create_graph_store(agent_id: str = "default"):
    """按 agent_id 获取或按需创建 GraphStore 实例。

    依赖对应 agent_id 的 GraphDatabase 实例。
    """
    if agent_id not in _graph_stores:
        with _graph_registry_lock:
            if agent_id not in _graph_stores:
                from server.core.memory.graph_store import SQLiteGraphStore

                gdb = _get_or_create_graph_database(agent_id)
                _graph_stores[agent_id] = SQLiteGraphStore(gdb)
    return _graph_stores[agent_id]


def get_graph_database_if_exists(agent_id: str = "default"):
    """返回已注册的 GraphDatabase 实例，不存在时返回 None（不创建）。"""
    return _graph_databases.get(agent_id)


def get_graph_store_if_exists(agent_id: str = "default"):
    """返回已注册的 GraphStore 实例，不存在时返回 None（不创建）。"""
    return _graph_stores.get(agent_id)


def remove_graph_database(agent_id: str) -> None:
    """从注册表移除并关闭对应 agent 的图数据库及图存储实例。

    迁移自 CXHMS：用于 agent 删除或重置时清理对应图数据库资源。
    底层 Database 由 server.core.graph.database 的 remove_database 同步移除。
    """
    with _graph_registry_lock:
        _graph_stores.pop(agent_id, None)
        gdb = _graph_databases.pop(agent_id, None)
    if gdb is not None:
        try:
            gdb.close()
        except Exception:
            pass
    try:
        from server.core.graph.database import remove_database

        remove_database(agent_id)
    except Exception:
        pass


def get_cxfc_manager(state: ServiceState = Depends(get_service_state)) -> Optional[Any]:
    return _resolve_state(state).cxfc_manager


def get_document_memory_manager(state: ServiceState = Depends(get_service_state)):
    """获取 DocumentMemoryManager 实例（迁移自 CXHMS）。

    用于 AnythingLLM Document API 兼容端点（/v1/document/*, /v1/workspace/{slug}/update-embeddings）。
    """
    state = _resolve_state(state)
    if state.document_memory_manager is None:
        raise HTTPException(status_code=503, detail="文档记忆服务不可用")
    return state.document_memory_manager
