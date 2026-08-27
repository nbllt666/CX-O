"""
server.services.asr_interrupt 与 server.services.agent_interrupt_user 单元测试。

覆盖伪全双工 / 双向全双工打断判定逻辑，隔离 aiohttp 网络与 LLM 依赖：

- ASRInterruptModule：启用开关 / 空文本 / TTS 未播 / 决策解析 / 主 LLM 路径 / 触发回调
- AgentInterruptUser：配置 / 语音状态机 / 三态决策解析 / 打断回调 / 冷却与最短时长闸门
- DualStreamSession × speech_end_fallback：LLM 插话打断后 VAD 兜底互斥（跳/不跳）

运行：python -m pytest tests/test_interrupt_modules.py -v
"""
import asyncio
import types

import pytest

from server.handlers.audio import DualStreamSession
from server.services.asr_interrupt import ASRInterruptModule, get_asr_interrupt_module
from server.services.agent_interrupt_user import AgentInterruptUser, get_agent_interrupt_module


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
    async def test_partial_interrupt_skips_context_write(self, monkeypatch):
        # 第六轮 C1-5：同一 utterance 的多帧 partial 命中 INTERRUPT——打断判定即时
        # 触发（保留实时性），但「写回真实上下文」仅在 final 时执行一次，
        # 避免同一句子的多个 partial 被重复写入真实 context 造成膨胀/污染。
        m = ASRInterruptModule()
        m.set_tts_playing(True)
        written = []
        cm = types.SimpleNamespace(
            get_context=lambda sid: [],
            add_message=lambda sid, msg: written.append(msg),
        )
        m.set_session_id("s1")
        m.set_context_manager(cm)
        llm = types.SimpleNamespace(chat=async_chat_with("##[INTERRUPT]## 打断"))
        monkeypatch.setattr("server.dependencies.get_llm_client", lambda: llm)

        for partial_text in ("请", "请问", "请问你"):
            d, t = await m.on_asr_result(partial_text, is_final=False)
            assert (d, t) == ("INTERRUPT", True)

        # 打断实时性保持：partial 阶段即置位
        assert m.is_interrupted is True
        # 但 partial 阶段未写回真实上下文
        assert written == []

        # final：仅写回一次
        df, tf = await m.on_asr_result("请问你是谁", is_final=True)
        assert (df, tf) == ("INTERRUPT", True)
        assert len(written) == 1
        assert written[0] == {"role": "user", "content": "请问你是谁"}

    @pytest.mark.asyncio
    async def test_ignore_partial_skips_context_write(self, monkeypatch):
        # IGNORE 判定同样只在 final 写回真实上下文一次
        m = ASRInterruptModule()
        m.set_tts_playing(True)
        written = []
        cm = types.SimpleNamespace(
            get_context=lambda sid: [],
            add_message=lambda sid, msg: written.append(msg),
        )
        m.set_session_id("s1")
        m.set_context_manager(cm)
        llm = types.SimpleNamespace(chat=async_chat_with("##[IGNORE]## 自语"))
        monkeypatch.setattr("server.dependencies.get_llm_client", lambda: llm)

        d, t = await m.on_asr_result("算了算了", is_final=False)
        assert (d, t) == ("IGNORE", False)
        assert written == []

        d, t = await m.on_asr_result("算了算了", is_final=True)
        assert (d, t) == ("IGNORE", False)
        assert len(written) == 1
        assert written[0] == {"role": "user", "content": "算了算了"}

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
        a.set_config({"agent_interrupt": {"enabled": False}})
        assert a.enabled is False

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

    @pytest.mark.asyncio
    async def test_stats_cumulative(self, monkeypatch):
        a = AgentInterruptUser()
        a.min_speech_duration_ms = 0
        a._interrupt_cooldown_ms = 0  # 关闭冷却，便于连续多次判定
        a.on_user_speech_start()

        results = {
            "CONTINUE": {"decision": "CONTINUE", "can_interrupt": False, "should_reply": False},
            "IGNORE": {"decision": "IGNORE", "can_interrupt": False, "should_reply": False},
            "INTERRUPT": {"decision": "INTERRUPT", "can_interrupt": True, "should_reply": True},
        }
        seq = iter(["CONTINUE", "IGNORE", "INTERRUPT", "CONTINUE"])

        async def fake_check(text, is_final):
            return results[next(seq)]

        monkeypatch.setattr(a, "_check_can_interrupt", fake_check)

        # 第 3 次返回 INTERRUPT 的文本需含提问/请求意图，命中 Feature A 闸门后仍按 INTERRUPT 累计
        await a.on_asr_partial_result("在吗？")
        await a.on_asr_partial_result("我在思考")
        await a.on_asr_partial_result("帮我查一下天气")
        await a.on_asr_partial_result("开始了")

        stats = a.get_stats()
        assert stats["total_judgments"] == 4
        assert stats["decisions"] == {"INTERRUPT": 1, "CONTINUE": 2, "IGNORE": 1}
        assert stats["interrupts_triggered"] == 1
        assert stats["replies_triggered"] == 0

    def test_reset_stats(self):
        a = AgentInterruptUser()
        a._stats["total_judgments"] = 5
        a._stats["decisions"]["INTERRUPT"] = 3
        a._stats["interrupts_triggered"] = 2
        a._stats["replies_triggered"] = 4
        a.reset_stats()
        assert a.get_stats() == {
            "total_judgments": 0,
            "decisions": {"INTERRUPT": 0, "CONTINUE": 0, "IGNORE": 0},
            "interrupts_triggered": 0,
            "replies_triggered": 0,
        }

    @pytest.mark.asyncio
    async def test_stats_no_duplicate_interrupt_count(self, monkeypatch):
        a = AgentInterruptUser()
        a.min_speech_duration_ms = 0
        a.on_user_speech_start()

        async def fake_check(text, is_final):
            return {"decision": "INTERRUPT", "can_interrupt": True, "should_reply": True}

        monkeypatch.setattr(a, "_check_can_interrupt", fake_check)
        await a.on_asr_partial_result("请回答")
        # 同 utterance 后续 partial 落入冷却早退，不再产生判定与打断计数
        await a.on_asr_partial_result("请回答继续")
        stats = a.get_stats()
        assert stats["interrupts_triggered"] == 1
        assert stats["total_judgments"] == 1

    def test_speech_end_fallback_default_false(self):
        a = AgentInterruptUser()
        assert a.speech_end_fallback is False

    def test_speech_end_fallback_parsed_true(self):
        a = AgentInterruptUser()
        a.set_config({"agent_interrupt": {"speech_end_fallback": True}})
        assert a.speech_end_fallback is True

    def test_speech_end_fallback_default_false_after_config(self):
        a = AgentInterruptUser()
        # 未传 speech_end_fallback 字段 → 保持默认 False
        a.set_config({"agent_interrupt": {"enabled": True}})
        assert a.speech_end_fallback is False

    # ================================================================ Feature A：提问意图硬闸门

    def test_has_question_or_request_basic(self):
        a = AgentInterruptUser()
        assert a._has_question_or_request("唉，今天好累啊") is False   # 情绪独白 → 无意图
        assert a._has_question_or_request("今天天气怎么样？") is True    # 提问词"？/怎么样"
        assert a._has_question_or_request("帮我查一下") is True          # 祈使请求"帮我/查"
        assert a._has_question_or_request("   ") is False               # 空白 → False

    @pytest.mark.asyncio
    async def test_question_gate_downgrades_interrupt(self, monkeypatch):
        # LLM 误判 INTERRUPT 但文本无提问/请求（self_talk）→ 闸门降级为不打断
        a = AgentInterruptUser()
        a.min_speech_duration_ms = 0
        a._interrupt_cooldown_ms = 0
        a.on_user_speech_start()

        async def fake_check(text, is_final):
            return {"decision": "INTERRUPT", "can_interrupt": True, "should_reply": True}

        monkeypatch.setattr(a, "_check_can_interrupt", fake_check)
        r = await a.on_asr_partial_result("唉今天好累啊")
        assert r["should_interrupt"] is False
        assert r["should_reply"] is False
        # 统计按实际生效 decision 累计（INTERRUPT 降级为 IGNORE）
        assert a.get_stats()["decisions"]["INTERRUPT"] == 0
        assert a.get_stats()["decisions"]["IGNORE"] == 1
        assert a.get_stats()["interrupts_triggered"] == 0

    @pytest.mark.asyncio
    async def test_question_gate_lets_question_pass(self, monkeypatch):
        a = AgentInterruptUser()
        a.min_speech_duration_ms = 0
        a._interrupt_cooldown_ms = 0
        a.on_user_speech_start()

        async def fake_check(text, is_final):
            return {"decision": "INTERRUPT", "can_interrupt": True, "should_reply": True}

        monkeypatch.setattr(a, "_check_can_interrupt", fake_check)
        r = await a.on_asr_partial_result("今天天气怎么样？")
        assert r["should_interrupt"] is True
        assert a.get_stats()["interrupts_triggered"] == 1

    @pytest.mark.asyncio
    async def test_question_gate_disabled_skips(self, monkeypatch):
        # question_intent_required=False → 不过闸门，LLM INTERRUPT 原样放行（回退上一轮行为）
        a = AgentInterruptUser()
        a.min_speech_duration_ms = 0
        a._interrupt_cooldown_ms = 0
        a.question_intent_required = False
        a.on_user_speech_start()

        async def fake_check(text, is_final):
            return {"decision": "INTERRUPT", "can_interrupt": True, "should_reply": True}

        monkeypatch.setattr(a, "_check_can_interrupt", fake_check)
        r = await a.on_asr_partial_result("唉今天好累啊")
        assert r["should_interrupt"] is True
        assert a.get_stats()["decisions"]["INTERRUPT"] == 1

    # ================================================================ Feature B：最终完整请求回复触发

    @pytest.mark.asyncio
    async def test_final_question_triggers_reply(self, monkeypatch, caplog):
        # is_final 且累计文本经意图闸门 → 触发一次回复（short_phrases 场景）
        # 【标签解耦】should_interrupt=False（非真打断）、should_reply=True（需回复）
        a = AgentInterruptUser()
        a.min_speech_duration_ms = 0
        a._interrupt_cooldown_ms = 0
        a.on_user_speech_start()

        async def fake_check(text, is_final):
            return {"decision": "CONTINUE", "can_interrupt": False, "should_reply": False}

        monkeypatch.setattr(a, "_check_can_interrupt", fake_check)
        with caplog.at_level("INFO", logger="server.services.agent_interrupt_user"):
            r = await a.on_asr_partial_result("嗯……然后呢？", is_final=True)
        assert r["should_interrupt"] is False
        assert r["should_reply"] is True
        assert a.get_stats()["replies_triggered"] == 1
        assert a.get_stats()["interrupts_triggered"] == 0
        # [O1 时序标定] 触发日志带相对耗时，供评测侧比对 send_done_rel
        assert any("reply triggered at" in rec.message and "since speech_start" in rec.message
                   for rec in caplog.records)

    @pytest.mark.asyncio
    async def test_final_organizing_no_question_no_trigger(self, monkeypatch):
        # 组织期（无提问）→ 不触发 Feature B
        a = AgentInterruptUser()
        a.min_speech_duration_ms = 0
        a._interrupt_cooldown_ms = 0
        a.on_user_speech_start()

        async def fake_check(text, is_final):
            return {"decision": "CONTINUE", "can_interrupt": False, "should_reply": False}

        monkeypatch.setattr(a, "_check_can_interrupt", fake_check)
        r = await a.on_asr_partial_result("嗯……", is_final=True)
        assert r["should_interrupt"] is False
        assert a.get_stats()["interrupts_triggered"] == 0
        assert a.get_stats()["replies_triggered"] == 0

    @pytest.mark.asyncio
    async def test_reply_on_final_question_disabled_no_trigger(self, monkeypatch):
        # reply_on_final_question=False → is_final 含提问也不触发
        a = AgentInterruptUser()
        a.min_speech_duration_ms = 0
        a._interrupt_cooldown_ms = 0
        a.reply_on_final_question = False
        a.on_user_speech_start()

        async def fake_check(text, is_final):
            return {"decision": "CONTINUE", "can_interrupt": False, "should_reply": False}

        monkeypatch.setattr(a, "_check_can_interrupt", fake_check)
        r = await a.on_asr_partial_result("然后呢？", is_final=True)
        assert r["should_interrupt"] is False
        assert r["should_reply"] is False
        assert a.get_stats()["interrupts_triggered"] == 0
        assert a.get_stats()["replies_triggered"] == 0

    @pytest.mark.asyncio
    async def test_final_question_no_duplicate_after_interrupt(self, monkeypatch):
        # 本 utterance 已打断（Feature A）后，is_final 不再重复触发 Feature B
        a = AgentInterruptUser()
        a.min_speech_duration_ms = 0
        a._interrupt_cooldown_ms = 0
        a.on_user_speech_start()

        async def fake_check(text, is_final):
            if is_final:
                return {"decision": "CONTINUE", "can_interrupt": False, "should_reply": False}
            return {"decision": "INTERRUPT", "can_interrupt": True, "should_reply": True}

        monkeypatch.setattr(a, "_check_can_interrupt", fake_check)
        r1 = await a.on_asr_partial_result("帮我查一下天气")  # Feature A 打断
        assert r1["should_interrupt"] is True
        # 同 utterance 后续 final：Feature B 因 _interrupted_this_utterance 守卫不再重复触发
        r2 = await a.on_asr_partial_result("然后呢？", is_final=True)
        assert r2["should_interrupt"] is False
        assert r2["should_reply"] is False
        assert a.get_stats()["interrupts_triggered"] == 1
        assert a.get_stats()["replies_triggered"] == 0

    # ================================================================ 边缘用例（人类裁决：测试边缘情况）

    # ---- Feature A 意图判定边界 ----
    def test_has_question_edge_cases(self):
        a = AgentInterruptUser()
        # 情绪化但无提问词/请求 → False
        assert a._has_question_or_request("哎，真烦人啊") is False
        assert a._has_question_or_request("累死了，不想动了") is False
        assert a._has_question_or_request("好吧好吧") is False
        # 情绪 + 提问混合 → 含提问词即 True
        assert a._has_question_or_request("唉，不过明天几点开门？") is True
        assert a._has_question_or_request("好烦啊，你觉得呢") is True
        # 未加提问标点的疑问/请求
        assert a._has_question_or_request("帮我看看是不是下雨了") is True
        assert a._has_question_or_request("我该怎么办") is True
        # 空/纯符号/纯语气 → False
        assert a._has_question_or_request("嗯嗯") is False
        assert a._has_question_or_request("...") is False

    @pytest.mark.asyncio
    async def test_question_gate_edge_emotion_variants(self, monkeypatch):
        # 多种情绪独白变体在 LLM 误判 INTERRUPT 时均被闸门降级
        a = AgentInterruptUser()
        a.min_speech_duration_ms = 0
        a._interrupt_cooldown_ms = 0
        a.on_user_speech_start()

        async def fake_check(text, is_final):
            return {"decision": "INTERRUPT", "can_interrupt": True, "should_reply": True}

        monkeypatch.setattr(a, "_check_can_interrupt", fake_check)
        for t in ("哎，真烦人啊", "累死了", "天啊", "我今天好难过"):
            a.on_user_speech_start()  # 重置本 utterance 状态（含 current_text 与打断标记）
            r = await a.on_asr_partial_result(t)
            assert r["should_interrupt"] is False, f"{t} 应被闸门降级"

    # ---- Feature B 边界 ----
    @pytest.mark.asyncio
    async def test_final_emotion_only_no_trigger(self, monkeypatch):
        # is_final 但为情绪独白（无提问）→ 不触发 Feature B
        a = AgentInterruptUser()
        a.min_speech_duration_ms = 0
        a._interrupt_cooldown_ms = 0
        a.on_user_speech_start()

        async def fake_check(text, is_final):
            return {"decision": "CONTINUE", "can_interrupt": False, "should_reply": False}

        monkeypatch.setattr(a, "_check_can_interrupt", fake_check)
        r = await a.on_asr_partial_result("唉，今天好累啊", is_final=True)
        assert r["should_interrupt"] is False
        assert r["should_reply"] is False
        assert a.get_stats()["interrupts_triggered"] == 0
        assert a.get_stats()["replies_triggered"] == 0

    @pytest.mark.asyncio
    async def test_final_empty_no_trigger(self, monkeypatch):
        # is_final 但空/纯语气文本 → 不触发 Feature B
        a = AgentInterruptUser()
        a.min_speech_duration_ms = 0
        a._interrupt_cooldown_ms = 0
        a.on_user_speech_start()

        async def fake_check(text, is_final):
            return {"decision": "CONTINUE", "can_interrupt": False, "should_reply": False}

        monkeypatch.setattr(a, "_check_can_interrupt", fake_check)
        r = await a.on_asr_partial_result("嗯……", is_final=True)
        assert r["should_interrupt"] is False
        assert r["should_reply"] is False
        assert a.get_stats()["interrupts_triggered"] == 0
        assert a.get_stats()["replies_triggered"] == 0

    @pytest.mark.asyncio
    async def test_final_second_duplicate_blocked(self, monkeypatch):
        # Feature B 触发一次后，同 utterance 后续 final 不再重复触发（防重复回复）
        a = AgentInterruptUser()
        a.min_speech_duration_ms = 0
        a._interrupt_cooldown_ms = 0
        a.on_user_speech_start()

        async def fake_check(text, is_final):
            return {"decision": "CONTINUE", "can_interrupt": False, "should_reply": False}

        monkeypatch.setattr(a, "_check_can_interrupt", fake_check)
        r1 = await a.on_asr_partial_result("帮我查一下", is_final=True)
        assert r1["should_interrupt"] is False
        assert r1["should_reply"] is True
        r2 = await a.on_asr_partial_result("帮我查一下", is_final=True)
        assert r2["should_interrupt"] is False
        assert r2["should_reply"] is False
        assert a.get_stats()["replies_triggered"] == 1
        assert a.get_stats()["interrupts_triggered"] == 0

    @pytest.mark.asyncio
    async def test_final_respects_cooldown(self, monkeypatch):
        # 冷却窗口内（上次打断尚在 cooldown）→ Feature B 被冷却早退拦截
        a = AgentInterruptUser()
        a.min_speech_duration_ms = 0
        a._interrupt_cooldown_ms = 3000
        a.on_user_speech_start()
        import time as _t
        a._last_interrupt_time = _t.time()  # 视为刚打断过

        async def fake_check(text, is_final):
            raise AssertionError("冷却早退不应触发 LLM 判定")

        monkeypatch.setattr(a, "_check_can_interrupt", fake_check)
        r = await a.on_asr_partial_result("明天几点？", is_final=True)
        assert r["should_interrupt"] is False

    # ================================================================ 极限边缘（用户裁决"再边缘一点"）
    def test_has_question_extreme_edge(self):
        a = AgentInterruptUser()
        # 全角 / 半角问号
        assert a._has_question_or_request("今天天气怎么样?") is True   # 半角 ?
        assert a._has_question_or_request("明天几点？") is True          # 全角 ？
        # 纯符号 / emoji / 无意义
        assert a._has_question_or_request("😀😀😀") is False
        assert a._has_question_or_request("。。。就是累") is False
        assert a._has_question_or_request("哈？……") is True             # 含 ？
        # 数字 / 日期 / 纯陈述长句
        assert a._has_question_or_request("2026年8月20日") is False
        assert a._has_question_or_request("我今天早上吃了一个苹果然后去上班") is False
        # 单字疑问
        assert a._has_question_or_request("嗯？") is True
        # 反馈词单独出现 → 无意图
        assert a._has_question_or_request("好的") is False
        assert a._has_question_or_request("收到") is False
        assert a._has_question_or_request("没问题") is False
        # 请求词独立触发（请 / 设 / 查 / 提醒 / 播放）
        assert a._has_question_or_request("请稍等") is True
        assert a._has_question_or_request("设个闹钟") is True
        assert a._has_question_or_request("提醒我下午开会") is True
        assert a._has_question_or_request("播放一首歌") is True
        # 全角空白归一化 → 无意图
        assert a._has_question_or_request("\u3000\u3000累\u3000") is False
        # 超长非意图文本（重复陈述，无任何提问词/请求词）
        assert a._has_question_or_request(
            "我今天早上吃了一个苹果，然后去公司开会，开完会就回家了" * 5) is False

    @pytest.mark.asyncio
    async def test_gate_fullwidth_question_lets_pass(self, monkeypatch):
        # LLM INTERRUPT + 半角问号 → 闸门放行（仍有真实提问/请求）
        a = AgentInterruptUser()
        a.min_speech_duration_ms = 0
        a._interrupt_cooldown_ms = 0
        a.on_user_speech_start()

        async def fake_check(text, is_final):
            return {"decision": "INTERRUPT", "can_interrupt": True, "should_reply": True}

        monkeypatch.setattr(a, "_check_can_interrupt", fake_check)
        r = await a.on_asr_partial_result("今天天气怎么样?")
        assert r["should_interrupt"] is True

    @pytest.mark.asyncio
    async def test_gate_emoji_no_trigger(self, monkeypatch):
        # LLM 误判 INTERRUPT + emoji（无意图）→ 闸门降级
        a = AgentInterruptUser()
        a.min_speech_duration_ms = 0
        a._interrupt_cooldown_ms = 0
        a.on_user_speech_start()

        async def fake_check(text, is_final):
            return {"decision": "INTERRUPT", "can_interrupt": True, "should_reply": True}

        monkeypatch.setattr(a, "_check_can_interrupt", fake_check)
        r = await a.on_asr_partial_result("😀😀😀")
        assert r["should_interrupt"] is False

    @pytest.mark.asyncio
    async def test_final_fullwidth_question_triggers(self, monkeypatch):
        # Feature B：is_final + 半角问号 → 触发回复
        a = AgentInterruptUser()
        a.min_speech_duration_ms = 0
        a._interrupt_cooldown_ms = 0
        a.on_user_speech_start()

        async def fake_check(text, is_final):
            return {"decision": "CONTINUE", "can_interrupt": False, "should_reply": False}

        monkeypatch.setattr(a, "_check_can_interrupt", fake_check)
        r = await a.on_asr_partial_result("明天几点?", is_final=True)
        assert r["should_interrupt"] is False
        assert r["should_reply"] is True

    @pytest.mark.asyncio
    async def test_gate_long_nonintent_downgrade(self, monkeypatch):
        # LLM 误判 INTERRUPT + 超长非意图陈述 → 闸门降级
        a = AgentInterruptUser()
        a.min_speech_duration_ms = 0
        a._interrupt_cooldown_ms = 0
        a.on_user_speech_start()

        async def fake_check(text, is_final):
            return {"decision": "INTERRUPT", "can_interrupt": True, "should_reply": True}

        monkeypatch.setattr(a, "_check_can_interrupt", fake_check)
        long_text = "我今天早上吃了一个苹果然后去公司开会开完会就回家了" * 5
        r = await a.on_asr_partial_result(long_text)
        assert r["should_interrupt"] is False

    # ================================================================ 极限边缘（人类裁决"再边缘一点"：非问句固定搭配/词碰撞）
    def test_has_question_statement_set_phrases(self):
        a = AgentInterruptUser()
        # 含疑问词但为陈述/客套/情绪填充 → 剔除后不触发
        assert a._has_question_or_request("什么都不想做") is False
        assert a._has_question_or_request("没什么") is False
        assert a._has_question_or_request("不怎么好看") is False
        assert a._has_question_or_request("哪里哪里") is False
        assert a._has_question_or_request("管他呢") is False
        assert a._has_question_or_request("还没呢") is False
        assert a._has_question_or_request("没办法嘛") is False
        assert a._has_question_or_request("就是嘛") is False
        assert a._has_question_or_request("这有什么难的") is False
        # 请求字词内碰撞（设）→ 剔除后不触发
        assert a._has_question_or_request("假设明天会下雨") is False
        assert a._has_question_or_request("设备已经装好了") is False

    # ---- 反诘/反问句式（模拟场景"说话中途打断"实测暴露：反诘被误打断）----
    def test_has_question_rhetorical_reverse(self):
        a = AgentInterruptUser()
        # 反诘/反问（含"什么"但属情绪宣泄，非对 Agent 的提问）→ 不触发
        assert a._has_question_or_request("这有什么好问的，我真是服了") is False
        assert a._has_question_or_request("什么好问的") is False       # ASR 缺前缀变体
        assert a._has_question_or_request("什么好笑的") is False       # ASR 缺前缀变体
        assert a._has_question_or_request("什么好奇怪的") is False     # ASR 缺前缀变体
        assert a._has_question_or_request("有什么了不起的") is False
        assert a._has_question_or_request("这有什么好笑的") is False
        # 反诘剔除不误杀真问句（硬问号/吗/反诘外句式保留）
        assert a._has_question_or_request("有什么好吃的吗？") is True
        assert a._has_question_or_request("你觉得什么好？") is True
        assert a._has_question_or_request("你说什么好？") is True
        assert a._has_question_or_request("我该怎么办") is True

    @pytest.mark.asyncio
    async def test_question_gate_rhetorical_downgrade(self, monkeypatch):
        # LLM 误判 INTERRUPT + 反诘/反问（"这有什么好问的"）→ 意图闸门降级不打断
        a = AgentInterruptUser()
        a.min_speech_duration_ms = 0
        a._interrupt_cooldown_ms = 0
        a.on_user_speech_start()

        async def fake_check(text, is_final):
            return {"decision": "INTERRUPT", "can_interrupt": True, "should_reply": True}

        monkeypatch.setattr(a, "_check_can_interrupt", fake_check)
        for t in ("这有什么好问的，我真是服了", "什么好笑的", "有什么了不起的"):
            a.on_user_speech_start()  # 重置本 utterance 状态
            r = await a.on_asr_partial_result(t)
            assert r["should_interrupt"] is False, f"{t} 反诘应被闸门降级"
            assert a.get_stats()["interrupts_triggered"] == 0

    def test_has_question_blocklist_does_not_kill_real_questions(self):
        a = AgentInterruptUser()
        # 剔除表不误杀真问句：硬性问号/吗/不在表内的疑问词仍触发
        assert a._has_question_or_request("还没呢，几点开会？") is True   # 硬问号保留
        assert a._has_question_or_request("没什么想问的吗") is True         # 吗 保留
        assert a._has_question_or_request("怎么了") is True                # 怎么（非"不怎么"）
        assert a._has_question_or_request("哪里不舒服") is True            # 哪里（非固定搭配）
        assert a._has_question_or_request("然后呢") is True                # 呢（非"还没呢/管他呢"）
        assert a._has_question_or_request("没办法解决吗") is True          # 吗（"没办法嘛"≠"没办法解决吗"）
        assert a._has_question_or_request("为什么") is True                # 疑问词独立触发
        assert a._has_question_or_request("多少") is True

    def test_has_question_mixed_lang_and_punct(self):
        a = AgentInterruptUser()
        # 中英混合 / 纯问号 / 连续无意义重复 / 极短请求 / 否定+提问
        assert a._has_question_or_request("How are you?") is True   # 半角 ?
        assert a._has_question_or_request("how are you") is False   # 纯英文无标点 → 不触发（中文意图闸门已知边界）
        assert a._has_question_or_request("我在听，ok?") is True
        assert a._has_question_or_request("？") is True
        assert a._has_question_or_request("?") is True
        assert a._has_question_or_request("啊啊啊") is False
        assert a._has_question_or_request("哈哈哈哈哈哈") is False
        assert a._has_question_or_request("帮我") is True
        assert a._has_question_or_request("不去了吗？") is True

    @pytest.mark.asyncio
    async def test_question_gate_statement_phrase_downgrade(self, monkeypatch):
        # Feature A：LLM 误判 INTERRUPT + 非问句固定搭配 → 闸门降级不打断
        a = AgentInterruptUser()
        a.min_speech_duration_ms = 0
        a._interrupt_cooldown_ms = 0
        a.on_user_speech_start()

        async def fake_check(text, is_final):
            return {"decision": "INTERRUPT", "can_interrupt": True, "should_reply": True}

        monkeypatch.setattr(a, "_check_can_interrupt", fake_check)
        for t in ("什么都不想做", "还没呢", "没办法嘛", "哪里哪里"):
            a.on_user_speech_start()  # 重置本 utterance 状态
            r = await a.on_asr_partial_result(t)
            assert r["should_interrupt"] is False, f"{t} 应被闸门降级"
            assert a.get_stats()["interrupts_triggered"] == 0

    @pytest.mark.asyncio
    async def test_final_statement_phrase_no_trigger(self, monkeypatch):
        # Feature B：is_final + 非问句固定搭配 → 不触发（防新增误触发路径）
        a = AgentInterruptUser()
        a.min_speech_duration_ms = 0
        a._interrupt_cooldown_ms = 0
        a.on_user_speech_start()

        async def fake_check(text, is_final):
            return {"decision": "CONTINUE", "can_interrupt": False, "should_reply": False}

        monkeypatch.setattr(a, "_check_can_interrupt", fake_check)
        for t in ("什么都不想做", "还没呢", "没办法嘛"):
            a.on_user_speech_start()
            r = await a.on_asr_partial_result(t, is_final=True)
            assert r["should_interrupt"] is False, f"{t} is_final 不应触发 Feature B"
        assert a.get_stats()["interrupts_triggered"] == 0

    @pytest.mark.asyncio
    async def test_final_blocklist_still_triggers_real_question(self, monkeypatch):
        # Feature B：is_final 含剔除表短语但另有硬问号 → 仍触发（剔除不误杀）
        a = AgentInterruptUser()
        a.min_speech_duration_ms = 0
        a._interrupt_cooldown_ms = 0
        a.on_user_speech_start()

        async def fake_check(text, is_final):
            return {"decision": "CONTINUE", "can_interrupt": False, "should_reply": False}

        monkeypatch.setattr(a, "_check_can_interrupt", fake_check)
        r = await a.on_asr_partial_result("还没呢，几点开会？", is_final=True)
        assert r["should_interrupt"] is False
        assert r["should_reply"] is True
        assert a.get_stats()["replies_triggered"] == 1
        assert a.get_stats()["interrupts_triggered"] == 0

    # ================================================================ 新开关 set_config 解析

    def test_config_new_switches_default_true(self):
        a = AgentInterruptUser()
        assert a.question_intent_required is True
        assert a.reply_on_final_question is True
        a.set_config({"agent_interrupt": {"enabled": True}})  # 未传 → 保持默认 True
        assert a.question_intent_required is True
        assert a.reply_on_final_question is True

    def test_config_new_switches_parse_false(self):
        a = AgentInterruptUser()
        a.set_config({"agent_interrupt": {
            "question_intent_required": False,
            "reply_on_final_question": False,
        }})
        assert a.question_intent_required is False
        assert a.reply_on_final_question is False

    # ---- speech_end_fallback × VAD 兜底互斥（DualStreamSession 层）----

    def _make_dual_session(self):
        """构造最小可用的 DualStreamSession（manager/tts_service 用假对象，隔离真实依赖）。"""
        mgr = types.SimpleNamespace(send_message=async_noop)
        tts = types.SimpleNamespace()
        return DualStreamSession(
            client_id="c1", agent_id="a1", request_id="r1",
            manager=mgr, tts_service=tts,
        )

    @pytest.mark.asyncio
    async def test_vad_fallback_skipped_when_interrupt_and_fallback_true(self, monkeypatch):
        # speech_end_fallback=true 且 _agent_interrupt_triggered 置位
        # → on_vad_speech_end 未触发分支开头跳过兜底（不启动 pipeline）
        session = self._make_dual_session()
        session._has_triggered_this_utterance = False
        session._agent_interrupt_triggered = True
        fake_mod = types.SimpleNamespace(speech_end_fallback=True)
        monkeypatch.setattr(
            "server.services.agent_interrupt_user.get_agent_interrupt_module",
            lambda client_id=None: fake_mod,
        )
        # 若兜底未被跳过会走到 create_task(_run_pipeline)；patch 为空便于断言未调用
        monkeypatch.setattr(session, "_run_pipeline", async_noop)

        await session.on_vad_speech_end({"text": "你好"})

        assert session._agent_interrupt_triggered is True  # 打断标记保持
        assert session._has_triggered_this_utterance is False  # 未触发 LLM
        assert session._pipeline_task is None  # 未启动兜底 pipeline

    @pytest.mark.asyncio
    async def test_vad_fallback_runs_when_fallback_false(self, monkeypatch):
        # speech_end_fallback=false → 即使已插话打断，VAD 兜底照常触发
        session = self._make_dual_session()
        session._has_triggered_this_utterance = False
        session._agent_interrupt_triggered = True
        fake_mod = types.SimpleNamespace(speech_end_fallback=False)
        monkeypatch.setattr(
            "server.services.agent_interrupt_user.get_agent_interrupt_module",
            lambda client_id=None: fake_mod,
        )
        monkeypatch.setattr(session, "_run_pipeline", async_noop)
        monkeypatch.setattr(session, "_finalize_turn", async_noop)

        await session.on_vad_speech_end({"text": "你好"})
        await asyncio.sleep(0)  # 让后台 task 跑完，避免 pending task warning

        assert session._has_triggered_this_utterance is True  # 已触发 LLM
        assert session._pipeline_task is not None  # 兜底 pipeline 已启动

    @pytest.mark.asyncio
    async def test_interrupt_and_reply_sets_agent_interrupt_triggered(self, monkeypatch):
        # interrupt_and_reply 命中后置位 _agent_interrupt_triggered（供 speech_end_fallback 互斥）
        session = self._make_dual_session()
        assert session._agent_interrupt_triggered is False
        monkeypatch.setattr(session, "_play_reply", async_noop)

        await session.interrupt_and_reply("好的")
        await asyncio.sleep(0)

        assert session._agent_interrupt_triggered is True

    # ================================================================ 打断/回复独立标签（人类裁决"全量重构"）
    @pytest.mark.asyncio
    async def test_ensure_reply_starts_pipeline_when_not_triggered(self, monkeypatch):
        # Feature B should_reply → ensure_reply：主管线未启动时启动主管线（真实回复）
        session = self._make_dual_session()
        session._current_user_text = "帮我查一下"
        monkeypatch.setattr(session, "_send_prefill_started", async_noop)
        monkeypatch.setattr(session, "_run_pipeline", async_noop)
        monkeypatch.setattr(session, "_finalize_turn", async_noop)

        await session.ensure_reply()
        await asyncio.sleep(0)  # 让后台 task 跑完

        assert session._has_triggered_this_utterance is True
        assert session._pipeline_task is not None
        # 与 interrupt_and_reply 解耦：不置打断标记（非打断，不互斥 VAD 兜底）
        assert session._agent_interrupt_triggered is False

    @pytest.mark.asyncio
    async def test_ensure_reply_noop_when_already_triggered(self, monkeypatch):
        # 主管线已启动（partial 驱动）→ ensure_reply no-op，防重复管线
        session = self._make_dual_session()
        session._has_triggered_this_utterance = True
        session._current_user_text = "帮我查一下"

        async def fail(*a, **k):
            raise AssertionError("不应重复启动主管线")

        monkeypatch.setattr(session, "_run_pipeline", fail)
        monkeypatch.setattr(session, "_send_prefill_started", fail)

        await session.ensure_reply()
        assert session._pipeline_task is None

    @pytest.mark.asyncio
    async def test_ensure_reply_noop_when_text_too_short(self, monkeypatch):
        # 候选文本 < 触发阈值 → no-op
        session = self._make_dual_session()
        session._current_user_text = "嗯"  # 1 字 < 2 字阈值

        async def fail(*a, **k):
            raise AssertionError("文本过短不应启动主管线")

        monkeypatch.setattr(session, "_run_pipeline", fail)
        await session.ensure_reply()
        assert session._has_triggered_this_utterance is False

    @pytest.mark.asyncio
    async def test_maybe_agent_interrupt_routes_reply_to_ensure_reply(self, monkeypatch):
        # 【标签解耦】should_reply=True 且 should_interrupt=False → 走 ensure_reply（不打断）
        session = self._make_dual_session()
        calls = []

        async def fake_ensure_reply():
            calls.append("ensure_reply")

        async def fake_interrupt(reply):
            calls.append(("interrupt", reply))

        monkeypatch.setattr(session, "ensure_reply", fake_ensure_reply)
        monkeypatch.setattr(session, "interrupt_and_reply", fake_interrupt)

        from server.handlers.audio import route_agent_interrupt_result
        await route_agent_interrupt_result(session, {
            "should_interrupt": False, "should_reply": True, "reply_content": "",
        })
        assert calls == ["ensure_reply"]

    @pytest.mark.asyncio
    async def test_maybe_agent_interrupt_routes_interrupt_to_interrupt_and_reply(self, monkeypatch):
        # should_interrupt=True（真打断带内容）→ 走 interrupt_and_reply（先打断再播 reply）
        session = self._make_dual_session()
        calls = []

        async def fake_ensure_reply():
            calls.append("ensure_reply")

        async def fake_interrupt(reply):
            calls.append(("interrupt", reply))

        monkeypatch.setattr(session, "ensure_reply", fake_ensure_reply)
        monkeypatch.setattr(session, "interrupt_and_reply", fake_interrupt)

        from server.handlers.audio import route_agent_interrupt_result
        await route_agent_interrupt_result(session, {
            "should_interrupt": True, "should_reply": True, "reply_content": "好的",
        })
        assert calls == [("interrupt", "好的")]

    @pytest.mark.asyncio
    async def test_route_reply_confirmation_noop_when_already_triggered(self, monkeypatch):
        # 【停顿续接确认】should_reply 后 0.5s 窗口内主管线已启动（用户继续说 →
        # partial 触发 _has_triggered_this_utterance=True）→ ensure_reply 守卫 no-op
        session = self._make_dual_session()
        # 用真实 ensure_reply：其 _has_triggered_this_utterance 守卫决定 no-op
        monkeypatch.setattr(session, "_send_prefill_started", async_noop)
        monkeypatch.setattr(session, "_run_pipeline", async_noop)
        monkeypatch.setattr(session, "_finalize_turn", async_noop)
        # 在 route_agent_interrupt_result 的 0.5s sleep 期间模拟主管线被启动
        from server.handlers.audio import REPLY_CONFIRM_S, route_agent_interrupt_result

        async def _trigger():
            await asyncio.sleep(REPLY_CONFIRM_S * 0.3)
            session._has_triggered_this_utterance = True
            session._current_user_text = "帮我查一下"

        await asyncio.gather(
            route_agent_interrupt_result(session, {
                "should_interrupt": False, "should_reply": True, "reply_content": "",
            }),
            _trigger(),
        )
        # 主管线已触发 → ensure_reply no-op：不启动新 pipeline
        assert session._pipeline_task is None

    @pytest.mark.asyncio
    async def test_route_reply_cancelled_during_confirm_window(self, monkeypatch):
        # 【任务取消】REPLY_CONFIRM_S 窗口内任务被取消（连接断开/会话终止）→
        # asyncio.sleep 抛 CancelledError 被捕获，不执行 ensure_reply、不残留异常
        session = self._make_dual_session()
        calls = []

        async def fake_ensure_reply():
            calls.append("ensure_reply")

        monkeypatch.setattr(session, "ensure_reply", fake_ensure_reply)

        from server.handlers.audio import REPLY_CONFIRM_S, route_agent_interrupt_result
        task = asyncio.create_task(route_agent_interrupt_result(session, {
            "should_interrupt": False, "should_reply": True, "reply_content": "",
        }))
        # 在睡眠窗口内取消任务
        await asyncio.sleep(REPLY_CONFIRM_S * 0.3)
        task.cancel()

        # 取消后 await 不抛 CancelledError（已捕获），且 ensure_reply 未执行
        await asyncio.gather(task, return_exceptions=True)
        assert calls == []


async def _should_not_be_called(text, is_final):
    raise AssertionError("不应触发 LLM 判定（时长不足）")


async def async_noop(*args, **kwargs):
    """空的 async 桩：用于隔离 DualStreamSession 的 pipeline / TTS 真实执行。"""
    return None


def async_chat_with(content):
    """返回一个 async 的 chat 方法，返回 llm 响应对象。"""

    async def chat(**kw):
        return types.SimpleNamespace(error=None, content=content)

    return chat


# ================================================================ call_ollama_decision
# 共享助手：POST Ollama /api/generate + JSON 解析 + 文本兜底 + 超时/异常降级
def _install_fake_shared_client(monkeypatch, response_text=None, exc=None):
    """用假共享 httpx 客户端替换 interrupt_llm.get_shared_http_client（L：共享客户端复用）。"""
    from server.services import interrupt_llm as il

    class FakeResponse:
        def __init__(self, text):
            self._text = text

        def json(self):
            return {"response": self._text}

    class FakeClient:
        def __init__(self):
            self.posts = []

        async def post(self, url, **kw):
            self.posts.append((url, kw))
            if exc is not None:
                raise exc
            return FakeResponse(response_text)

    fake_client = FakeClient()
    monkeypatch.setattr(il, "get_shared_http_client", lambda: fake_client)
    return fake_client


class TestCallOllamaDecision:
    @pytest.mark.asyncio
    async def test_parses_json_decision(self, monkeypatch):
        client = _install_fake_shared_client(monkeypatch, '{"decision": "INTERRUPT", "reason": "r"}')
        result = await interrupt_llm_import().call_ollama_decision("http://x", "m", "p")
        assert result == {"decision": "INTERRUPT", "reason": "r"}
        assert client.posts[0][1]["json"]["format"] == "json"
        # L：timeout 每次调用显式传入
        assert client.posts[0][1].get("timeout") is not None

    @pytest.mark.asyncio
    async def test_json_missing_decision_defaults_ignore(self, monkeypatch):
        _install_fake_shared_client(monkeypatch, '{"foo": "bar"}')
        result = await interrupt_llm_import().call_ollama_decision("http://x", "m", "p")
        assert result["decision"] == "IGNORE"

    @pytest.mark.asyncio
    async def test_json_fail_text_interrupt(self, monkeypatch):
        _install_fake_shared_client(monkeypatch, "not json INTERRUPT here")
        result = await interrupt_llm_import().call_ollama_decision("http://x", "m", "p")
        assert result == {"decision": "INTERRUPT", "reason": "文本解析"}

    @pytest.mark.asyncio
    async def test_json_fail_text_ignore(self, monkeypatch):
        _install_fake_shared_client(monkeypatch, "IGNORE whatever")
        result = await interrupt_llm_import().call_ollama_decision("http://x", "m", "p")
        assert result["decision"] == "IGNORE"

    @pytest.mark.asyncio
    async def test_json_fail_no_keyword_continue(self, monkeypatch):
        _install_fake_shared_client(monkeypatch, "完全没有标记的文本")
        result = await interrupt_llm_import().call_ollama_decision("http://x", "m", "p")
        assert result["decision"] == "CONTINUE"

    @pytest.mark.asyncio
    async def test_timeout_returns_continue(self, monkeypatch):
        import httpx as _httpx

        _install_fake_shared_client(monkeypatch, exc=_httpx.TimeoutException("t/o"))
        result = await interrupt_llm_import().call_ollama_decision("http://x", "m", "p")
        assert result["decision"] == "CONTINUE"
        assert result["reason"] == "超时"

    @pytest.mark.asyncio
    async def test_other_exception_returns_ignore(self, monkeypatch):
        _install_fake_shared_client(monkeypatch, exc=RuntimeError("boom"))
        result = await interrupt_llm_import().call_ollama_decision("http://x", "m", "p")
        assert result["decision"] == "IGNORE"
        assert result["reason"] == "boom"


def interrupt_llm_import():
    from server.services import interrupt_llm

    return interrupt_llm


# ================================================================ H1：上下文注入与防护
class TestInterruptContextInjection:
    """H1：_context_manager/_session_id 组装层注入 + _apply_decision 未注入防护。"""

    @pytest.mark.asyncio
    async def test_apply_decision_skips_write_when_not_injected(self, monkeypatch, caplog):
        # (a) 防护层：未注入时 final 判定不抛 AttributeError、打断动作照常执行、仅 warning 留痕
        m = ASRInterruptModule()
        assert m._context_manager is None and m._session_id is None
        m.set_tts_playing(True)
        fired = []

        async def cb(text, resp):
            fired.append(text)

        m.set_interrupt_callback(cb)
        llm = types.SimpleNamespace(chat=async_chat_with("##[INTERRUPT]## 打断"))
        monkeypatch.setattr("server.dependencies.get_llm_client", lambda: llm)

        with caplog.at_level("WARNING", logger="server.services.asr_interrupt"):
            decision, triggered = await m.on_asr_result("请回答", is_final=True)
        # 打断功能不再静默失效（判定/触发不受写回缺失影响）
        assert decision == "INTERRUPT"
        assert triggered is True
        assert fired == ["请回答"]
        # 跳过写回并 warning 留痕（不再被 except 吞掉的 AttributeError）
        assert any("跳过上下文写回" in rec.message for rec in caplog.records)

    @pytest.mark.asyncio
    async def test_apply_decision_writes_when_injected(self, monkeypatch):
        # 注入齐全时行为不变：final 判定正常写回
        m = ASRInterruptModule()
        m.set_tts_playing(True)
        written = []
        cm = types.SimpleNamespace(
            get_context=lambda sid: [],
            add_message=lambda sid, msg: written.append(msg),
        )
        m.set_session_id("s1")
        m.set_context_manager(cm)
        llm = types.SimpleNamespace(chat=async_chat_with("##[INTERRUPT]## 打断"))
        monkeypatch.setattr("server.dependencies.get_llm_client", lambda: llm)

        d, t = await m.on_asr_result("请问你是谁", is_final=True)
        assert (d, t) == ("INTERRUPT", True)
        assert written == [{"role": "user", "content": "请问你是谁"}]

    @pytest.mark.asyncio
    async def test_factory_injects_context_manager_and_client_session(self):
        # (b) 注入层：per-client 工厂创建的实例持有真实 ContextManager 与 session_id
        from server.services.agent_interrupt_user import (
            release_agent_interrupt_module,
        )
        from server.services.asr_interrupt import release_asr_interrupt_module

        try:
            mod = get_asr_interrupt_module("h1-client-a")
            from server.services.context_manager import get_context_manager as _gcm

            assert mod._context_manager is _gcm()
            assert mod._session_id == "h1-client-a"

            amod = get_agent_interrupt_module("h1-client-a")
            assert amod._context_manager is _gcm()
            assert amod._session_id == "h1-client-a"
        finally:
            release_asr_interrupt_module("h1-client-a")
            release_agent_interrupt_module("h1-client-a")

    @pytest.mark.asyncio
    async def test_live_init_corrects_real_session_id(self, monkeypatch):
        # live_client._handle_init 持有真实 session_id 时覆盖 client_id 兜底值
        from server.services.live_client import LiveClientHandler

        sent = []
        mgr = types.SimpleNamespace(
            send_message=lambda cid, payload: _async_append(sent, payload)
        )
        handler = LiveClientHandler.__new__(LiveClientHandler)
        handler.manager = mgr
        handler.client_id = "h1-live"
        handler.client_config = {}
        handler.marker_adapter = types.SimpleNamespace(process_danmaku=lambda d: d)
        handler.frontend_marker = types.SimpleNamespace(format_for_frontend=lambda x: x)

        class _CM:
            def add_danmaku_message(self, sid, data):
                pass

        handler.context_manager = _CM()
        handler.firewall = types.SimpleNamespace(
            filter_message=lambda c, u, n: types.SimpleNamespace(allowed=False, reason="x")
        )
        tracker_calls = []
        handler.feedback_tracker = types.SimpleNamespace(
            on_danmaku=lambda **kw: _async_append(tracker_calls, kw)
        )
        handler._session_id = None

        await handler._handle_init(None, {"data": {"session_id": "real-session"}})

        from server.services.agent_interrupt_user import (
            release_agent_interrupt_module,
        )
        from server.services.asr_interrupt import release_asr_interrupt_module

        try:
            assert get_asr_interrupt_module("h1-live")._session_id == "real-session"
            assert get_agent_interrupt_module("h1-live")._session_id == "real-session"
        finally:
            release_asr_interrupt_module("h1-live")
            release_agent_interrupt_module("h1-live")


async def _async_append(store, item):
    store.append(item)
