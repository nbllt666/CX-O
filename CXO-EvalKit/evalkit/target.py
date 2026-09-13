"""被测主服务（CX-O-SERVER）客户端（httpx 同步，供各 suite 复用）。

封装评测所需的主服务端点。所有方法在网络/HTTP 失败时抛 TargetError；
业务失败（主服务返回 4xx/5xx）抛 TargetHttpError（携带 status code），
由 suite 决定计入失败率还是终止 run。

隔离约定：评测一律使用专用 agent_id（如 eval-agent-{run_id}），
本客户端不提供任何"无 agent_id 过滤"的写操作。

计时说明：延迟一律用 wall-clock（perf_counter）围绕请求测量（spec 要求的
"客户端计时"口径）。不用 resp.elapsed——MockTransport 下它不可用（RuntimeError），
且 wall-clock 天然覆盖连接/编码等全部客户端开销。
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import httpx

from evalkit.config import EvalConfig

DEFAULT_TIMEOUT = 120.0


class TargetError(RuntimeError):
    """网络层失败（连接拒绝/超时等），主服务不可达。"""


class TargetHttpError(TargetError):
    """主服务返回非 2xx。"""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"HTTP {status_code}: {detail}")


class TargetClient:
    """主服务 REST 客户端。transport 参数供测试注入 httpx.MockTransport。"""

    def __init__(self, config: EvalConfig, transport: Optional[httpx.BaseTransport] = None):
        self.base_url = config.target.base_url.rstrip("/")
        self.admin_api_key = config.target.admin_api_key
        self._transport = transport

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    def _client(self, timeout: float = DEFAULT_TIMEOUT) -> httpx.Client:
        # trust_env=False：httpx 默认会经 urllib 读 Windows 注册表系统代理，
        # 企业代理环境下 localhost:8000 请求被转给代理返回 502（实测教训）。
        # 本客户端只直连被测主服务，必须绕过一切系统代理。
        return httpx.Client(
            base_url=self.base_url, timeout=timeout, transport=self._transport,
            trust_env=False,
        )

    @staticmethod
    def _unwrap(resp: httpx.Response) -> Dict[str, Any]:
        if resp.status_code >= 400:
            detail = resp.text[:300]
            try:
                detail = resp.json().get("detail", detail)
            except Exception:
                pass
            raise TargetHttpError(resp.status_code, str(detail))
        return resp.json()

    def _admin_headers(self) -> Dict[str, str]:
        if not self.admin_api_key:
            if self._transport is not None:
                # Mock/测试 transport（build_client 的 stub 模式）：不强制真实 admin key
                return {}
            raise TargetError("target.admin_api_key 未配置，无法调用主服务 admin 端点")
        return {"X-API-Key": self.admin_api_key}

    # ------------------------------------------------------------------
    # 基础
    # ------------------------------------------------------------------
    def health(self) -> Dict[str, Any]:
        with self._client(timeout=10) as c:
            return self._unwrap(c.get("/health"))

    # ------------------------------------------------------------------
    # 对话（延迟/质量/劣化提问共用）
    # ------------------------------------------------------------------
    def chat(self, message: str, agent_id: str, timeout: float = DEFAULT_TIMEOUT) -> Dict[str, Any]:
        """非流式对话。返回 {"response": str, "session_id": str, ...}，附 elapsed_ms wall-clock 计时。"""
        payload = {"message": message, "agent_id": agent_id, "stream": False}
        t0 = time.perf_counter()
        with self._client(timeout=timeout) as c:
            resp = c.post("/api/chat", json=payload)
            data = self._unwrap(resp)
        data["elapsed_ms"] = (time.perf_counter() - t0) * 1000.0
        return data

    # ------------------------------------------------------------------
    # eval agent 生命周期（真实模式：主服务按 data/agents.json 校验 agent，
    # 必须注册真实 agent 才能对话/写记忆；删除时服务端连带清理记忆表/向量/图）
    # ------------------------------------------------------------------
    def create_eval_agent(self, run_id: str) -> Dict[str, Any]:
        """按 run 注册一次性评测 agent，返回 agent dict（含服务端生成的 id）。

        名称带 run_id 前 8 位保证可追溯且天然防重名；删除时走 delete_agent。
        """
        body = {
            "name": f"CXO-Eval-{run_id[:8]}",
            "description": f"CXO-EvalKit 评测专用 agent（run {run_id}，run 结束即删）",
            "system_prompt": "你是 CX-O 评测助手，正在参与一次系统评测。请以自然、稳定的方式回答问题；"
                             "当被问到关于用户的事实性问题时，基于记忆如实回答；记住的内容就明确说出来，"
                             "不记得就直说不知道，不要编造。",
            "model": "main",
            "temperature": 0.7,
            "max_tokens": 0,
            "use_memory": True,
            "use_tools": False,
            "memory_scene": "chat",
            "decay_model": "exponential",
        }
        with self._client() as c:
            data = self._unwrap(c.post("/api/agents", json=body))
        return data["agent"]

    def delete_agent(self, agent_id: str) -> Dict[str, Any]:
        """删除评测 agent（服务端连带清理 per-agent 记忆表/Weaviate collection/图库）。"""
        with self._client() as c:
            return self._unwrap(c.delete(f"/api/agents/{agent_id}"))

    # ------------------------------------------------------------------
    # 记忆写入/列表/清理（均带 agent_id 隔离）
    # ------------------------------------------------------------------
    def create_memory(
        self,
        content: str,
        agent_id: str,
        memory_type: str = "long_term",
        importance: int = 3,
        tags: Optional[List[str]] = None,
        permanent: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
        emotion_score: Optional[float] = None,
    ) -> int:
        """种入单条记忆（POST /api/memories 支持 agent_id，保证 eval agent 隔离）。

        注：主服务 POST /api/memories/batch/write 不透传 agent_id（写入 default agent），
        为满足隔离要求本客户端逐条走 POST /api/memories。
        """
        body: Dict[str, Any] = {
            "content": content,
            "type": memory_type,
            "importance": importance,
            "tags": tags or [],
            "permanent": permanent,
            "metadata": metadata or {},
            "agent_id": agent_id,
        }
        if emotion_score is not None:
            body["emotion_score"] = emotion_score
        with self._client() as c:
            data = self._unwrap(c.post("/api/memories", json=body))
        return int(data["memory_id"])

    def list_memories(self, agent_id: str, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """列出该 agent 的记忆（GET /api/memories?agent_id=...，分页聚合到 limit 上限）。"""
        out: List[Dict[str, Any]] = []
        with self._client() as c:
            while True:
                data = self._unwrap(
                    c.get(
                        "/api/memories",
                        params={
                            "agent_id": agent_id,
                            "limit": min(100, limit),
                            "offset": offset,
                        },
                    )
                )
                batch = data.get("memories", [])
                out.extend(batch)
                if len(batch) < min(100, limit) or len(out) >= limit:
                    break
                offset += len(batch)
        return out

    def batch_delete(self, ids: List[int], agent_id: str) -> Dict[str, Any]:
        """按 id 批量物理删除（POST /api/memories/batch/delete，soft_delete=False）。"""
        with self._client() as c:
            return self._unwrap(
                c.post(
                    "/api/memories/batch/delete",
                    json={"ids": ids, "agent_id": agent_id},
                    params={"soft_delete": "false"},
                )
            )

    # ------------------------------------------------------------------
    # 检索（劣化命中率 / 延迟探针共用）
    # ------------------------------------------------------------------
    def search_memories(
        self, query: str, agent_id: str, limit: int = 5, timeout: float = DEFAULT_TIMEOUT
    ) -> List[Dict[str, Any]]:
        """POST /api/memories/search。返回 memories 列表，附 elapsed_ms wall-clock 计时。"""
        body = {"query": query, "agent_id": agent_id, "limit": limit}
        t0 = time.perf_counter()
        with self._client(timeout=timeout) as c:
            resp = c.post("/api/memories/search", json=body)
            data = self._unwrap(resp)
        data["elapsed_ms"] = (time.perf_counter() - t0) * 1000.0
        return data

    def rag_search(
        self, query: str, agent_id: str, limit: int = 5, timeout: float = DEFAULT_TIMEOUT
    ) -> List[Dict[str, Any]]:
        """POST /api/memories/rag（query params 传参）。返回 results 列表，附 elapsed_ms wall-clock 计时。"""
        t0 = time.perf_counter()
        with self._client(timeout=timeout) as c:
            resp = c.post(
                "/api/memories/rag", params={"query": query, "agent_id": agent_id, "limit": limit}
            )
            data = self._unwrap(resp)
        data["elapsed_ms"] = (time.perf_counter() - t0) * 1000.0
        return data

    # ------------------------------------------------------------------
    # 劣化模拟支撑
    # ------------------------------------------------------------------
    def recall(self, memory_id: int, agent_id: str) -> Dict[str, Any]:
        """召回记忆（POST /api/memories/recall/{id}?agent_id=...，递增 reactivation_count）。

        注意：必须显式传 eval agent 的 agent_id（该端点默认 default，会污染真实记忆）。
        """
        with self._client() as c:
            return self._unwrap(
                c.post(f"/api/memories/recall/{memory_id}", params={"agent_id": agent_id})
            )

    def clear_session_messages(self, agent_id: str) -> bool:
        """清空 eval agent 会话消息（DELETE /api/context/sessions/{sid}/messages）。

        评测防污染关键步骤：chat 会话（agent-{agent_id}）的消息历史跨时间点累积，
        上一时间点的问答对会让 agent 在后续时间点"从历史复述答案"——衰减/竞争
        被完全旁路，保持率虚高为 1.0。每个时间点提问前必须清空。
        """
        sid = f"agent-{agent_id}"
        try:
            with self._client() as c:
                self._unwrap(c.delete(f"/api/context/sessions/{sid}/messages"))
            return True
        except TargetHttpError as exc:
            if exc.status_code == 404:
                return False  # 会话尚未创建（首轮提问前），无需清理
            raise

    def time_travel(
        self,
        agent_id: str,
        shift_days: int,
        memory_ids: Optional[List[int]] = None,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """时间旅行回拨（POST /api/memories/eval/time-travel，admin key 门控）。"""
        body: Dict[str, Any] = {"agent_id": agent_id, "shift_days": shift_days}
        if memory_ids:
            body["memory_ids"] = memory_ids
        if tags:
            body["tags"] = tags
        with self._client() as c:
            return self._unwrap(
                c.post(
                    "/api/memories/eval/time-travel", json=body, headers=self._admin_headers()
                )
            )

    def sync_decay(self) -> Dict[str, Any]:
        """触发衰减重算（POST /api/memories/sync-decay）。"""
        with self._client() as c:
            return self._unwrap(c.post("/api/memories/sync-decay", params={"workspace_id": "default"}))

    def decay_stats(self) -> Dict[str, Any]:
        """衰减统计（GET /api/memories/decay-stats）。"""
        with self._client() as c:
            return self._unwrap(c.get("/api/memories/decay-stats", params={"workspace_id": "default"}))


def build_client(config: EvalConfig, transport: Optional[httpx.BaseTransport] = None) -> TargetClient:
    """suite 统一入口：mock.enabled=true 时自动接入内置 stub transport。"""
    if config.mock.enabled:
        from evalkit.stub import build_stub_transport

        transport = build_stub_transport(config.mock.chat_delay_ms)
    return TargetClient(config, transport=transport)
