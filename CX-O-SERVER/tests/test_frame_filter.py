"""FrameFilter 帧筛选器 + POST /api/vision/frame 路由单元测试（spec add-vlm-frame-filter-face-match T4.4）。

隔离外部依赖（全离线）：
- requests.post 经 monkeypatch 替换为 PostRecorder（不真连 VLM 端点）
- ContextManager / NarrativeVisionMemory 经 FrameFilter 构造注入替身
- 路由测试 monkeypatch vision 模块的 get_settings / get_frame_filter；
  face 服务经 sys.modules 注入 fake 模块（对齐 test_face_router.py 范式）

覆盖：
- FrameFilter 单测：三态判定各一、上下文注入条数与内容断言、回退链两跳
  （专属配置→multimodal 回退→不可用）、四类降级（配置落空/超时/连接失败/
  JSON 解析失败，另加 HTTP 非 200）× 两 fail_mode、围栏 JSON 容忍、
  summarize 空 summary→discard、沉淀失败不阻塞、importance 缺省/非法回退、
  face_labels 注入 prompt、沉淀 NarrativeSummary 字段、调用参数（temperature/
  max_tokens/timeout）。
- 路由测试：off 立即直通（mock FrameFilter 断言零调用）、on 三态透传、
  422 参数校验、413 大小上限、face 不可用跳过、face 命中标签组装、
  camera 源写 frame_cache（screen/off 不写）、ts 缺省服务端补齐。

运行：python -m pytest tests/test_frame_filter.py -q
"""
import json
import sys
import types
from types import SimpleNamespace

import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.routers import vision as vision_mod
from server.core.vision import frame_cache
from server.core.vision import frame_filter as frame_filter_mod
from server.core.vision.frame_filter import FrameFilter, FrameFilterDecision


# --------------------------------------------------------------------------- #
# 假配置
# --------------------------------------------------------------------------- #
class FakeVisionEnhanced:
    """vision_enhanced 配置替身（仅帧筛选相关字段）。"""

    def __init__(self, **kw):
        self.frame_filter_enabled = kw.get("frame_filter_enabled", False)
        self.filter_vlm_endpoint = kw.get("filter_vlm_endpoint", "")
        self.filter_vlm_model = kw.get("filter_vlm_model", "")
        self.filter_context_messages = kw.get("filter_context_messages", 6)
        self.filter_timeout_seconds = kw.get("filter_timeout_seconds", 8.0)
        self.filter_fail_mode = kw.get("filter_fail_mode", "passthrough")


class FakeMultimodal:
    """multimodal_pipeline 配置替身（仅 vision 回退通道字段）。"""

    def __init__(self, vision_base_url="", vision_model=""):
        self.vision_base_url = vision_base_url
        self.vision_model = vision_model


class FakeSettings:
    """get_settings() 替身（FrameFilter 单测用）。"""

    def __init__(self, ve=None, mm=None):
        self.config = SimpleNamespace(
            vision_enhanced=ve or FakeVisionEnhanced(),
            multimodal_pipeline=mm or FakeMultimodal(),
        )


# --------------------------------------------------------------------------- #
# 假依赖：上下文管理器 / 记忆沉淀 / requests.post
# --------------------------------------------------------------------------- #
class FakeAsyncContextManager:
    """带 async 变体的 ContextManager 替身（get_recent_messages 返回最近 limit 条升序）。"""

    def __init__(self, messages=None):
        self.messages = messages or []
        self.calls = []

    def get_recent_messages(self, session_id, limit=50):
        self.calls.append((session_id, limit, "sync"))
        return list(self.messages[-limit:]) if limit else []

    async def get_recent_messages_async(self, session_id, limit=50):
        self.calls.append((session_id, limit, "async"))
        return list(self.messages[-limit:]) if limit else []


class FakeSyncContextManager:
    """无 async 变体的 ContextManager 替身（验证 to_thread 回退路径）。"""

    def __init__(self, messages=None):
        self.messages = messages or []
        self.calls = []

    def get_recent_messages(self, session_id, limit=50):
        self.calls.append((session_id, limit, "sync"))
        return list(self.messages[-limit:]) if limit else []


class FakeMemory:
    """NarrativeVisionMemory 替身：记录沉淀调用，可注入失败。"""

    def __init__(self):
        self.sediment_calls = []
        self.fail = False

    def sediment(self, narrative, session_id):
        if self.fail:
            raise RuntimeError("memory boom")
        self.sediment_calls.append((narrative, session_id))


class FakeResponse:
    """requests.Response 最小替身。"""

    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data

    def json(self):
        if self._json is None:
            raise ValueError("no json body")
        return self._json


class PostRecorder:
    """requests.post 替身：记录调用，可预设响应或异常。"""

    def __init__(self, response=None, exc=None):
        self.calls = []
        self.response = response
        self.exc = exc

    def __call__(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if self.exc is not None:
            raise self.exc
        return self.response


def _vlm_reply(payload_obj):
    """构造 200 响应：choices[0].message.content = JSON 序列化的判定对象。"""
    content = json.dumps(payload_obj, ensure_ascii=False)
    return FakeResponse(200, {"choices": [{"message": {"content": content}}]})


def _decision_payload(action="forward", summary="画面中出现一个杯子", reason="与对话相关", importance="medium"):
    return {"action": action, "summary": summary, "reason": reason, "importance": importance}


def _patch_vlm_config(monkeypatch, ve, mm=None):
    monkeypatch.setattr(frame_filter_mod, "get_settings", lambda: FakeSettings(ve, mm))


# --------------------------------------------------------------------------- #
# FrameFilter 单元测试
# --------------------------------------------------------------------------- #
class TestFrameFilterThreeActions:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("action", ["forward", "summarize", "discard"])
    async def test_three_actions_pass_through(self, monkeypatch, action):
        """三态判定各一：VLM JSON → 同 action 透传；仅 summarize 沉淀。"""
        ve = FakeVisionEnhanced(frame_filter_enabled=True, filter_vlm_endpoint="http://v:8100", filter_vlm_model="m")
        _patch_vlm_config(monkeypatch, ve)
        memory = FakeMemory()
        ff = FrameFilter(memory=memory)
        rec = PostRecorder(_vlm_reply(_decision_payload(action=action)))
        monkeypatch.setattr(requests, "post", rec)

        d = await ff.filter_frame("data:image/jpeg;base64,AA", agent_id="a1", session_id="agent-a1", source="camera", ts=1.0)

        assert d.action == action
        assert d.degraded is False
        assert d.importance == "medium"
        assert len(rec.calls) == 1
        assert len(memory.sediment_calls) == (1 if action == "summarize" else 0)


class TestFrameFilterContextInjection:
    @pytest.mark.asyncio
    async def test_context_count_truncate_and_content(self, monkeypatch):
        """上下文注入：条数按 filter_context_messages、单条截断 200 字符、空内容跳过。"""
        ve = FakeVisionEnhanced(filter_vlm_endpoint="http://v:8100", filter_vlm_model="m", filter_context_messages=4)
        _patch_vlm_config(monkeypatch, ve)
        msgs = [
            {"role": "user", "content": "好" * 500},  # 超长 → 截断到 200 + …
            {"role": "assistant", "content": "你好，需要帮忙吗？"},
            {"role": "user", "content": "看看这个杯子"},
            {"role": "assistant", "content": ""},  # 空内容 → 跳过
        ]
        cm = FakeAsyncContextManager(msgs)
        ff = FrameFilter(context_manager=cm)
        rec = PostRecorder(_vlm_reply(_decision_payload()))
        monkeypatch.setattr(requests, "post", rec)

        await ff.filter_frame("img", agent_id="a1", session_id="agent-a1", source="camera", ts=1.0)

        assert cm.calls == [("agent-a1", 4, "async")]
        system_text = rec.calls[0]["json"]["messages"][0]["content"]
        assert "user: " + "好" * 200 + "…" in system_text
        assert "assistant: 你好，需要帮忙吗？" in system_text
        assert "user: 看看这个杯子" in system_text
        # 空内容消息不产生行（3 行有效 → 上下文段仅 2 个换行分隔）
        context_section = system_text.split("【当前对话近期上下文】")[1]
        assert context_section.count("assistant: ") == 1

    @pytest.mark.asyncio
    async def test_context_empty_session_placeholder(self, monkeypatch):
        """会话不存在/无消息 → 系统提示含（无近期对话）。"""
        ve = FakeVisionEnhanced(filter_vlm_endpoint="http://v:8100", filter_vlm_model="m")
        _patch_vlm_config(monkeypatch, ve)
        ff = FrameFilter(context_manager=FakeAsyncContextManager([]))
        rec = PostRecorder(_vlm_reply(_decision_payload()))
        monkeypatch.setattr(requests, "post", rec)

        await ff.filter_frame("img", agent_id="a1", session_id="agent-none", source="camera", ts=1.0)

        assert "（无近期对话）" in rec.calls[0]["json"]["messages"][0]["content"]

    @pytest.mark.asyncio
    async def test_context_sync_manager_fallback(self, monkeypatch):
        """无 async 变体的 ContextManager → 经 asyncio.to_thread 走同步方法。"""
        ve = FakeVisionEnhanced(filter_vlm_endpoint="http://v:8100", filter_vlm_model="m")
        _patch_vlm_config(monkeypatch, ve)
        cm = FakeSyncContextManager([{"role": "user", "content": "hi"}])
        ff = FrameFilter(context_manager=cm)
        rec = PostRecorder(_vlm_reply(_decision_payload()))
        monkeypatch.setattr(requests, "post", rec)

        await ff.filter_frame("img", agent_id="a1", session_id="agent-a1", source="camera", ts=1.0)

        assert cm.calls == [("agent-a1", 6, "sync")]
        assert "user: hi" in rec.calls[0]["json"]["messages"][0]["content"]

    @pytest.mark.asyncio
    async def test_context_manager_raise_treated_as_empty(self, monkeypatch):
        """上下文读取抛异常 → 按无上下文处理，不阻断判定。"""
        ve = FakeVisionEnhanced(filter_vlm_endpoint="http://v:8100", filter_vlm_model="m")
        _patch_vlm_config(monkeypatch, ve)

        class BoomCM:
            async def get_recent_messages_async(self, session_id, limit=50):
                raise RuntimeError("db gone")

        ff = FrameFilter(context_manager=BoomCM())
        rec = PostRecorder(_vlm_reply(_decision_payload()))
        monkeypatch.setattr(requests, "post", rec)

        d = await ff.filter_frame("img", agent_id="a1", session_id="s", source="camera", ts=1.0)
        assert d.action == "forward"
        assert "（无近期对话）" in rec.calls[0]["json"]["messages"][0]["content"]


class TestFrameFilterEndpointResolution:
    @pytest.mark.asyncio
    async def test_dedicated_config_preferred(self, monkeypatch):
        """回退链第一跳：专属 filter_vlm_endpoint/model 非空优先（含 /v1 后缀归一）。"""
        ve = FakeVisionEnhanced(filter_vlm_endpoint="http://dedicated:8100/v1", filter_vlm_model="dedi-m")
        mm = FakeMultimodal("http://mm:8080", "mm-m")
        _patch_vlm_config(monkeypatch, ve, mm)
        ff = FrameFilter()
        rec = PostRecorder(_vlm_reply(_decision_payload()))
        monkeypatch.setattr(requests, "post", rec)

        await ff.filter_frame("img", agent_id="a1", session_id="s", source="camera", ts=1.0)

        assert rec.calls[0]["url"] == "http://dedicated:8100/v1/chat/completions"
        assert rec.calls[0]["json"]["model"] == "dedi-m"

    @pytest.mark.asyncio
    async def test_fallback_to_multimodal_channel(self, monkeypatch):
        """回退链第二跳：专属为空 → multimodal vision_base_url/vision_model。"""
        ve = FakeVisionEnhanced()
        mm = FakeMultimodal("http://mm:8080", "mm-m")
        _patch_vlm_config(monkeypatch, ve, mm)
        ff = FrameFilter()
        rec = PostRecorder(_vlm_reply(_decision_payload()))
        monkeypatch.setattr(requests, "post", rec)

        await ff.filter_frame("img", agent_id="a1", session_id="s", source="camera", ts=1.0)

        assert rec.calls[0]["url"] == "http://mm:8080/v1/chat/completions"
        assert rec.calls[0]["json"]["model"] == "mm-m"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("fail_mode", ["passthrough", "discard"])
    async def test_unavailable_degrades_without_call(self, monkeypatch, fail_mode):
        """回退链落空（配置落空降级）：不发起任何请求，按 fail_mode 兜底。"""
        ve = FakeVisionEnhanced(filter_fail_mode=fail_mode)
        mm = FakeMultimodal("", "")
        _patch_vlm_config(monkeypatch, ve, mm)
        ff = FrameFilter()
        rec = PostRecorder(_vlm_reply(_decision_payload()))
        monkeypatch.setattr(requests, "post", rec)

        d = await ff.filter_frame("img", agent_id="a1", session_id="s", source="camera", ts=1.0)

        assert rec.calls == []  # 未调用模型
        assert d.degraded is True
        assert d.action == ("discard" if fail_mode == "discard" else "forward")


class TestFrameFilterDegradation:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("fail_mode", ["passthrough", "discard"])
    @pytest.mark.parametrize("case", ["no_config", "timeout", "conn_fail", "bad_json", "http_500"])
    async def test_degradation_paths(self, monkeypatch, case, fail_mode):
        """四类降级（配置落空/超时/连接失败/JSON 解析失败，另加 HTTP 非 500 类）× 两 fail_mode。"""
        if case == "no_config":
            ve = FakeVisionEnhanced(filter_fail_mode=fail_mode)
        else:
            ve = FakeVisionEnhanced(
                filter_vlm_endpoint="http://v:8100", filter_vlm_model="m", filter_fail_mode=fail_mode
            )
        _patch_vlm_config(monkeypatch, ve, FakeMultimodal("", ""))
        ff = FrameFilter()

        if case == "timeout":
            rec = PostRecorder(exc=requests.exceptions.Timeout("timeout"))
        elif case == "conn_fail":
            rec = PostRecorder(exc=requests.exceptions.ConnectionError("refused"))
        elif case == "bad_json":
            rec = PostRecorder(FakeResponse(200, {"choices": [{"message": {"content": "这帧我觉得还行"}}]}))
        elif case == "http_500":
            rec = PostRecorder(FakeResponse(500, {"error": "boom"}))
        else:
            rec = PostRecorder(_vlm_reply(_decision_payload()))
        monkeypatch.setattr(requests, "post", rec)

        d = await ff.filter_frame("img", agent_id="a1", session_id="s", source="camera", ts=1.0)

        expected_action = "discard" if fail_mode == "discard" else "forward"
        assert d.action == expected_action
        assert d.degraded is True
        assert d.reason  # 降级原因留痕
        if case == "no_config":
            assert rec.calls == []  # 配置落空不发起请求
        else:
            assert len(rec.calls) == 1

    @pytest.mark.asyncio
    async def test_invalid_action_degrades(self, monkeypatch):
        """action 非三态 → JSON 判定无效，走降级。"""
        ve = FakeVisionEnhanced(filter_vlm_endpoint="http://v:8100", filter_vlm_model="m")
        _patch_vlm_config(monkeypatch, ve)
        ff = FrameFilter()
        rec = PostRecorder(_vlm_reply({"action": "maybe", "summary": "s"}))
        monkeypatch.setattr(requests, "post", rec)

        d = await ff.filter_frame("img", agent_id="a1", session_id="s", source="camera", ts=1.0)
        assert d.degraded is True
        assert d.action == "forward"


class TestFrameFilterJsonParsing:
    @pytest.mark.asyncio
    async def test_fenced_json_tolerated(self, monkeypatch):
        """容忍 ```json 围栏：带围栏回复正常解析。"""
        ve = FakeVisionEnhanced(filter_vlm_endpoint="http://v:8100", filter_vlm_model="m")
        _patch_vlm_config(monkeypatch, ve)
        memory = FakeMemory()
        ff = FrameFilter(memory=memory)
        content = (
            "```json\n"
            + json.dumps(_decision_payload(action="summarize", summary="用户拿起杯子"), ensure_ascii=False)
            + "\n```"
        )
        rec = PostRecorder(FakeResponse(200, {"choices": [{"message": {"content": content}}]}))
        monkeypatch.setattr(requests, "post", rec)

        d = await ff.filter_frame("img", agent_id="a1", session_id="agent-a1", source="camera", ts=5.0)

        assert d.action == "summarize"
        assert d.summary == "用户拿起杯子"
        assert d.degraded is False
        assert len(memory.sediment_calls) == 1

    @pytest.mark.asyncio
    async def test_summarize_empty_summary_downgrades_to_discard(self, monkeypatch):
        """summarize 且 summary 空 → 降为 discard（非 degraded），不沉淀。"""
        ve = FakeVisionEnhanced(filter_vlm_endpoint="http://v:8100", filter_vlm_model="m")
        _patch_vlm_config(monkeypatch, ve)
        memory = FakeMemory()
        ff = FrameFilter(memory=memory)
        rec = PostRecorder(_vlm_reply(_decision_payload(action="summarize", summary="")))
        monkeypatch.setattr(requests, "post", rec)

        d = await ff.filter_frame("img", agent_id="a1", session_id="s", source="camera", ts=1.0)

        assert d.action == "discard"
        assert d.degraded is False
        assert "summary 为空" in d.reason
        assert memory.sediment_calls == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("importance", [None, "urgent", "HIGH"])
    async def test_importance_default_and_invalid(self, monkeypatch, importance):
        """importance 缺省/非法 → 回退 medium（大写合法值归一）。"""
        ve = FakeVisionEnhanced(filter_vlm_endpoint="http://v:8100", filter_vlm_model="m")
        _patch_vlm_config(monkeypatch, ve)
        ff = FrameFilter()
        payload = _decision_payload()
        if importance is None:
            payload.pop("importance")
        else:
            payload["importance"] = importance
        rec = PostRecorder(_vlm_reply(payload))
        monkeypatch.setattr(requests, "post", rec)

        d = await ff.filter_frame("img", agent_id="a1", session_id="s", source="camera", ts=1.0)
        assert d.importance == ("high" if importance == "HIGH" else "medium")


class TestFrameFilterSedimentAndPrompt:
    @pytest.mark.asyncio
    async def test_sediment_failure_does_not_block(self, monkeypatch):
        """沉淀失败仅记日志，判定照常返回。"""
        ve = FakeVisionEnhanced(filter_vlm_endpoint="http://v:8100", filter_vlm_model="m")
        _patch_vlm_config(monkeypatch, ve)
        memory = FakeMemory()
        memory.fail = True
        ff = FrameFilter(memory=memory)
        rec = PostRecorder(_vlm_reply(_decision_payload(action="summarize")))
        monkeypatch.setattr(requests, "post", rec)

        d = await ff.filter_frame("img", agent_id="a1", session_id="agent-a1", source="camera", ts=2.5)

        assert d.action == "summarize"
        assert d.degraded is False
        assert memory.sediment_calls == []

    @pytest.mark.asyncio
    async def test_sediment_narrative_fields(self, monkeypatch):
        """沉淀 NarrativeSummary 字段：event_type=frame_summary/source 透传/clip_ts/confidence=0.6。"""
        ve = FakeVisionEnhanced(filter_vlm_endpoint="http://v:8100", filter_vlm_model="m")
        _patch_vlm_config(monkeypatch, ve)
        memory = FakeMemory()
        ff = FrameFilter(memory=memory)
        rec = PostRecorder(_vlm_reply(_decision_payload(action="summarize", summary="屏幕上出现报错弹窗")))
        monkeypatch.setattr(requests, "post", rec)

        await ff.filter_frame("img", agent_id="a1", session_id="agent-a1", source="screen", ts=9.5)

        narrative, session_id = memory.sediment_calls[0]
        assert session_id == "agent-a1"
        assert narrative.content == "屏幕上出现报错弹窗"
        assert narrative.event_type == "frame_summary"
        assert narrative.source == "screen"
        assert narrative.clip_ts == pytest.approx(9.5)
        assert narrative.confidence == pytest.approx(0.6)
        assert narrative.events == []
        assert narrative.degraded is False

    @pytest.mark.asyncio
    async def test_face_labels_injected_into_user_prompt(self, monkeypatch):
        """face_labels 注入用户 prompt（"画面中识别到：…"）；空标签走无人脸文案。"""
        ve = FakeVisionEnhanced(filter_vlm_endpoint="http://v:8100", filter_vlm_model="m")
        _patch_vlm_config(monkeypatch, ve)
        ff = FrameFilter()
        rec = PostRecorder(_vlm_reply(_decision_payload()))
        monkeypatch.setattr(requests, "post", rec)

        await ff.filter_frame(
            "img", agent_id="a1", session_id="s", source="camera", ts=1.0,
            face_labels=["小A", "未知人脸×1"],
        )
        user_text = rec.calls[0]["json"]["messages"][1]["content"][0]["text"]
        assert "画面中识别到：小A；未知人脸×1" in user_text

        rec2 = PostRecorder(_vlm_reply(_decision_payload()))
        monkeypatch.setattr(requests, "post", rec2)
        await ff.filter_frame("img", agent_id="a1", session_id="s", source="camera", ts=1.0)
        user_text2 = rec2.calls[0]["json"]["messages"][1]["content"][0]["text"]
        assert "画面中无人脸识别结果" in user_text2

    @pytest.mark.asyncio
    async def test_request_params_and_image_url_shape(self, monkeypatch):
        """调用参数：temperature=0.1、max_tokens=300、timeout 透传；帧走 image_url dataURL 形态。"""
        ve = FakeVisionEnhanced(filter_vlm_endpoint="http://v:8100", filter_vlm_model="m", filter_timeout_seconds=3.5)
        _patch_vlm_config(monkeypatch, ve)
        ff = FrameFilter()
        rec = PostRecorder(_vlm_reply(_decision_payload()))
        monkeypatch.setattr(requests, "post", rec)

        img = "data:image/jpeg;base64,QUJD"
        await ff.filter_frame(img, agent_id="a1", session_id="s", source="camera", ts=1.0)

        call = rec.calls[0]
        assert call["timeout"] == pytest.approx(3.5)
        body = call["json"]
        assert body["temperature"] == 0.1
        assert body["max_tokens"] == 300
        user_content = body["messages"][1]["content"]
        assert user_content[1] == {"type": "image_url", "image_url": {"url": img}}
        assert user_content[0]["type"] == "text"


# --------------------------------------------------------------------------- #
# 路由测试：POST /vision/frame
# --------------------------------------------------------------------------- #
_IMG = "data:image/jpeg;base64,QUJDREVG"


class FakeFrameFilter:
    """路由注入的 FrameFilter 替身：记录调用，返回预设判定。"""

    def __init__(self):
        self.decision = FrameFilterDecision(
            action="forward", summary="s", reason="r", importance="medium", degraded=False
        )
        self.calls = []

    async def filter_frame(self, image_b64, **kwargs):
        self.calls.append({"image": image_b64, **kwargs})
        return self.decision


def _router_settings(frame_filter_enabled=True, face_enabled=False):
    """路由 get_settings() 替身（vision_enhanced + face_match 节）。"""
    return SimpleNamespace(
        config=SimpleNamespace(
            vision_enhanced=FakeVisionEnhanced(
                frame_filter_enabled=frame_filter_enabled,
                filter_vlm_endpoint="http://v:8100",
                filter_vlm_model="m",
            ),
            face_match=SimpleNamespace(enabled=face_enabled),
        )
    )


@pytest.fixture
def face_module(monkeypatch):
    """注入 fake server.services.face_profile_service 模块，返回 match 行为控制器。"""
    state = {"matches": [], "raise": None, "calls": []}

    class FaceServiceUnavailable(RuntimeError):
        pass

    class FakeSvc:
        async def match(self, image_b64):
            state["calls"].append(image_b64)
            if state["raise"] is not None:
                raise state["raise"]
            return list(state["matches"])

    mod = types.ModuleType("server.services.face_profile_service")
    mod.FaceServiceUnavailable = FaceServiceUnavailable
    mod.get_face_profile_service = lambda: FakeSvc()
    monkeypatch.setitem(sys.modules, "server.services.face_profile_service", mod)
    state["unavailable_cls"] = FaceServiceUnavailable
    return state


@pytest.fixture
def frame_env(monkeypatch):
    """路由测试环境：注入 FakeFrameFilter，返回应用构造器。每个用例复位帧缓存。"""
    frame_cache.clear()
    fake_filter = FakeFrameFilter()
    monkeypatch.setattr(vision_mod, "get_frame_filter", lambda: fake_filter)

    def _build(frame_filter_enabled=True, face_enabled=False, decision=None):
        if decision is not None:
            fake_filter.decision = decision
        monkeypatch.setattr(vision_mod, "get_settings", lambda: _router_settings(frame_filter_enabled, face_enabled))
        app = FastAPI()
        app.include_router(vision_mod.router)
        return TestClient(app, raise_server_exceptions=False), fake_filter

    yield _build
    frame_cache.clear()


def _post_frame(client, *, drop=(), **overrides):
    payload = {"image": _IMG, "agent_id": "a1", "source": "camera", "ts": 1234.5}
    payload.update(overrides)
    for key in drop:
        payload.pop(key, None)
    return client.post("/vision/frame", json=payload)


class TestFrameRouteDisabled:
    def test_disabled_returns_forward_and_zero_filter_calls(self, frame_env):
        """off：立即 forward + filter_active=False，零筛选调用、不写缓存。"""
        client, fake_filter = frame_env(frame_filter_enabled=False)
        r = _post_frame(client)
        assert r.status_code == 200
        body = r.json()
        assert body == {"action": "forward", "filter_active": False, "degraded": False}
        assert fake_filter.calls == []  # 未调用任何模型
        assert frame_cache.get_recent_frame() is None  # camera 源也不写缓存


class TestFrameRouteEnabled:
    def test_on_forward_pass_through(self, frame_env):
        """on：forward 判定透传 + filter_active=True + 参数组装正确。"""
        client, fake_filter = frame_env()
        r = _post_frame(client)
        assert r.status_code == 200
        body = r.json()
        assert body["action"] == "forward"
        assert body["summary"] == "s"
        assert body["reason"] == "r"
        assert body["importance"] == "medium"
        assert body["degraded"] is False
        assert body["face_labels"] is None  # face_match 未启用
        assert body["filter_active"] is True
        # 调用参数：session 对齐 chat 命名 agent-{agent_id}
        assert len(fake_filter.calls) == 1
        call = fake_filter.calls[0]
        assert call["image"] == _IMG
        assert call["agent_id"] == "a1"
        assert call["session_id"] == "agent-a1"
        assert call["source"] == "camera"
        assert call["ts"] == pytest.approx(1234.5)

    @pytest.mark.parametrize("action", ["summarize", "discard"])
    def test_on_three_states_pass_through(self, frame_env, action):
        """on：summarize/discard 判定透传。"""
        client, _ = frame_env(decision=FrameFilterDecision(action=action, summary="摘要", reason="理由", importance="low", degraded=False))
        r = _post_frame(client)
        assert r.status_code == 200
        body = r.json()
        assert body["action"] == action
        assert body["filter_active"] is True

    def test_on_degraded_pass_through(self, frame_env):
        """on：降级判定透传（degraded=True）。"""
        client, _ = frame_env(
            decision=FrameFilterDecision(action="forward", summary="", reason="超时", importance="medium", degraded=True)
        )
        r = _post_frame(client)
        assert r.json()["degraded"] is True

    def test_ts_missing_filled_by_server(self, frame_env):
        """ts 缺省 → 服务端补齐（float 时间戳）。"""
        client, fake_filter = frame_env()
        r = _post_frame(client, drop=("ts",))
        assert r.status_code == 200
        ts = fake_filter.calls[0]["ts"]
        assert isinstance(ts, float) and ts > 0


class TestFrameRouteValidation:
    def test_empty_image_422(self, frame_env):
        client, fake_filter = frame_env()
        r = _post_frame(client, image="")
        assert r.status_code == 422
        assert fake_filter.calls == []

    def test_whitespace_image_422(self, frame_env):
        client, _ = frame_env()
        assert _post_frame(client, image="   ").status_code == 422

    def test_missing_image_422(self, frame_env):
        client, _ = frame_env()
        assert _post_frame(client, drop=("image",)).status_code == 422

    def test_empty_agent_id_422(self, frame_env):
        client, _ = frame_env()
        assert _post_frame(client, agent_id="").status_code == 422

    def test_invalid_source_422(self, frame_env):
        client, fake_filter = frame_env()
        assert _post_frame(client, source="mic").status_code == 422
        assert fake_filter.calls == []

    def test_oversize_image_413(self, frame_env, monkeypatch):
        """大小防呆：base64 长度预检超限 → 413（monkeypatch 阈值对齐 test_face_router 范式）。"""
        client, _ = frame_env()
        monkeypatch.setattr(vision_mod, "_MAX_FRAME_BYTES", 12)
        r = _post_frame(client, image="x" * 40)
        assert r.status_code == 413


class TestFrameRouteFaceIntegration:
    def test_face_match_hit_collects_labels(self, frame_env, face_module):
        """camera + face_match.enabled：命中收集 name，unknown 计数 → "未知人脸×N"。"""
        face_module["matches"] = [
            {"name": "小A", "similarity": 0.8, "bbox": [1, 2, 3, 4]},
            {"unknown": True, "best_similarity": 0.2, "bbox": [5, 6, 7, 8]},
        ]
        client, fake_filter = frame_env(face_enabled=True)
        r = _post_frame(client)
        assert r.status_code == 200
        body = r.json()
        assert body["face_labels"] == ["小A", "未知人脸×1"]
        assert fake_filter.calls[0]["face_labels"] == ["小A", "未知人脸×1"]

    def test_face_unavailable_skips_and_continues(self, frame_env, face_module):
        """FaceServiceUnavailable → 跳过 face_labels（空列表），不阻断筛选。"""
        face_module["raise"] = face_module["unavailable_cls"]("unavailable")
        client, fake_filter = frame_env(face_enabled=True)
        r = _post_frame(client)
        assert r.status_code == 200
        body = r.json()
        assert body["face_labels"] == []
        assert body["action"] == "forward"
        assert len(fake_filter.calls) == 1

    def test_face_disabled_no_match_call(self, frame_env, face_module):
        """face_match.enabled=False → 不触发匹配，face_labels=None。"""
        client, _ = frame_env(face_enabled=False)
        r = _post_frame(client)
        assert r.json()["face_labels"] is None
        assert face_module["calls"] == []

    def test_screen_source_no_face_no_cache(self, frame_env, face_module):
        """screen 源：不触发人脸匹配、不写帧缓存。"""
        client, _ = frame_env(face_enabled=True)
        r = _post_frame(client, source="screen")
        assert r.status_code == 200
        assert face_module["calls"] == []
        assert frame_cache.get_recent_frame() is None


class TestFrameRouteCacheWrite:
    def test_camera_source_writes_frame_cache(self, frame_env):
        """camera 源覆盖写入最近帧缓存（无论判定结果）。"""
        client, _ = frame_env(
            decision=FrameFilterDecision(action="discard", summary="", reason="静止", importance="low", degraded=False)
        )
        r = _post_frame(client)
        assert r.status_code == 200
        assert frame_cache.get_recent_frame() == _IMG

    def test_camera_cache_overwritten_by_latest(self, frame_env):
        """单槽覆盖语义：后帧覆盖前帧。"""
        client, _ = frame_env()
        _post_frame(client)
        _post_frame(client, image="data:image/jpeg;base64,TkVX")
        assert frame_cache.get_recent_frame() == "data:image/jpeg;base64,TkVX"
