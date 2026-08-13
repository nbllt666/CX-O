"""CXFC 电脑控制接入后端测试（Task 3 + B-1 修复）。

覆盖：
- 注册携带 token、tls_cert_fingerprint 与 tls_cert_pem，并持久化到 SQLite
- call_tool 转发带令牌插件时携带 Authorization: Bearer <token> 与唯一 request_id
- B-1：带证书插件经 https:// 访问，并使用带 verify=<CA文件> 的专用 HTTPS client（TOFU 证书固定）
- B-1：证书指纹与注册证书不匹配 → 拒绝注册（首次信任校验失败）
- 无令牌/无证书的既有插件兼容：http:// 转发、不加认证头、不加 request_id
- 注销清理（disconnect_plugin 从内存与存储中移除）
- 重复注册（同 host/port 重新注册）更新而非累积
- 插件断开时 call_tool 不发起调用
- SQLite 旧库（无 token/指纹/证书列）向后兼容迁移
"""
import asyncio
import os

import aiosqlite
import pytest

from server.core.cxfc.manager import CXFCManager
from server.core.cxfc.models import CXFCRegisterRequest, PluginStatus
from server.core.cxfc.storage import CXFCStorage


def run(coro):
    return asyncio.run(coro)


# B-1：真实自签名证书 PEM 与其 SHA-256 指纹（冒号分隔，对齐 Electron tls.ts 格式）
TLS_CERT_PEM = """-----BEGIN CERTIFICATE-----
MIIC8jCCAdqgAwIBAgIUNuX9q8ntgApiw8F9bb9V3IpPJbcwDQYJKoZIhvcNAQEL
BQAwIzEhMB8GA1UEAwwYY3hvLXBldC1jb21wdXRlci1jb250cm9sMB4XDTI2MDgx
MzA4MzAxOFoXDTM2MDgxMDA4MzAxOFowIzEhMB8GA1UEAwwYY3hvLXBldC1jb21w
dXRlci1jb250cm9sMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAtLML
WwmbOIoKeQg32ngQUHGW/QlGqvT6audFtRmpeVGiy/svLwPUsRo9zNcoOxFXUTZO
EIyYbpa/lJiCvHCCMYz6F7buRxM/Vbu/OZvci6hPfnXC/FIZjj9wohhIYETBmQG2
9C0vRRNTFSDcTsi+J6YwHq9pywZKdwtIjT6zfaxrsJy9ZkWGGqA805X+/Ts+AHJp
I8xLH0PzCBvPDYA4a24Nlhct+vjrD56fniSgmnHxsKnA7poeZTRZzXSQx//uqPyH
zmnyYMoSnpOjHgbWCjodicTHubVgjVFjXxpEBhqPF0EDp3K3AFQsRu4ryUPASykd
gU/6Lls3ITgYXn8vIQIDAQABox4wHDAaBgNVHREEEzARgglsb2NhbGhvc3SHBH8A
AAEwDQYJKoZIhvcNAQELBQADggEBAIgpyk8B/Tl3T2+u1Iow8TW806ZxRR3/c+hk
q2JsQAsGrtCxbBT88gPByBAzOY7ut6KC12YJMKrI3aaDo6D1d37POFnmL6eRWqCE
VcEdRnWCcNj+XTvQXFAGf54ko6MwrXCc16NgWS8YnyVxdNDckZjGA1RC7qg8XxwK
spGyvgV29aEhRG1qKFiD38Y3McFOeyXB7KON98QTXqy6al9wMLVrJL9GPt8Ktmyu
pNpST/+9tjjCm3HQI3Bc9YaiWCfkFixJAQR21aSVP3h35ZfpJ7d9iwGM7j2nindR
2KgYBmOLCUnwUnw27eFSrJdhWuf79zvTzPcS7taxu2AIGByQtDk=
-----END CERTIFICATE-----
"""
# 该 PEM 对应的 SHA-256 指纹（冒号分隔，大写）
TLS_CERT_FINGERPRINT = "F4:9D:F4:00:C2:78:FD:6D:4D:B6:08:3F:85:25:2D:61:C7:80:B2:3E:48:EB:F8:B2:85:AE:27:0C:7E:01:37:7C"


class FakeResp:
    def __init__(self, status_code=200, data=None):
        self.status_code = status_code
        self._data = data or {}

    def json(self):
        return self._data


class FakeHttp:
    """伪造 httpx.AsyncClient，捕获 post/get 调用参数。"""

    def __init__(self):
        self.post_calls = []
        self.get_calls = []

    async def post(self, url, json=None, headers=None, timeout=None):
        self.post_calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return FakeResp(200, {"ok": True, "result": {"done": True}})

    async def get(self, url, timeout=None):
        self.get_calls.append({"url": url, "timeout": timeout})
        return FakeResp(200, {"status": "ok"})


class FakeTlsFactory:
    """B-1：可注入的 httpx.AsyncClient 工厂，捕获 verify 参数并返回可记录的假 client。"""

    def __init__(self):
        self.kwargs_list = []
        self.clients = []

    def __call__(self, **kwargs):
        self.kwargs_list.append(kwargs)
        c = FakeHttp()
        self.clients.append(c)
        return c


@pytest.fixture
def manager(tmp_path):
    m = CXFCManager(storage_path=str(tmp_path / "cxfc_plugins.db"))
    run(m._storage.init_db())
    return m


@pytest.fixture
def token_request():
    return CXFCRegisterRequest(
        host="127.0.0.1",
        port=8443,
        name="computer-control",
        version="1.0.0",
        tools=[{"name": "computer_screen_control", "description": "d", "parameters": {}, "returns": {}}],
        token="reg-token-abc",
        tls_cert_fingerprint=TLS_CERT_FINGERPRINT,
        tls_cert_pem=TLS_CERT_PEM,
    )


def test_register_persists_token_and_fingerprint(manager, token_request):
    plugin = run(manager.register_plugin(token_request))
    assert plugin.plugin_id == "cxfc_127.0.0.1_8443"
    assert plugin.token == "reg-token-abc"
    assert plugin.tls_cert_fingerprint == TLS_CERT_FINGERPRINT
    assert plugin.tls_cert_pem == TLS_CERT_PEM
    assert plugin.status == PluginStatus.CONNECTED

    # 持久化后从存储重载仍保留 token/指纹/证书
    loaded = run(manager._storage.load_plugins())
    assert len(loaded) == 1
    assert loaded[0].token == "reg-token-abc"
    assert loaded[0].tls_cert_fingerprint == TLS_CERT_FINGERPRINT
    assert loaded[0].tls_cert_pem == TLS_CERT_PEM


def test_call_tool_https_dedicated_client_with_verify(manager, token_request):
    """B-1：带证书插件经 https 转发，使用带 verify=<CA文件> 的专用 HTTPS client。"""
    run(manager.register_plugin(token_request))
    pid = "cxfc_127.0.0.1_8443"
    plugin = manager.get_plugin(pid)
    assert plugin.tls_cert_pem == TLS_CERT_PEM

    # 注入工厂构建专用 TLS client，捕获 verify 参数
    factory = FakeTlsFactory()
    manager._client_factory = factory
    manager._ensure_tls_client(plugin)
    assert factory.kwargs_list[-1]["verify"] == manager._tls_ca_paths[pid]
    ca_path = manager._tls_ca_paths[pid]
    # CA 文件存在且包含注册的证书原文
    assert os.path.exists(ca_path)
    with open(ca_path, encoding="utf-8") as f:
        assert "BEGIN CERTIFICATE" in f.read()

    result = run(manager.call_tool(pid, "computer_screen_control", {"action": "capture"}))

    assert result["ok"] is True
    fake = factory.clients[-1]
    assert len(fake.post_calls) == 1
    call = fake.post_calls[0]
    # 带证书插件必须以 https 访问（不得降级为明文 http 转发）
    assert call["url"] == "https://127.0.0.1:8443/call"
    assert call["headers"]["Authorization"] == "Bearer reg-token-abc"
    # 带令牌插件必须携带唯一 request_id 以满足防重放契约
    assert isinstance(call["json"]["request_id"], str) and len(call["json"]["request_id"]) > 0
    assert call["json"]["tool"] == "computer_screen_control"
    assert call["json"]["arguments"] == {"action": "capture"}


def test_register_rejects_fingerprint_mismatch(manager):
    """B-1：证书指纹与注册证书不匹配 → 拒绝注册（首次信任校验失败）。"""
    req = CXFCRegisterRequest(
        host="127.0.0.1",
        port=8444,
        name="computer-control",
        tools=[{"name": "computer_screen_control", "description": "d", "parameters": {}, "returns": {}}],
        token="reg-token-abc",
        tls_cert_fingerprint="AA:BB:CC:DD:EE:FF:00:11:22:33:44:55:66:77:88:99:AA:BB:CC:DD:EE:FF:00:11:22:33:44:55:66:77:88:99",
        tls_cert_pem=TLS_CERT_PEM,
    )
    with pytest.raises(ValueError):
        run(manager.register_plugin(req))
    # 被拒注册不应进入内存或存储
    assert manager.get_plugins() == []
    assert run(manager._storage.load_plugins()) == []


def test_call_tool_no_token_plugin_compat(manager):
    # 无 token、无证书的既有插件
    req = CXFCRegisterRequest(host="10.0.0.5", port=9000, name="legacy", tools=[{"name": "t"}])
    run(manager.register_plugin(req))
    fake = FakeHttp()
    manager._http_client = fake

    result = run(manager.call_tool("cxfc_10.0.0.5_9000", "t", {}))

    assert result["ok"] is True
    call = fake.post_calls[0]
    # 兼容性：http 明文转发、不加认证头、不加 request_id
    assert call["url"] == "http://10.0.0.5:9000/call"
    assert call["headers"] is None or call["headers"] == {}
    assert "request_id" not in (call["json"] or {})
    assert call["json"] == {"tool": "t", "arguments": {}}


def test_disconnect_plugin_cleans_up(manager, token_request):
    plugin = run(manager.register_plugin(token_request))
    plugin_id = plugin.plugin_id

    run(manager.disconnect_plugin(plugin_id, remove_persistent=True))

    assert manager.get_plugin(plugin_id) is None
    assert run(manager._storage.load_plugins()) == []
    # 专用 TLS client 与 CA 文件已释放
    assert plugin_id not in manager._tls_clients
    assert plugin_id not in manager._tls_ca_paths
    # 后续 call_tool 返回不可用
    fake = FakeHttp()
    manager._http_client = fake
    result = run(manager.call_tool(plugin_id, "computer_screen_control", {}))
    assert result["success"] is False
    assert fake.post_calls == []


def test_re_register_same_host_port_replaces(manager, token_request):
    first = run(manager.register_plugin(token_request))
    plugin_id = first.plugin_id

    # 同一 host/port 用新 token 重新注册 → 更新而非累积
    req2 = token_request.model_copy(update={"token": "new-token-xyz"})
    run(manager.register_plugin(req2))

    assert len(manager.get_plugins()) == 1
    updated = manager.get_plugin(plugin_id)
    assert updated.token == "new-token-xyz"
    assert len(run(manager._storage.load_plugins())) == 1


def test_call_tool_disconnected_plugin_not_called(manager, token_request):
    plugin = run(manager.register_plugin(token_request))
    plugin_id = plugin.plugin_id
    plugin.status = PluginStatus.DISCONNECTED

    fake = FakeHttp()
    manager._http_client = fake
    result = run(manager.call_tool(plugin_id, "computer_screen_control", {}))
    assert result["success"] is False
    assert fake.post_calls == []


def test_call_tool_timeout_returns_error(manager):
    """工具调用超时/网络异常 → 返回 success:false 且不抛异常（边界处理）。

    B-1 后：无证书旧插件走共享 http client，故用无证书插件注入抛错 client 验证。
    """
    req = CXFCRegisterRequest(host="10.0.0.6", port=9001, name="legacy", tools=[{"name": "t"}])
    run(manager.register_plugin(req))

    class RaisingHttp:
        async def post(self, url, json=None, headers=None, timeout=None):
            raise TimeoutError("call timeout")

    manager._http_client = RaisingHttp()
    result = run(manager.call_tool("cxfc_10.0.0.6_9001", "computer_run_command", {"command": "echo"}))
    assert result["success"] is False
    assert "call timeout" in result["error"]


def test_refresh_plugin_keeps_token_and_fingerprint(manager, token_request):
    """刷新插件（重拉 tools/skills）后 token、指纹与证书保持不变。"""
    plugin = run(manager.register_plugin(token_request))
    plugin_id = plugin.plugin_id
    fake = FakeHttp()
    manager._http_client = fake

    refreshed = run(manager.refresh_plugin(plugin_id))
    assert refreshed is not None
    assert refreshed.token == "reg-token-abc"
    assert refreshed.tls_cert_fingerprint == TLS_CERT_FINGERPRINT
    assert refreshed.tls_cert_pem == TLS_CERT_PEM
    # 持久化仍保留 token
    loaded = run(manager._storage.load_plugins())
    assert loaded[0].token == "reg-token-abc"


def test_storage_migration_adds_columns_to_old_db(tmp_path):
    """旧库（无 token/指纹/证书列）在 init_db 后自动迁移补充列，历史数据保持可读。"""
    db_path = str(tmp_path / "legacy.db")
    # 手工按旧 schema 建表并插入一条记录（无 token 列）
    async def _seed():
        db = await aiosqlite.connect(db_path)
        await db.execute(
            """
            CREATE TABLE cxfc_plugins (
                plugin_id TEXT PRIMARY KEY, host TEXT, port INTEGER, name TEXT, version TEXT,
                capabilities TEXT, status TEXT, last_seen TEXT, tools TEXT, skills TEXT,
                created_at TEXT, updated_at TEXT
            )
            """
        )
        await db.execute(
            "INSERT INTO cxfc_plugins (plugin_id, host, port, name, version, status, tools, skills) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("cxfc_old_1", "127.0.0.1", 1111, "legacy", "1.0.0", "connected", "[]", "[]"),
        )
        await db.commit()
        await db.close()

    run(_seed())

    storage = CXFCStorage(db_path)
    run(storage.init_db())
    try:
        # 迁移后新增列存在
        async def _cols():
            cursor = await storage._db.execute("PRAGMA table_info(cxfc_plugins)")
            return {row["name"] for row in await cursor.fetchall()}

        cols = run(_cols())
        assert "token" in cols
        assert "tls_cert_fingerprint" in cols
        assert "tls_cert_pem" in cols

        # 历史记录可加载，token/指纹/证书为 None
        loaded = run(storage.load_plugins())
        assert len(loaded) == 1
        assert loaded[0].plugin_id == "cxfc_old_1"
        assert loaded[0].token is None
        assert loaded[0].tls_cert_fingerprint is None
        assert loaded[0].tls_cert_pem is None
    finally:
        run(storage.close())

