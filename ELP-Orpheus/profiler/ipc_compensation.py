"""IPC 延迟补偿 Decorator：WSL2 退化路径下评估真实 CUDA IPC 潜力。

设计动机
========
WSL2 不支持 CUDA IPC，``SingleProcessTransport`` 用跨卡 D2D 拷贝（tensor.to()
经 PCIe）模拟传输。这产生真实架构中不存在的 PCIe 延迟（毫秒级），若直接计入
``ipc_transfer_ms`` 会严重高估真实 CUDA IPC 的延迟（~0.5ms）。

本 Decorator 包装 ``TensorTransport``，在 Profile 时：
    1. 精确测量实际传输时间（含 PCIe 拷贝）→ 记录到 ``ipc_pcie_ms``
    2. 注入 IPC 预期延迟（默认 0.5ms）→ 记录到 ``ipc_transfer_ms``

报告中两个 stage 并存：
    - ``ipc_pcie_ms``：WSL2 退化路径实测（PCIe 拷贝，毫秒级）
    - ``ipc_transfer_ms``：真实 CUDA IPC 预期（~0.5ms，用于 TTFA 预估）

TTFA 预估时用 ``ipc_transfer_ms``（0.5ms）而非 ``ipc_pcie_ms``，从而"扣除
PCIe 传输时间，加上 IPC 预期时间"，得到真实 Linux + CUDA IPC 环境的潜力评估。

测量精度
========
- **CUDA 环境**：用 ``torch.cuda.Event(enable_timing=True)`` 测量，精度达微秒
  级，能准确捕获 PCIe 拷贝的毫秒级延迟。需 ``torch.cuda.synchronize()`` 同步，
  会阻塞流水线，故仅在 ``measure=True``（Profile 模式）时启用。
- **无 CUDA 环境**：回退 ``time.perf_counter_ns()``，精度 ~200ns，足够 host 路径。

使用模式
========
    # Profile 模式（测量 + 补偿）
    transport = TensorTransportFactory.create("ipc:///x", "sender")
    wrapped = IpcCompensationDecorator(
        transport, ipc_expected_ms=0.5, profiler=_default_profiler, measure=True
    )
    wrapped.send_tokens(tokens)  # 测 PCIe + 注入 0.5ms

    # 生产模式（直通，零开销）
    prod = IpcCompensationDecorator(transport, measure=False)
    prod.send_tokens(tokens)  # 直接调用，不计时

预期 IPC 延迟 0.5ms 的来源：
    CUDA IPC 的实际开销 = ZeroMQ 小消息（handle bytes，几十字节，微秒级）+
    cuIpcOpenMemHandle 映射（微秒级，仅在首次）+ 引用计数同步（微秒级）。
    实测跨进程 CUDA IPC 单次往返在 0.3-0.8ms（含 ZeroMQ 握手），取 0.5ms
    作为保守估计，与瓶颈 C 修复目标（3-5ms → 微秒级）一致。
"""

from __future__ import annotations

import time
from typing import Any

import numpy as np

try:
    import torch
    _TORCH_AVAILABLE = True
except Exception:  # pragma: no cover - torch 缺失属于环境异常
    torch = None  # type: ignore[assignment]
    _TORCH_AVAILABLE = False

# 延迟导入 TensorTransport：避免循环依赖（ipc 模块不 import profiler）。
# 此处仅用于类型注解与 isinstance 检查，运行时按鸭子类型调用方法。


class IpcCompensationDecorator:
    """包装 TensorTransport，在 Profile 时扣除 PCIe、注入 IPC 预期延迟。

    本类实现与 ``TensorTransport`` 相同的方法集（send_tokens / recv_tokens /
    send_pcm / recv_pcm / send_tensor / recv_tensor / close），可直接替换原
    transport 注入调用方，无需改动调用方代码。

    设计决策：
        1. **测量可控**：``measure=True`` 时用 CUDA Event 精确计时（含
           ``cuda.synchronize()`` 同步开销，仅 Profile 用）；``measure=False``
           时直通原 transport，零开销（生产用）。
        2. **双 stage 记录**：``ipc_pcie_ms`` 记实测，``ipc_transfer_ms`` 记
           补偿值（0.5ms）。TTFA 预估用后者，PCIe 分析用前者。
        3. **CUDA Event 优先**：跨卡拷贝是 GPU 操作，perf_counter 受 Python
           GIL 与调度抖动影响；CUDA Event 直接测 GPU 时间，精度更高。
        4. **profiler 可选**：``profiler=None`` 时不记录任何采样，Decorator
           退化为透明代理（便于在不接 Profiler 的场景复用）。

    Args:
        transport: 被包装的 ``TensorTransport`` 实例。
        ipc_expected_ms: 真实 CUDA IPC 的预期延迟（ms，默认 0.5）。
        profiler: ``Profiler`` 实例（None 时不记录采样）。
        measure: 是否开启测量（True=Profile 模式，False=生产直通）。
        stage_pcie: PCIe 实测 stage 名（默认 "ipc_pcie_ms"）。
        stage_ipc: IPC 预期 stage 名（默认 "ipc_transfer_ms"）。
    """

    def __init__(
        self,
        transport: Any,
        ipc_expected_ms: float = 0.5,
        profiler: Any = None,
        measure: bool = True,
        stage_pcie: str = "ipc_pcie_ms",
        stage_ipc: str = "ipc_transfer_ms",
    ) -> None:
        self._transport = transport
        self._ipc_expected_ms = float(ipc_expected_ms)
        self._profiler = profiler
        self._measure = bool(measure)
        self._stage_pcie = stage_pcie
        self._stage_ipc = stage_ipc
        self._use_cuda_event = (
            _TORCH_AVAILABLE and torch.cuda.is_available() and self._measure
        )

    # ------------------------------------------------------------------
    # 内部：测量 + 补偿
    # ------------------------------------------------------------------
    def _measure_and_record(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        """调用 fn，测量耗时并注入补偿采样。

        - ``measure=True``：用 CUDA Event / perf_counter 精确计时，记录两个 stage。
        - ``measure=False``：直接调用，零开销。
        """
        if not self._measure or self._profiler is None:
            # 生产直通或无 profiler：不计时，直接调用。
            return fn(*args, **kwargs)

        if self._use_cuda_event:
            # CUDA Event 精确计时（微秒级，跨卡拷贝为 GPU 操作必用此路径）。
            start = torch.cuda.Event(enable_timing=True)
            end = torch.cuda.Event(enable_timing=True)
            start.record()
            result = fn(*args, **kwargs)
            end.record()
            # synchronize 阻塞至 GPU 完成，确保 end.elapsed_time 准确。
            # 这会引入流水线停顿，故仅 measure=True 时启用。
            torch.cuda.synchronize()
            elapsed_ms = start.elapsed_time(end)
        else:
            # 无 CUDA：perf_counter 计时（host 路径，精度 ~200ns）。
            t0 = time.perf_counter_ns()
            result = fn(*args, **kwargs)
            elapsed_ms = (time.perf_counter_ns() - t0) / 1e6

        # 记录实测 PCIe 延迟 + 注入 IPC 预期延迟。
        self._profiler.record_sample(self._stage_pcie, elapsed_ms)
        self._profiler.record_sample(self._stage_ipc, self._ipc_expected_ms)
        return result

    # ------------------------------------------------------------------
    # TensorTransport 接口委托（带测量 + 补偿）
    # ------------------------------------------------------------------
    def send_tokens(self, token_ids: Any) -> None:
        self._measure_and_record(self._transport.send_tokens, token_ids)

    def recv_tokens(self) -> list[int]:
        return self._measure_and_record(self._transport.recv_tokens)

    def send_pcm(self, pcm: Any) -> None:
        self._measure_and_record(self._transport.send_pcm, pcm)

    def recv_pcm(self) -> np.ndarray:
        return self._measure_and_record(self._transport.recv_pcm)

    def send_tensor(self, tensor: Any) -> None:
        self._measure_and_record(self._transport.send_tensor, tensor)

    def recv_tensor(self) -> Any:
        return self._measure_and_record(self._transport.recv_tensor)

    def close(self) -> None:
        self._transport.close()

    def __enter__(self) -> "IpcCompensationDecorator":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # 诊断元信息
    # ------------------------------------------------------------------
    @property
    def backend(self) -> str:
        """底层 transport 的 backend 名（透传）。"""
        return getattr(self._transport, "backend", "unknown")

    @property
    def measure(self) -> bool:
        """是否开启测量模式。"""
        return self._measure

    @property
    def ipc_expected_ms(self) -> float:
        """真实 CUDA IPC 的预期延迟（ms）。"""
        return self._ipc_expected_ms

    @property
    def stage_pcie(self) -> str:
        """PCIe 实测 stage 名。"""
        return self._stage_pcie

    @property
    def stage_ipc(self) -> str:
        """IPC 预期 stage 名。"""
        return self._stage_ipc

    @property
    def transport(self) -> Any:
        """被包装的底层 transport（供需要原始句柄的场景使用）。"""
        return self._transport


def make_profiled_transport(
    endpoint: str,
    role: str,
    profiler: Any,
    ipc_expected_ms: float = 0.5,
    measure: bool = True,
    **kwargs: Any,
) -> IpcCompensationDecorator:
    """便捷工厂：创建 transport + 包裹补偿 Decorator。

    用法：
        from profiler.ipc_compensation import make_profiled_transport
        wrapped = make_profiled_transport(
            "ipc:///tmp/x", "sender", profiler=_default_profiler, measure=True
        )
        wrapped.send_tokens(tokens)

    Args:
        endpoint: 传给 TensorTransportFactory.create。
        role: "sender" / "receiver"。
        profiler: Profiler 实例。
        ipc_expected_ms: 真实 CUDA IPC 预期延迟（默认 0.5ms）。
        measure: 是否测量（True=Profile，False=生产直通）。
        **kwargs: 透传给 TensorTransportFactory.create（gpu_id/src_gpu/dst_gpu 等）。

    Returns:
        包裹了 IpcCompensationDecorator 的 transport。
    """
    # 延迟导入避免循环依赖（tensor_transport 不 import profiler）。
    from ipc.tensor_transport import TensorTransportFactory

    transport = TensorTransportFactory.create(endpoint, role, **kwargs)
    return IpcCompensationDecorator(
        transport,
        ipc_expected_ms=ipc_expected_ms,
        profiler=profiler,
        measure=measure,
    )
