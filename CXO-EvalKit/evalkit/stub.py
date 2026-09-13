"""Mock 模式内置 stub：确定性仿真 CX-O-SERVER（target）与 OpenAI 兼容 judge。

config.mock.enabled=true 时，evalkit.target.build_client 与 evalkit.judge 构造入口
统一接入本模块的 stub transport——suite 代码零感知，Mock E2E 与真实模式同一条代码路径。

stub 行为（确定性，无随机）：
- POST /api/chat：从已写入种子中按 bigram 重叠召回拼接回复（中文整句无分词也能命中）
- POST /api/memories：分配自增 memory_id 记录种子（content/importance/tags/permanent）
- GET  /api/memories：返回全部种子
- POST /api/memories/search、/api/memories/rag：按 bigram 重叠过滤种子（top-k）
- POST /api/memories/recall/{id}：返回该种子并递增其再激活计数
- POST /api/memories/eval/time-travel：累积回拨天数并返回 shifted_count
- POST /api/memories/batch/delete：真正从 stub 状态删除这些 id
- 衰减模拟：累积回拨 ≥180 天（6 月）后，非 permanent 且从未再激活的种子视为
  "已被衰减遗忘"——chat/search/rag 不再召回；permanent 与再激活过的种子始终可召回。
  （使 Mock 下保持率矩阵/再激活对照/单调性判定都有真实区分度）
- POST /v1/chat/completions（judge）：提取 prompt 中 "expected fact: X" 与 "answer: Y"，
  X 出现在 Y 中 → scores 全 5，否则全 1（确定性判分）
"""
from __future__ import annotations
import json
import re
import threading
import time
from typing import Any, Dict, List

import httpx

_FORGET_AFTER_DAYS = 180  # 模拟衰减：累积回拨超过该天数后未再激活的非永久记忆不再召回


def _keywords(text: str) -> set:
    """bigram 关键词：CJK 取相邻二字窗口，字母数字取 ≥2 连续片段。

    中文问句"你还记得我最喜欢的电影是什么吗"与种子"我最喜欢的电影是..."
    经 bigram 重叠即可命中（整句分词法会因零交集漏召回）。
    """
    out = set(re.findall(r"[A-Za-z0-9]{2,}", text or ""))
    cjk = re.findall(r"[\u4e00-\u9fff]", text or "")
    out |= {cjk[i] + cjk[i + 1] for i in range(len(cjk) - 1)}
    return out


def _overlap(a: str, b: str) -> int:
    return len(_keywords(a) & _keywords(b))


class _StubState:
    """单次 run 内的种子状态（每 run 新建，天然隔离）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._next_id = 1
        self._next_agent = 1
        self.memories: Dict[int, Dict[str, Any]] = {}
        self.agents: Dict[str, Dict[str, Any]] = {}
        self.shift_total_days = 0

    def next_agent_seq(self) -> int:
        with self._lock:
            seq = self._next_agent
            self._next_agent += 1
            return seq

    def add(self, mem: Dict[str, Any]) -> int:
        with self._lock:
            mid = self._next_id
            self._next_id += 1
            self.memories[mid] = {
                **mem,
                "id": mid,
                "is_deleted": 0,
                "reactivations": 0,
            }
            return mid

    def _recallable(self, mem: Dict[str, Any]) -> bool:
        """衰减模拟：非 permanent 且从未再激活的种子，在累积回拨 ≥180 天后被遗忘。"""
        if mem.get("permanent"):
            return True
        if mem.get("reactivations", 0) > 0:
            return True
        return self.shift_total_days < _FORGET_AFTER_DAYS

    def recallable(self, query: str, limit: int) -> List[Dict[str, Any]]:
        pool = [m for m in self.memories.values() if self._recallable(m)]
        scored = sorted(
            pool,
            key=lambda m: (_overlap(query, str(m.get("content", ""))), m["id"]),
            reverse=True,
        )
        hits = [m for m in scored if _overlap(query, str(m.get("content", ""))) > 0]
        if not hits:
            # 语义检索代理：词面零重叠时（真实系统靠向量语义仍能召回）回退全量可召回种子，
            # 避免 Mock 因问句措辞与种子无字面交集而系统性漏召回。
            hits = sorted(pool, key=lambda m: m["id"], reverse=True)
        return hits[:limit]

    def delete(self, ids: List[int]) -> int:
        with self._lock:
            removed = 0
            for mid in ids:
                if int(mid) in self.memories:
                    del self.memories[int(mid)]
                    removed += 1
            return removed


def build_stub_transport(chat_delay_ms: int = 0) -> httpx.MockTransport:
    """构造同时仿真 target 与 judge 的 httpx.MockTransport。"""
    state = _StubState()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method

        if method == "POST" and path == "/api/agents":
            body = json.loads(request.content.decode("utf-8") or "{}")
            aid = f"agent-{state.next_agent_seq():08x}"
            agent = {**body, "id": aid, "is_default": False}
            state.agents[aid] = agent
            return httpx.Response(200, json={"status": "success", "agent": agent, "message": "Agent 创建成功"})

        if method == "DELETE" and path.startswith("/api/agents/"):
            aid = path.rsplit("/", 1)[1]
            if aid not in state.agents:
                return httpx.Response(404, json={"detail": f"Agent '{aid}' 不存在"})
            del state.agents[aid]
            return httpx.Response(200, json={"status": "success", "message": "已删除"})

        if method == "POST" and path == "/api/chat":
            body = json.loads(request.content.decode("utf-8") or "{}")
            message = str(body.get("message", ""))
            hits = state.recallable(message, limit=5)
            if hits:
                recall = "；".join(f"我记得，{m['content']}" for m in hits)
            else:
                recall = "好的呀～"
            if chat_delay_ms > 0:
                time.sleep(chat_delay_ms / 1000.0)
            return httpx.Response(
                200,
                json={"status": "success", "response": recall, "session_id": "stub-session", "tokens_used": 0},
            )

        if method == "POST" and path == "/api/memories":
            body = json.loads(request.content.decode("utf-8") or "{}")
            mid = state.add(body)
            return httpx.Response(200, json={"status": "success", "memory_id": mid, "message": "记忆创建成功"})

        if method == "GET" and path == "/api/memories":
            mems = sorted(state.memories.values(), key=lambda m: m["id"])
            return httpx.Response(200, json={"status": "success", "memories": mems, "total": len(mems)})

        if method == "POST" and path in ("/api/memories/search", "/api/memories/rag"):
            body = json.loads(request.content.decode("utf-8") or "{}")
            query = str(body.get("query", request.url.params.get("query", "")))
            limit = int(body.get("limit", request.url.params.get("limit", 5)) or 5)
            hits = state.recallable(query, limit=limit)
            key = "memories" if path.endswith("/search") else "results"
            return httpx.Response(
                200, json={"status": "success", key: hits, "total": len(hits), "query": query}
            )

        if method == "POST" and path.startswith("/api/memories/recall/"):
            try:
                mid = int(path.rsplit("/", 1)[1])
            except ValueError:
                return httpx.Response(404, json={"detail": "记忆不存在"})
            mem = state.memories.get(mid)
            if mem is None:
                return httpx.Response(404, json={"detail": "记忆不存在"})
            mem["reactivations"] = int(mem.get("reactivations", 0)) + 1
            return httpx.Response(200, json={"status": "success", "memory": mem, "message": "记忆召回成功"})

        if method == "POST" and path == "/api/memories/eval/time-travel":
            body = json.loads(request.content.decode("utf-8") or "{}")
            count = len(state.memories)
            if count == 0:
                return httpx.Response(404, json={"detail": "该 agent 下没有可操作的记忆"})
            state.shift_total_days += int(body.get("shift_days", 0) or 0)
            return httpx.Response(200, json={"status": "success", "shifted_count": count, "message": "已回拨"})

        if method == "POST" and path == "/api/memories/sync-decay":
            return httpx.Response(200, json={"status": "success", "result": {"ok": True}})

        if method == "POST" and path == "/api/memories/batch/delete":
            body = json.loads(request.content.decode("utf-8") or "{}")
            removed = state.delete(body.get("ids", []))
            return httpx.Response(200, json={"status": "success", "result": {"deleted_count": removed}})

        if method == "POST" and path.endswith("/chat/completions"):
            body = json.loads(request.content.decode("utf-8") or "{}")
            prompt = ""
            try:
                prompt = body["messages"][0]["content"]
            except (KeyError, IndexError, TypeError):
                pass
            m_exp = re.search(r"expected fact:\s*(.+)", prompt)
            m_ans = re.search(r"answer:\s*(.+)", prompt, re.S)
            expected = m_exp.group(1).strip() if m_exp else ""
            answer = m_ans.group(1).strip() if m_ans else ""
            score = 5 if expected and expected in answer else 1
            reason = "答案包含目标事实" if score == 5 else "答案未包含目标事实"
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": json.dumps(
                            {"scores": {"memory_accuracy": score, "persona_consistency": score, "coherence": score},
                             "reason": reason}, ensure_ascii=False)}}
                    ]
                },
            )

        return httpx.Response(404, json={"detail": f"stub 未实现: {method} {path}"})

    return httpx.MockTransport(handler)
