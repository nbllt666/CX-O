"""Token Router Python 绑定。

优先加载 C++ pybind11 模块（绕过 GIL），若编译不可用则回退到
multiprocessing + SharedMemory 备选方案。

模块关系：
    - token_router.cpp  -> 编译产物 token_router.<arch>.pyd / .so
    - token_router_binding.py（本文件）-> 对外暴露 TokenRouterPy
    - 调用方：from scheduler.token_router_binding import TokenRouterPy

设计要点：
    - C++ 路径：push/pop 在 C++ 层完成，pybind11 call_guard 释放 GIL，
      彻底消除 Python 调度毛刺。
    - 备选路径：multiprocessing.Queue 底层使用管道 + 后台 feeder 线程，
      在 pickle 序列化与管道 IO 期间会释放 GIL；SharedMemory 用于跨进程
      共享 finished 标志。虽不及 C++ 方案彻底，但能显著减轻 GIL 阻塞。
"""

from __future__ import annotations

import os
import sys
import threading
from typing import Optional

import numpy as np

# 将本文件所在目录加入 sys.path，便于直接 import 编译出的 token_router 扩展。
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)


def _try_load_cpp_module():
    """尝试加载 C++ pybind11 模块 token_router。

    成功返回模块对象，失败返回 None。失败原因通常是未编译（缺 .pyd/.so）。
    """
    try:
        import token_router  # type: ignore
        # 校验模块确实暴露了 TokenRouter 类，避免误命中同名模块。
        if hasattr(token_router, "TokenRouter"):
            return token_router
    except Exception:
        # 编译不可用、ABI 不匹配、缺 pybind11 运行时等均回退。
        pass
    return None


_CPP_MODULE = _try_load_cpp_module()
CPP_AVAILABLE: bool = _CPP_MODULE is not None


class TokenRouterPy:
    """Token 路由 Python 接口（C++ 优先，备选 multiprocessing）。"""

    def __init__(self, max_queue_size: int = 1024, use_cpp: bool = True):
        """初始化。优先加载 C++ 模块，失败则用 SharedMemory 备选。

        Args:
            max_queue_size: 队列最大块数，防止无界堆积。
            use_cpp: 是否优先使用 C++ 模块；False 强制走备选方案。
        """
        self._max_queue_size = max_queue_size
        self._use_cpp = False
        self._cpp_router = None
        self._fallback = None

        if use_cpp and CPP_AVAILABLE:
            try:
                self._cpp_router = _CPP_MODULE.TokenRouter(max_queue_size=max_queue_size)
                self._use_cpp = True
                return
            except Exception:
                # 即使模块存在，构造失败也回退。
                self._cpp_router = None

        # 备选方案：multiprocessing + SharedMemory。
        self._fallback = _SharedMemoryTokenRouter(max_queue_size=max_queue_size)

    @property
    def backend(self) -> str:
        """当前实际使用的后端名（"cpp" 或 "shared_memory"）。"""
        return "cpp" if self._use_cpp else "shared_memory"

    def push_tokens(self, token_ids: list[int]) -> None:
        """LLM 生产者写入 token 块。"""
        arr = np.asarray(token_ids, dtype=np.int32)
        if self._use_cpp and self._cpp_router is not None:
            # C++ 路径：在 C++ 层释放 GIL 完成入队。
            self._cpp_router.push_tokens(arr)
        else:
            self._fallback.push_tokens(list(token_ids))

    def pop_tokens(self) -> list[int]:
        """TTS 消费者阻塞读取 token 块。

        流结束且队列清空后返回空列表 []，调用方据此终止消费循环。
        """
        if self._use_cpp and self._cpp_router is not None:
            arr = self._cpp_router.pop_tokens()
            # numpy 数组 -> list[int]
            return arr.tolist()
        else:
            return self._fallback.pop_tokens()

    def try_pop_tokens(self) -> Optional[list[int]]:
        """非阻塞尝试读取。无数据返回 None，有数据返回 list[int]。"""
        if self._use_cpp and self._cpp_router is not None:
            obj = self._cpp_router.try_pop_tokens()
            if obj is None:
                return None
            return obj.tolist()
        else:
            return self._fallback.try_pop_tokens()

    def mark_finished(self) -> None:
        """标记 LLM 流结束。"""
        if self._use_cpp and self._cpp_router is not None:
            self._cpp_router.mark_finished()
        else:
            self._fallback.mark_finished()

    def is_drained(self) -> bool:
        """是否已结束且队列空。"""
        if self._use_cpp and self._cpp_router is not None:
            return bool(self._cpp_router.is_drained())
        else:
            return self._fallback.is_drained()

    def queue_size(self) -> int:
        """当前队列长度（块数）。"""
        if self._use_cpp and self._cpp_router is not None:
            return int(self._cpp_router.queue_size())
        else:
            return self._fallback.queue_size()

    def close(self) -> None:
        """释放底层资源（SharedMemory 块等）。C++ 路径无需操作。"""
        if self._fallback is not None:
            self._fallback.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


class _SharedMemoryTokenRouter:
    """备选方案：multiprocessing + SharedMemory 实现（当 C++ 不可用时）。

    用 multiprocessing.Queue 传递 token 块（Queue 底层管道 IO 释放 GIL），
    用 SharedMemory 共享 finished 标志位，从而在 C++ 模块不可用时仍能
    减轻 GIL 阻塞。

    说明：本方案不如 C++ 方案彻底（pickle 序列化仍有 GIL 开销），但相比
    纯 threading.Queue 已大幅减少 GIL 持有时间，可作为编译不可用时的降级。
    """

    # SharedMemory 状态块布局：byte 0 = finished 标志（0/1）。
    _SHM_SIZE = 8

    def __init__(self, max_queue_size: int = 1024):
        # 延迟导入，避免在仅用 C++ 时引入 multiprocessing 开销。
        from multiprocessing import Queue
        from multiprocessing.shared_memory import SharedMemory

        self._max_queue_size = max_queue_size
        # multiprocessing.Queue：带 maxsize 限流；put 在满时阻塞。
        # 其底层使用管道 + 后台 feeder 线程，IO 期间释放 GIL。
        self._queue = Queue(maxsize=max_queue_size)
        # SharedMemory 状态块：跨进程共享 finished 标志。
        self._shm = SharedMemory(create=True, size=self._SHM_SIZE)
        # 初始化 finished = 0
        self._shm.buf[0] = 0
        self._closed = False
        self._lock = threading.Lock()

    def push_tokens(self, token_ids: list[int]) -> None:
        if self._closed:
            raise RuntimeError("TokenRouter: already closed")
        if self._shm.buf[0]:
            raise RuntimeError("TokenRouter: push_tokens called after mark_finished")
        # put 在队列满时阻塞；multiprocessing.Queue 的 put 会通过 feeder
        # 线程异步发送，主线程在 put 内部等待期间释放 GIL。
        self._queue.put(list(token_ids))

    def pop_tokens(self) -> list[int]:
        """阻塞读取 token 块。流结束且队列空时返回 []。"""
        from queue import Empty
        import time
        while True:
            try:
                # 用短超时轮询，使得 mark_finished 能及时被消费者感知。
                chunk = self._queue.get(timeout=0.05)
                return chunk
            except Empty:
                if not self._shm.buf[0]:
                    # 未结束：继续等待生产者写入。
                    continue
                # 已结束：可能还有数据在 multiprocessing.Queue 的 feeder 线程
                # 内部 buffer 中未发送到管道（empty() 此时会误报为空）。
                # 短暂等待 feeder 线程刷新后重试 get_nowait，避免遗漏最后几个 token。
                time.sleep(0.001)
                try:
                    return self._queue.get_nowait()
                except Empty:
                    return []

    def try_pop_tokens(self) -> Optional[list[int]]:
        """非阻塞尝试读取。无数据返回 None。"""
        from queue import Empty
        try:
            return self._queue.get_nowait()
        except Empty:
            # multiprocessing.Queue 的 put 是异步的：put 返回后数据由 feeder 线程
            # 后台刷新到管道，可能尚未就绪。put 后立即 try_pop 会出现竞态（Linux
            # 上尤为明显）。短暂等待 feeder 线程刷新后重试一次，保证 put 后的
            # try_pop 能读到数据。正常路径（有数据）无延迟；真正的空队列仍返回 None。
            import time
            time.sleep(0.001)
            try:
                return self._queue.get_nowait()
            except Empty:
                return None

    def mark_finished(self) -> None:
        # 通过 SharedMemory 写入 finished 标志，跨进程可见。
        self._shm.buf[0] = 1

    def is_drained(self) -> bool:
        return bool(self._shm.buf[0]) and self._queue.empty()

    def queue_size(self) -> int:
        # multiprocessing.Queue 的 qsize 在某些平台（如 macOS）可能不可靠，
        # 这里仅作近似返回。
        try:
            return self._queue.qsize()
        except NotImplementedError:
            return 0

    def close(self) -> None:
        """释放 SharedMemory 块。多次调用安全。"""
        with self._lock:
            if self._closed:
                return
            self._closed = True
        try:
            self._shm.close()
            self._shm.unlink()
        except Exception:
            # SharedMemory 可能已被其它持有者释放，忽略错误。
            pass
