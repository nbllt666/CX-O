"""CXO-Tuner evolution 集成出口路由。

连接 CX-O 主后端与 CXO-Tuner 自适应微调服务（host 8300）：
  - ``TunerClient``：httpx 异步客户端，封装 Tuner 后端 HTTP 接口；
    不可达/超时/错误时降级，返回 None 且不抛异常破坏主线程（CX-O 核心零影响）。
  - 会话历史导出：GET /api/v1/tuner/conversations（供后端 Judge 使用）。
  - 反馈转发代理：POST /api/v1/tuner/feedback（evolution 未启用或 Tuner 不可达 -> 503）。
  - 适配器 Phase1 手动应用：POST /api/v1/tuner/adapters/{id}/apply（骨架阶段返回
    applied 状态并记录配置，不强制真实切换）。

最终路径（挂载 prefix=/api）：
    GET  /api/v1/tuner/conversations
    GET  /api/v1/tuner/stats
    POST /api/v1/tuner/feedback
    POST /api/v1/tuner/train/trigger
    GET  /api/v1/tuner/train/status
    GET  /api/v1/tuner/adapters
    POST /api/v1/tuner/adapters/{adapter_id}/apply

对齐 public/interface_stub/cxo_tuner.pyi 的请求/响应模型与
public/schema/cxo_tuner_feedback.schema.json、cxo_tuner_config.schema.json。
evolution 未启用时 (enabled=False) 保持与现状一致的向后兼容（端点返回 503 或降级默认）。
"""
import asyncio
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from server.core.logging_config import get_contextual_logger
from server.config import get_config

router = APIRouter()
logger = get_contextual_logger(__name__)


# ---------------------------------------------------------------------------
# 请求 / 响应模型（对齐 public/schema/cxo_tuner_feedback.schema.json）
# ---------------------------------------------------------------------------
class FeedbackIn(BaseModel):
    """单条偏好反馈输入。字段与 cxo_tuner_feedback.schema.json 一致。"""

    prompt: str
    response_chosen: str
    response_rejected: str
    source: str  # enum: live_danmaku / judge / distillation
    timestamp: str  # ISO 8601 date-time
    session_id: Optional[str] = None
    quality_score: Optional[float] = None  # 0-1
    metadata: Optional[Dict[str, Any]] = None


class TrainTriggerRequest(BaseModel):
    """触发训练请求。base_model 为空时回退配置 base_model。"""

    base_model: Optional[str] = None
    epochs: int = 1
    sample_ratio: float = 1.0  # 0-1
    anchor_ratio: float = 0.2  # 0-1
    job_id: str = ""


# ---------------------------------------------------------------------------
# CXO-Tuner 异步客户端（超时 / 重试 / 降级：失败返回 None，不抛异常）
# ---------------------------------------------------------------------------
class TunerClient:
    """封装向后端 CXO-Tuner 服务（默认 host 8300）的异步 HTTP 调用。

    所有方法在请求失败（连接错误 / 超时 / 非 2xx / 解析失败）时返回 ``None``，
    并记录日志，绝不向上抛出异常——保证 CX-O 核心主线程零影响。网络类错误
    做了轻量重试（默认 2 次，短退避）；普通 HTTP 错误码不重试。
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8300",
        timeout: int = 10,
        max_retries: int = 2,
        client: Optional[httpx.AsyncClient] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._max_retries = max_retries
        # 拆查结论（issue 07 附录）：默认 httpx.AsyncClient 构造在本机因
        # 证书库加载/代理发现可耗时 ~21s。不再急切构造——优先注入（测试/Mock），
        # 否则惰性复用项目共享客户端（已连接池化，见 core/utils.get_shared_http_client）。
        self._client = client
        self._owns_client = client is None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            from server.core.utils import get_shared_http_client

            self._client = get_shared_http_client()
        return self._client

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
    ) -> Optional[Any]:
        url = f"{self.base_url}{path}"
        last_err: Optional[Exception] = None
        client = self._get_client()
        for attempt in range(self._max_retries):
            try:
                resp = await client.request(method, url, params=params, json=json)
                if resp.is_error:
                    logger.warning(
                        f"CXO-Tuner {method} {path} 返回 {resp.status_code}：{resp.text[:200]}"
                    )
                    return None
                return resp.json() if resp.content else None
            except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as e:
                last_err = e
                if attempt < self._max_retries - 1:
                    await asyncio.sleep(0.05 * (attempt + 1))
            except Exception as e:  # 其他异常：直接降级，不重试
                logger.warning(f"CXO-Tuner {method} {path} 请求异常: {e}")
                return None
        if last_err is not None:
            logger.warning(f"CXO-Tuner {method} {path} 不可达（重试 {self._max_retries} 次）: {last_err}")
        return None

    async def submit_feedback(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """POST /api/v1/feedback —— 转发一条偏好反馈。"""
        return await self._request("POST", "/api/v1/feedback", json=payload)

    async def get_dataset_stats(self) -> Optional[Dict[str, Any]]:
        """GET /api/v1/dataset/stats —— 数据集统计。"""
        return await self._request("GET", "/api/v1/dataset/stats")

    async def trigger_train(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """POST /api/v1/train/trigger —— 触发 LoRA 训练。"""
        return await self._request("POST", "/api/v1/train/trigger", json=payload)

    async def get_train_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """GET /api/v1/train/status —— 查询训练任务状态。"""
        return await self._request("GET", "/api/v1/train/status", params={"job_id": job_id})

    async def list_adapters(self) -> Optional[List[Dict[str, Any]]]:
        """GET /api/v1/adapters —— 列出全部适配器。"""
        return await self._request("GET", "/api/v1/adapters")

    async def apply_adapter(self, adapter_id: str) -> Optional[Dict[str, Any]]:
        """POST /api/v1/adapters/{id}/apply —— 应用适配器（预留，也可直接调用 Tuner）。"""
        return await self._request("POST", f"/api/v1/adapters/{adapter_id}/apply")

    async def delete_adapter(self, adapter_id: str) -> Optional[Dict[str, Any]]:
        """DELETE /api/v1/adapters/{id} —— 删除指定适配器。"""
        return await self._request("DELETE", f"/api/v1/adapters/{adapter_id}")

    async def close(self) -> None:
        # 不关闭共享客户端（非本实例拥有）；仅关闭自主创建的实例
        if not self._owns_client or self._client is None:
            return
        try:
            await self._client.aclose()
        except Exception as e:
            logger.warning(f"关闭 CXO-Tuner 客户端失败: {e}")


def _get_tuner_client(request: Request) -> TunerClient:
    """从 app.state 获取（必要时惰性创建）并缓存 TranerClient。

    Tuner 客户端实例挂在 ``app.state.tuner_client`` 供路由复用；由 evolution 配置
    节的 host / timeout 构建。
    """
    cfg = get_config().evolution
    client = getattr(request.app.state, "tuner_client", None)
    if client is None or client.base_url != cfg.host:
        # host 变更或首次：重建客户端（旧客户端若存在则关闭）
        old = getattr(request.app.state, "tuner_client", None)
        if old is not None and hasattr(old, "close"):
            asyncio.ensure_future(_safe_close(old))
        client = TunerClient(base_url=cfg.host, timeout=cfg.timeout)
        request.app.state.tuner_client = client
    return client


async def _safe_close(client: TunerClient) -> None:
    await client.close()


# ---------------------------------------------------------------------------
# 会话历史导出（供后端 Judge 使用）
# ---------------------------------------------------------------------------
def _build_conversations(limit: int) -> List[Dict[str, Any]]:
    """从会话存储读取最近 N 个会话，构造 (prompt, response 多版本) 对。

    每个会话取最后一条 user 消息为 prompt，全部 assistant 消息为 responses。
    无会话或无 user 消息时返回空列表。
    """
    try:
        from server.core.session import get_session_store

        store = get_session_store()
        sessions = store.get_sessions(active_only=True, limit=limit)
    except Exception as e:
        logger.warning(f"读取会话历史失败（返回空列表）: {e}")
        return []

    conversations: List[Dict[str, Any]] = []
    for s in sessions:
        try:
            msgs = store.get_messages(s.id, limit=100)
        except Exception as e:
            logger.warning(f"读取会话 {s.id} 消息失败，跳过: {e}")
            continue
        user_msgs = [m.content for m in msgs if m.role == "user" and m.content]
        assistant_responses = [m.content for m in msgs if m.role == "assistant" and m.content]
        if not user_msgs:
            continue
        conversations.append(
            {
                "session_id": s.id,
                "prompt": user_msgs[-1],
                "responses": assistant_responses,
            }
        )
    return conversations


# ---------------------------------------------------------------------------
# 路由端点
# ---------------------------------------------------------------------------
@router.get("/v1/tuner/conversations")
async def export_conversations(limit: int = 10):
    """导出最近 N 条会话历史（(prompt, response 多版本)），供后端 Judge 使用。

    无会话时返回空列表（不 503，会话导出对 CX-O 核心无影响）。
    """
    conversations = _build_conversations(limit=max(1, min(limit, 100)))
    return {"status": "success", "conversations": conversations}


@router.post("/v1/tuner/feedback")
async def forward_feedback(request: Request, payload: FeedbackIn):
    """转发 CX-O 内 feedback 到 CXO-Tuner。

    evolution 未启用（enabled=False）或 Tuner 不可达时返回 503（不抛破坏主线程）。
    """
    cfg = get_config().evolution
    if not cfg.enabled:
        raise HTTPException(status_code=503, detail="CXO-Tuner evolution 未启用")

    client = _get_tuner_client(request)
    result = await client.submit_feedback(payload.model_dump(exclude_none=True))
    if result is None:
        raise HTTPException(status_code=503, detail="CXO-Tuner 不可达，反馈转发降级")
    return {"status": "success", "forwarded": True, "feedback": result}


@router.get("/v1/tuner/stats")
async def get_dataset_stats(request: Request):
    """获取 CXO-Tuner 数据集统计。Tuner 不可达/未启用时返回降级默认结构（不 503）。"""
    client = _get_tuner_client(request)
    stats = await client.get_dataset_stats()
    if stats is None:
        return {
            "status": "degraded",
            "stats": {
                "total": 0,
                "source_breakdown": {},
                "positive_ratio": 0.0,
                "negative_ratio": 0.0,
                "anchor_count": 0,
            },
        }
    return {"status": "success", "stats": stats}


@router.post("/v1/tuner/train/trigger")
async def trigger_train(request: Request, payload: TrainTriggerRequest):
    """触发 LoRA 训练。Tuner 不可达时返回 503。"""
    client = _get_tuner_client(request)
    result = await client.trigger_train(payload.model_dump(exclude_none=True))
    if result is None:
        raise HTTPException(status_code=503, detail="CXO-Tuner 不可达，训练触发失败")
    return {"status": "success", "train": result}


@router.get("/v1/tuner/train/status")
async def get_train_status(request: Request, job_id: str = ""):
    """查询训练任务状态。Tuner 不可达时返回 503。"""
    if not job_id:
        raise HTTPException(status_code=422, detail="job_id 必填")
    client = _get_tuner_client(request)
    result = await client.get_train_status(job_id)
    if result is None:
        raise HTTPException(status_code=503, detail="CXO-Tuner 不可达，无法查询训练状态")
    return {"status": "success", "train": result}


@router.get("/v1/tuner/adapters")
async def list_adapters(request: Request):
    """列出全部适配器。Tuner 不可达时返回空列表（降级默认）。"""
    client = _get_tuner_client(request)
    result = await client.list_adapters()
    if result is None:
        return {"status": "degraded", "adapters": []}
    return {"status": "success", "adapters": result}


@router.delete("/v1/tuner/adapters/{adapter_id}")
async def delete_adapter(request: Request, adapter_id: str):
    """删除指定适配器。Tuner 不可达时返回删失败（降级）。"""
    client = _get_tuner_client(request)
    try:
        result = await client.delete_adapter(adapter_id)
    finally:
        await _safe_close(client)
    if result is None:
        return {"status": "degraded", "deleted": False, "adapter_id": adapter_id}
    return {
        "status": "success",
        "deleted": bool(result.get("deleted", True)),
        "adapter_id": adapter_id,
    }


@router.post("/v1/tuner/adapters/{adapter_id}/apply")
async def apply_adapter(request: Request, adapter_id: str):
    """Phase1 手动应用适配器：通过 config_hot_reload 切换 llm.host/port 或标记 lora。

    骨架阶段不强制真实切换，返回 applied 状态 + 记录当前 evolution 配置，并保留
    原 llm.host/port 供回滚使用。若 evolution 未启用返回 503。
    """
    cfg = get_config().evolution
    if not cfg.enabled:
        raise HTTPException(status_code=503, detail="CXO-Tuner evolution 未启用")

    from server.config import get_settings

    settings = get_settings()
    prev_llm_host = settings.config.llm.host
    prev_llm_port = getattr(settings.config.llm, "port", None)

    # 通过 config_hot_reload 记录配置（不强制重建组件）
    from server.config_hot_reload import apply_section

    apply_result = await apply_section("evolution", cfg.model_dump(), None)

    return {
        "adapter_id": adapter_id,
        "applied": bool(apply_result.get("applied", True)),
        "detail": "骨架阶段：已记录 adapter 应用意图与 evolution 配置，未真实切换 llm",
        "lora_enabled": cfg.lora_enabled,
        "rollback": {"previous_llm_host": prev_llm_host, "previous_llm_port": prev_llm_port},
    }