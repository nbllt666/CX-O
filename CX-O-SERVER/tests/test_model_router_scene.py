"""ModelRouter 多 LoRA 场景路由单测。

覆盖（P2-T3 扩展到 base/streaming/intimate 多 adapter）：
- base / streaming / intimate 三种 scene → 对应 lora_adapter
- roleplay / writing / chat 向后兼容映射保持
- 未知 scene → None（保持 P2-T3 语义）
- 未启用 LoRA 时恒返回 None（回归）
- 配置覆盖映射（evolution.adapter_mapping / scene_adapters）
- 多 adapter 装载的 compose 配置解析（docker-compose.yml + Dockerfile.vllm 分词）

运行：python -m pytest tests/test_model_router_scene.py -v
"""
from pathlib import Path
from types import SimpleNamespace

import yaml

from server.core.model_router import ModelRouter

# 项目根（CX-O-SERVER 的上一级，即 c:\CX-O）
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DOCKER_COMPOSE = PROJECT_ROOT / "docker-compose.yml"
DOCKERFILE_VLLM = PROJECT_ROOT / "docker" / "llm" / "Dockerfile.vllm"


def _settings(lora_enabled=True, adapter_mapping=None, scene_adapters=None):
    """构造 get_settings 返回的假 Settings 对象（含 evolution）。"""
    evolution = SimpleNamespace(lora_enabled=lora_enabled)
    if adapter_mapping is not None:
        evolution.adapter_mapping = adapter_mapping
    if scene_adapters is not None:
        evolution.scene_adapters = scene_adapters
    return SimpleNamespace(config=SimpleNamespace(evolution=evolution))


def _router(monkeypatch, **kw):
    r = ModelRouter()
    monkeypatch.setattr(
        "server.core.model_router.get_settings", lambda: _settings(**kw)
    )
    return r


# ---------------------------------------------------------------- base/streaming/intimate
class TestMultiSceneRouting:
    def test_base_returns_base_adapter(self, monkeypatch):
        r = _router(monkeypatch, lora_enabled=True)
        assert r.resolve_lora_request("base") == {
            "model": "base-adapter",
            "lora_weight": 1.0,
        }

    def test_streaming_returns_streaming_adapter(self, monkeypatch):
        r = _router(monkeypatch, lora_enabled=True)
        assert r.resolve_lora_request("streaming") == {
            "model": "streaming-adapter",
            "lora_weight": 1.0,
        }

    def test_intimate_returns_intimate_adapter(self, monkeypatch):
        r = _router(monkeypatch, lora_enabled=True)
        assert r.resolve_lora_request("intimate") == {
            "model": "intimate-adapter",
            "lora_weight": 1.0,
        }

    def test_backward_compat_roleplay_writing_chat(self, monkeypatch):
        """P2-T3 的 roleplay / writing / chat 映射保持。"""
        r = _router(monkeypatch, lora_enabled=True)
        assert r.resolve_lora_request("roleplay")["model"] == "roleplay-adapter"
        assert r.resolve_lora_request("writing")["model"] == "writing-adapter"
        assert r.resolve_lora_request("chat")["model"] == "chat-adapter"

    def test_unknown_scene_returns_none(self, monkeypatch):
        """未知 scene 恒返回 None（P2-T3 语义，明确断言）。"""
        r = _router(monkeypatch, lora_enabled=True)
        assert r.resolve_lora_request("nonexistent_scene") is None
        assert r.resolve_lora_request("") is None
        assert r.resolve_lora_request(None) is None

    def test_returned_dict_is_copy(self, monkeypatch):
        """返回值是映射副本，不得外泄内部引用（防止调用方篡改映射）。"""
        r = _router(monkeypatch, lora_enabled=True)
        req = r.resolve_lora_request("intimate")
        req["lora_weight"] = 0.0
        assert r.resolve_lora_request("intimate")["lora_weight"] == 1.0


# ---------------------------------------------------------------- 未启用 LoRA 回归
class TestDisabledRegression:
    def test_disabled_returns_none_for_all_scenes(self, monkeypatch):
        r = _router(monkeypatch, lora_enabled=False)
        for scene in ("base", "streaming", "intimate", "roleplay", "writing", "chat"):
            assert r.resolve_lora_request(scene) is None

    def test_disabled_even_with_existing_mapping(self, monkeypatch):
        """未启用 LoRA 时即使映射存在也恒返回 None。"""
        r = _router(monkeypatch, lora_enabled=False)
        r._scene_adapters = {"base": {"model": "x", "lora_weight": 1.0}}
        assert r.resolve_lora_request("base") is None


# ---------------------------------------------------------------- 配置覆盖映射
class TestConfigOverride:
    def test_adapter_mapping_overrides_default(self, monkeypatch):
        r = _router(
            monkeypatch,
            lora_enabled=True,
            adapter_mapping={"base": {"model": "custom-base", "lora_weight": 0.9}},
        )
        assert r.resolve_lora_request("base") == {
            "model": "custom-base",
            "lora_weight": 0.9,
        }
        # 未覆盖 scene 仍走默认映射
        assert r.resolve_lora_request("streaming")["model"] == "streaming-adapter"

    def test_scene_adapters_falls_back_when_no_adapter_mapping(self, monkeypatch):
        """独立 scene_adapters 节同样生效。"""
        r = _router(
            monkeypatch,
            lora_enabled=True,
            scene_adapters={"intimate": {"model": "night-lora", "lora_weight": 1.0}},
        )
        assert r.resolve_lora_request("intimate")["model"] == "night-lora"

    def test_malformed_override_ignored(self, monkeypatch):
        """结构不符的覆盖节被忽略，回退默认映射且不抛异常。"""
        r = _router(
            monkeypatch,
            lora_enabled=True,
            adapter_mapping={"base": "not-a-dict", "streaming": ["bad"]},
        )
        assert r.resolve_lora_request("base")["model"] == "base-adapter"
        assert r.resolve_lora_request("streaming")["model"] == "streaming-adapter"


# ---------------------------------------------------------------- compose 多 adapter 装载解析
class TestComposeMultiAdapter:
    def test_compose_defines_lora_envs(self):
        """docker-compose.yml 的 llm 服务应暴露 LORA_MODULES / MAX_LORAS 默认值。"""
        assert DOCKER_COMPOSE.exists(), f"缺少 {DOCKER_COMPOSE}"
        with open(DOCKER_COMPOSE, "r", encoding="utf-8") as f:
            compose = yaml.safe_load(f)
        env = compose["services"]["llm"]["environment"]
        env_str = "\n".join(str(e) for e in env)
        assert "LORA_MODULES=${LLM_LORA_MODULES:-}" in env_str
        assert "MAX_LORAS=${LLM_MAX_LORAS:-8}" in env_str

    def test_dockerfile_splits_multi_adapter_value(self):
        """Dockerfile.vllm 应将逗号分隔的 LORA_MODULES 分词为多个 --lora-modules。"""
        assert DOCKERFILE_VLLM.exists(), f"缺少 {DOCKERFILE_VLLM}"
        content = DOCKERFILE_VLLM.read_text(encoding="utf-8")
        cmd_block = content[content.index("CMD ["):]
        assert "tr ',' ' '" in cmd_block, "Dockerfile 缺少逗号→空格分词逻辑"
        assert "--lora-modules $LORA_SPLIT" in cmd_block
        # 语义示例：三个 adapter 逗号分隔应在展开后变成 3 个 name=path 词元
        joined = ",".join(
            [
                "base=./models/base_lora",
                "streaming=./models/streaming_lora",
                "intimate=./models/intimate_lora",
            ]
        )
        assert len(joined.split(",")) == 3