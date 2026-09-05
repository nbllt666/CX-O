"""CXFC 端点——插件注册、心跳、事件分发与数据网关接口。"""
import hashlib
import json
import os
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from server.api.routers.admin import verify_admin_api_key
from server.core.utils import run_io
from server.dependencies import get_memory_manager

from server.core.cxfc.models import (
    CXFCRegisterRequest,
    CXFCHeartbeatRequest,
    CXFCEvent,
    CXFCConnectRequest,
    CXFCRelayRegisterRequest,
    CXFCRelayResultRequest,
    CXFCEmbeddedRegisterRequest,
    CXFCRegisterAccessResponse,
)
from server.core.logging_config import get_contextual_logger

router = APIRouter()
logger = get_contextual_logger(__name__)


class CXFCCallToolRequest(BaseModel):
    """CXFC 插件工具调用请求"""

    tool: str
    arguments: Dict[str, Any] = {}


class CXFCGatewayMemorySearchRequest(BaseModel):
    """CXFC 数据网关记忆检索请求体：{query, limit?, agent_id?}。"""

    query: str
    # 分页边界与既有 /memories/search 口径一致（上限 200，防恶意大 limit 拖库）
    limit: int = Field(default=10, ge=1, le=200)
    agent_id: str = "default"


class CXFCGatewayPhysioReportRequest(BaseModel):
    """CXFC 数据网关心率上报请求体（语义同 POST /physio/hr：仅内存不落盘）。"""

    bpm: float
    ts: Optional[Any] = None
    device_fingerprint: Optional[str] = None


# ---------------------------------------------------------------------------
# CXFC 数据网关（spec: enhance-cxfc-admin-and-integrate-dream Task 1）
# 供已注册插件经 plugin_access_token 访问宿主记忆库与生理数据（衍生指标）。
# ---------------------------------------------------------------------------

def _gateway_admin_api_key() -> str:
    """惰性读取管理密钥（同 admin.py._admin_api_key 模式，避免导入期冻结 env）。"""
    return os.environ.get("ADMIN_API_KEY", "")


def require_plugin_access(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None),
) -> Dict[str, str]:
    """CXFC 数据网关统一鉴权依赖。

    - 运维旁路：X-API-Key 与 ADMIN_API_KEY 恒时比对（secrets.compare_digest），
      命中后以 admin 身份放行（供前端管理页测试器使用）；
    - 插件令牌：Authorization: Bearer <plugin_access_token>，sha256 后与库中
      哈希恒时比对，命中则将 plugin_id 绑定到 request.state 并注入端点；
    - 无令牌 → 401；令牌无效 → 403；管理器未装配 → 503。
    """
    admin_key = _gateway_admin_api_key()
    if admin_key and x_api_key and secrets.compare_digest(x_api_key, admin_key):
        request.state.plugin_id = "admin"
        return {"plugin_id": "admin", "via": "admin_key"}

    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="缺少插件访问令牌（Authorization: Bearer <plugin_access_token> 或 X-API-Key）",
        )

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=401,
            detail="鉴权头格式错误，需 Authorization: Bearer <plugin_access_token>",
        )

    cxfc_manager = get_cxfc_manager()
    if cxfc_manager is None:
        raise HTTPException(status_code=503, detail="CXFC 管理器不可用")
    verifier = getattr(cxfc_manager, "verify_plugin_access_token", None)
    plugin_id = verifier(token) if callable(verifier) else None
    if not plugin_id:
        raise HTTPException(status_code=403, detail="插件访问令牌无效")

    request.state.plugin_id = plugin_id
    return {"plugin_id": plugin_id, "via": "plugin_token"}


# 疑似原始心率序列的键名（隐私红线 store_raw_hr=false：网关响应绝不携带原始 HR 序列）
_RAW_HR_EXACT_KEYS = frozenset(
    {"samples", "raw_samples", "hr_series", "hr_list", "hr_values", "hr_sequence", "hr_history", "bpm_series"}
)
_RAW_HR_SUBSTRINGS = ("raw_hr", "rawhr", "raw_sample")


def _strip_raw_hr(payload: Any) -> Any:
    """递归剥离响应中疑似原始心率序列的键（防御纵深）。

    正常路径下估计器/睡眠传感器本就只返回衍生指标（base_hr/置信度/信号权重等）；
    本清洗器保证即使底层状态意外混入原始 HR 键，也不会经网关外露。
    """
    if isinstance(payload, dict):
        cleaned = {}
        for key, value in payload.items():
            key_lower = str(key).lower()
            if key_lower in _RAW_HR_EXACT_KEYS or any(p in key_lower for p in _RAW_HR_SUBSTRINGS):
                continue
            cleaned[key] = _strip_raw_hr(value)
        return cleaned
    if isinstance(payload, list):
        return [_strip_raw_hr(item) for item in payload]
    return payload


@lru_cache(maxsize=1)
def _load_memory_schema() -> Optional[Dict[str, Any]]:
    """加载 public/schema/memory.schema.json（结果缓存）。

    从本文件向上逐级定位 public/schema/（兼容 CX-O-SERVER 为项目根、以及上层
    仓库根两种目录布局），未命中返回 None。
    """
    current = Path(__file__).resolve().parent
    for _ in range(8):
        candidate = current / "public" / "schema" / "memory.schema.json"
        if candidate.is_file():
            with open(candidate, "r", encoding="utf-8") as f:
                return json.load(f)
        if current.parent == current:
            break
        current = current.parent
    return None


def _held_plugin_access_token(cxfc_manager, plugin_id: str) -> Optional[str]:
    """读取管理器内存代持的插件访问令牌明文（仅注册响应一次性披露）。

    对未实现代持接口的旧式替身管理器（既有测试 Fake）返回 None，保持兼容。
    """
    getter = getattr(cxfc_manager, "get_plugin_access_token", None)
    if callable(getter):
        return getter(plugin_id)
    return None

_cxfc_manager = None
_discovery = None


def get_cxfc_manager():
    """返回模块级 CXFC 管理器单例（未设置时为 None）。"""
    return _cxfc_manager


def set_cxfc_manager(manager):
    """设置 CXFC 管理器实例。"""
    global _cxfc_manager
    _cxfc_manager = manager


def set_cxfc_discovery(d):
    """设置网络发现器实例，用于局域网插件发现扫描。"""
    global _discovery
    _discovery = d


@router.post("/cxfc/register", response_model=CXFCRegisterAccessResponse)
async def register_plugin(request: CXFCRegisterRequest):
    cxfc_manager = get_cxfc_manager()
    try:
        plugin = await cxfc_manager.register_plugin(request)
        # CXFC 数据网关：注册成功即签发 plugin_access_token（明文仅此一次返回，
        # 后端库中只存 SHA-256 哈希；旧式替身管理器无代持接口时返回 None 保持兼容）
        return CXFCRegisterAccessResponse(
            status="ok",
            plugin_id=plugin.plugin_id,
            plugin_access_token=_held_plugin_access_token(cxfc_manager, plugin.plugin_id),
        )
    except Exception as e:
        logger.error(f"插件注册失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.post("/cxfc/heartbeat")
async def heartbeat(request: CXFCHeartbeatRequest):
    cxfc_manager = get_cxfc_manager()
    try:
        alive = await cxfc_manager.update_heartbeat(request.plugin_id, request.port)
        if not alive:
            raise HTTPException(status_code=404, detail="插件不存在")
        return {"status": "alive"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"心跳处理失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.post("/cxfc/event/push")
async def push_event(event: CXFCEvent):
    """推送一个 CXFC 事件。"""
    cxfc_manager = get_cxfc_manager()
    try:
        await cxfc_manager.push_event(event)
        return {"status": "received"}
    except Exception as e:
        logger.error(f"事件推送失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.get("/cxfc/discover")
async def discover_plugins(scan: bool = False):
    cxfc_manager = get_cxfc_manager()
    try:
        plugins = cxfc_manager.get_plugins()
        result = {"plugins": plugins}
        if scan:
            if _discovery:
                network_plugins = await _discovery.scan_network()
                result["network_plugins"] = network_plugins
            else:
                result["network_plugins"] = []
        return result
    except Exception as e:
        logger.error(f"插件发现失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.get("/cxfc/skills")
async def get_skills():
    cxfc_manager = get_cxfc_manager()
    try:
        skills = cxfc_manager.get_skill_registry().get_all_skills()
        return {"skills": skills}
    except Exception as e:
        logger.error(f"获取Skills失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.post("/cxfc/connect")
async def connect_to_plugin(request: CXFCConnectRequest):
    cxfc_manager = get_cxfc_manager()
    try:
        plugin = await cxfc_manager.connect_to_plugin(request.host, request.port)
        if not plugin:
            raise HTTPException(status_code=503, detail="无法连接到指定插件")
        return {"status": "ok", "plugin": plugin}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"连接插件失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.delete("/cxfc/plugins/{plugin_id}")
async def disconnect_plugin(plugin_id: str):
    cxfc_manager = get_cxfc_manager()
    try:
        await cxfc_manager.disconnect_plugin(plugin_id, remove_persistent=True)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"断开插件失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.post("/cxfc/plugins/{plugin_id}/disconnect")
async def disconnect_plugin_keep_registration(plugin_id: str):
    """断开插件连接但保留注册记录（可重新连接）。"""
    cxfc_manager = get_cxfc_manager()
    try:
        await cxfc_manager.disconnect_plugin(plugin_id, remove_persistent=False)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"断开插件失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.get("/cxfc/plugins")
async def list_plugins():
    """列出已注册的 CXFC 插件。"""
    cxfc_manager = get_cxfc_manager()
    try:
        plugins = cxfc_manager.get_plugins()
        return {"plugins": plugins}
    except Exception as e:
        logger.error(f"列出插件失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.post("/cxfc/plugins/{plugin_id}/refresh")
async def refresh_plugin(plugin_id: str):
    """刷新指定插件的信息。"""
    cxfc_manager = get_cxfc_manager()
    try:
        plugin = await cxfc_manager.refresh_plugin(plugin_id)
        if not plugin:
            raise HTTPException(status_code=404, detail="插件不存在或未连接")
        return {"status": "ok", "plugin": plugin}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"刷新插件失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.post("/cxfc/plugins/{plugin_id}/call")
async def call_plugin_tool(
    plugin_id: str,
    request: CXFCCallToolRequest,
    _: bool = Depends(verify_admin_api_key),
):
    """调用指定插件的工具

    通过主系统转发到插件侧的 POST /call 端点，实现工具调用。
    用于测试工具验证端到端调用链路。
    #31（差异审查登记）: 该端点此前无任何鉴权，任意调用方可触发携合法 token
    的插件工具转发（越权工具调用入口）。挂 verify_admin_api_key 管理密钥。
    """
    cxfc_manager = get_cxfc_manager()
    try:
        result = await cxfc_manager.call_tool(plugin_id, request.tool, request.arguments)
        return {"status": "ok", "result": result}
    except Exception as e:
        logger.error(f"调用插件工具失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.post("/cxfc/relay/register", response_model=CXFCRegisterAccessResponse)
async def relay_register(request: CXFCRelayRegisterRequest):
    """注册一个 relay（前端转接）插件目标。

    前端（或经前端代理的远端插件）登记插件描述与令牌；后端随后需为该 plugin_id
    注入活跃通道（register_relay_dispatcher）才能投递调用。
    CXFC 数据网关：注册成功即签发 plugin_access_token（明文仅此一次返回，
    后端内存代持，供后续调用方使用、不外露）。
    """
    cxfc_manager = get_cxfc_manager()
    try:
        plugin = await cxfc_manager.register_relay_plugin(
            plugin_id=request.plugin_id or request.name,
            name=request.name,
            tools=request.tools,
            skills=request.skills,
            capabilities=request.capabilities,
            token=request.token,
        )
        return CXFCRegisterAccessResponse(
            status="ok",
            plugin_id=plugin.plugin_id,
            plugin_access_token=_held_plugin_access_token(cxfc_manager, plugin.plugin_id),
        )
    except Exception as e:
        logger.error(f"relay 注册失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.get("/cxfc/relay/targets")
async def relay_targets():
    """列出已注册并注入通道的 relay 插件目标。"""
    cxfc_manager = get_cxfc_manager()
    try:
        return {"targets": cxfc_manager.get_relay_targets()}
    except Exception as e:
        logger.error(f"获取 relay 目标失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.post("/cxfc/relay/result")
async def relay_result(request: CXFCRelayResultRequest):
    """前端回报一次被转发的工具调用结果，回填给后端等待中的调用方。"""
    cxfc_manager = get_cxfc_manager()
    try:
        payload = {
            "success": request.success,
            "result": request.result,
            "error": request.error,
        }
        resolved = cxfc_manager.complete_relay_result(request.plugin_id, request.request_id, payload)
        if not resolved:
            raise HTTPException(status_code=404, detail="未找到对应待回报调用")
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"relay 结果回报失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


@router.post("/cxfc/embedded", response_model=CXFCRegisterAccessResponse)
async def embedded_register(request: CXFCEmbeddedRegisterRequest):
    """登记后端进程内嵌入式工具描述（transport=embedded，不走网络）。

    实际 handler 由 register_embedded_plugin() 以 Callable 在进程内注入；此处登记
    描述供列出与管理时展示传输类型。handler 由调用方注入后，调用走进程内分发。
    CXFC 数据网关：登记成功即签发 plugin_access_token（明文仅此一次返回，
    后端内存代持，供后续调用方使用、不外露）。
    """
    cxfc_manager = get_cxfc_manager()
    try:
        tools = [t.model_dump() for t in request.tools]
        plugin = await cxfc_manager.register_embedded_plugin(
            plugin_id=request.plugin_id,
            name=request.name,
            tools=tools,
            skills=request.skills,
            capabilities=request.capabilities,
        )
        return CXFCRegisterAccessResponse(
            status="ok",
            plugin_id=plugin.plugin_id,
            plugin_access_token=_held_plugin_access_token(cxfc_manager, plugin.plugin_id),
        )
    except Exception as e:
        logger.error(f"嵌入式插件注册失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="内部服务器错误")


# ---------------------------------------------------------------------------
# CXFC 数据网关端点（Task 1）——全部挂 require_plugin_access 鉴权。
# 记忆端点复用 MemoryManager 既有管道（search_memories/write_memory/get_statistics/
# get_memory，经 run_io 移入 IO 线程池）；写入经 public/schema/memory.schema.json
# jsonschema 契约校验。生理端点复用 physio router 的 runtime 管道，响应统一经
# _strip_raw_hr 清洗（隐私红线 store_raw_hr=false：绝不返回原始 HR 序列）。
# ---------------------------------------------------------------------------

@router.post("/cxfc/memory/search")
async def gateway_memory_search(
    body: CXFCGatewayMemorySearchRequest,
    _access: Dict[str, str] = Depends(require_plugin_access),
    memory_mgr=Depends(get_memory_manager),
):
    """CXFC 数据网关：记忆检索（复用 MemoryManager.search_memories 管道）。"""
    try:
        memories = await run_io(
            memory_mgr.search_memories,
            query=body.query,
            limit=body.limit,
            agent_id=body.agent_id,
        )
        return {
            "status": "success",
            "memories": memories,
            "total": len(memories),
            "plugin_id": _access["plugin_id"],
        }
    except Exception as e:
        logger.error(f"CXFC 网关记忆检索失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="记忆检索失败")


@router.post("/cxfc/memory/write")
async def gateway_memory_write(
    body: Dict[str, Any],
    _access: Dict[str, str] = Depends(require_plugin_access),
    memory_mgr=Depends(get_memory_manager),
):
    """CXFC 数据网关：记忆写入（body 经 memory.schema.json 契约校验，违约 422）。"""
    schema = _load_memory_schema()
    if schema is None:
        raise HTTPException(
            status_code=500,
            detail="记忆契约 public/schema/memory.schema.json 加载失败",
        )
    try:
        import jsonschema  # 局部导入：仅网关写入路径依赖，缺库不影响其余 CXFC 端点

        jsonschema.validate(instance=body, schema=schema)
    except jsonschema.ValidationError as e:
        raise HTTPException(
            status_code=422,
            detail=f"记忆写入不符合 memory 契约: {e.message}",
        )

    content = body.get("content")
    if not content or not str(content).strip():
        raise HTTPException(status_code=422, detail="记忆内容不能为空")

    try:
        memory_id = await run_io(
            memory_mgr.write_memory,
            content=content,
            memory_type=body.get("memory_type", "long_term"),
            importance=body.get("importance", 3),
            tags=body.get("tags") or [],
            metadata=body.get("metadata") or {},
            permanent=bool(body.get("permanent", False)),
            emotion_score=float(body.get("emotion_score", 0.0)),
            workspace_id=body.get("workspace_id", "default"),
            agent_id=body.get("agent_id", "default"),
        )
        return {
            "status": "success",
            "memory_id": memory_id,
            "message": "记忆写入成功",
            "plugin_id": _access["plugin_id"],
        }
    except Exception as e:
        logger.error(f"CXFC 网关记忆写入失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="记忆写入失败")


# 注意：本路由必须声明在 /cxfc/memory/{memory_id} 之前，否则静态段 stats
# 会被 int 型 memory_id 参数吞掉导致恒 422（与 memory router 的 permanent 同型教训）。
@router.get("/cxfc/memory/stats")
async def gateway_memory_stats(
    workspace_id: str = "default",
    _access: Dict[str, str] = Depends(require_plugin_access),
    memory_mgr=Depends(get_memory_manager),
):
    """CXFC 数据网关：记忆统计（复用 /memories/stats 的 get_statistics 数据来源）。"""
    try:
        stats = await run_io(memory_mgr.get_statistics, workspace_id)
        return {
            "status": "success",
            "statistics": stats,
            "plugin_id": _access["plugin_id"],
        }
    except Exception as e:
        logger.error(f"CXFC 网关获取记忆统计失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="获取记忆统计失败")


@router.get("/cxfc/memory/{memory_id}")
async def gateway_memory_get(
    memory_id: int,
    agent_id: str = "default",
    _access: Dict[str, str] = Depends(require_plugin_access),
    memory_mgr=Depends(get_memory_manager),
):
    """CXFC 数据网关：按 ID 读取单条记忆（复用 MemoryManager.get_memory）。"""
    try:
        memory = await run_io(memory_mgr.get_memory, memory_id, agent_id=agent_id)
        if not memory:
            raise HTTPException(status_code=404, detail="记忆不存在")
        return {
            "status": "success",
            "memory": memory,
            "plugin_id": _access["plugin_id"],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"CXFC 网关获取记忆失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="获取记忆失败")


@router.post("/cxfc/physio/report")
def gateway_physio_report(
    body: CXFCGatewayPhysioReportRequest,
    _access: Dict[str, str] = Depends(require_plugin_access),
):
    """CXFC 数据网关：心率样本上报（复用 POST /physio/hr 的 runtime 管道，仅内存不落盘）。"""
    from server.api.routers import physio as physio_router

    result = physio_router.ingest_hr(
        physio_router.HrSampleRequest(
            bpm=body.bpm,
            ts=body.ts,
            device_fingerprint=body.device_fingerprint,
        )
    )
    return _strip_raw_hr(result)


@router.get("/cxfc/physio/status")
def gateway_physio_status(_access: Dict[str, str] = Depends(require_plugin_access)):
    """CXFC 数据网关：生理采集/估计器状态（仅衍生指标，剥离疑似原始 HR 序列）。"""
    from server.api.routers import physio as physio_router

    return _strip_raw_hr(physio_router.get_status())


@router.get("/cxfc/physio/sleep")
def gateway_physio_sleep(_access: Dict[str, str] = Depends(require_plugin_access)):
    """CXFC 数据网关：睡眠融合状态（仅衍生指标，剥离疑似原始 HR 序列）。"""
    from server.api.routers import physio as physio_router

    return _strip_raw_hr(physio_router.get_sleep())
