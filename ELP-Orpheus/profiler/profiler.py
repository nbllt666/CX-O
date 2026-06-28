"""ELP-Orpheus Profiler Python 封装。

提供高级 API：context manager（stage）、装饰器（profile）、采样查询。

模块关系：
    - probe.cpp / probe.h  -> 编译产物 probe_cpp.<arch>.pyd / .so
    - profiler.py（本文件）-> 对外暴露 Profiler / _PyProbe / stage / profile
    - 调用方：from profiler import Profiler, stage, profile

设计决策：
    - C++ 优先：尝试 import probe_cpp（编译产物），成功则用 C++ Probe（< 100ns 探针）。
    - Python 回退：编译不可用时用 _PyProbe（time.perf_counter_ns），接口与 C++ 一致，
      保证开发环境（Windows 无编译器 / 无 CUDA）也能正常使用。
    - 全局单例：_default_profiler = Profiler()，模块级 stage()/profile() 便利函数
      委托给单例，简化调用方代码。
    - ns → ms：get_samples 返回 ms 列表（底层存储 ns，转换在 Python 层做），
      与 run_e2e.py 的 stages 字典（ms 单位）保持一致。

参考：
    - scripts/run_e2e.py 的 stages 字典结构（asr_ms/llm_ttft_ms/router_ms/
      ft_prefill_ms/audio_head_ms/generation_ms/snac_decode_ms/crossfade_ms）
    - scheduler/token_router.cpp 的 pybind11 GIL 策略
    - tests/benchmark_decode.py 的 _stats / _percentile 实现
"""

from __future__ import annotations

import functools
import os
import sys
import threading
import time
from typing import Optional

# 将本文件所在目录加入 sys.path，便于直接 import 编译出的 probe_cpp 扩展
# （参考 scheduler/token_router_binding.py 的 sys.path 注入方式）。
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)


def _try_load_cpp_module():
    """尝试加载 C++ pybind11 模块 probe_cpp。

    成功返回模块对象，失败返回 None。失败原因通常是未编译（缺 .pyd/.so），
    此时上层自动回退到 _PyProbe 纯 Python 路径。
    """
    try:
        import probe_cpp  # type: ignore
        # 校验模块确实暴露了 Probe 类，避免误命中同名模块。
        if hasattr(probe_cpp, "Probe"):
            return probe_cpp
    except Exception:
        # 编译不可用、ABI 不匹配、缺 pybind11 运行时等均回退。
        pass
    return None


_CPP_MODULE = _try_load_cpp_module()
CPP_AVAILABLE: bool = _CPP_MODULE is not None


class _PyProbe:
    """纯 Python 回退探针（当 C++ probe_cpp 不可用时使用）。

    用 time.perf_counter_ns() 计时，接口与 C++ Probe 完全一致：
        begin / end / get_samples / clear / overhead_ns /
        cuda_event_begin / cuda_event_end

    设计决策：
        - 用 threading.Lock 保证并发流（concurrent_runner 4 流）下线程安全。
        - start_times 用 dict[str, list] 当栈，支持嵌套 stage。
        - cuda_event_begin/end 无 CUDA 时等价于 begin/end（与 C++ 回退行为一致）。
        - 单次 begin/end 开销约 200-500ns（perf_counter_ns + Lock），满足 < 1μs 目标。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # name -> list[int]（开始时戳栈，perf_counter_ns 返回 int）
        self._start_times: dict[str, list[int]] = {}
        # name -> list[int]（已采样耗时，ns）
        self._samples: dict[str, list[int]] = {}

    def begin(self, name: str) -> None:
        """记录 stage 开始时戳（压入栈，支持嵌套）。"""
        now = time.perf_counter_ns()
        with self._lock:
            self._start_times.setdefault(name, []).append(now)

    def end(self, name: str) -> None:
        """记录 stage 结束时戳，计算 elapsed_ns 存入采样列表。"""
        now = time.perf_counter_ns()
        with self._lock:
            stack = self._start_times.get(name)
            if not stack:
                # 无匹配 begin：静默忽略（防御性，避免崩溃）。
                return
            start = stack.pop()
            elapsed = now - start
            self._samples.setdefault(name, []).append(elapsed)

    def cuda_event_begin(self, name: str, stream: int = 0) -> None:
        """无 CUDA 回退：等价于 begin（与 C++ probe_cpp 行为一致）。"""
        self.begin(name)

    def cuda_event_end(self, name: str, stream: int = 0) -> None:
        """无 CUDA 回退：等价于 end。"""
        self.end(name)

    def get_samples(self, name: str) -> list[int]:
        """返回某 stage 的所有采样（ns）。"""
        with self._lock:
            return list(self._samples.get(name, []))

    def clear(self) -> None:
        """清空所有采样与开始时戳栈。"""
        with self._lock:
            self._start_times.clear()
            self._samples.clear()

    def overhead_ns(self) -> int:
        """测量 begin/end 一次的自身开销（ns）。

        begin 紧跟 end，中间无工作，采样值即探针自身开销。
        """
        self.clear()
        self.begin("__overhead__")
        self.end("__overhead__")
        samples = self.get_samples("__overhead__")
        result = samples[0] if samples else 0
        self.clear()
        return result


# Probe 公共类：C++ 优先，回退 _PyProbe。供 __init__.py 导出。
Probe = _CPP_MODULE.Probe if _CPP_MODULE is not None else _PyProbe


class _StageContext:
    """stage 上下文管理器：__enter__ 调 begin，__exit__ 调 end。

    用法：
        with profiler.stage("ft_prefill"):
            ...  # 被计时代码
    """

    def __init__(self, probe, name: str):
        self._probe = probe
        self._name = name

    def __enter__(self):
        self._probe.begin(self._name)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._probe.end(self._name)
        return False  # 不吞异常


class Profiler:
    """高级 Profiler：封装 C++ Probe 或 _PyProbe，提供 stage/profile API。

    设计决策：
        - 持有一个底层 probe 对象（C++ 或 Python），所有调用委托给它。
        - backend() 返回 "cpp" 或 "python"，便于上层报告标注与测试断言。
        - get_samples 返回 ms 列表（底层 ns / 1e6），与 run_e2e.py stages 单位一致。
    """

    def __init__(self, name: str = "default") -> None:
        """初始化。优先加载 C++ Probe，失败回退 _PyProbe。

        Args:
            name: Profiler 实例名（仅用于标识，不影响行为）。
        """
        self._name = name
        self._cpp_probe = None
        self._py_probe: Optional[_PyProbe] = None
        self._backend = "python"
        # 注入采样存储（ns）：record_sample 写入，与底层 probe 解耦，
        # 使 C++ Probe 环境下 IpcCompensationDecorator 也能注入补偿值。
        self._injected_samples: dict[str, list[int]] = {}

        if CPP_AVAILABLE and _CPP_MODULE is not None:
            try:
                self._cpp_probe = _CPP_MODULE.Probe()
                self._backend = "cpp"
                return
            except Exception:
                # 即使模块存在，构造失败也回退。
                self._cpp_probe = None

        self._py_probe = _PyProbe()
        self._backend = "python"

    @property
    def _probe(self):
        """当前实际使用的底层 probe 对象（C++ 或 Python）。"""
        return self._cpp_probe if self._cpp_probe is not None else self._py_probe

    def stage(self, name: str) -> _StageContext:
        """返回 context manager，包裹代码块自动 begin/end。

        用法：
            with profiler.stage("snac_decode"):
                pcm = snac_decoder.decode(tokens)
        """
        return _StageContext(self._probe, name)

    def profile(self, name: str):
        """返回装饰器，包裹函数自动 begin/end。

        用法：
            @profiler.profile("ft_decode")
            def decode_one_token(...):
                ...
        """

        def decorator(fn):
            @functools.wraps(fn)
            def wrapper(*args, **kwargs):
                self._probe.begin(name)
                try:
                    return fn(*args, **kwargs)
                finally:
                    self._probe.end(name)

            return wrapper

        return decorator

    def get_samples(self, name: str) -> list[float]:
        """返回某 stage 的所有采样（ms，底层 ns → ms 转换）。

        合并底层 probe 的实测采样与 ``record_sample`` 注入的补偿采样，
        使 IpcCompensationDecorator 注入的 IPC 预期延迟在报告中可见。

        与 run_e2e.py 的 stages 字典（ms 单位）保持一致。
        """
        samples_ns = list(self._probe.get_samples(name))
        samples_ns.extend(self._injected_samples.get(name, []))
        return [ns / 1e6 for ns in samples_ns]

    def record_sample(self, name: str, value_ms: float) -> None:
        """直接注入一个采样值（ms），不经 begin/end 计时。

        用途：``IpcCompensationDecorator`` 在测量真实 PCIe 传输后，用本方法注入
        "补偿后的 IPC 预期延迟"（如 0.5ms），使报告中 ``ipc_transfer_ms`` 反映
        真实 CUDA IPC 的预期延迟而非 WSL2 退化路径的 PCIe 实测值。

        实现细节：用独立的 ``_injected_samples`` dict 存储（ns），与底层 probe
        解耦——无论 C++ Probe 还是 _PyProbe 都可用。``get_samples`` 会合并
        probe 实测采样与注入采样，保证注入值可见。

        Args:
            name: stage 名（如 "ipc_transfer"）。
            value_ms: 待注入的采样值（ms）。
        """
        value_ns = int(round(value_ms * 1e6))
        self._injected_samples.setdefault(name, []).append(value_ns)

    def clear(self) -> None:
        """清空所有采样（含底层 probe 实测与注入补偿采样）。"""
        self._probe.clear()
        self._injected_samples.clear()

    def measure_overhead_ns(self) -> int:
        """测量 begin/end 一次的自身开销（ns）。"""
        return int(self._probe.overhead_ns())

    def backend(self) -> str:
        """返回当前后端名："cpp" 或 "python"。"""
        return self._backend


# ============================================================================
# 全局单例与模块级便利函数
# ============================================================================
# _default_profiler 是模块级单例，stage()/profile() 便利函数委托给它，
# 简化调用方代码（无需显式创建 Profiler 实例）。
_default_profiler = Profiler()


def stage(name: str) -> _StageContext:
    """模块级便利函数：使用默认单例 Profiler 的 stage。

    用法：
        from profiler import stage
        with stage("ft_prefill"):
            ...
    """
    return _default_profiler.stage(name)


def profile(name: str):
    """模块级便利函数：使用默认单例 Profiler 的 profile 装饰器。

    用法：
        from profiler import profile
        @profile("ft_decode")
        def decode(...):
            ...
    """
    return _default_profiler.profile(name)
