"""server.core.acp.discover (ACPLanDiscovery) 单元测试。

通过注入 FakeSocket 隔离真实 UDP 网络，覆盖：状态查询、start/stop 生命周期与幂等、
beacon 广播载荷、网络扫描（外部/自身 beacon 过滤）、单次发现（端口占用回退、
超时安全）、get_local_ip 获取与回退。

运行：python -m pytest tests/test_acp_discover.py -v
"""
import asyncio
import json
import socket

import pytest

from server.core.acp.discover import ACPLanDiscovery
from server.core.acp.manager import ACPManager


class FakeSocket:
    """模拟 UDP socket：可配置 sendto/recvfrom 行为。"""

    def __init__(self, recv_data=None, connect_ip="192.168.1.5"):
        self.sent = []
        self.recv_data = recv_data or []
        self.connect_ip = connect_ip
        self.closed = False
        self.bound = None

    def setsockopt(self, *a):
        return None

    def settimeout(self, *a):
        return None

    def setblocking(self, *a):
        return None

    def bind(self, addr):
        self.bound = addr

    def close(self):
        self.closed = True

    def sendto(self, data, addr):
        self.sent.append((data, addr))
        return len(data)

    def recvfrom(self, bufsize):
        if self.recv_data:
            return self.recv_data.pop(0)
        raise socket.timeout("no data")

    def connect(self, addr):
        return None

    def getsockname(self):
        return (self.connect_ip, 0)


def _make_discovery(tmp_path, recv_data=None, **kw):
    mgr = ACPManager(data_dir=str(tmp_path))
    mgr.initialize("sys", "系统")
    d = ACPLanDiscovery(acp_manager=mgr, interval=1000, **kw)
    return mgr, d, FakeSocket(recv_data=recv_data)


def _beacon(agent_id="peer", agent_name="对方", port=9999):
    return (
        json.dumps({
            "type": "ACP_BEACON",
            "agent_id": agent_id,
            "agent_name": agent_name,
            "timestamp": "2026-08-07T00:00:00",
            "version": "1.0.0",
            "capabilities": ["memory"],
            "port": port,
        }).encode(),
        ("10.0.0.5", 9998),
    )


# ================================================================ 状态与生命周期
class TestStatusLifecycle:
    def test_get_status(self, tmp_path):
        mgr = ACPManager(data_dir=str(tmp_path))
        d = ACPLanDiscovery(acp_manager=mgr, broadcast_port=8001, discovery_port=8002)
        st = d.get_status()
        assert st["running"] is False
        assert st["broadcast_port"] == 8001
        assert st["discovery_port"] == 8002
        assert st["interval"] == 30  # 默认

    @pytest.mark.asyncio
    async def test_start_sets_running_and_creates_task(self, tmp_path):
        mgr, d, fake = _make_discovery(tmp_path)
        d._socket_factory = lambda *a, **k: fake
        await d.start()
        assert d._running is True
        assert d._task is not None
        await d.stop()

    @pytest.mark.asyncio
    async def test_start_idempotent(self, tmp_path):
        mgr, d, fake = _make_discovery(tmp_path)
        d._socket_factory = lambda *a, **k: fake
        await d.start()
        first_task = d._task
        await d.start()  # 已运行，直接返回
        assert d._task is first_task
        await d.stop()

    @pytest.mark.asyncio
    async def test_stop_closes_sockets(self, tmp_path):
        mgr, d, fake = _make_discovery(tmp_path)
        d._socket_factory = lambda *a, **k: fake
        await d.start()
        await d.stop()
        assert d._running is False
        assert fake.closed is True

    @pytest.mark.asyncio
    async def test_start_failure_calls_stop_and_raises(self, tmp_path):
        mgr, d, fake = _make_discovery(tmp_path)

        def boom(*a, **k):
            raise OSError("bind fail")

        d._socket_factory = boom
        with pytest.raises(OSError):
            await d.start()
        assert d._running is False


# ================================================================ 广播
class TestBroadcast:
    @pytest.mark.asyncio
    async def test_broadcast_presence_payload(self, tmp_path):
        mgr, d, fake = _make_discovery(tmp_path)
        d._broadcast_socket = fake
        await d._broadcast_presence()
        assert len(fake.sent) == 1
        data, addr = fake.sent[0]
        msg = json.loads(data.decode())
        assert msg["type"] == "ACP_BEACON"
        assert msg["agent_id"] == "sys"
        assert msg["agent_name"] == "系统"
        assert addr == ("255.255.255.255", d.discovery_port)
        # #21: 广播目标统一为 discovery_port（对端实际绑定监听的端口）；旧实现
        # 发往 broadcast_port 默认 9998，对端监听 9999，UDP 发现失效。

    @pytest.mark.asyncio
    async def test_broadcast_no_socket_noop(self, tmp_path):
        mgr, d, _ = _make_discovery(tmp_path)
        d._broadcast_socket = None
        await d._broadcast_presence()  # 不抛异常


# ================================================================ 网络扫描
class TestScan:
    @pytest.mark.asyncio
    async def test_scan_registers_external_agent(self, tmp_path):
        mgr, d, fake = _make_discovery(tmp_path, recv_data=[_beacon()])
        d._discovery_socket = fake
        await d._scan_network()
        peer = await mgr.get_agent("peer")
        assert peer is not None
        assert peer.status == "online"
        assert peer.host == "10.0.0.5"

    @pytest.mark.asyncio
    async def test_scan_skips_self(self, tmp_path):
        mgr, d, fake = _make_discovery(tmp_path, recv_data=[_beacon(agent_id="sys")])
        d._discovery_socket = fake
        await d._scan_network()
        # 自身 beacon 不注册
        assert await mgr.get_agent("sys") is None

    @pytest.mark.asyncio
    async def test_scan_no_data_noop(self, tmp_path):
        mgr, d, _ = _make_discovery(tmp_path, recv_data=[])
        d._discovery_socket = FakeSocket(recv_data=[])
        await d._scan_network()  # BlockingIOError/timeout 被捕获，不抛异常


# ================================================================ 单次发现
class TestDiscoverOnce:
    @pytest.mark.asyncio
    async def test_discover_once_finds_agent(self, tmp_path):
        # 第一条 recvfrom 返回 beacon，第二条（列表空）抛 timeout 结束
        mgr, d, fake = _make_discovery(tmp_path, recv_data=[_beacon()])
        d._socket_factory = lambda *a, **k: fake
        agents = await d.discover_once(timeout=0.1)
        assert len(agents) == 1
        assert agents[0]["id"] == "peer"
        assert await mgr.get_agent("peer") is not None

    @pytest.mark.asyncio
    async def test_discover_once_skips_self(self, tmp_path):
        mgr, d, fake = _make_discovery(tmp_path, recv_data=[_beacon(agent_id="sys")])
        d._socket_factory = lambda *a, **k: fake
        agents = await d.discover_once(timeout=0.1)
        assert agents == []

    @pytest.mark.asyncio
    async def test_discover_once_bind_fallback(self, tmp_path):
        # 首次 bind 抛 OSError，随后回退随机端口成功
        mgr, d, fake = _make_discovery(tmp_path, recv_data=[])
        real_bind = fake.bind

        def bind(addr):
            if addr == ("", d.discovery_port):
                raise OSError("addr in use")
            return real_bind(addr)

        fake.bind = bind
        d._socket_factory = lambda *a, **k: fake
        agents = await d.discover_once(timeout=0.1)
        assert agents == []

    @pytest.mark.asyncio
    async def test_discover_once_timeout(self, tmp_path):
        mgr, d, fake = _make_discovery(tmp_path, recv_data=[])
        d._socket_factory = lambda *a, **k: fake
        agents = await d.discover_once(timeout=0.1)
        assert agents == []


# ================================================================ 本地 IP
class TestLocalIP:
    @pytest.mark.asyncio
    async def test_get_local_ip(self, tmp_path):
        mgr, d, fake = _make_discovery(tmp_path)
        d._socket_factory = lambda *a, **k: fake
        assert await d.get_local_ip() == "192.168.1.5"

    @pytest.mark.asyncio
    async def test_get_local_ip_fallback(self, tmp_path):
        mgr, d, fake = _make_discovery(tmp_path)

        def boom(*a, **k):
            raise OSError("no net")

        d._socket_factory = boom
        assert await d.get_local_ip() == "127.0.0.1"