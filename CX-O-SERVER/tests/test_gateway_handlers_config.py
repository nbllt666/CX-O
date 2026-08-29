"""
server/handlers/config.py 回归测试
配置处理器：section 点号遍历读取 / 写入保存 / 空 section 与非字符串 key 校验
"""
import pytest

import server.config as config_mod
from server.handlers.config import register_config_handlers
from server.protocol.actions import ConfigActions


class FakeModel:
    """迷你 pydantic 替身：点号属性 + model_dump 递归。"""
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def model_dump(self):
        return {
            k: (v.model_dump() if isinstance(v, FakeModel) else v)
            for k, v in self.__dict__.items()
        }


def make_config():
    return FakeModel(
        gateway=FakeModel(host="0.0.0.0", port=8000),
        services=FakeModel(asr=FakeModel(url="http://asr")),
        model="default",
    )


class FakeManager:
    def __init__(self):
        self.handlers = {}
        self.sent = []

    def register_handler(self, action, handler):
        self.handlers[action] = handler

    async def send_message(self, client_id, message):
        self.sent.append((client_id, message))


@pytest.fixture
def mgr():
    return FakeManager()


@pytest.fixture
def handlers(mgr):
    register_config_handlers(mgr)
    return mgr.handlers


def _patch_conf(monkeypatch, conf=None, on_save=None):
    saved = []
    monkeypatch.setattr(config_mod, "get_config", lambda: conf if conf is not None else make_config())
    monkeypatch.setattr(config_mod, "save_config", lambda c: (saved.append(c), on_save(c))[1] if on_save else saved.append(c))
    return saved


def _err(mgr):
    msg = mgr.sent[-1][1]
    assert msg["type"] == "error"
    return msg["error"]["code"]


class TestConfigGet:
    @pytest.mark.asyncio
    async def test_get_full(self, handlers, mgr, monkeypatch):
        _patch_conf(monkeypatch)
        await handlers[ConfigActions.GET](None, {"request_id": "r1"}, "c1")
        msg = mgr.sent[-1][1]
        assert msg["action"] == ConfigActions.GET
        assert msg["request_id"] == "r1"
        assert msg["data"]["config"]["gateway"]["host"] == "0.0.0.0"

    @pytest.mark.asyncio
    async def test_get_section(self, handlers, mgr, monkeypatch):
        _patch_conf(monkeypatch)
        await handlers[ConfigActions.GET](None, {"data": {"section": "gateway"}}, "c1")
        data = mgr.sent[-1][1]["data"]["config"]
        assert data == {"host": "0.0.0.0", "port": 8000}

    @pytest.mark.asyncio
    async def test_get_nested_scalar(self, handlers, mgr, monkeypatch):
        _patch_conf(monkeypatch)
        await handlers[ConfigActions.GET](None, {"data": {"section": "gateway.host"}}, "c1")
        assert mgr.sent[-1][1]["data"]["config"] == "0.0.0.0"

    @pytest.mark.asyncio
    async def test_get_missing_section_returns_none(self, handlers, mgr, monkeypatch):
        _patch_conf(monkeypatch)
        await handlers[ConfigActions.GET](None, {"data": {"section": "nope.deep"}}, "c1")
        assert mgr.sent[-1][1]["data"]["config"] is None


class TestConfigSet:
    @pytest.mark.asyncio
    async def test_set_empty_section_error(self, handlers, mgr, monkeypatch):
        _patch_conf(monkeypatch)
        await handlers[ConfigActions.SET](None, {"data": {"section": "", "data": {"a": 1}}}, "c1")
        assert _err(mgr) == "INVALID_REQUEST"

    @pytest.mark.asyncio
    async def test_set_section_saves(self, handlers, mgr, monkeypatch):
        conf = make_config()
        saved = _patch_conf(monkeypatch, conf=conf)
        await handlers[ConfigActions.SET](None, {"data": {"section": "gateway", "data": {"port": 9000}}}, "c1")
        msg = mgr.sent[-1][1]
        assert msg["data"] == {"saved": True}
        assert conf.gateway.port == 9000
        assert len(saved) == 1

    @pytest.mark.asyncio
    async def test_set_non_string_key_error(self, handlers, mgr, monkeypatch):
        _patch_conf(monkeypatch)
        await handlers[ConfigActions.SET](None, {"data": {"section": "gateway", "data": {123: "x"}}}, "c1")
        assert _err(mgr) == "INVALID_REQUEST"

    @pytest.mark.asyncio
    async def test_set_unknown_key_noop(self, handlers, mgr, monkeypatch):
        conf = make_config()
        _patch_conf(monkeypatch, conf=conf)
        await handlers[ConfigActions.SET](None, {"data": {"section": "gateway", "data": {"zzz": 1}}}, "c1")
        assert mgr.sent[-1][1]["data"] == {"saved": True}
        assert not hasattr(conf.gateway, "zzz")


# ================================================================ 脱敏与回验（WS 配置安全修复回归）
from pydantic import BaseModel as _PydBaseModel


class TestConfigGetSanitize:
    """config.get 回包脱敏：key 名含 api_key/apikey/api-key/secret/token/
    password/credential（大小写不敏感）的值必须打码为 "***"。"""

    @pytest.mark.asyncio
    async def test_get_full_masks_api_key(self, handlers, mgr, monkeypatch):
        conf = make_config()
        conf.gateway.api_key = "sk-secret123"
        _patch_conf(monkeypatch, conf=conf)
        await handlers[ConfigActions.GET](None, {"request_id": "r1"}, "c1")
        data = mgr.sent[-1][1]["data"]["config"]
        assert data["gateway"]["api_key"] == "***"
        assert data["gateway"]["host"] == "0.0.0.0"  # 非敏感字段不受影响

    @pytest.mark.asyncio
    async def test_get_section_masks_case_insensitive(self, handlers, mgr, monkeypatch):
        conf = make_config()
        conf.services.asr.SecretToken = "t-abc"  # 大小写不敏感命中 token 标记
        _patch_conf(monkeypatch, conf=conf)
        await handlers[ConfigActions.GET](None, {"data": {"section": "services.asr"}}, "c1")
        assert mgr.sent[-1][1]["data"]["config"] == {"url": "http://asr", "SecretToken": "***"}

    @pytest.mark.asyncio
    async def test_get_masks_inside_list_of_dicts(self, handlers, mgr, monkeypatch):
        # list 内嵌 dict 的敏感 key 同样递归脱敏
        conf = make_config()
        conf.gateway.providers = [{"name": "openai", "api_key": "k1"}]
        _patch_conf(monkeypatch, conf=conf)
        await handlers[ConfigActions.GET](None, {"data": {"section": "gateway"}}, "c1")
        providers = mgr.sent[-1][1]["data"]["config"]["providers"]
        assert providers[0]["api_key"] == "***"
        assert providers[0]["name"] == "openai"


class _RealGateSection(_PydBaseModel):
    """真实 pydantic 段模型：专测 config.set 的 Pydantic 回验路径。"""
    host: str = "0.0.0.0"
    port: int = 8000


class TestConfigSetValidation:
    @pytest.mark.asyncio
    async def test_set_invalid_value_rejected_not_saved(self, handlers, mgr, monkeypatch):
        conf = make_config()
        conf.gateway = _RealGateSection()
        saved = _patch_conf(monkeypatch, conf=conf)
        await handlers[ConfigActions.SET](
            None, {"data": {"section": "gateway", "data": {"port": "not-an-int"}}}, "c1"
        )
        msg = mgr.sent[-1][1]
        assert msg["type"] == "error"
        assert msg["error"]["code"] == "VALIDATION_ERROR"
        assert saved == []                 # 校验失败不落盘
        assert conf.gateway.port == 8000   # 原值未被污染

    @pytest.mark.asyncio
    async def test_set_valid_value_passes_validation(self, handlers, mgr, monkeypatch):
        conf = make_config()
        conf.gateway = _RealGateSection()
        saved = _patch_conf(monkeypatch, conf=conf)
        await handlers[ConfigActions.SET](
            None, {"data": {"section": "gateway", "data": {"port": 9001}}}, "c1"
        )
        assert mgr.sent[-1][1]["data"] == {"saved": True}
        assert conf.gateway.port == 9001
        assert len(saved) == 1