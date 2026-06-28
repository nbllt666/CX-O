"""TensorTransport 抽象层：统一 SingleProcessTransport 与 CudaIPCTransport。

设计动机
========
WSL2 确认不支持 CUDA IPC（``cuIpcOpenMemHandle`` 失败，见
``tests/test_ipc_zero_copy.py:_detect_wsl`` 注释），但 WSL2 仍可访问双卡
（cuda:0 / cuda:1）。为在 WSL2 下跑通"跨卡传输"逻辑并评估真实潜力，需要一条
**单进程双卡**传输路径：tensor 在同进程内跨 GPU 拷贝（D2D over PCIe/NVLink），
而非跨进程 CUDA IPC。

本模块提供三层抽象：

1. ``TensorTransport``（ABC）：统一接口契约，与 ``CudaIpcChannel`` /
   ``TokenChannel`` 对齐（``send_tokens`` / ``recv_tokens`` / ``send_pcm`` /
   ``recv_pcm`` / ``send_tensor`` / ``recv_tensor``），调用方无需感知底层。
2. ``SingleProcessTransport``：单进程双卡，用线程安全 mailbox 在同进程的
   sender/receiver 间传递 tensor。``send_tensor`` 时若 src_gpu != dst_gpu 且
   CUDA 可用，做一次 ``tensor.to(f"cuda:{dst_gpu}")`` 跨卡拷贝——这恰好产生
   真实架构中 GPU0→GPU1 的 PCIe 延迟，供 ``IpcCompensationDecorator`` 测量并
   补偿（扣除 PCIe、加 IPC 预期 0.5ms）以评估真实 CUDA IPC 潜力。
3. ``CudaIPCTransport``：薄封装 ``CudaIpcChannel``，原生 Linux 跨进程零拷贝。

切换策略
========
通过环境变量 ``ENABLE_CUDA_IPC`` 控制（``TensorTransportFactory.create``）：

    ENABLE_CUDA_IPC=1  且 原生 Linux + CUDA + 非 WSL  →  CudaIPCTransport
    ENABLE_CUDA_IPC=0 / 未设置 / WSL / Windows         →  SingleProcessTransport

为什么 WSL2 强制走 SingleProcessTransport：
    WSL2 的 GPU-PV 虚拟化层支持 ``cuIpcGetMemHandle`` 但不支持
    ``cuIpcOpenMemHandle``（接收端 ``rebuild_cuda_tensor`` 报
    ``cudaErrorDeviceUninitialized``）。即使用户显式设 ``ENABLE_CUDA_IPC=1``，
    工厂也会在 WSL2 下回退到 SingleProcessTransport 并记录 warning。

为什么保留 ``send_tensor`` / ``recv_tensor``：
    ``CudaIpcChannel`` 已暴露这两个方法（零拷贝传递 GPU tensor）；
    ``SingleProcessTransport`` 同样支持，使抽象层接口完整，便于上层按 tensor
    而非 list/ndarray 传递（避免不必要的 .tolist()/.cpu() 转换）。
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from abc import ABC, abstractmethod
from collections import deque
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)

# torch 可选导入：SingleProcessTransport 的跨卡拷贝需要 torch；无 torch 时退化为
# 纯 host 路径（tensor 不跨卡，仅 mailbox 传递），保证无 CUDA 环境也能跑逻辑。
try:
    import torch
    _TORCH_AVAILABLE = True
except Exception:  # pragma: no cover - torch 缺失属于环境异常
    torch = None  # type: ignore[assignment]
    _TORCH_AVAILABLE = False


# ============================================================================
# 平台检测：复用 test_ipc_zero_copy._detect_wsl 的判定逻辑（不直接 import 测试模块）
# ============================================================================
def _detect_wsl() -> bool:
    """检测当前是否运行在 WSL2 环境。

    WSL2 内核版本字符串含 "microsoft-standard-WSL2"。WSL2 的 GPU-PV 不支持
    cuIpcOpenMemHandle，CUDA IPC 接收端必失败，故 WSL2 强制走 SingleProcessTransport。
    """
    if not sys.platform.startswith("linux"):
        return False
    try:
        with open("/proc/sys/kernel/osrelease", "r") as f:
            osrelease = f.read().lower()
        return "microsoft" in osrelease and "wsl" in osrelease
    except OSError:
        return False


_IS_LINUX = sys.platform.startswith("linux")
_IS_WSL = _detect_wsl()
_CUDA_AVAILABLE = _TORCH_AVAILABLE and _IS_LINUX and torch.cuda.is_available()
# 原生 Linux（非 WSL）+ CUDA 才允许走 CUDA IPC 路径
_CUDA_IPC_CAPABLE = _CUDA_AVAILABLE and not _IS_WSL


# ============================================================================
# 单进程邮箱：线程安全的 deque，按 endpoint 共享
# ============================================================================
class _Mailbox:
    """单进程传输邮箱：线程安全 deque + Condition。

    sender.put() 追加元素并 notify；receiver.get() 阻塞等待元素。
    用于 SingleProcessTransport 在同进程的 sender/receiver 间传递 tensor。

    设计决策：
        - 用 Condition 而非 Queue：需要支持 non-blocking try_get（probe 时避免
          死锁），Condition 的 wait 可设 timeout 且不消费元素即可检查空。
        - mailbox 按 endpoint 共享（模块级 ``_MAILBOXES`` dict），使 sender 与
          receiver 只需约定 endpoint 字符串即可配对，与 ZeroMQ endpoint 语义一致。
    """

    def __init__(self) -> None:
        self._deque: deque[Any] = deque()
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)

    def put(self, item: Any) -> None:
        """追加一个元素并唤醒一个等待的 receiver。"""
        with self._cond:
            self._deque.append(item)
            self._cond.notify()

    def get(self, timeout: Optional[float] = None) -> Any:
        """阻塞等待并取回一个元素。

        Args:
            timeout: 最长等待秒数；None 表示无限等待。

        Returns:
            取回的元素；超时返回 None。
        """
        with self._cond:
            if not self._deque and timeout is not None:
                self._cond.wait(timeout=timeout)
            if not self._deque:
                return None
            return self._deque.popleft()

    def qsize(self) -> int:
        """当前积压元素数（探针/诊断用）。"""
        with self._lock:
            return len(self._deque)


# 模块级 endpoint -> mailbox 映射，使 sender/receiver 用相同 endpoint 配对。
_MAILBOXES: dict[str, _Mailbox] = {}
_MAILBOXES_LOCK = threading.Lock()


def _get_mailbox(endpoint: str) -> _Mailbox:
    """按 endpoint 取（或创建）共享 mailbox。

    同一 endpoint 的 sender 与 receiver 共享同一个 _Mailbox 实例。
    """
    with _MAILBOXES_LOCK:
        if endpoint not in _MAILBOXES:
            _MAILBOXES[endpoint] = _Mailbox()
        return _MAILBOXES[endpoint]


def _drop_mailbox(endpoint: str) -> None:
    """close 时清理已无引用的 mailbox，避免内存泄漏。"""
    with _MAILBOXES_LOCK:
        mb = _MAILBOXES.get(endpoint)
        if mb is not None and mb.qsize() == 0:
            _MAILBOXES.pop(endpoint, None)


# multipart 首帧类型标签，与 zmq_channel / cuda_ipc_channel 保持一致，
# 便于接收端按 tag 分发（SingleProcessTransport 内部用 (tag, payload) 元组）。
_MSG_TYPE_TOKENS = b"tokens"
_MSG_TYPE_PCM_PREFIX = b"pcm:"


# ============================================================================
# TensorTransport 抽象基类
# ============================================================================
class TensorTransport(ABC):
    """统一传输层接口契约。

    所有方法与 ``CudaIpcChannel`` / ``TokenChannel`` 对齐，调用方可按统一接口
    编程，由 ``TensorTransportFactory`` 按环境选择具体实现。

    生命周期：用 context manager（``with``）保证 close 释放资源。
    """

    @abstractmethod
    def send_tokens(self, token_ids: "list[int] | torch.Tensor") -> None:
        """发送 Token ID 数组。"""

    @abstractmethod
    def recv_tokens(self) -> list[int]:
        """接收 Token ID 数组，返回 list[int]。"""

    @abstractmethod
    def send_pcm(self, pcm: "np.ndarray | torch.Tensor") -> None:
        """发送 PCM 音频块（float32 或 int16）。"""

    @abstractmethod
    def recv_pcm(self) -> np.ndarray:
        """接收 PCM 音频块，返回 numpy 数组。"""

    @abstractmethod
    def send_tensor(self, tensor: "torch.Tensor") -> None:
        """零拷贝发送一个 GPU tensor（若底层支持）。"""

    @abstractmethod
    def recv_tensor(self) -> "torch.Tensor":
        """接收并重建 GPU tensor（若底层支持）。"""

    @abstractmethod
    def close(self) -> None:
        """释放底层资源。"""

    def __enter__(self) -> "TensorTransport":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    # ------------------------------------------------------------------
    # 便于诊断的元信息
    # ------------------------------------------------------------------
    @property
    @abstractmethod
    def backend(self) -> str:
        """返回后端名："single_process" / "cuda_ipc"。"""


# ============================================================================
# SingleProcessTransport：单进程双卡传输（WSL2 降级 / 单进程验证路径）
# ============================================================================
class SingleProcessTransport(TensorTransport):
    """单进程双卡传输：用 mailbox 在同进程 sender/receiver 间传递 tensor。

    设计决策：
        1. **跨卡拷贝模拟真实传输延迟**：``send_tensor`` 时若 src_gpu != dst_gpu
           且 CUDA 可用，做一次 ``tensor.to(f"cuda:{dst_gpu}")``。这产生 GPU0→GPU1
           的真实 PCIe 延迟（毫秒级），供 ``IpcCompensationDecorator`` 测量并
           补偿（扣除 PCIe、加 IPC 预期 0.5ms）以评估真实 CUDA IPC 潜力。
        2. **mailbox 按 endpoint 共享**：sender 与 receiver 用相同 endpoint
           字符串即可配对，与 ZeroMQ endpoint 语义一致，调用方代码无需改动。
        3. **线程安全**：mailbox 用 Condition 保证多线程下 put/get 安全；
           单线程同步使用时退化为阻塞 get（直到有元素）。
        4. **无 CUDA 退化**：无 torch 或无 CUDA 时跳过跨卡拷贝，仅做 mailbox
           传递（host tensor / numpy），保证逻辑可跑通，仅损失"PCIe 延迟模拟"。

    Args:
        endpoint: 邮箱标识（任意字符串，sender/receiver 需一致）。
        role: "sender" 或 "receiver"。
        src_gpu: 发送方 GPU（tensor 来源），默认 0。
        dst_gpu: 接收方 GPU（tensor 目标），默认 1。仅当 src != dst 且 CUDA
            可用时才做跨卡拷贝。
        recv_timeout: receiver 阻塞等待超时（秒）；None 表示无限等待。

    Raises:
        ValueError: role 非法。
    """

    def __init__(
        self,
        endpoint: str,
        role: str,
        src_gpu: int = 0,
        dst_gpu: int = 1,
        recv_timeout: Optional[float] = None,
    ) -> None:
        if role not in ("sender", "receiver"):
            raise ValueError(f"role 必须是 'sender' 或 'receiver'，得到: {role!r}")
        self._endpoint = endpoint
        self._role = role
        self._src_gpu = src_gpu
        self._dst_gpu = dst_gpu
        self._recv_timeout = recv_timeout
        self._mailbox = _get_mailbox(endpoint)
        self._closed = False

    # ------------------------------------------------------------------
    # 内部：跨卡拷贝（产生真实 PCIe 延迟）
    # ------------------------------------------------------------------
    def _move_to_dst(self, tensor: "torch.Tensor") -> "torch.Tensor":
        """把 tensor 拷贝到目标 GPU（若 src != dst 且 CUDA 可用）。

        这是"模拟真实跨卡传输"的核心：单进程内做一次 D2D copy（经 PCIe/NVLink），
        产生与真实架构中 GPU0→GPU1 传输等价的延迟。该延迟会被
        ``IpcCompensationDecorator`` 测量并在报告中扣除，加上 IPC 预期 0.5ms。
        """
        if not _CUDA_AVAILABLE:
            # 无 CUDA：不跨卡，仅原地返回（mailbox 传递 host tensor）。
            return tensor
        if self._src_gpu == self._dst_gpu:
            # 同卡无需拷贝。
            return tensor
        target = f"cuda:{self._dst_gpu}"
        # .to() 跨卡拷贝 + .contiguous() 保证后续接收端可直接用。
        return tensor.to(target).contiguous()

    def _device_for_recv(self) -> "torch.device | None":
        """接收端期望的设备（用于把 host 数据搬回 GPU）。"""
        if not _CUDA_AVAILABLE:
            return None
        return torch.device(f"cuda:{self._dst_gpu}")

    # ------------------------------------------------------------------
    # send_tokens / recv_tokens
    # ------------------------------------------------------------------
    def send_tokens(self, token_ids: "list[int] | torch.Tensor") -> None:
        """发送 Token ID 数组。

        输入是 list 时构造 int32 tensor 再跨卡拷贝；输入是 tensor 时直接跨卡拷贝。
        mailbox 传递 (tag, tensor) 元组，接收端按 tag 还原。
        """
        if isinstance(token_ids, torch.Tensor):
            t = token_ids.to(dtype=torch.int32)
        else:
            arr = np.asarray(token_ids, dtype=np.int32)
            t = torch.from_numpy(arr)
        t = self._move_to_dst(t)
        self._mailbox.put((_MSG_TYPE_TOKENS, t))

    def recv_tokens(self) -> list[int]:
        """接收 Token ID 数组，返回 list[int]。

        从 mailbox 取出 tensor，做一次 device→host 拷贝（.cpu()）后 .tolist()，
        与 ``CudaIpcChannel.recv_tokens`` 接口一致。
        """
        tag, t = self._mailbox.get(timeout=self._recv_timeout)
        if tag != _MSG_TYPE_TOKENS:
            raise ValueError(f"期望 tokens 消息，收到类型标签: {tag!r}")
        return t.cpu().tolist()

    # ------------------------------------------------------------------
    # send_pcm / recv_pcm
    # ------------------------------------------------------------------
    def send_pcm(self, pcm: "np.ndarray | torch.Tensor") -> None:
        """发送 PCM 音频块（float32 或 int16）。"""
        if isinstance(pcm, torch.Tensor):
            t = pcm
            if t.dtype not in (torch.float32, torch.int16):
                t = t.to(dtype=torch.float32)
        else:
            arr = np.asarray(pcm)
            if arr.dtype != np.float32 and arr.dtype != np.int16:
                arr = arr.astype(np.float32)
            t = torch.from_numpy(arr)
        t = self._move_to_dst(t)
        tag = _MSG_TYPE_PCM_PREFIX + str(t.dtype).replace("torch.", "").encode("ascii")
        self._mailbox.put((tag, t))

    def recv_pcm(self) -> np.ndarray:
        """接收 PCM 音频块，返回 numpy 数组。"""
        tag, t = self._mailbox.get(timeout=self._recv_timeout)
        if not tag.startswith(_MSG_TYPE_PCM_PREFIX):
            raise ValueError(f"期望 pcm 消息，收到类型标签: {tag!r}")
        return t.cpu().numpy()

    # ------------------------------------------------------------------
    # send_tensor / recv_tensor（零拷贝语义：同进程内传递 tensor 引用）
    # ------------------------------------------------------------------
    def send_tensor(self, tensor: "torch.Tensor") -> None:
        """发送一个 tensor（跨卡拷贝到 dst_gpu 后放入 mailbox）。"""
        t = self._move_to_dst(tensor)
        self._mailbox.put((b"tensor", t))

    def recv_tensor(self) -> "torch.Tensor":
        """接收一个 tensor（从 mailbox 取出，已位于 dst_gpu）。"""
        tag, t = self._mailbox.get(timeout=self._recv_timeout)
        if tag != b"tensor":
            raise ValueError(f"期望 tensor 消息，收到类型标签: {tag!r}")
        return t

    # ------------------------------------------------------------------
    # 资源释放
    # ------------------------------------------------------------------
    def close(self) -> None:
        """关闭：清理空 mailbox。mailbox 本身是进程级共享资源，不强制清空数据。"""
        if self._closed:
            return
        self._closed = True
        # 仅在无积压时清理 mailbox 映射，避免影响仍在使用的对端。
        _drop_mailbox(self._endpoint)

    @property
    def backend(self) -> str:
        return "single_process"

    @property
    def src_gpu(self) -> int:
        return self._src_gpu

    @property
    def dst_gpu(self) -> int:
        return self._dst_gpu


# ============================================================================
# CudaIPCTransport：薄封装 CudaIpcChannel（原生 Linux 跨进程零拷贝）
# ============================================================================
class CudaIPCTransport(TensorTransport):
    """CUDA IPC 零拷贝传输：薄封装 ``CudaIpcChannel``。

    仅在原生 Linux + CUDA + 非 WSL 环境可用（实例化即校验）。
    所有方法委托给内部 ``CudaIpcChannel`` 实例，接口语义完全一致。

    Args:
        endpoint: ZeroMQ 端点（Linux 通常用 UDS）。
        role: "sender" 或 "receiver"。
        gpu_id: 目标 GPU 设备号。
    """

    def __init__(self, endpoint: str, role: str, gpu_id: int = 1) -> None:
        # 延迟导入避免循环依赖（cuda_ipc_channel 不 import 本模块）。
        from .cuda_ipc_channel import CudaIpcChannel

        self._channel = CudaIpcChannel(endpoint, role, gpu_id=gpu_id)

    def send_tokens(self, token_ids: "list[int] | torch.Tensor") -> None:
        self._channel.send_tokens(token_ids)

    def recv_tokens(self) -> list[int]:
        return self._channel.recv_tokens()

    def send_pcm(self, pcm: "np.ndarray | torch.Tensor") -> None:
        self._channel.send_pcm(pcm)

    def recv_pcm(self) -> np.ndarray:
        return self._channel.recv_pcm()

    def send_tensor(self, tensor: "torch.Tensor") -> None:
        self._channel.send_tensor(tensor)

    def recv_tensor(self) -> "torch.Tensor":
        return self._channel.recv_tensor()

    def close(self) -> None:
        self._channel.close()

    @property
    def backend(self) -> str:
        return "cuda_ipc"

    @property
    def channel(self) -> Any:
        """暴露底层 CudaIpcChannel（供需要原始句柄的场景使用）。"""
        return self._channel


# ============================================================================
# TensorTransportFactory：按环境变量与平台能力选择后端
# ============================================================================
class TensorTransportFactory:
    """按 ``ENABLE_CUDA_IPC`` 环境变量与平台能力选择 TensorTransport 后端。

    选择逻辑（优先级从高到低）：
        1. ``ENABLE_CUDA_IPC=1`` 且 原生 Linux + CUDA + 非 WSL
           → ``CudaIPCTransport``（跨进程 CUDA IPC 零拷贝）
        2. ``ENABLE_CUDA_IPC=1`` 但在 WSL2 / Windows / 无 CUDA
           → ``SingleProcessTransport``（记录 warning，回退单进程双卡）
        3. ``ENABLE_CUDA_IPC=0`` 或未设置
           → ``SingleProcessTransport``（显式选择单进程路径）

    Args:
        endpoint: 端点标识（CUDA IPC 用 ZeroMQ endpoint；单进程用 mailbox key）。
        role: "sender" 或 "receiver"。
        gpu_id / src_gpu: 发送方 GPU（CudaIPCTransport 用 gpu_id；SingleProcessTransport
            用 src_gpu，默认 0）。
        dst_gpu: 接收方 GPU（仅 SingleProcessTransport，默认 1）。
        prefer_cuda_ipc: 是否优先尝试 CUDA IPC（默认 True，等价于 ENABLE_CUDA_IPC=1
            的环境变量；显式 False 则强制单进程）。

    Returns:
        TensorTransport 实例。
    """

    @staticmethod
    def create(
        endpoint: str,
        role: str,
        gpu_id: int = 1,
        src_gpu: int = 0,
        dst_gpu: int = 1,
        prefer_cuda_ipc: bool = True,
    ) -> TensorTransport:
        """按环境变量与平台能力创建 TensorTransport 实例。"""
        env_flag = os.environ.get("ENABLE_CUDA_IPC", "").strip()
        env_force_cuda_ipc = env_flag in ("1", "true", "True", "TRUE", "yes", "on")
        env_force_single = env_flag in ("0", "false", "False", "FALSE", "no", "off")

        # 显式关闭 CUDA IPC → 直接单进程
        if env_force_single:
            return SingleProcessTransport(endpoint, role, src_gpu, dst_gpu)

        # prefer_cuda_ipc=True 或 ENABLE_CUDA_IPC=1：尝试 CUDA IPC
        want_cuda_ipc = prefer_cuda_ipc or env_force_cuda_ipc
        if want_cuda_ipc and _CUDA_IPC_CAPABLE:
            try:
                return CudaIPCTransport(endpoint, role, gpu_id=gpu_id)
            except RuntimeError as exc:
                # CUDA IPC 实例化失败（gpu_id 越界等）：回退单进程并记录 warning。
                logger.warning(
                    "CudaIPCTransport 实例化失败，回退到 SingleProcessTransport。原因: %s",
                    exc,
                )
            except Exception as exc:  # pragma: no cover - 兜底
                logger.warning(
                    "CudaIPCTransport 非预期异常 %r，回退到 SingleProcessTransport。",
                    exc,
                    exc_info=True,
                )

        # 用户要求 CUDA IPC 但平台不支持（WSL2 / Windows / 无 CUDA）：记录 warning
        if env_force_cuda_ipc and not _CUDA_IPC_CAPABLE:
            if _IS_WSL:
                reason = "WSL2 GPU-PV 不支持 cuIpcOpenMemHandle"
            elif not _CUDA_AVAILABLE:
                reason = "当前环境无 CUDA 或非 Linux"
            else:
                reason = "平台不支持 CUDA IPC"
            logger.warning(
                "ENABLE_CUDA_IPC=1 但 %s，回退到 SingleProcessTransport。",
                reason,
            )

        return SingleProcessTransport(endpoint, role, src_gpu, dst_gpu)
