"""server/autonomy/dream/generator.py（DreamGenerator 联想生成）单测。

覆盖：
1. 生成 candidates_per_session 条结构化候选
   （content / emotion_shift{valence,arousal} / associated_entities / lucidity_score / session_id）
2. 用 summary 模型（model_router.get_client(config.model)），temperature 传 dream_temperature
3. prompt 含素材摘要、情绪基调、第一人称非事实要求、结构化 JSON 约束
4. JSON 容错：```json 代码块、前后说明文字取首个合法对象、坏 JSON 重试一次后丢弃不中断
5. lucidity 缺失时确定性启发式（同内容同分）
6. 模型不可用降级：router=None / get_client 抛异常 / 返回 None client /
   chat 返回 error / chat 抛异常 / candidates=0 → 空列表

运行：python -m pytest tests/test_dream_generator.py -q
"""
import asyncio
import json

from server.autonomy.dream.collector import DreamMaterialSnapshot
from server.autonomy.dream.config import DreamConfig
from server.autonomy.dream.generator import DreamCandidate, DreamGenerator
from server.core.llm.client import LLMResponse


def _snapshot(memories=None, entities=None, baseline=0.0, agent_id="default"):
    return DreamMaterialSnapshot(
        memories=memories or [],
        isolated_entities=entities or [],
        emotion_baseline=baseline,
        agent_id=agent_id,
    )


def _valid_obj(index=0, content=None):
    return {
        "content": content or f"梦见第{index}片发光的森林",
        "emotion_shift": {"valence": 0.3, "arousal": 0.6},
        "associated_entities": ["森林", "光"],
        "lucidity_score": 0.8,
    }


class FakeClient:
    """mock LLM 客户端：按 responses 依次返回，未提供时自动生成合法 JSON。"""

    def __init__(self, responses=None, error=None, raise_exc=False):
        self.responses = list(responses or [])
        self.error = error
        self.raise_exc = raise_exc
        self.calls = 0
        self.last_messages = None
        self.last_kwargs = None

    async def chat(self, messages, stream=False, **kwargs):
        self.calls += 1
        self.last_messages = messages
        self.last_kwargs = kwargs
        if self.raise_exc:
            raise RuntimeError("client down")
        if self.error:
            return LLMResponse(content="", finish_reason="error", error=self.error)
        if self.responses:
            text = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        else:
            text = json.dumps(_valid_obj(self.calls))
        return LLMResponse(content=text, finish_reason="stop")


class FakeRouter:
    """mock model_router：仅实现 get_client，并记录请求的模型类型。"""

    def __init__(self, client=None, raise_on_get=False):
        self.client = client
        self.raise_on_get = raise_on_get
        self.get_calls = []

    def get_client(self, model_type="main"):
        self.get_calls.append(model_type)
        if self.raise_on_get:
            raise RuntimeError("no client")
        return self.client


# ================================================================ 结构化生成
class TestGenerateStructured:
    def test_returns_candidates_per_session(self):
        client = FakeClient()
        router = FakeRouter(client=client)
        gen = DreamGenerator(model_router=router, config=DreamConfig(candidates_per_session=3))
        cands = asyncio.run(gen.generate(_snapshot()))
        assert len(cands) == 3
        for c in cands:
            assert isinstance(c, DreamCandidate)
            assert c.content
            assert isinstance(c.emotion_shift, dict)
            assert "valence" in c.emotion_shift and "arousal" in c.emotion_shift
            assert isinstance(c.associated_entities, list)
            assert 0.0 <= c.lucidity_score <= 1.0
            assert c.session_id
        # 同一次会话共享 session_id
        assert len({c.session_id for c in cands}) == 1
        # temperature 传 dream_temperature（默认 0.9）
        assert client.last_kwargs.get("temperature") == 0.9

    def test_uses_summary_model(self):
        client = FakeClient()
        router = FakeRouter(client=client)
        gen = DreamGenerator(model_router=router, config=DreamConfig(model="summary"))
        asyncio.run(gen.generate(_snapshot()))
        assert router.get_calls == ["summary"]

    def test_prompt_contains_requirements(self):
        client = FakeClient()
        gen = DreamGenerator(model_router=FakeRouter(client=client), config=DreamConfig())
        snap = _snapshot(
            memories=[{"content": "傍晚在海边散步", "created_at": "2026-08-20T10:00:00"}],
            entities=["海边", "石头"],
            baseline=-0.2,
        )
        asyncio.run(gen.generate(snap))
        prompt = client.last_messages[-1]["content"]
        assert "第一人称" in prompt
        assert "非事实" in prompt
        assert "海边" in prompt and "石头" in prompt
        assert "情绪基调" in prompt
        assert "傍晚在海边散步" in prompt


# ================================================================ JSON 容错
class TestJsonTolerance:
    def test_code_fence_stripped(self):
        obj = _valid_obj(0)
        fenced = f"```json\n{json.dumps(obj, ensure_ascii=False)}\n```"
        client = FakeClient(responses=[fenced])
        gen = DreamGenerator(model_router=FakeRouter(client=client), config=DreamConfig(candidates_per_session=1))
        cands = asyncio.run(gen.generate(_snapshot()))
        assert len(cands) == 1
        assert cands[0].content == obj["content"]
        assert cands[0].associated_entities == ["森林", "光"]

    def test_prose_before_json_takes_first_object(self):
        obj = _valid_obj(0)
        text = "好的，这是我的联想：\n" + json.dumps(obj, ensure_ascii=False)
        client = FakeClient(responses=[text])
        gen = DreamGenerator(model_router=FakeRouter(client=client), config=DreamConfig(candidates_per_session=1))
        cands = asyncio.run(gen.generate(_snapshot()))
        assert len(cands) == 1
        assert cands[0].content == obj["content"]

    def test_bad_json_retry_once_then_success(self):
        valid = json.dumps(_valid_obj(1), ensure_ascii=False)
        client = FakeClient(responses=["not json at all", valid])
        gen = DreamGenerator(model_router=FakeRouter(client=client), config=DreamConfig(candidates_per_session=1))
        cands = asyncio.run(gen.generate(_snapshot()))
        assert len(cands) == 1
        assert client.calls == 2  # 首次失败 + 重试一次成功

    def test_bad_json_discard_without_interrupt(self):
        client = FakeClient(responses=["bad", "bad"])  # 两次都失败
        gen = DreamGenerator(model_router=FakeRouter(client=client), config=DreamConfig(candidates_per_session=1))
        cands = asyncio.run(gen.generate(_snapshot()))
        assert cands == []
        assert client.calls == 2

    def test_partial_failure_does_not_break_session(self):
        # 3 条候选：第 1 条两次失败丢弃，第 2/3 条成功 → 会话继续
        valid = json.dumps(_valid_obj(0), ensure_ascii=False)
        client = FakeClient(responses=["bad", "bad", valid, valid])
        gen = DreamGenerator(model_router=FakeRouter(client=client), config=DreamConfig(candidates_per_session=3))
        cands = asyncio.run(gen.generate(_snapshot()))
        assert len(cands) == 2
        assert client.calls == 4

    def test_lucidity_fallback_deterministic(self):
        # JSON 无 lucidity_score → 确定性启发式（基于内容），同内容两次生成同分
        obj = _valid_obj(0)
        obj.pop("lucidity_score", None)
        payload = json.dumps(obj, ensure_ascii=False)
        client = FakeClient(responses=[payload, payload])
        gen = DreamGenerator(model_router=FakeRouter(client=client), config=DreamConfig(candidates_per_session=2))
        cands = asyncio.run(gen.generate(_snapshot()))
        assert len(cands) == 2
        assert cands[0].lucidity_score == cands[1].lucidity_score
        assert 0.0 <= cands[0].lucidity_score <= 1.0


# ================================================================ 模型不可用降级
class TestModelUnavailable:
    def test_router_none_returns_empty(self):
        gen = DreamGenerator(model_router=None)
        assert asyncio.run(gen.generate(_snapshot())) == []

    def test_get_client_raises_returns_empty(self):
        gen = DreamGenerator(model_router=FakeRouter(raise_on_get=True))
        assert asyncio.run(gen.generate(_snapshot())) == []

    def test_get_client_none_returns_empty(self):
        gen = DreamGenerator(model_router=FakeRouter(client=None))
        assert asyncio.run(gen.generate(_snapshot())) == []

    def test_client_chat_error_returns_empty(self):
        client = FakeClient(error="模型不可用")
        gen = DreamGenerator(model_router=FakeRouter(client=client), config=DreamConfig(candidates_per_session=2))
        assert asyncio.run(gen.generate(_snapshot())) == []

    def test_client_chat_raises_returns_empty(self):
        client = FakeClient(raise_exc=True)
        gen = DreamGenerator(model_router=FakeRouter(client=client), config=DreamConfig(candidates_per_session=2))
        assert asyncio.run(gen.generate(_snapshot())) == []

    def test_zero_candidates_returns_empty(self):
        gen = DreamGenerator(
            model_router=FakeRouter(client=FakeClient()),
            config=DreamConfig(candidates_per_session=0),
        )
        assert asyncio.run(gen.generate(_snapshot())) == []
