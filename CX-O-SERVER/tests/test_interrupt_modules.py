"""server.services.asr_interrupt 与 server.services.agent_interrupt_user 单元测试。

覆盖伪全双工 / 双向全双工打断判定逻辑，隔离 aiohttp 网络与 LLM 依赖：

- ASRInterruptModule：启用开关 / 空文本 / TTS 未播 / 决策解析 / 主 LLM 路径 / 触发回调
- AgentInterruptUser：配置 / 语音状态机 / 三态决策解析 / 打断回调 / 冷却与最短时长闸门

运行：python -m pytest tests/test_interrupt_modules.py -v
"""
import types
import json

import pytest

from server.services.asr_interrupt import ASRInterruptModule
from server.services.agent_interrupt_user import AgentInterruptUser, UserSpeechState


# ================================================================ ASRInterruptModule
class TestASRInterruptModule:
    def test_initial_defaults(self):
        m = ASRInterruptModule()
        assert m.mode == "main_llm"
        assert m.enabled is True

    def test_set_config(self):
        m = ASRInterruptModule()
        m.set_config({"interrupt": {"enabled": False, "mode": "independent_llm"}})
        assert m.enabled is False
        assert m.mode == "independent_llm"

    def test_set_tts_playing_resets_interrupt(self):
        m = ASRInterruptModule()
        m._is_interrupted = True
        m.set_tts_playing(False)
        assert m._is_interrupted is False

    @pytest.mark.asyncio
    async def test_on_asr_result_disabled(self):
        m = ASRInterruptModule()
        m.enabled = False
        decision, triggered = await m.on_asr_result("你好")
        assert decision == "IGNORE"
        assert triggered is False

    @pytest.mark.asyncio
    async def test_on_asr_result_empty(self):
        m = ASRInterruptModule()
        decision, _ = await m.on_asr_result("   ")
        assert decision == "IGNORE"

    @pytest.mark.asyncio
    async def test_on_asr_result_tts_not_playing(self):
        m = ASRInterruptModule()
        m.set_tts_playing(False)
        decision, _ = await m.on_asr_result("你好")
        assert decision == "IGNORE"

    def test_parse_interrupt_decision(self):
        m = ASRInterruptModule()
        assert m._parse_interrupt_decision("x ##[INTERRUPT]## y") == "INTERRUPT"
        assert m._parse_interrupt_decision("x ##[IGNORE]## y") == "IGNORE"
        assert m._parse_interrupt_decision("x ##[CONTINUE]## y") == "CONTINUE"
        assert m._parse_interrupt_decision("no marker") == "IGNORE"

    @pytest.mark.asyncio
    async def test_trigger_interrupt_async_callback(self):
        m = ASRInterruptModule()
        fired = []

        async def cb(text, resp):
            fired.append((text, resp))

        m.set_interrupt_callback(cb)
        ok = await m._trigger_interrupt("hi", "resp")
        assert ok is True
        assert fired == [("hi", "resp")]
        assert m.is_interrupted is True

    @pytest.mark.asyncio
    async def test_trigger_interrupt_sync_callback(self):
        m = ASRInterruptModule()
        fired = []
        m.set_interrupt_callback(lambda text, resp: fired.append((text, resp)))
        await m._trigger_interrupt("a", "b")
        assert fired == [("a", "b")]

    @pytest.mark.asyncio
    async def test_trigger_interrupt_callback_error_ignored(self):
        m = ASRInterruptModule()

        def bad(text, resp):
            raise RuntimeError("boom")

        m.set_interrupt_callback(bad)
        assert await m._trigger_interrupt("a", "b") is True  # 不抛

    def test_reset_interrupt(self):
        m = ASRInterruptModule()
        m._is_interrupted = True
        m.reset_interrupt()
        assert m.is_interrupted is False

    @pytest.mark.asyncio
    async def test_check_main_llm_interrupt(self, monkeypatch):
        m = ASRInterruptModule()
        m.set_tts_playing(True)
        cm = types.SimpleNamespace(
            get_context=lambda sid: [],
            add_message=lambda sid, msg: None,
        )
        m.set_session_id("s1")
        m.set_context_manager(cm)
        llm = types.SimpleNamespace(
            chat=async_chat_with("##[INTERRUPT]## 打断")
        )
        monkeypatch.setattr("server.dependencies.get_llm_client", lambda: llm)
        decision, triggered = await m.on_asr_result("请回答")
        assert decision == "INTERRUPT"
        assert triggered is True

    @pytest.mark.asyncio
    async def test_check_main_llm_no_client(self, monkeypatch):
        m = ASRInterruptModule()
        m.set_tts_playing(True)
        monkeypatch.setattr(
            "server.dependencies.get_llm_client",
            lambda: (_ for _ in ()).throw(RuntimeError("no llm")),
        )
        decision, _ = await m.on_asr_result("x")
        assert decision == "IGNORE"

    @pytest.mark.asyncio
    async def test_independent_llm_timeout(self, monkeypatch):
        m = ASRInterruptModule()
        m.mode = "independent_llm"

        async def fake_call(text):
            raise TimeoutError

        monkeypatch.setattr(m, "_call_independent_llm", fake_call)
        # 外层 on_asr_result 捕获通用异常返回 IGNORE
        decision, _ = await m.on_asr_result("x")
        assert decision == "IGNORE"


# ================================================================ AgentInterruptUser
class TestAgentInterruptUser:
    def test_set_config(self):
        a = AgentInterruptUser()
        a.set_config({"agent_interrupt": {"enabled": False, "interrupt_threshold_ms": 800}})
        assert a.enabled is False
        assert a.interrupt_threshold_ms == 800

    def test_on_user_speech_start_end(self):
        a = AgentInterruptUser()
        a.on_user_speech_start()
        assert a.is_user_speaking is True
        a.on_user_speech_end()
        assert a.is_user_speaking is False

    def test_parse_interrupt_response_interrupt(self):
        a = AgentInterruptUser()
        r = a._parse_interrupt_response(
            '{"decision": "INTERRUPT", "reply_content": "好的", "reason": "r"}',
            is_final=True,
        )
        assert r["can_interrupt"] is True
        assert r["should_reply"] is True
        assert r["reply_content"] == "好的"

    def test_parse_interrupt_response_continue(self):
        a = AgentInterruptUser()
        r = a._parse_interrupt_response(
            '{"decision": "CONTINUE", "reply_content": "", "reason": "r"}',
            is_final=False,
        )
        assert r["can_interrupt"] is False

    def test_parse_interrupt_response_fallback_question(self):
        a = AgentInterruptUser()
        r = a._parse_interrupt_response("你能帮我吗？", is_final=True)
        assert r["can_interrupt"] is True  # 含问号 → 推断可打断

    def test_parse_interrupt_response_fallback_no_question(self):
        a = AgentInterruptUser()
        r = a._parse_interrupt_response("嗯嗯", is_final=True)
        assert r["can_interrupt"] is False

    @pytest.mark.asyncio
    async def test_on_asr_partial_disabled(self):
        a = AgentInterruptUser()
        a.enabled = False
        r = await a.on_asr_partial_result("x")
        assert r == {"should_interrupt": False, "should_reply": False}

    @pytest.mark.asyncio
    async def test_on_asr_partial_too_short(self, monkeypatch):
        a = AgentInterruptUser()
        # 拉高最短语音时长，保证命中 < min_speech_duration 分支
        a.min_speech_duration_ms = 10_000_000
        a.on_user_speech_start()
        monkeypatch.setattr(a, "_check_can_interrupt", _should_not_be_called)
        r = await a.on_asr_partial_result("短")
        assert r["should_interrupt"] is False

    @pytest.mark.asyncio
    async def test_check_independent_not_enabled(self):
        a = AgentInterruptUser()
        a.independent_llm_config["enabled"] = False
        r = await a._check_with_independent_llm("x", False)
        assert r["can_interrupt"] is False

    @pytest.mark.asyncio
    async def test_interrupt_user_callbacks(self):
        a = AgentInterruptUser()
        fired = []

        async def on_interrupt():
            fired.append("interrupt")

        async def on_tts(content):
            fired.append(("tts", content))

        a.set_callbacks(on_interrupt, on_tts)
        ok = await a.interrupt_user("你好")
        assert ok is True
        assert fired == ["interrupt", ("tts", "你好")]
        assert a.is_user_speaking is False

    @pytest.mark.asyncio
    async def test_interrupt_user_no_reply_skips_tts(self):
        a = AgentInterruptUser()
        fired = []
        a.set_callbacks(interrupt_user_callback=lambda: fired.append("i"))
        await a.interrupt_user("")
        assert fired == ["i"]  # 空 reply 不触发 TTS

    def test_build_interrupt_prompt_contains_rules(self):
        a = AgentInterruptUser()
        prompt = a._build_interrupt_prompt("你好", is_final=True)
        assert "INTERRUPT" in prompt
        assert "用户说完了" in prompt

    def test_build_interrupt_prompt_not_final(self):
        a = AgentInterruptUser()
        prompt = a._build_interrupt_prompt("你好", is_final=False)
        assert "用户正在说话" in prompt

    @pytest.mark.asyncio
    async def test_call_independent_llm_returns_parsed(self, monkeypatch):
        a = AgentInterruptUser()
        a.independent_llm_config["enabled"] = True

        async def fake_call(text):
            return {"decision": "INTERRUPT", "reason": "r"}

        monkeypatch.setattr(a, "_call_independent_llm", fake_call)
        r = await a._check_with_independent_llm("x", False)
        assert r["can_interrupt"] is True


async def _should_not_be_called(text, is_final):
    raise AssertionError("不应触发 LLM 判定（时长不足）")


def async_chat_with(content):
    """返回一个 async 的 chat 方法，返回 llm 响应对象。"""

    async def chat(**kw):
        return types.SimpleNamespace(error=None, content=content)

    return chat


# ================================================================ call_ollama_decision
# 共享助手：POST Ollama /api/generate + JSON 解析 + 文本兜底 + 超时/异常降级
def _install_fake_aiohttp(monkeypatch, response_text=None, exc=None):
    """用假 aiohttp 替换 call_ollama_decision 内部 `import aiohttp` 拿到的模块。"""
    import sys

    class FakeResponse:
        def __init__(self, text):
            self._text = text

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def json(self):
            return {"response": self._text}

    class FakeSession:
        def __init__(self):
            self.posts = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def post(self, url, **kw):
            """同步返回 async 上下文管理器，模拟真实 aiohttp 的 session.post。"""
            self.posts.append((url, kw))
            if exc is not None:
                raise exc
            return FakeResponse(response_text)

    class FakeClientTimeout:
        def __init__(self, total):
            self.total = total

    fake_session = FakeSession()
    fake_module = types.SimpleNamespace(
        ClientSession=lambda: fake_session,
        ClientTimeout=FakeClientTimeout,
    )
    monkeypatch.setitem(sys.modules, "aiohttp", fake_module)
    return fake_session


class TestCallOllamaDecision:
    @pytest.mark.asyncio
    async def test_parses_json_decision(self, monkeypatch):
        session = _install_fake_aiohttp(monkeypatch, '{"decision": "INTERRUPT", "reason": "r"}')
        result = await interrupt_llm_import().call_ollama_decision("http://x", "m", "p")
        assert result == {"decision": "INTERRUPT", "reason": "r"}
        assert session.posts[0][1]["json"]["format"] == "json"

    @pytest.mark.asyncio
    async def test_json_missing_decision_defaults_ignore(self, monkeypatch):
        _install_fake_aiohttp(monkeypatch, '{"foo": "bar"}')
        result = await interrupt_llm_import().call_ollama_decision("http://x", "m", "p")
        assert result["decision"] == "IGNORE"

    @pytest.mark.asyncio
    async def test_json_fail_text_interrupt(self, monkeypatch):
        _install_fake_aiohttp(monkeypatch, "not json INTERRUPT here")
        result = await interrupt_llm_import().call_ollama_decision("http://x", "m", "p")
        assert result == {"decision": "INTERRUPT", "reason": "文本解析"}

    @pytest.mark.asyncio
    async def test_json_fail_text_ignore(self, monkeypatch):
        _install_fake_aiohttp(monkeypatch, "IGNORE whatever")
        result = await interrupt_llm_import().call_ollama_decision("http://x", "m", "p")
        assert result["decision"] == "IGNORE"

    @pytest.mark.asyncio
    async def test_json_fail_no_keyword_continue(self, monkeypatch):
        _install_fake_aiohttp(monkeypatch, "完全没有标记的文本")
        result = await interrupt_llm_import().call_ollama_decision("http://x", "m", "p")
        assert result["decision"] == "CONTINUE"

    @pytest.mark.asyncio
    async def test_timeout_returns_continue(self, monkeypatch):
        _install_fake_aiohttp(monkeypatch, exc=TimeoutError())
        result = await interrupt_llm_import().call_ollama_decision("http://x", "m", "p")
        assert result["decision"] == "CONTINUE"
        assert result["reason"] == "超时"

    @pytest.mark.asyncio
    async def test_other_exception_returns_ignore(self, monkeypatch):
        _install_fake_aiohttp(monkeypatch, exc=RuntimeError("boom"))
        result = await interrupt_llm_import().call_ollama_decision("http://x", "m", "p")
        assert result["decision"] == "IGNORE"
        assert result["reason"] == "boom"


def interrupt_llm_import():
    from server.services import interrupt_llm

    return interrupt_llm
