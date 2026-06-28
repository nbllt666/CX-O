"""ELP-Orpheus C++/Python 混合 Profiler 框架（Task 6）。

公共 API：
    Profiler        — 高级 Profiler（封装 C++ Probe 或 _PyProbe 回退）
    Probe           — 底层探针类（C++ probe_cpp.Probe 或 _PyProbe）
    profile         — 装饰器（默认单例）
    stage           — context manager（默认单例）
    Report          — 统一报告生成器（北极星指标 + stats/table/json）
    VramSampler     — 显存与碎片率采样器
    ConcurrentRunner — 并发流负载测试器
    IpcCompensationDecorator — IPC 延迟补偿 Decorator（WSL2 退化路径下评估真实 CUDA IPC 潜力）
    make_profiled_transport  — 便捷工厂：创建 transport + 包裹补偿 Decorator

后端切换：
    - C++ probe_cpp 编译可用时，Profiler.backend() == "cpp"（< 100ns 探针）。
    - 编译不可用时自动回退 _PyProbe（time.perf_counter_ns），backend() == "python"。
    - CUDA：probe.cpp 用 #ifdef HAVE_CUDA 包裹，无 CUDA 时 cuda_event_* 回退 steady_clock。

用法：
    from profiler import stage, Report, VramSampler

    with stage("ft_prefill"):
        ...  # 被计时代码

    report = Report()
    report.add_stage_samples("ft_decode", [0.8, 0.9, 1.1])
    print(report.to_table())
"""

from .profiler import Profiler, Probe, profile, stage, _PyProbe, _default_profiler
from .report import Report
from .vram_sampler import VramSampler
from .concurrent_runner import ConcurrentRunner
from .ipc_compensation import IpcCompensationDecorator, make_profiled_transport

__all__ = [
    "Profiler",
    "Probe",
    "profile",
    "stage",
    "Report",
    "VramSampler",
    "ConcurrentRunner",
    "IpcCompensationDecorator",
    "make_profiled_transport",
]
