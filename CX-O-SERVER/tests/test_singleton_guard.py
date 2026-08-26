"""SingleLeaderGuard 跨进程单 leader guard 单元测试。

验证：
- N 个并发 guard 实例对同一锁文件竞争时，恰好一个成为 leader；
- 无竞争（对应默认 workers=1 场景）下唯一进程必然拿到 leader；
- release 后可重新获取（对应进程重启 / 优雅关闭）。
"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from server.core.singleton import SingleLeaderGuard

_SERVER_DIR = str(Path(__file__).resolve().parent.parent)


def _acquire_proc(lock: str, hold_sec: float, pre_sleep: float = 0.0) -> subprocess.Popen:
    """启动独立 Python 子进程对同一锁做 SingleLeaderGuard.acquire()，持有可选时长。

    返回 Popen，stdout 输出 "OK"（成为 leader）或 "LOSE"（竞争失败）。
    """
    code = (
        "import sys,time;"
        "sys.path.insert(0,sys.argv[1]);"
        "from server.core.singleton import SingleLeaderGuard;"
        "time.sleep(float(sys.argv[3]));"
        "g=SingleLeaderGuard(sys.argv[2]);"
        "ok=g.acquire();"
        "print('OK' if ok else 'LOSE', flush=True);"
        "time.sleep(float(sys.argv[4])) if ok else None;"
        "g.release() if ok else None"
    )
    return subprocess.Popen(
        [sys.executable, "-c", code, _SERVER_DIR, lock, str(pre_sleep), str(hold_sec)],
        cwd=_SERVER_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def test_cross_process_exactly_one_leader():
    """真实 OS 进程竞争同一锁（对应 uvicorn workers>1）：恰一个拿到 leader。

    领先者持有锁 >2s（等同多 worker 下 leader 进程驻留），后到者竞争被拒。
    """
    lock = os.path.join(tempfile.mkdtemp(prefix="cxo_leader_proc_"), "leader.lck")
    leader = _acquire_proc(lock, hold_sec=2.0)
    time.sleep(0.4)  # 确保 leader 已持锁
    contender = _acquire_proc(lock, hold_sec=0.0, pre_sleep=0.2)
    out_l, _ = leader.communicate(timeout=10)
    out_c, _ = contender.communicate(timeout=10)
    assert "OK" in out_l, f"leader 应返回 OK，实际: {out_l!r}"
    assert "LOSE" in out_c, f"contender 应返回 LOSE，实际: {out_c!r}"


def _unique_path() -> str:
    d = tempfile.mkdtemp(prefix="cxo_leader_")
    return os.path.join(d, "leader.lck")


def test_exactly_one_leader_among_N():
    """并发创建 N=4 个 guard 实例，断言恰有一个成为 leader。"""
    path = _unique_path()
    guards = [SingleLeaderGuard(lock_path=path) for _ in range(4)]
    try:
        results = [g.acquire() for g in guards]
        # 恰有一个 True，其余均为 False（锁不允许多 leader）
        assert results.count(True) == 1, f"expected exactly 1 leader, got {results}"
        assert results.count(False) == 3, f"expected 3 non-leader, got {results}"
        # 获得 leader 的实例 is_leader 为 True，其余为 False
        for acquired, guard in zip(results, guards):
            assert guard.is_leader == acquired
    finally:
        for g in guards:
            g.release()


def test_single_instance_defaults_to_leader():
    """无竞争场景（默认 workers=1 语义）下唯一进程必然拿到 leader。"""
    path = _unique_path()
    guard = SingleLeaderGuard(lock_path=path)
    try:
        assert guard.acquire() is True
        assert guard.is_leader is True
    finally:
        guard.release()


def test_release_allows_reacquire():
    """leader release 后，新的 guard 可重新获取（对应进程重启/优雅关闭）。"""
    path = _unique_path()
    g1 = SingleLeaderGuard(lock_path=path)
    g2 = SingleLeaderGuard(lock_path=path)
    try:
        assert g1.acquire() is True
        assert g2.acquire() is False  # g1 未释放时 g2 拿不到
        g1.release()
        g3 = SingleLeaderGuard(lock_path=path)
        try:
            assert g3.acquire() is True  # 释放后可重新成为 leader
        finally:
            g3.release()
    finally:
        g1.release()
        g2.release()


def test_context_manager_acquire_release():
    """with 语句支持 acquire/release，离开作用域自动释放。"""
    path = _unique_path()
    guard = SingleLeaderGuard(lock_path=path)
    other = SingleLeaderGuard(lock_path=path)
    try:
        with guard:
            assert guard.is_leader
            assert other.acquire() is False  # guard 仍在时 other 拿不到
        assert guard.is_leader is False
        # 退出 with 后 other 可获取
        assert other.acquire() is True
    finally:
        other.release()