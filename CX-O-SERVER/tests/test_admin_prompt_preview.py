"""server.core.admin.prompt_preview 测试：分支回显 + 零副作用断言 + 端点冒烟。

替身策略（spec enhance-cxfc-admin-and-integrate-dream 三）：
- monkeypatch server.chat_helpers.get_agent_config（agent 配置替身，不触真实 agents.json）
- monkeypatch server.prompt_builder.get_settings / server.config.get_settings（配置替身）
- monkeypatch server.prompt_builder._get_hidden_prompts（隐藏提示词替身）
- monkeypatch server.dependencies.get_cxfc_manager（技能注入隔离，避免触真实插件管理器）

运行：python -m pytest tests/test_admin_prompt_preview.py -v
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server import chat_helpers as chat_helpers_mod
from server import prompt_builder as prompt_builder_mod
from server.api.routers import admin as admin_router_mod
from server.core.admin.control_plane import AdminControlError, AdminControlPlane
from server.core.admin.prompt_preview import PREVIEW_SESSION_ID, build_preview_messages


class FakeSection:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class FakeSettings:
    """配置替身：仅提供预览相关读取路径（limits.context.chat_context_limit）。"""

    def __init__(self):
        self.config = FakeSection(
            limits=FakeSection(context=FakeSection(chat_context_limit=10)),
        )


AGENT = {
    "id": "agent-x",
    "name": "测试助手",
    "system_prompt": "你是单元测试助手。",
    "model": "main",
    "use_memory": True,
}


@pytest.fixture
def preview_env(monkeypatch):
    """统一替身环境：agent 配置 + 配置单例 + 隐藏提示词 + CXFC 管理器隔离。"""
    monkeypatch.setattr(
        chat_helpers_mod, "get_agent_config",
        lambda aid: dict(AGENT) if aid == "agent-x" else None,
    )
    fake_settings = FakeSettings()
    # prompt_preview 内部经 server.config.get_settings 读 history_limit
    monkeypatch.setattr("server.config.get_settings", lambda: fake_settings)
    # prompt_builder 顶层绑定的 get_settings（build_messages 默认分支读 history_limit）
    monkeypatch.setattr(prompt_builder_mod, "get_settings", lambda: fake_settings)
    # 隐藏提示词替身（覆盖 tools + main 分支的两个键）
    monkeypatch.setattr(
        prompt_builder_mod, "_get_hidden_prompts",
        lambda: {"tools": "工具提示词", "emotion_prompts": "情绪提示词"},
    )
    # 技能注入隔离：_inject_cxfc_skills 内部延迟导入 server.dependencies.get_cxfc_manager
    monkeypatch.setattr("server.dependencies.get_cxfc_manager", lambda: None)
    return fake_settings


class TestBranchEcho:
    """三种装配分支各一例（ACP / 实时语音 / 默认）。"""

    def test_default_branch(self, preview_env):
        out = build_preview_messages("agent-x", "你好")
        assert out["branch"] == "default"
        # 首条为 system 人设
        assert out["messages"][0] == {"role": "system", "content": "你是单元测试助手。"}
        # 末条为 user 消息
        assert out["messages"][-1] == {"role": "user", "content": "你好"}
        # 隐藏提示词键回显：tools 恒注入 + main 分支命中的 emotion_prompts
        assert out["hidden_prompt_keys"] == ["tools", "emotion_prompts"]
        assert out["history_limit"] == 10
        assert out["history_count"] == 0
        # 哨兵 session_id
        assert out["session_id"] == PREVIEW_SESSION_ID == "__admin_preview__"
        # token 粗估 = 全部消息字符数 // 4
        total = sum(
            len(m["content"]) for m in out["messages"] if isinstance(m["content"], str)
        )
        assert out["token_estimate"] == total // 4

    def test_realtime_branch(self, preview_env):
        out = build_preview_messages("agent-x", "说话", is_realtime_voice=True)
        assert out["branch"] == "realtime"
        # 实时语音分支跳过重型隐藏提示词
        assert out["hidden_prompt_keys"] == []
        # system 人设末尾追加 prefix-cache padding（仅追加、不精简）
        assert out["messages"][0]["role"] == "system"
        assert out["messages"][0]["content"].endswith(
            prompt_builder_mod.REALTIME_VOICE_PROMPT_PADDING
        )
        # 末条为 user 消息（实时语音直接送文本）
        assert out["messages"][-1] == {"role": "user", "content": "说话"}

    def test_acp_branch(self, preview_env):
        out = build_preview_messages("agent-x", "应被忽略", acp_context={"from_agent_id": "agent-b"})
        assert out["branch"] == "acp"
        contents = [m["content"] for m in out["messages"] if m["role"] == "system"]
        # ACP 专用回复提示与 incoming_message 上下文注入
        assert any("acp_send_message" in c for c in contents)
        assert any("from_agent_id=agent-b" in c for c in contents)
        # ACP 分支无用户轮次：不追加 user 消息
        assert all(m["role"] != "user" for m in out["messages"])
        assert out["hidden_prompt_keys"] == []

    def test_history_passthrough_and_limit(self, preview_env):
        hist = [
            {"role": "user", "content": "早"},
            {"role": "assistant", "content": "早"},
            {"role": "system", "content": "非对话历史应被过滤"},
        ]
        out = build_preview_messages("agent-x", "继续", history=hist)
        assert out["history_count"] == 3
        roles = [m["role"] for m in out["messages"]]
        # _append_history 仅保留 user/assistant（system 历史被过滤）
        assert roles.count("user") == 2 and roles.count("assistant") == 1

    def test_agent_not_found(self, preview_env):
        with pytest.raises(AdminControlError) as ei:
            build_preview_messages("ghost", "hi")
        assert "ADMIN_AGENT_NOT_FOUND" in str(ei.value)

    def test_invalid_params(self, preview_env):
        with pytest.raises(AdminControlError) as ei:
            build_preview_messages("agent-x", "")
        assert "ADMIN_PREVIEW_INVALID" in str(ei.value)
        with pytest.raises(AdminControlError) as ei2:
            build_preview_messages("agent-x", "hi", acp_context="不是dict")
        assert "ADMIN_PREVIEW_INVALID" in str(ei2.value)


class TestZeroSideEffect:
    """零副作用断言：哨兵 session、显式 history、context_mgr 为无写方法的只读替身。"""

    def _spy_build(self, monkeypatch, captured):
        """包装真实 build_messages：捕获预览函数实际传入的参数后委托原实现。"""
        real_build = prompt_builder_mod.build_messages

        def spy(**kw):
            captured.update(kw)
            return real_build(**kw)

        monkeypatch.setattr(prompt_builder_mod, "build_messages", spy)

    def test_no_write_methods_and_sentinel_session(self, preview_env, monkeypatch):
        captured = {}
        self._spy_build(monkeypatch, captured)
        out = build_preview_messages(
            "agent-x", "探查", history=[{"role": "user", "content": "旧"}]
        )
        # 哨兵 session：预览流绝不与真实会话混淆（真实 context store 不可能被触碰）
        assert captured["session_id"] == "__admin_preview__"
        # history 显式透传（不触发 context_mgr 读历史路径）
        assert captured["history"] == [{"role": "user", "content": "旧"}]
        # context_mgr 为只读替身：不提供任何写方法（写操作将 AttributeError 快速失败）
        cm = captured["context_mgr"]
        for write in (
            "add_message", "append_message", "write_message", "save",
            "save_message", "ensure_session", "delete_session", "delete_messages",
        ):
            assert not hasattr(cm, write), f"预览 context_mgr 不应携带写方法: {write}"
        # 真实装配仍被执行（messages 非空）
        assert out["messages"]

    def test_history_defaults_empty_not_none(self, preview_env, monkeypatch):
        captured = {}
        self._spy_build(monkeypatch, captured)
        build_preview_messages("agent-x", "无历史")
        # 未传 history 时按 [] 处理（绝不传 None——None 会让 _resolve_history 走
        # context_mgr 读路径，违背零副作用约束）
        assert captured["history"] == []

    def test_memory_not_touched(self, preview_env, monkeypatch):
        captured = {}
        self._spy_build(monkeypatch, captured)
        build_preview_messages("agent-x", "无记忆检索")
        # memory_context 恒为 None：预览不检索记忆库
        assert captured["memory_context"] is None


class TestDispatchEntry:
    """经 CX-A 统一控制入口 dispatch 的 prompt/preview 路径。"""

    def test_dispatch_prompt_preview(self, preview_env):
        plane = AdminControlPlane(services=None, auth=None, cluster_bridge=None)
        out = plane.dispatch(
            "preview", "prompt", "r-1", "default",
            {"agent_id": "agent-x", "user_message": "经控制面预览"},
        )
        assert out["ok"] is True and out["target"] == "prompt"
        assert out["result"]["branch"] == "default"

    def test_dispatch_prompt_unknown_action(self, preview_env):
        from server.core.admin.auth import AdminUnknownActionError

        plane = AdminControlPlane(services=None, auth=None, cluster_bridge=None)
        with pytest.raises(AdminUnknownActionError):
            plane.dispatch("fly", "prompt", "r-1", "default", {"user_message": "x"})


class _FakeAuth:
    """AdminAuth 替身：恒通过指定级别校验（readonly）。"""

    def authenticate(self, token):
        return "readonly"

    def check_required_level(self, level, required):
        from server.core.admin.auth import AdminForbiddenError

        order = {"readonly": 0, "operator": 1, "superadmin": 2}
        if order.get(level, 0) < order.get(required, 0):
            raise AdminForbiddenError("forbidden")

    def check_rate_limit(self):
        pass

    def check_replay(self, request_id):
        pass


class TestEndpoint:
    """POST /admin/prompt/preview 端点冒烟（readonly + 审计落盘）。"""

    @pytest.fixture
    def client(self, monkeypatch):
        audit_rec = []
        admin_router_mod.inject_admin_runtime(_FakeAuth(), None, None, None, None, None)
        monkeypatch.setattr(
            admin_router_mod, "audit_now", lambda *a, **k: audit_rec.append((a, k))
        )
        app = FastAPI()
        app.include_router(admin_router_mod.router)
        return TestClient(app, raise_server_exceptions=False), audit_rec

    def test_preview_endpoint_readonly(self, preview_env, client):
        c, audit_rec = client
        r = c.post(
            "/admin/prompt/preview",
            json={"agent_id": "agent-x", "user_message": "端到端预览"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "success"
        assert body["preview"]["branch"] == "default"
        assert body["preview"]["session_id"] == "__admin_preview__"
        # 审计落盘被调用
        assert audit_rec, "预览端点必须落审计"

    def test_preview_endpoint_agent_not_found_400(self, preview_env, client):
        c, _ = client
        r = c.post(
            "/admin/prompt/preview",
            json={"agent_id": "ghost", "user_message": "x"},
        )
        assert r.status_code == 400
        assert "ADMIN_AGENT_NOT_FOUND" in r.json()["detail"]

    def test_preview_endpoint_requires_auth(self, preview_env, monkeypatch):
        # 未注入 admin 运行时 → 503 disabled
        admin_router_mod.inject_admin_runtime(_FakeAuth(), None, None, None, None, None)
        monkeypatch.setattr(admin_router_mod, "_admin_auth", None)
        app = FastAPI()
        app.include_router(admin_router_mod.router)
        c = TestClient(app, raise_server_exceptions=False)
        r = c.post("/admin/prompt/preview", json={"agent_id": "agent-x", "user_message": "x"})
        assert r.status_code == 503
