from typing import Optional

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


_service_state: Optional[ServiceState] = None


def set_service_state(state: ServiceState):
    global _service_state
    _service_state = state


def get_service_state(request: Request) -> ServiceState:
    return request.app.state.services


def _resolve_state(state=None) -> ServiceState:
    if isinstance(state, ServiceState):
        return state
    if _service_state is not None:
        return _service_state
    raise RuntimeError("Service state not initialized. Call set_service_state() first.")


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
