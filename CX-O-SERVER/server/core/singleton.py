"""跨进程单 leader（leader guard）——供多 worker 后台服务去重使用。

背景：当 ``uvicorn workers>1`` 时，uWSGI/uvicorn 会用多进程加载 ``app`` 并各自
跑一遍 lifespan。核心 HTTP 承载服务（model_router / memory / context / ASR/TTS / API）
每个 worker 都必须有；但「定时/后台/告警/预热」这类全局副作用服务在各 worker 各起一份
会导致重复触发。本模块提供基于文件锁的跨进程单 leader 判定，仅允许获得 leader 的进程
运行该类后台服务。

设计原则（保守 / 向后兼容）：
- 默认 ``workers=1`` 时唯一进程必然拿到 leader，行为与现状完全一致（零侵入）。
- ``workers>1`` 时通过操作系统级排它文件锁（POSIX 用 ``fcntl.flock``，Windows 用
  ``msvcrt.locking``，均非阻塞）保证所有并发 worker 中恰好一个成为 leader。
- 锁由操作系统进程持有：进程退出/崩溃时锁自动释放，无需清理残留文件，健壮。
- ``release()`` 显式释放（配合调用侧 try…finally），幂等。
- 非 leader 进程跳过后台服务并记日志即可，不抛错、不阻塞。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

try:  # POSIX 文件锁
    import fcntl

    _HAS_FCNTL = True
except ImportError:  # pragma: no cover - 非 POSIX 平台
    fcntl = None
    _HAS_FCNTL = False

try:  # Windows 文件锁
    import msvcrt

    _HAS_MSVCRT = True
except ImportError:  # pragma: no cover - 非 Windows 平台
    msvcrt = None
    _HAS_MSVCRT = False

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class SingleLeaderGuard:
    """基于文件排它锁的跨进程单 leader 判定器。

    Args:
        lock_path: 锁文件路径。为 None 时自动落到 ``<项目根>/data/leader.lock``。
    """

    def __init__(self, lock_path: Optional[str] = None) -> None:
        self.lock_path = str(lock_path) if lock_path else str(_PROJECT_ROOT / "data" / "leader.lock")
        self._fd: Optional[int] = None
        self._marker: Optional[str] = None
        self._leader: bool = False

    @classmethod
    def for_background(cls, lock_path: Optional[str] = None) -> "SingleLeaderGuard":
        """构造默认后台服务 leader guard（锁文件位于 ``<项目根>/data/leader.lock``）。"""
        return cls(lock_path=lock_path)

    @property
    def is_leader(self) -> bool:
        """当前进程是否为本角色 leader。"""
        return self._leader

    def acquire(self) -> bool:
        """尝试获取 leader。成功返回 True，否则返回 False（等价 try_acquire）。"""
        if self._leader:
            return True
        if self._fd is not None:  # 已持有句柄但非 leader（异常态兜底）
            return False

        parent = os.path.dirname(self.lock_path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)

        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o644)
        # 确保文件至少 1 字节，供 Windows msvcrt.locking 锁 1 字节范围
        if os.fstat(fd).st_size == 0:
            os.write(fd, b"\x00")
            os.fsync(fd)

        if self._acquire_lock(fd):
            self._fd = fd
            self._leader = True
            return True

        # 竞争失败：放弃句柄，避免误解锁
        self._close_fd(fd)
        return False

    try_acquire = acquire

    def release(self) -> None:
        """释放 leader 锁（幂等）。调用侧通过 try…finally 保证在关闭段执行。"""
        if self._fd is not None:
            self._unlock_fd(self._fd)
            self._close_fd(self._fd)
        self._fd = None
        self._marker = None
        self._leader = False

    def __enter__(self) -> "SingleLeaderGuard":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.release()
        return False

    # -------- 平台相关加锁/解锁实现 --------
    def _acquire_lock(self, fd: int) -> bool:
        if _HAS_FCNTL and fcntl is not None:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except OSError:
                return False

        if _HAS_MSVCRT and msvcrt is not None:
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                return True
            except OSError:
                return False

        # 无 fcntl/msvcrt 的兜底：原子创建标记文件（O_EXCL）。
        marker = self.lock_path + ".mark"
        if self._marker is None:
            try:
                mfd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
                os.close(mfd)
                self._marker = marker
                return True
            except OSError:
                return False
        return False

    def _unlock_fd(self, fd: int) -> None:
        try:
            if _HAS_FCNTL and fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_UN)
            elif _HAS_MSVCRT and msvcrt is not None:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass  # 解锁失败不影响关闭（进程退出时 OS 亦会释放）
        if self._marker is not None:
            try:
                os.unlink(self._marker)
            except OSError:
                pass
            self._marker = None

    @staticmethod
    def _close_fd(fd: int) -> None:
        try:
            os.close(fd)
        except OSError:
            pass