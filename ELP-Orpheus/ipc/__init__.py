"""ELP-Orpheus IPC 通信层。

提供基于 ZeroMQ 的极简进程间通信，用于双卡物理隔离架构中 Token ID 数组与 PCM
音频块在 CPU 调度器与 GPU TTS 引擎之间的高效传递（单条消息 < 1ms）。

Task 5 新增两条零拷贝路径（修复瓶颈 C）：
    1. ZeroMQ 零拷贝（`TokenChannel`）：`send_multipart(copy=False)` 跳过
       tobytes() 的堆拷贝，跨平台可用。
    2. CUDA IPC 零拷贝（`CudaIpcChannel`）：Linux + CUDA 下发送/接收方共享
       GPU 显存，数据不离开 GPU，延迟最低。
`ChannelFactory` 按运行环境自动选择，调用方无需感知平台差异。

TensorTransport 抽象层（WSL2 降级 / 单进程双卡验证）：
    `TensorTransport` 统一 ``SingleProcessTransport``（单进程双卡，WSL2 降级）
    与 ``CudaIPCTransport``（原生 Linux 跨进程 CUDA IPC）。通过环境变量
    ``ENABLE_CUDA_IPC`` 切换，``TensorTransportFactory.create`` 按平台能力
    自动选择后端。WSL2 下强制走 SingleProcessTransport（GPU-PV 不支持
    cuIpcOpenMemHandle），配合 ``profiler.IpcCompensationDecorator`` 测量
    PCIe 传输并补偿 IPC 预期延迟（0.5ms）以评估真实潜力。
"""

from .zmq_channel import TokenChannel
from .cuda_ipc_channel import CudaIpcChannel
from .channel_factory import ChannelFactory
from .tensor_transport import (
    TensorTransport,
    SingleProcessTransport,
    CudaIPCTransport,
    TensorTransportFactory,
)

__all__ = [
    "TokenChannel",
    "CudaIpcChannel",
    "ChannelFactory",
    "TensorTransport",
    "SingleProcessTransport",
    "CudaIPCTransport",
    "TensorTransportFactory",
]
