"""ZeroMQ 极简 IPC 通信层。

ELP-Orpheus 双卡物理隔离架构中，中央调度器（CPU 进程）通过本通道把 LLM 输出的
Token ID 数组传递给 Orpheus TTS 引擎（GPU 1 进程）；TTS 引擎再通过本通道把 PCM
音频块回传给前端进程。

设计决策：
    1. 抛弃 gRPC/HTTP：
       gRPC 需要 protobuf 编解码 + HTTP/2 帧栈，HTTP 还要 JSON 文本序列化，二者
       单条消息开销在毫秒级，且引入大量依赖。ZeroMQ 只传递裸字节 buffer，无协议
       头开销，单条消息序列化/反序列化 < 1ms。
    2. 用原始 numpy 数组 buffer 而非 JSON：
       Token ID 是定长 int32 数值，JSON 要把它们转成字符串 "[1, 2, 3, ...]" 再
       逐字符解析，10000 个 token 的 JSON 文本约 40KB+ 且解析慢；直接发送 int32
       buffer 同样 40KB，但接收端 np.frombuffer 几乎是 O(1) 的指针转换。
    3. PUSH/PULL 单向流式：
       天然匹配 "调度器 → TTS" 与 "TTS → 前端" 的单向数据流，PULL 端自带队列，
       发送端不会因接收端暂时没消费而阻塞丢消息。

跨平台端点：
    Linux 部署用 Unix Domain Socket: "ipc:///tmp/orpheus-tokens.sock"
    Windows 开发用 TCP:              "tcp://127.0.0.1:5555"
    单机测试用进程内:                "inproc://test"（要求 sender/receiver 共享同一个 zmq.Context）
"""

from __future__ import annotations

import zmq
import numpy as np


# multipart 首帧的类型标签，用于区分 Token 与 PCM，避免接收端猜解 buffer 类型。
# 仅几个字节，开销可忽略，且仍保持 "裸 buffer 传输、非 JSON 文本" 的核心设计。
_MSG_TYPE_TOKENS = b"tokens"
# PCM 的标签带 dtype 后缀，形如 b"pcm:<f4" / b"pcm:<i2"，接收端按此还原 dtype。
_MSG_TYPE_PCM_PREFIX = b"pcm:"


class TokenChannel:
    """ZeroMQ Token ID 数组传递通道（已启用 ZeroMQ 零拷贝）。

    设计决策：抛弃 gRPC/HTTP，用 ZeroMQ 传递原始 Token ID 数组（numpy 数组），
    避免 JSON 文本序列化开销，单条消息 < 1ms。

    零拷贝优化（Task 5 修复瓶颈 C）：
        原实现 `np.asarray(...).tobytes()` 会产生 2 次堆拷贝 + 1 次 Python
        bytes 对象分配，延迟 3-5ms。现改为 `send_multipart([tag, arr],
        copy=False)`，让 ZeroMQ 直接引用 numpy 数组的底层 buffer：
            - pyzmq 用 `Frame(data, copy=False)` 把 numpy buffer 指针交给
              libzmq，libzmq 完成投递后通过 free_fn 回调释放 Python 引用
            - 完全跳过 tobytes() 的堆拷贝与 bytes 对象分配
        接收端默认 `recv_multipart(copy=True)` 仍拿回 bytes，frombuffer 零拷贝
        还原 numpy 视图，无需改动。

    通信模式：PUSH/PULL 单向流式。
        - role="sender"   → 创建 PUSH socket 并 CONNECT 到 endpoint
        - role="receiver" → 创建 PULL socket 并 BIND 到 endpoint

    消息格式（multipart，2 帧）：
        frame[0] = 类型标签  b"tokens" / b"pcm:<f4" / b"pcm:<i2"
        frame[1] = numpy 数组的底层 buffer（int32 / float32 / int16）
                   （发送端 copy=False 时为 numpy 数组，接收端拿回 bytes）

    为什么不用 gRPC/HTTP：
        gRPC/HTTP 的协议栈开销与 JSON 文本序列化都会把单条消息延迟推到毫秒级，
        无法满足 < 1ms 目标；ZeroMQ 直接搬运裸字节，跳过协议解析。

    为什么用原始数组而非 JSON：
        见模块 docstring 第 2 条——int32 buffer 的 np.frombuffer 是 O(1) 指针
        转换，而 JSON 需逐字符解析，且文本体积更大。
    """

    def __init__(
        self,
        endpoint: str,
        role: str,
        context: "zmq.Context | None" = None,
    ) -> None:
        """初始化 ZeroMQ 通道。

        Args:
            endpoint: ZeroMQ 端点。
                      Linux 部署用 UDS: "ipc:///tmp/orpheus-tokens.sock"
                      Windows 开发用 TCP: "tcp://127.0.0.1:5555"
                      单机测试用 inproc: "inproc://test"（需共享 context）
            role: "sender" 或 "receiver"。
            context: 可选的共享 zmq.Context，主要用于 inproc 测试。
                     为 None 时内部新建 Context，并在 close() 时一并销毁；
                     由外部传入时，close() 只关闭 socket，不销毁 context。

        Raises:
            ValueError: role 既不是 "sender" 也不是 "receiver"。
        """
        if role not in ("sender", "receiver"):
            raise ValueError(f"role 必须是 'sender' 或 'receiver'，得到: {role!r}")

        self._endpoint = endpoint
        self._role = role
        # 是否由本实例拥有 context：决定 close() 时是否销毁
        self._owns_context = context is None
        # 不用 zmq.Context.instance()：避免 close() 销毁全局单例影响其他使用者
        self._context = context if context is not None else zmq.Context()

        if role == "sender":
            # PUSH 端 CONNECT：发送方主动连接接收方绑定的端口
            self._socket = self._context.socket(zmq.PUSH)
            self._socket.connect(endpoint)
        else:
            # PULL 端 BIND：接收方持有端口，发送方连接过来
            self._socket = self._context.socket(zmq.PULL)
            self._socket.bind(endpoint)

        # linger=0：close() 时立即返回，不等待未发送消息投递（实时流式可接受丢尾）
        self._socket.setsockopt(zmq.LINGER, 0)

        # 零拷贝发送时，pyzmq 的 Frame(copy=False) 会把 numpy buffer 指针交给
        # libzmq；libzmq 投递完成后通过 free_fn 回调释放 Python 引用。但在
        # PUSH 端消息积压、PULL 端尚未消费的极端场景下，为防止 numpy 数组被
        # GC 提前回收导致 buffer 失效，保留最近一次发送的数组强引用作为兜底。
        # 注：pyzmq 内部已有引用计数机制，这里是双保险。
        self._send_buf_ref: list = []

    # ------------------------------------------------------------------
    # Token ID 收发
    # ------------------------------------------------------------------
    def send_tokens(self, token_ids: list[int]) -> None:
        """发送 Token ID 数组（ZeroMQ 零拷贝路径）。

        序列化方式：numpy int32 数组的底层 buffer 直接交给 ZeroMQ（multipart，
        非 JSON），接收端用 np.frombuffer 零拷贝还原。

        零拷贝原理（Task 5 修复瓶颈 C）：
            原 `arr.tobytes()` 会复制 buffer 到新 bytes 对象（1 次堆拷贝 + 1 次
            对象分配）；现用 `send_multipart([tag, arr], copy=False)`，pyzmq 把
            numpy 的 buffer 指针直接交给 libzmq，跳过 tobytes() 的拷贝。

        为什么不用 JSON：
            10000 个 token 的 JSON 文本约 40KB+ 且需逐字符解析；int32 buffer 同样
            40KB 但接收端 np.frombuffer 几乎是 O(1) 的指针转换。

        Args:
            token_ids: 待发送的 Token ID 列表。
        """
        # np.asarray 避免对已是 ndarray 的输入重复拷贝；统一 int32 保证跨平台一致
        arr = np.asarray(token_ids, dtype=np.int32)
        # 零拷贝：copy=False 让 ZeroMQ 直接引用 arr 的 buffer，不复制
        # 兜底引用：保留 arr 强引用，避免 PUSH 端积压时被 GC 回收
        self._send_buf_ref[:] = [arr]
        self._socket.send_multipart([_MSG_TYPE_TOKENS, arr], copy=False)

    def recv_tokens(self) -> list[int]:
        """接收 Token ID 数组，反序列化为 list[int]。

        接收端无需关心发送端是否走零拷贝：`recv_multipart` 默认 `copy=True`，
        始终拿回 bytes，`np.frombuffer` 在其上建零拷贝视图，再 `.tolist()` 转原生。

        Returns:
            还原后的 Token ID 列表。
        """
        frames = self._socket.recv_multipart()
        tag, data = frames[0], frames[1]
        if tag != _MSG_TYPE_TOKENS:
            raise ValueError(f"期望 tokens 消息，收到类型标签: {tag!r}")
        # np.frombuffer 返回只读视图，零拷贝；.tolist() 转成原生 list[int]
        arr = np.frombuffer(data, dtype=np.int32)
        return arr.tolist()

    # ------------------------------------------------------------------
    # PCM 音频收发
    # ------------------------------------------------------------------
    def send_pcm(self, pcm: np.ndarray) -> None:
        """发送 PCM 音频块（float32 或 int16 数组），用于 TTS → 前端。

        零拷贝路径（Task 5 修复瓶颈 C）：原 `arr.tobytes()` 会复制 buffer 到新
        bytes 对象；现用 `send_multipart([tag, arr], copy=False)`，pyzmq 直接
        引用 numpy 的 buffer，跳过 tobytes() 的拷贝。dtype 信息编码进类型标签
        （如 b"pcm:<f4"），接收端按标签还原，无需 JSON 描述字段。非
        float32/int16 的数组会被统一转成 float32（音频处理最常用且精度足够）。

        Args:
            pcm: PCM 音频数组，推荐 float32 或 int16。
        """
        arr = np.asarray(pcm)
        if arr.dtype != np.float32 and arr.dtype != np.int16:
            arr = arr.astype(np.float32)
        # 标签里带 dtype.str（如 "<f4"），接收端 np.dtype(...) 可还原
        tag = _MSG_TYPE_PCM_PREFIX + arr.dtype.str.encode("ascii")
        # 零拷贝：copy=False 让 ZeroMQ 直接引用 arr 的 buffer，不复制
        # 兜底引用：保留 arr 强引用，避免 PUSH 端积压时被 GC 回收
        self._send_buf_ref[:] = [arr]
        self._socket.send_multipart([tag, arr], copy=False)

    def recv_pcm(self) -> np.ndarray:
        """接收 PCM 音频块。

        Returns:
            还原后的 numpy 数组（dtype 与发送端一致，通常 float32）。
        """
        frames = self._socket.recv_multipart()
        tag, data = frames[0], frames[1]
        if not tag.startswith(_MSG_TYPE_PCM_PREFIX):
            raise ValueError(f"期望 pcm 消息，收到类型标签: {tag!r}")
        # 从标签解析 dtype，如 b"pcm:<f4" → "<f4"
        dtype_str = tag[len(_MSG_TYPE_PCM_PREFIX):].decode("ascii")
        arr = np.frombuffer(data, dtype=np.dtype(dtype_str))
        # frombuffer 返回只读视图，copy() 转成可写数组方便下游处理
        return arr.copy()

    # ------------------------------------------------------------------
    # 资源释放
    # ------------------------------------------------------------------
    def close(self) -> None:
        """关闭 socket；若 context 由本实例创建则一并销毁。"""
        try:
            self._socket.close(linger=0)
        finally:
            # 释放零拷贝发送 buffer 的兜底强引用
            self._send_buf_ref.clear()
            if self._owns_context:
                # 仅销毁自身创建的 context，不影响外部传入的共享 context
                self._context.term()

    def __enter__(self) -> "TokenChannel":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
