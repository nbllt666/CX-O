"""IPC 通道工厂：按运行环境自动选择 ZeroMQ 零拷贝 或 CUDA IPC 零拷贝。

设计决策
========

1. **为什么需要工厂**：
   `CudaIpcChannel` 仅在 Linux + CUDA 且发送/接收方同机时可用；其他场景
   （Windows 开发机、无 GPU 的部署机、跨节点部署）必须回退到 `TokenChannel`
   零拷贝路径。调用方不应散落 `if/else` 平台判断，统一交给工厂决策。

2. **回退策略**：
   - `prefer_cuda_ipc=True`（默认）：先尝试 `CudaIpcChannel`，实例化抛
     `RuntimeError` 则记录 warning 并回退到 `TokenChannel`（已启用零拷贝）。
   - `prefer_cuda_ipc=False`：直接返回 `TokenChannel`。
   - 工厂永不静默失败：`CudaIpcChannel` 异常一定记录 warning，便于排查。

3. **零拷贝保证**：
   无论走哪条路径，发送端都用 `copy=False`：
     - ZeroMQ 路径：`send_multipart([tag, arr], copy=False)` 跳过 tobytes() 拷贝
     - CUDA IPC 路径：GPU 显存直接共享，数据不离开 GPU
   两条路径的 `send_tokens` / `recv_tokens` / `send_pcm` / `recv_pcm` 接口
   完全一致，调用方无需感知底层差异。
"""

from __future__ import annotations

import sys
import logging
from typing import Any

from .zmq_channel import TokenChannel
from .cuda_ipc_channel import CudaIpcChannel

logger = logging.getLogger(__name__)


class ChannelFactory:
    """按平台/CUDA 可用性自动选择 IPC 通道的工厂类。

    所有方法均为静态方法，无需实例化。选择逻辑封装在此，调用方只需：

        channel = ChannelFactory.create_token_channel(endpoint, "sender")

    即可拿到适合当前环境的零拷贝通道实例。
    """

    @staticmethod
    def create_token_channel(
        endpoint: str,
        role: str,
        gpu_id: int = 1,
        prefer_cuda_ipc: bool = True,
        context: "Any | None" = None,
    ) -> "TokenChannel | CudaIpcChannel":
        """创建 Token 通道，自动选择 ZeroMQ 或 CUDA IPC。

        选择逻辑（优先级从高到低）：
            1. 若 `prefer_cuda_ipc=False` → 直接返回 `TokenChannel`（零拷贝）
            2. 若 `prefer_cuda_ipc=True` 且 Linux + CUDA 可用 → 尝试
               `CudaIpcChannel`；实例化失败则回退 `TokenChannel`
            3. 其他平台（Windows 等）→ `TokenChannel`（零拷贝）

        Args:
            endpoint: ZeroMQ 端点。
            role: "sender" 或 "receiver"。
            gpu_id: 目标 GPU 设备号（仅 CUDA IPC 路径使用）。
            prefer_cuda_ipc: 是否优先尝试 CUDA IPC 路径，默认 True。
            context: 可选的共享 zmq.Context（仅 ZeroMQ 路径使用）。

        Returns:
            通道实例：`CudaIpcChannel`（Linux+CUDA）或 `TokenChannel`（其他）。
        """
        if not prefer_cuda_ipc:
            return TokenChannel(endpoint, role, context=context)

        # 尝试 CUDA IPC：仅在 Linux + CUDA 可用时才有意义
        # Windows 即使 CUDA 可用也不支持 cuIpcMemHandle，CudaIpcChannel 会抛 RuntimeError
        if sys.platform.startswith("linux"):
            try:
                return CudaIpcChannel(endpoint, role, gpu_id=gpu_id)
            except RuntimeError as exc:
                # 平台/CUDA 不满足或 gpu_id 越界：记录 warning 并回退
                logger.warning(
                    "CudaIpcChannel 实例化失败，回退到 TokenChannel 零拷贝路径。"
                    "原因: %s",
                    exc,
                )
            except Exception as exc:  # pragma: no cover - 兜底，避免未知异常炸工厂
                logger.warning(
                    "CudaIpcChannel 实例化时发生非预期异常 %r，回退到 TokenChannel。",
                    exc,
                    exc_info=True,
                )

        # 非 Linux 或 CUDA IPC 不可用：ZeroMQ 零拷贝路径兜底
        return TokenChannel(endpoint, role, context=context)

    @staticmethod
    def create(
        endpoint: str,
        role: str,
        channel_type: str = "auto",
        **kwargs: Any,
    ) -> "TokenChannel | CudaIpcChannel":
        """通用工厂方法，按显式指定的 channel_type 创建通道。

        Args:
            endpoint: ZeroMQ 端点。
            role: "sender" 或 "receiver"。
            channel_type:
                - "auto"（默认）：自动选择，等价于 `create_token_channel`
                  with `prefer_cuda_ipc=True`
                - "zmq"：强制使用 `TokenChannel`（ZeroMQ 零拷贝）
                - "cuda_ipc"：强制使用 `CudaIpcChannel`；不可用时抛 RuntimeError
            **kwargs: 透传给具体通道：
                - gpu_id（CUDA IPC 路径）
                - context（ZeroMQ 路径，可选）
                - prefer_cuda_ipc（auto 路径，可选）

        Returns:
            通道实例。

        Raises:
            RuntimeError: channel_type="cuda_ipc" 且环境不满足时。
            ValueError: channel_type 非法。
        """
        if channel_type == "zmq":
            # 显式 ZeroMQ：剥离 cuda 专属 kwargs
            context = kwargs.get("context")
            return TokenChannel(endpoint, role, context=context)

        if channel_type == "cuda_ipc":
            # 显式 CUDA IPC：不回退，环境不满足时直接抛错（让调用方明确知道）
            gpu_id = kwargs.get("gpu_id", 1)
            return CudaIpcChannel(endpoint, role, gpu_id=gpu_id)

        if channel_type == "auto":
            prefer_cuda_ipc = kwargs.get("prefer_cuda_ipc", True)
            gpu_id = kwargs.get("gpu_id", 1)
            context = kwargs.get("context")
            return ChannelFactory.create_token_channel(
                endpoint,
                role,
                gpu_id=gpu_id,
                prefer_cuda_ipc=prefer_cuda_ipc,
                context=context,
            )

        raise ValueError(
            f"channel_type 必须是 'auto' / 'zmq' / 'cuda_ipc'，得到: {channel_type!r}"
        )
