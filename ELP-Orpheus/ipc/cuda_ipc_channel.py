"""CUDA IPC 零拷贝通道（Linux + CUDA 专用）。

设计决策
========

1. **为什么需要 CUDA IPC**：
   原有 `TokenChannel` 用 ZeroMQ 传递 `np.asarray(...).tobytes()`，每个 Chunk 至少
   2 次堆拷贝 + 1 次 Python list 转换，延迟 3-5ms（瓶颈 C）。当调度器与 TTS 引擎
   在同一台物理机的不同进程中，两者可共享同一块 GPU 显存——CUDA IPC 让接收方
   直接映射发送方的 GPU 显存指针，完全跳过 host 端序列化与跨进程字节搬运，
   延迟降至微秒级。

2. **为什么仅 Linux 可用**：
   CUDA IPC 依赖 OS 层面的进程间共享内存机制（cuIpcMemHandle），Windows 的 WDDM
   驱动模型不暴露此能力。本类在非 Linux 平台实例化即抛 `RuntimeError`，调用方
   （`ChannelFactory`）应捕获并回退到 ZeroMQ 零拷贝路径。

3. **为什么用 PyTorch 高层封装而非裸 CUDA driver API**：
   直接调 `cuIpcGetMemHandle` / `cuIpcOpenMemHandle` 需要手写 C 扩展、绑定上下文、
   维护引用计数，错误处理复杂且版本相关性强。PyTorch 的 `torch.Tensor._typed_storage()
   ._share_cuda_()` 已封装好上述细节，并通过 `torch.multiprocessing.reductions
   .rebuild_cuda_tensor` 提供对称的接收端重建逻辑，引用计数与 event 同步均由
   PyTorch 内部处理。

4. **传输什么**：
   - 实际数据（GPU tensor 的全部字节）**完全不离开显存**，零拷贝。
   - 通过 ZeroMQ 传输的只有 "handle bytes" + tensor 元信息（shape/dtype/offset
     等几十字节小消息）。ZeroMQ 的小消息延迟本就在微秒级，不构成瓶颈。

5. **强引用持有**：
   发送方必须持有 GPU tensor 的强引用直到接收方完成 `rebuild_cuda_tensor`，
   否则 CUDA caching allocator 可能回收该显存块导致接收端读到脏数据。本类用
   `_tensor_refs` 列表保留引用，并在 close 时统一释放。

约束
====
- 发送方与接收方必须在同一台机器（不能跨节点），且 CUDA context 兼容
  （相同 major/minor 计算能力，且 `CUDA_VISIBLE_DEVICES` 配置允许互相访问）。
- Windows 不支持 CUDA IPC，本类实例化即抛 `RuntimeError`。
"""

from __future__ import annotations

import sys
import json
import struct
import logging
from typing import Any

import zmq
import numpy as np

logger = logging.getLogger(__name__)

# 必须在导入 torch 前声明；torch 在 Windows 上导入开销较大，但 CUDA IPC 路径必用
try:
    import torch
    from torch.multiprocessing.reductions import rebuild_cuda_tensor
    _TORCH_AVAILABLE = True
except Exception:  # pragma: no cover - torch 缺失属于环境异常
    torch = None  # type: ignore[assignment]
    rebuild_cuda_tensor = None  # type: ignore[assignment]
    _TORCH_AVAILABLE = False


# multipart 首帧类型标签，与 zmq_channel 保持一致，便于接收端按 tag 分发。
_MSG_TYPE_TOKENS = b"tokens"
_MSG_TYPE_PCM_PREFIX = b"pcm:"

# IPC handle 元信息帧的标签，用于区分 "CUDA IPC handle 元数据" 与裸 ZMQ 字节流。
# 当通道两端均在 Linux + CUDA 环境时走 handle 路径，否则不应出现该标签。
_MSG_TYPE_CUDA_IPC = b"cuda_ipc"


class CudaIpcChannel:
    """基于 PyTorch CUDA IPC + ZeroMQ 的零拷贝 Token / PCM 通道。

    通信模式：PUSH/PULL 单向流式（与 `TokenChannel` 一致）。
        - role="sender"   → PUSH socket，CONNECT 到 endpoint
        - role="receiver" → PULL socket，BIND 到 endpoint

    消息格式（multipart，3 帧）：
        frame[0] = 类型标签  b"tokens" / b"pcm:<f4" / b"cuda_ipc"
        frame[1] = IPC handle 的元信息 JSON（shape/dtype/offset/handle 长度等）
        frame[2] = IPC handle 的原始字节（几十字节，由 `_share_cuda_()` 返回）

    接收端用 `torch.multiprocessing.reductions.rebuild_cuda_tensor` 重建 tensor，
    重建得到的 tensor 直接映射发送方的 GPU 显存，零拷贝访问。

    Args:
        endpoint: ZeroMQ 端点（Linux 通常用 UDS，如 "ipc:///tmp/orpheus-cuda.sock"）。
        role: "sender" 或 "receiver"。
        gpu_id: 目标 GPU 设备号，发送方将 tensor 移到该设备后共享。

    Raises:
        RuntimeError: 非 Linux 平台 或 CUDA 不可用 或 torch 未安装。
        ValueError: role 非法。
    """

    def __init__(self, endpoint: str, role: str, gpu_id: int = 1) -> None:
        # ------------------------------------------------------------------
        # 平台与依赖检测：Windows / 无 CUDA / 无 torch 都必须显式失败
        # ------------------------------------------------------------------
        if not _TORCH_AVAILABLE:
            raise RuntimeError(
                "CudaIpcChannel 需要 torch，但当前环境导入失败。请使用 TokenChannel。"
            )
        if not sys.platform.startswith("linux"):
            # 关键：Windows 下 WDDM 不支持 cuIpcMemHandle，必须显式抛错而非静默降级
            raise RuntimeError(
                f"CudaIpcChannel 仅支持 Linux（CUDA IPC 依赖 cuIpcMemHandle 共享显存），"
                f"当前平台 {sys.platform!r} 不支持。请改用 TokenChannel 零拷贝路径。"
            )
        if not torch.cuda.is_available():
            raise RuntimeError(
                "CudaIpcChannel 需要 CUDA 设备，但 torch.cuda.is_available() 为 False。"
            )
        if role not in ("sender", "receiver"):
            raise ValueError(f"role 必须是 'sender' 或 'receiver'，得到: {role!r}")
        if gpu_id < 0 or gpu_id >= torch.cuda.device_count():
            raise RuntimeError(
                f"gpu_id={gpu_id} 越界，当前可见 GPU 数量: {torch.cuda.device_count()}"
            )

        self._endpoint = endpoint
        self._role = role
        self._gpu_id = gpu_id
        self._owns_context = True
        self._context = zmq.Context()

        if role == "sender":
            self._socket = self._context.socket(zmq.PUSH)
            self._socket.connect(endpoint)
        else:
            self._socket = self._context.socket(zmq.PULL)
            self._socket.bind(endpoint)
        # linger=0：close() 立即返回，避免阻塞流式关停
        self._socket.setsockopt(zmq.LINGER, 0)

        # 发送方持有 tensor 强引用，防止 caching allocator 在接收端 rebuild 前
        # 回收显存。close() 时清空此列表，触发显存释放。
        self._tensor_refs: list[Any] = []

    # ------------------------------------------------------------------
    # 底层：CUDA tensor 的零拷贝发送/接收
    # ------------------------------------------------------------------
    def send_tensor(self, tensor: "torch.Tensor") -> None:
        """零拷贝发送一个 GPU tensor。

        实现：调用 `tensor._typed_storage()._share_cuda_()` 取得 IPC handle 与元
        信息，通过 ZeroMQ 发送 handle bytes（几十字节），实际数据驻留发送方 GPU
        显存。接收方重建后映射同一块显存。

        Args:
            tensor: 待发送的 tensor，自动移到 self._gpu_id 设备并 contiguous。
        """
        # 确保在目标 GPU 上且连续，否则 _share_cuda_ 可能返回非整块的子视图
        tensor = tensor.to(device=f"cuda:{self._gpu_id}").contiguous()
        storage = tensor._typed_storage()
        (
            device,
            handle,
            storage_size_bytes,
            storage_offset_bytes,
            ref_counter_handle,
            ref_counter_offset,
            event_handle,
            event_sync_required,
        ) = storage._share_cuda_()

        # 强引用：发送方必须保留 tensor/storage 直到接收端 rebuild 完成
        self._tensor_refs.append(tensor)

        # 元信息 JSON：接收端 rebuild_cuda_tensor 的所有位置参数都要传过去
        meta = {
            "tensor_cls": type(tensor).__name__,
            "tensor_size": list(tensor.size()),
            "tensor_stride": list(tensor.stride()),
            "tensor_offset": tensor.storage_offset(),
            "storage_cls": type(storage).__name__,
            "dtype": str(tensor.dtype).replace("torch.", ""),
            # device 在新版 PyTorch（2.12+）下为 int 索引（如 0），旧版为 torch.device 对象。
            # 统一存为 "cuda:N" 字符串，确保接收端 torch.device(meta["device"]) 可解析。
            # 旧版用 str(device) 得 "cuda:0"；新版用 f"cuda:{device}" 得 "cuda:0"。
            "device": str(device) if not isinstance(device, int) else f"cuda:{device}",
            "storage_size_bytes": storage_size_bytes,
            "storage_offset_bytes": storage_offset_bytes,
            "requires_grad": tensor.requires_grad,
            "ref_counter_handle_len": len(ref_counter_handle),
            "ref_counter_offset": ref_counter_offset,
            "event_handle_len": len(event_handle) if event_handle is not None else 0,
            "event_sync_required": event_sync_required,
            "handle_len": len(handle),
        }
        meta_bytes = json.dumps(meta).encode("utf-8")

        # 3 帧：[类型标签, 元信息JSON, handle+ref+event 拼接字节]
        # handle/ref_counter/event 都是 bytes，拼接成一帧以减少 multipart 开销
        handle_blob = (
            bytes(handle)
            + bytes(ref_counter_handle)
            + (bytes(event_handle) if event_handle is not None else b"")
        )
        self._socket.send_multipart([_MSG_TYPE_CUDA_IPC, meta_bytes, handle_blob])

    def recv_tensor(self) -> "torch.Tensor":
        """接收并重建 GPU tensor，零拷贝映射发送方显存。

        Returns:
            重建的 tensor，与发送方共享同一块 GPU 显存。
        """
        frames = self._socket.recv_multipart()
        if len(frames) != 3:
            raise ValueError(f"期望 3 帧 CUDA IPC 消息，实际收到 {len(frames)} 帧")
        tag, meta_bytes, handle_blob = frames[0], frames[1], frames[2]
        if tag != _MSG_TYPE_CUDA_IPC:
            raise ValueError(f"期望 cuda_ipc 消息，收到类型标签: {tag!r}")

        meta = json.loads(meta_bytes.decode("utf-8"))
        # 按 handle_len / ref_counter_handle_len / event_handle_len 切回三段
        h_len = meta["handle_len"]
        rc_len = meta["ref_counter_handle_len"]
        handle = handle_blob[:h_len]
        ref_counter_handle = handle_blob[h_len:h_len + rc_len]
        ev_len = meta["event_handle_len"]
        event_handle = handle_blob[h_len + rc_len:h_len + rc_len + ev_len] if ev_len > 0 else None

        # 解析 dtype/device：dtype 字符串形如 "int32"/"float32"，device 形如 "cuda:1"
        dtype = getattr(torch, meta["dtype"])
        # PyTorch 2.12+ 的 rebuild_cuda_tensor 内部调用 _new_shared_cuda 期望 int device index，
        # 不接受 torch.device 对象（旧版可自动转换）。解析 "cuda:N" 取 N 作为整数索引。
        dev_obj = torch.device(meta["device"])
        device_index = dev_obj.index if dev_obj.index is not None else 0

        # 调用 PyTorch 的对称重建函数：内部调用 storage_cls._new_shared_cuda
        # 映射发送方 GPU 显存，引用计数由 ref_counter_handle 维护
        tensor = rebuild_cuda_tensor(
            torch.Tensor,                              # tensor_cls
            tuple(meta["tensor_size"]),                # tensor_size
            tuple(meta["tensor_stride"]),              # tensor_stride
            meta["tensor_offset"],                     # tensor_offset
            torch.storage.TypedStorage,                # storage_cls
            dtype,
            device_index,                              # int device index（非 torch.device）
            handle,                                    # storage_handle
            meta["storage_size_bytes"],
            meta["storage_offset_bytes"],
            meta["requires_grad"],
            ref_counter_handle,
            meta["ref_counter_offset"],
            event_handle,
            meta["event_sync_required"],
        )
        # 通知 PyTorch 缓存 allocator 回收接收端已消费的 IPC 计数器
        try:
            torch.cuda.ipc_collect()
        except Exception:
            # ipc_collect 失败不致命：仅延迟回收，不影响数据正确性
            logger.debug("torch.cuda.ipc_collect() 调用失败，可忽略", exc_info=True)
        return tensor

    # ------------------------------------------------------------------
    # Token ID 收发（与 TokenChannel 接口一致）
    # ------------------------------------------------------------------
    def send_tokens(self, token_ids: "list[int] | torch.Tensor") -> None:
        """发送 Token ID 数组。

        与 `TokenChannel.send_tokens` 接口一致，但底层走 CUDA IPC 零拷贝：
        - 输入是 list 时，一次性拷到 GPU（仅这一次拷贝，在发送方边界）
        - 输入已是 GPU tensor 时，直接共享，零拷贝

        Args:
            token_ids: Token ID 列表或已位于 GPU 的 int32 tensor。
        """
        if isinstance(token_ids, torch.Tensor):
            t = token_ids.to(dtype=torch.int32, device=f"cuda:{self._gpu_id}")
        else:
            # list → numpy → torch tensor，再移到 GPU：仅这一次 host→device 拷贝
            arr = np.asarray(token_ids, dtype=np.int32)
            t = torch.from_numpy(arr).to(device=f"cuda:{self._gpu_id}")
        self.send_tensor(t)

    def recv_tokens(self) -> list[int]:
        """接收 Token ID 数组，返回 list[int]（与 `TokenChannel` 一致）。

        接收端拿到的 tensor 与发送方共享显存（零拷贝）；为保持接口一致，最后
        一次 device→host 转换并 `.tolist()`。
        """
        t = self.recv_tensor()
        # .cpu().tolist() 在接收端边界做一次拷贝；上游处理仍是零拷贝
        return t.cpu().tolist()

    # ------------------------------------------------------------------
    # PCM 音频收发
    # ------------------------------------------------------------------
    def send_pcm(self, pcm: "np.ndarray | torch.Tensor") -> None:
        """发送 PCM 音频块（float32 或 int16）。

        与 `TokenChannel.send_pcm` 接口一致。dtype 信息编码进类型标签，发送方
        一次性把 numpy 数组移到 GPU，后续 IPC 共享为零拷贝。

        Args:
            pcm: PCM 音频数组，推荐 float32 或 int16。
        """
        if isinstance(pcm, torch.Tensor):
            t = pcm.to(device=f"cuda:{self._gpu_id}")
            if t.dtype not in (torch.float32, torch.int16):
                t = t.to(dtype=torch.float32)
        else:
            arr = np.asarray(pcm)
            if arr.dtype != np.float32 and arr.dtype != np.int16:
                arr = arr.astype(np.float32)
            t = torch.from_numpy(arr).to(device=f"cuda:{self._gpu_id}")
        self.send_tensor(t)

    def recv_pcm(self) -> np.ndarray:
        """接收 PCM 音频块，返回 numpy 数组（与 `TokenChannel.recv_pcm` 一致）。"""
        t = self.recv_tensor()
        # .cpu().numpy() 在接收端边界做一次拷贝；映射本身零拷贝
        return t.cpu().numpy()

    # ------------------------------------------------------------------
    # 资源释放
    # ------------------------------------------------------------------
    def close(self) -> None:
        """关闭 socket 与 context，并释放发送方持有的 tensor 强引用。"""
        try:
            self._socket.close(linger=0)
        finally:
            # 释放显存引用：接收端若已 rebuild 完毕，caching allocator 可回收
            self._tensor_refs.clear()
            if self._owns_context:
                self._context.term()

    def __enter__(self) -> "CudaIpcChannel":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
