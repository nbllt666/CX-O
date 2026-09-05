"""模型上下文端点测试（GET/PUT /admin/model-context）+ control_plane config.update 白名单。

替身策略（参照 test_admin_router.py 的 TestClient + monkeypatch 模式）：
- FakeSettings 持真实 LLMConfig/ModelsConfig（GET 回显/PUT setattr 走真实结构）
- monkeypatch server.config.get_settings（配置替身，save_config 只记标记不落盘）
- monkeypatch server.core.cache.agent_config_cache（spy，断言缓存失效被调用）
- monkeypatch agents._update_agents_locked（stub，agent 级更新不触真实 agents.json）
- monkeypatch admin.audit_now（记录器，断言审计落盘被调用）

运行：python -m pytest tests/test_admin_model_context.py -v
"""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.routers import admin as admin_router_mod
from server.core import cache as cache_mod
from server.core.admin.auth import AdminForbiddenError
from server.core.admin.control_plane import AdminControlError, AdminControlPlane
from server.config import LLMConfig, ModelsConfig


class _FakeAuth:
    """AdminAuth 替身：恒通过指定级别的权限校验。"""

    def __init__(self, level="operator"):
        self.level = level

    def authenticate(self, token):
        return self.level

    def check_required_level(self, level, required):
        order = {"readonly": 0, "operator": 1, "superadmin": 2}
        if order.get(level, 0) < order.get(required, 0):
            raise AdminForbiddenError(f"需要 {required} 级别")

    def check_rate_limit(self):
        pass

    def check_replay(self, request_id):
        pass


class CacheSpy:
    """agent_config_cache 替身：记录 delete 调用。"""

    def __init__(self):
        self.deleted = []

    def delete(self, key):
        self.deleted.append(key)
        return True


class FakeSettings:
    """配置替身：llm/models 用真实 pydantic 模型，save_config 只记标记。"""

    def __init__(self):
        self.config = SimpleNamespace(llm=LLMConfig(), models=ModelsConfig())
        self.saved = False

    def save_config(self):
        self.saved = True


@pytest.fixture
def env(monkeypatch):
    """统一测试环境：FakeSettings + 缓存 spy + agent 持久化 stub + 审计记录器。"""
    fake = FakeSettings()
    monkeypatch.setattr("server.config.get_settings", lambda: fake)

    spy = CacheSpy()
    monkeypatch.setattr(cache_mod, "agent_config_cache", spy)

    # agent 级持久化 stub（agents.json 不触盘；mutator 语义与 _update_agents_locked 一致）
    agents_after = [{
        "id": "agent-x", "name": "x", "system_prompt": "旧人设",
        "model": "main", "max_tokens": 8192, "temperature": 0.7, "updated_at": "",
    }]
    calls = {"update_locked": 0}

    def fake_update_locked(mutator):
        calls["update_locked"] += 1
        mutator(agents_after)
        return agents_after

    monkeypatch.setattr("server.api.routers.agents._update_agents_locked", fake_update_locked)

    audit_rec = []
    # 注入管理面运行时：真实 AdminControlPlane（config.update 白名单走真实实现）
    plane = AdminControlPlane(services=None, auth=_FakeAuth(), cluster_bridge=None)
    admin_router_mod.inject_admin_runtime(_FakeAuth("operator"), plane, None, None, None, None)
    monkeypatch.setattr(admin_router_mod, "audit_now", lambda *a, **k: audit_rec.append((a, k)))

    app = FastAPI()
    app.include_router(admin_router_mod.router)
    client = TestClient(app, raise_server_exceptions=False)
    return SimpleNamespace(
        client=client, fake=fake, spy=spy, calls=calls,
        audit=audit_rec, agents=agents_after, monkeypatch=monkeypatch,
    )


def _readonly_client(env):
    """以 readonly 级别重建管理面运行时（权限不足场景）。"""
    env.monkeypatch.setattr(
        admin_router_mod, "_admin_auth", _FakeAuth("readonly"), raising=True
    )
    return env.client


class TestGetModelContext:
    def test_get_global_slots(self, env):
        r = env.client.get("/admin/model-context")
        assert r.status_code == 200
        mc = r.json()["model_context"]
        slots = mc["global"]["models"]
        # 外部改动（CX-O-Dream）为 ModelsConfig 增设 dream 槽位，槽位集合随之扩展
        assert set(slots) == {"main", "summary", "memory", "dream"}
        assert mc["global"]["defaults"] == {
            "summary": "main",
            "memory": "main",
            "dream": "main",
        }
        # 默认未显式配置 → summary/memory/dream 跟随 main
        assert slots["summary"]["explicit"] is False
        assert slots["summary"]["following"] == "main"
        assert slots["memory"]["following"] == "main"
        assert slots["dream"]["following"] == "main"
        # 槽位字段完整（model/max_tokens/temperature/host/port）
        for slot in slots.values():
            assert set(slot) == {"model", "max_tokens", "temperature", "host", "port", "explicit", "following"}

    def test_get_explicit_slot_disables_following(self, env):
        # 真实 ModelsConfig._set_explicit：summary 显式配置后不再跟随
        env.fake.config.models._set_explicit(["summary"])
        r = env.client.get("/admin/model-context")
        slots = r.json()["model_context"]["global"]["models"]
        assert slots["summary"]["explicit"] is True
        assert slots["summary"]["following"] is None
        assert slots["memory"]["following"] == "main"

    def test_get_with_agent(self, env, monkeypatch):
        from server import chat_helpers as chat_helpers_mod

        agent = {
            "id": "agent-x", "system_prompt": "人设A", "model": "summary",
            "max_tokens": 4096, "temperature": 0.5,
        }
        monkeypatch.setattr(chat_helpers_mod, "get_agent_config", lambda aid: agent if aid == "agent-x" else None)
        r = env.client.get("/admin/model-context", params={"agent_id": "agent-x"})
        assert r.status_code == 200
        ag = r.json()["model_context"]["agent"]
        assert ag == {
            "agent_id": "agent-x", "system_prompt": "人设A",
            "model": "summary", "max_tokens": 4096, "temperature": 0.5,
        }

    def test_get_unknown_agent_404(self, env, monkeypatch):
        from server import chat_helpers as chat_helpers_mod

        monkeypatch.setattr(chat_helpers_mod, "get_agent_config", lambda aid: None)
        r = env.client.get("/admin/model-context", params={"agent_id": "ghost"})
        assert r.status_code == 404

    def test_get_requires_auth(self, monkeypatch):
        # 未注入 admin 运行时 → 503 disabled
        admin_router_mod.inject_admin_runtime(_FakeAuth(), None, None, None, None, None)
        monkeypatch.setattr(admin_router_mod, "_admin_auth", None)
        app = FastAPI()
        app.include_router(admin_router_mod.router)
        c = TestClient(app, raise_server_exceptions=False)
        assert c.get("/admin/model-context").status_code == 503


class TestPutModelContextGlobal:
    def test_whitelist_inside_persists_and_echoes(self, env):
        r = env.client.put(
            "/admin/model-context",
            json={"global": {"models.main.max_tokens": 4096, "llm.temperature": 0.3}},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["updated"]["global"]["updated"] == ["llm.temperature", "models.main.max_tokens"]
        # 配置落盘被调用（FakeSettings 记标记）
        assert env.fake.saved is True
        # agent_config_cache 失效被调用
        assert "all_agents" in env.spy.deleted
        # 审计落盘被调用
        assert env.audit
        # GET 回显新值
        slots = env.client.get("/admin/model-context").json()["model_context"]["global"]["models"]
        assert slots["main"]["max_tokens"] == 4096
        # llm.temperature 落到 FakeSettings.config.llm
        assert env.fake.config.llm.temperature == 0.3

    def test_whitelist_outside_400(self, env):
        # 本轮 spec（enhance-admin-telemetry）已将 system.debug 纳入白名单，
        # "白名单外"示例改用 llm.stream（LLMConfig 实有字段、刻意不放开）
        r = env.client.put(
            "/admin/model-context",
            json={"global": {"llm.stream": True}},
        )
        assert r.status_code == 400
        assert "ADMIN_CONFIG_FIELD_NOT_ALLOWED" in r.json()["detail"]

    def test_llm_api_key_outside_whitelist_400(self, env):
        # api_key 属敏感字段，刻意不在白名单内
        r = env.client.put(
            "/admin/model-context",
            json={"global": {"llm.api_key": "sk-x"}},
        )
        assert r.status_code == 400
        assert "ADMIN_CONFIG_FIELD_NOT_ALLOWED" in r.json()["detail"]

    def test_llm_port_field_unknown_400(self, env):
        # llm.port 在白名单内但 LLMConfig 无该字段 → 字段存在性校验拒绝
        r = env.client.put(
            "/admin/model-context",
            json={"global": {"llm.port": 11434}},
        )
        assert r.status_code == 400
        assert "ADMIN_CONFIG_FIELD_UNKNOWN" in r.json()["detail"]

    def test_value_type_mismatch_400(self, env):
        r = env.client.put(
            "/admin/model-context",
            json={"global": {"llm.max_tokens": "不是数字"}},
        )
        assert r.status_code == 400
        assert "ADMIN_CONFIG_VALUE_TYPE" in r.json()["detail"]

    def test_bool_temperature_rejected_400(self, env):
        # bool 是 int 子类，数值字段显式拒绝布尔冒充
        r = env.client.put(
            "/admin/model-context",
            json={"global": {"llm.temperature": True}},
        )
        assert r.status_code == 400
        assert "ADMIN_CONFIG_VALUE_TYPE" in r.json()["detail"]

    def test_empty_global_400(self, env):
        r = env.client.put("/admin/model-context", json={"global": {}})
        assert r.status_code == 400

    def test_empty_body_400(self, env):
        r = env.client.put("/admin/model-context", json={})
        assert r.status_code == 400
        assert "global" in r.json()["detail"]

    def test_requires_operator(self, env):
        # readonly 级令牌 → 403
        c = _readonly_client(env)
        r = c.put("/admin/model-context", json={"global": {"llm.model": "m"}})
        assert r.status_code == 403


class TestPutModelContextAgent:
    def test_agent_level_uses_agents_store_stub(self, env):
        r = env.client.put(
            "/admin/model-context",
            json={"agent_id": "agent-x", "system_prompt": "新人设", "max_tokens": 4096},
        )
        assert r.status_code == 200
        # 复用 agents 路由持久化函数（stub 被调用一次）
        assert env.calls["update_locked"] == 1
        # mutator 就地更新 agents 记录
        assert env.agents[0]["system_prompt"] == "新人设"
        assert env.agents[0]["max_tokens"] == 4096
        assert "updated_at" in env.agents[0]
        # 响应回显 agent 级新值
        ag = r.json()["updated"]["agent"]
        assert ag["system_prompt"] == "新人设" and ag["max_tokens"] == 4096
        # 缓存失效被调用（admin PUT 的防御性失效）
        assert "all_agents" in env.spy.deleted
        # 审计落盘被调用
        assert env.audit

    def test_agent_not_found_404(self, env):
        r = env.client.put(
            "/admin/model-context",
            json={"agent_id": "ghost", "system_prompt": "x"},
        )
        assert r.status_code == 404

    def test_agent_fields_missing_400(self, env):
        r = env.client.put(
            "/admin/model-context",
            json={"agent_id": "agent-x"},
        )
        assert r.status_code == 400
        assert "至少一个字段" in r.json()["detail"]

    def test_mixed_global_and_agent(self, env):
        r = env.client.put(
            "/admin/model-context",
            json={
                "global": {"models.summary.model": "qwen-sum"},
                "agent_id": "agent-x",
                "model": "summary",
            },
        )
        assert r.status_code == 200
        updated = r.json()["updated"]
        assert updated["global"]["updated"] == ["models.summary.model"]
        assert updated["agent"]["model"] == "summary"
        assert env.fake.config.models.summary.model == "qwen-sum"


class TestConfigUpdateUnit:
    """control_plane config.update 白名单单元测试（requires_restart 判定）。"""

    def _plane(self):
        return AdminControlPlane(services=None, auth=None, cluster_bridge=None)

    def test_llm_section_hot_updatable(self, monkeypatch):
        fake = FakeSettings()
        monkeypatch.setattr("server.config.get_settings", lambda: fake)
        monkeypatch.setattr(cache_mod, "agent_config_cache", CacheSpy())
        out = self._plane().dispatch("update", "config", "r", "default", {"llm.host": "http://x"})
        # llm 节可热更（REQUIRES_RESTART["llm"]=False）
        assert out["result"]["requires_restart"] == {"llm": False}
        assert fake.saved is True

    def test_models_section_requires_restart(self, monkeypatch):
        fake = FakeSettings()
        monkeypatch.setattr("server.config.get_settings", lambda: fake)
        monkeypatch.setattr(cache_mod, "agent_config_cache", CacheSpy())
        out = self._plane().dispatch("update", "config", "r", "default", {"models.main.model": "m2"})
        # models 节保守登记需重启（REQUIRES_RESTART["models"]=True）
        assert out["result"]["requires_restart"] == {"models": True}

    def test_empty_params_raises(self, monkeypatch):
        monkeypatch.setattr("server.config.get_settings", lambda: FakeSettings())
        with pytest.raises(AdminControlError) as ei:
            self._plane().dispatch("update", "config", "r", "default", {})
        assert "ADMIN_CONFIG_UPDATE_EMPTY" in str(ei.value)
