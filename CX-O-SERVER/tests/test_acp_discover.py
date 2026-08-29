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

    @pytest.mark.asyncio
    async def test_scan_dedup_skips_unchanged_beacon(self, tmp_path, monkeypatch):
        """M-C 定向: 四元组（host/port/version/id）无变化不重复注册、不重复落盘。"""
        # 两个完全相同的 beacon
        mgr, d, fake = _make_discovery(tmp_path, recv_data=[_beacon(), _beacon()])
        d._discovery_socket = fake

        reg_calls = {"n": 0}
        orig_register = mgr.register_agent

        async def spy_register(agent, persist=True):
            reg_calls["n"] += 1
            return await orig_register(agent, persist=persist)

        save_calls = {"n": 0}
        orig_save = mgr._save_data

        async def spy_save():
            save_calls["n"] += 1
            return await orig_save()

        monkeypatch.setattr(mgr, "register_agent", spy_register)
        monkeypatch.setattr(mgr, "_save_data", spy_save)

        await d._scan_network()

        assert reg_calls["n"] == 1          # 第二个相同 beacon 被去重
        assert len(mgr.agents) == 1
        assert save_calls["n"] == 1         # 单次合并落盘，无变化不追加落盘

    @pytest.mark.asyncio
    async def test_scan_reregisters_when_quad_changes(self, tmp_path, monkeypatch):
        """M-C 定向: host/port/version/id 任一变化 → 重新注册。"""
        changed = json.loads(_beacon()[0].decode())
        changed["port"] = 7000
        changed_payload = (json.dumps(changed).encode(), ("10.0.0.5", 9998))
        mgr, d, fake = _make_discovery(
            tmp_path, recv_data=[_beacon(), changed_payload]
        )
        d._discovery_socket = fake

        reg_calls = {"n": 0}
        orig_register = mgr.register_agent

        async def spy_register(agent, persist=True):
            reg_calls["n"] += 1
            return await orig_register(agent, persist=persist)

        monkeypatch.setattr(mgr, "register_agent", spy_register)

        await d._scan_network()

        assert reg_calls["n"] == 2          # 端口变化触发重注册
        peer = await mgr.get_agent("peer")
        assert peer.port == 7000


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
        # M-C 旧行为契约更新（20260827 第四轮）: bind 占用不再回退随机端口盲听
        # （对端定向广播收不到 → 恒空扫描假象），改为抛 RuntimeError 让调用方得
        # 明确错误；finally 兜底确保本次临时 socket 被关闭。
        mgr, d, fake = _make_discovery(tmp_path, recv_data=[])
        real_bind = fake.bind

        def bind(addr):
            if addr == ("", d.discovery_port):
                raise OSError("addr in use")
            return real_bind(addr)

        fake.bind = bind
        d._socket_factory = lambda *a, **k: fake
        with pytest.raises(RuntimeError, match="discovery port .* occupied by background service"):
            await d.discover_once(timeout=0.1)
        assert fake.closed is True

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


class BlockingFakeSocket(FakeSocket):
    """模拟阻塞收包 socket：recvfrom 记录执行线程并短暂阻塞后再超时。

    旧实现（recvfrom 直接跑在事件循环线程）下，阻塞期间 heartbeat 无法
    调度；新实现（to_thread 卸载）下 heartbeat 正常推进——以此区分修复前后。
    """

    def __init__(self, **kw):
        super().__init__(**kw)
        self.recv_thread = None

    def recvfrom(self, bufsize):
        import threading
        import time

        self.recv_thread = threading.get_ident()
        time.sleep(0.1)  # 模拟阻塞收包（无信标）
        raise socket.timeout("no data")


# ================================================================ 事件循环不冻结（第十轮）
class TestDiscoverOnceEventLoopNotFrozen:
    @pytest.mark.asyncio
    async def test_discover_once_does_not_block_event_loop(self, tmp_path):
        """无信标时 discover_once 不冻结事件循环：收包在 to_thread 工作线程
        执行，等待期间的并发任务（heartbeat）仍能推进。"""
        import threading

        mgr, d, _ = _make_discovery(tmp_path)
        fake = BlockingFakeSocket()
        d._socket_factory = lambda *a, **k: fake

        ticks = {"n": 0}
        stop = asyncio.Event()

        async def heartbeat():
            while not stop.is_set():
                ticks["n"] += 1
                await asyncio.sleep(0.01)

        hb = asyncio.create_task(heartbeat())
        try:
            agents = await d.discover_once(timeout=0.5)
        finally:
            stop.set()
            await hb

        assert agents == []
        # 收包发生在非事件循环线程（to_thread 工作线程）
        assert fake.recv_thread is not None
        assert fake.recv_thread != threading.get_ident()
        # 事件循环未被冻结：0.1s 阻塞收包期间 heartbeat 获得多轮调度
        # （旧实现下该值只会是 1——阻塞期间事件循环无法调度任何任务）
        assert ticks["n"] >= 3
        # finally 兜底关闭仍然生效
        assert fake.closed is True

    @pytest.mark.asyncio
    async def test_discover_once_still_parses_beacon_from_worker_thread(self, tmp_path):
        """to_thread 化后收包解析语义不变：beacon 仍被正确发现并注册。"""
        import threading

        mgr, d, fake = _make_discovery(tmp_path, recv_data=[_beacon()])

        real_recvfrom = fake.recvfrom
        recv_threads = []

        def spy_recvfrom(bufsize):
            recv_threads.append(threading.get_ident())
            return real_recvfrom(bufsize)

        fake.recvfrom = spy_recvfrom
        d._socket_factory = lambda *a, **k: fake

        agents = await d.discover_once(timeout=0.2)

        assert len(agents) == 1
        assert agents[0]["id"] == "peer"
        assert recv_threads and recv_threads[0] != threading.get_ident()
        assert await mgr.get_agent("peer") is not None