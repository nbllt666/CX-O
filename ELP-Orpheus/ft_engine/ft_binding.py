"""FT Llama C++ 引擎 Python 绑定封装层。

模块关系：
    - FT C++ 源码（外部 FasterTransformer 仓库）编译为 ft_llama 扩展模块
    - ft_binding.py（本文件）-> 对外暴露 FTLlamaBinding
    - 调用方：orpheus_engine.OrpheusFTEngine 通过本模块驱动 Context/Decode

设计要点：
    1. 真实 FT 引擎只跑到 Llama 最后一层，输出 hidden_states，不做 LM head。
       Orpheus 的 LM head 是自定义 Audio Head（由 Task 3 处理），与 FT 解耦，
       因此 FT 侧不需要加载 lm_head 权重，只保留 backbone（embedding + transformer
       layers + final norm）。
    2. 通过 pybind11 暴露给 Python 的 C++ 接口风格（参考 NVIDIA FasterTransformer
       examples/cpp/llama）：
         forward(input_ids, kv_cache, start_step, step, is_context)
         -> hidden_states
       其中 kv_cache 为预分配的连续张量，C++ 侧按 start_step 偏移写入新 K/V。
    3. FT 在开发环境可能未编译。本模块优先加载真实扩展；不可用时回退到
       MockFTLlama（纯 PyTorch 模拟），使上层代码可独立运行验证。
"""

from __future__ import annotations

import os
import sys
from typing import Optional

import numpy as np
import torch

# 将本文件所在目录加入 sys.path，便于直接 import 编译出的 ft_llama 扩展。
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)


def _try_load_ft_module():
    """尝试加载真实 FT C++ pybind11 模块 ft_llama。

    成功返回模块对象，失败返回 None。失败原因通常是未编译 FT（缺 .pyd/.so），
    或 ABI 与当前 PyTorch 版本不匹配。

    真实模块需暴露 FTLlama 类，构造签名：
        FTLlama(checkpoint_path, gpu_id, tensor_para_size, pipeline_para_size,
                data_type, cuda_graph)
    并提供：
        forward(input_ids, kv_cache, start_step, step, is_context) -> hidden_states
    """
    try:
        import ft_llama  # type: ignore
        if hasattr(ft_llama, "FTLlama"):
            return ft_llama
    except Exception:
        # 编译不可用、ABI 不匹配、缺 pybind11 运行时等均回退到 Mock。
        pass
    return None


_FT_MODULE = _try_load_ft_module()
FT_AVAILABLE: bool = _FT_MODULE is not None


class FTLlamaBinding:
    """FT Llama C++ 引擎 Python 绑定。

    优先加载真实 FT 引擎；不可用时回退到 MockFTLlama（纯 PyTorch 模拟）用于开发/测试。
    真实 FT 引擎只跑到 Llama 最后一层，输出 hidden_states，不做 LM head。

    为什么 FT 不做 LM head：
        Orpheus 的输出层是自定义 Audio Head（生成 SNAC tokens），结构与损失函数
        迭代频繁。若把 Audio Head 也下沉进 FT/TRT Plugin，每次结构调整都要重编译
        引擎。改用 PyTorch 实现 Audio Head 可在保留 FT 骨干极致性能的同时快速迭代。
        因此 FT 侧只产出 hidden_states，Audio Head 在 Python 侧消费。

    接口契约（与 C++ 侧 pybind11 绑定一致）：
        forward(input_ids, kv_cache, start_step, step, is_context)
            - input_ids: [batch, step] int32/int64 token ids
            - kv_cache:  [num_layers, 2, max_seq_len, batch, hidden_dim] float16
            - start_step: 当前序列已处理 token 数（K/V 写入偏移起点）
            - step: 本批次新 token 数
            - is_context: True=Context Encoding(Prefill), False=Decode(单步)
        返回:
            hidden_states: [batch, step, hidden_dim] float16（Llama 最后一层输出）
    """

    def __init__(
        self,
        checkpoint_path: str,
        gpu_id: int,
        tensor_para_size: int,
        pipeline_para_size: int,
        data_type: str,
        cuda_graph: bool,
        # 以下参数仅 Mock 路径需要，真实 FT 从 checkpoint config 读取：
        hidden_dim: int = 3072,
        num_layers: int = 28,
        max_seq_len: int = 512,
        vocab_size: int = 128256,
    ) -> None:
        """初始化绑定。

        Args:
            checkpoint_path: FT checkpoint 目录路径（含 1-gpu/ 子目录与权重 .bin 文件）。
            gpu_id: 目标 GPU 物理索引（Orpheus 进程绑定 GPU 1）。
            tensor_para_size: 张量并行度（单卡物理隔离下=1）。
            pipeline_para_size: 流水线并行度（=1）。
            data_type: "fp16" 或 "fp32"（Ampere FP16 Tensor Core 最优）。
            cuda_graph: 是否开启 CUDA Graphs（Decode 单 token <1ms 的关键）。
            hidden_dim: 隐藏维度（Mock 路径用，真实 FT 从 checkpoint 读）。
            num_layers: 层数（Mock 路径用）。
            max_seq_len: 最大序列长度（Mock 路径用）。
            vocab_size: 词表大小（Mock 路径用）。
        """
        self._checkpoint_path = checkpoint_path
        self._gpu_id = gpu_id
        self._tensor_para_size = tensor_para_size
        self._pipeline_para_size = pipeline_para_size
        self._data_type = data_type
        self._cuda_graph = cuda_graph
        self._hidden_dim = hidden_dim
        self._num_layers = num_layers
        self._max_seq_len = max_seq_len
        self._vocab_size = vocab_size

        # dtype 映射：FT 侧用 fp16 对应 Ampere Tensor Core 最优路径。
        self._dtype: torch.dtype = (
            torch.float16 if data_type == "fp16" else torch.float32
        )

        self._use_real_ft = False
        self._real_engine = None
        self._mock_engine: Optional[MockFTLlama] = None

        if FT_AVAILABLE:
            try:
                self._real_engine = _FT_MODULE.FTLlama(
                    checkpoint_path=checkpoint_path,
                    gpu_id=gpu_id,
                    tensor_para_size=tensor_para_size,
                    pipeline_para_size=pipeline_para_size,
                    data_type=data_type,
                    cuda_graph=cuda_graph,
                )
                self._use_real_ft = True
                return
            except Exception:
                # 即使模块存在，构造失败也回退到 Mock（例如 checkpoint 路径不存在）。
                self._real_engine = None

        # 回退到 Mock：用纯 PyTorch 模拟 FT 引擎行为，便于无 FT 环境下开发/测试。
        self._mock_engine = MockFTLlama(
            hidden_dim=hidden_dim,
            num_layers=num_layers,
            max_seq_len=max_seq_len,
            vocab_size=vocab_size,
            dtype=self._dtype,
            gpu_id=gpu_id,
        )

    @property
    def backend(self) -> str:
        """当前实际使用的后端名（"ft" 或 "mock"）。"""
        return "ft" if self._use_real_ft else "mock"

    @property
    def hidden_dim(self) -> int:
        return self._hidden_dim

    @property
    def num_layers(self) -> int:
        return self._num_layers

    def forward(
        self,
        input_ids: torch.Tensor,
        kv_cache: torch.Tensor,
        start_step: int,
        step: int,
        is_context: bool,
    ) -> torch.Tensor:
        """前向：is_context=True 为 Context Encoding（Prefill），False 为 Decode。

        核心逻辑：
            FT C++ 引擎从 start_step 偏移开始，处理 step 个新 token 的前向计算，
            并将每一层新产生的 K/V 写入 kv_cache 的 [layer, :, start_step:start_step+step]
            切片。返回 Llama 最后一层的 hidden_states（不做 LM head 投影）。

        Args:
            input_ids: [batch, step] token ids。
            kv_cache: [num_layers, 2, max_seq_len, batch, hidden_dim] 连续 KV Cache。
            start_step: 当前序列已处理 token 数（写入偏移起点）。
            step: 本批次新 token 数（Context 阶段可 >1，Decode 阶段=1）。
            is_context: True=Context Encoding，False=Decode。

        Returns:
            返回类型随 backend 与 is_context 变化（Task 3 返回类型契约）：

            - is_context=True（Context Encoding / Prefill）：
                FT 与 Mock 路径一致，返回 hidden_states 张量
                [batch, step, hidden_dim]（Llama 最后一层输出）。首 token 的 hidden_states
                交由 Audio Head 生成首个 SNAC token，此处暴露给 Python 用于调试/驱动 Audio Head。

            - is_context=False（Decode）：
                * FT 路径：C++ 端在 forward 末尾就地调用 AudioHeadKernel 完成 argmax，返回
                  int32 SNAC token [batch, num_codebooks]（pybind11 的 py::array_t<int32_t>
                  在 Python 侧表现为 numpy.ndarray，本封装转为 torch.Tensor）。这样消灭了
                  PyTorch ↔ FT 跨框架拷贝：不再把 hidden_states 拷回 Python 再做 argmax，
                  而是在 C++ 内一次完成 backbone 前向 + Audio Head argmax。
                * Mock 路径：仍返回 hidden_states 张量 [batch, step, hidden_dim]（保持开发
                  环境可运行），argmax 由上层 generation_forward 完成（保持现有行为）。

        为什么连续显存能保证 Attention 上下文完整：
            kv_cache 在 max_seq_len 维度上连续预分配，Attention kernel 可一次读取
            [0 : start_step+step] 的全部历史 K/V，无需跨不连续块拼接，上下文绝对完整。
        """
        if self._use_real_ft and self._real_engine is not None:
            # 真实 FT C++ 路径：在 C++ 层完成前向，pybind11 call_guard 释放 GIL。
            result = self._real_engine.forward(
                input_ids, kv_cache, start_step, step, is_context
            )
            if not is_context:
                # FT 路径 Decode：C++ AudioHeadKernel 已在 forward 末尾就地完成 argmax，
                # 返回 int32 SNAC token（py::array_t<int32_t> -> numpy.ndarray）。
                # 转为 torch.Tensor 以统一上层接口；dtype 上转交由调用方处理。
                if isinstance(result, np.ndarray) and result.dtype == np.int32:
                    return torch.from_numpy(result).to(self._device)
            # is_context=True：返回 hidden_states 张量（首次 prefill，C++ Audio Head 内部
            # 消费，同时暴露给 Python 用于驱动 Audio Head / 调试）。
            return result

        # Mock 路径：纯 PyTorch 模拟，返回 hidden_states（保持开发环境可运行）。
        assert self._mock_engine is not None
        return self._mock_engine.forward(
            input_ids, kv_cache, start_step, step, is_context
        )

    def reset(self) -> None:
        """重置引擎内部状态（CUDA Graphs 缓存等）。Mock 路径为空操作。"""
        if self._use_real_ft and self._real_engine is not None:
            if hasattr(self._real_engine, "reset"):
                self._real_engine.reset()


# ============================================================================
# MockFTLlama：纯 PyTorch 模拟 FT Llama 引擎（开发/测试用）
# ============================================================================
# 设计目标：
#   1. 当真实 FT 未编译时，让上层 OrpheusFTEngine 仍可独立运行验证逻辑。
#   2. 行为契约与真实 FT 一致：forward 接收 input_ids + kv_cache + start_step/step，
#      将新 K/V 写入 kv_cache 的 [layer, :, start_step:start_step+step] 偏移位置，
#      返回 [batch, step, hidden_dim] 的 hidden_states。
#   3. 不追求数值精度，只保证形状/语义正确，使测试可断言。
#
# 简化点：
#   - 用随机初始化的小型参数模拟 Llama 层（embedding + 1 层简化 attention + final norm）
#   - attention 只做缩放点积，不做 GQA/casual mask 精确实现（够测形状与 KV 写入语义）
#   - CPU/GPU 均可运行：gpu_id 指向的设备不可用时回退 CPU
# ============================================================================


class MockFTLlama:
    """纯 PyTorch 模拟的 FT Llama 引擎（开发/测试用）。

    模拟 FT C++ 引擎的行为契约：
        - forward 将新 K/V 写入 kv_cache 的偏移位置
        - 返回 [batch, step, hidden_dim] 的 hidden_states
        - 只跑到"最后一层"，不做 LM head

    为什么用 Mock：
        真实 FT 需要 C++ 编译 + checkpoint 转换，开发期频繁迭代不现实。Mock 用
        纯 PyTorch 复刻接口契约，使 OrpheusFTEngine 的增量 KV Cache 逻辑、
        current_seq_len 状态机、CUDA Graphs 占位等均可独立验证。
    """

    def __init__(
        self,
        hidden_dim: int = 3072,
        num_layers: int = 28,
        max_seq_len: int = 512,
        vocab_size: int = 128256,
        dtype: torch.dtype = torch.float16,
        gpu_id: int = 1,
    ) -> None:
        """初始化 Mock 引擎。

        Args:
            hidden_dim: 隐藏维度（与真实 Llama-3B 一致=3072）。
            num_layers: 层数（=28）。
            max_seq_len: 最大序列长度。
            vocab_size: 词表大小。
            dtype: 权重与 KV Cache 数据类型。
            gpu_id: 目标 GPU 索引（不可用时回退 CPU）。
        """
        self._hidden_dim = hidden_dim
        self._num_layers = num_layers
        self._max_seq_len = max_seq_len
        self._vocab_size = vocab_size
        self._dtype = dtype

        # 设备选择：优先指定 GPU，不可用回退 CPU（保证无 GPU 环境下测试可运行）。
        if torch.cuda.is_available() and gpu_id < torch.cuda.device_count():
            self._device = torch.device(f"cuda:{gpu_id}")
        else:
            self._device = torch.device("cpu")

        # 用固定随机种子保证 Mock 行为可复现（测试断言稳定）。
        g = torch.Generator(device="cpu").manual_seed(42)

        # Embedding 层：token id -> hidden_states。
        # 用小尺度初始化避免显存爆炸（Mock 不追求精度）。
        self._embedding = torch.nn.Parameter(
            torch.randn(vocab_size, hidden_dim, generator=g, dtype=dtype)
            * 0.02
        ).to(self._device)

        # 简化 attention 参数：Q/K/V/output 投影（不拆 head，仅保证形状正确）。
        # 真实 Llama 用 GQA，Mock 简化为单头全连接。
        self._wq = torch.nn.Parameter(
            torch.randn(hidden_dim, hidden_dim, generator=g, dtype=dtype) * 0.02
        ).to(self._device)
        self._wk = torch.nn.Parameter(
            torch.randn(hidden_dim, hidden_dim, generator=g, dtype=dtype) * 0.02
        ).to(self._device)
        self._wv = torch.nn.Parameter(
            torch.randn(hidden_dim, hidden_dim, generator=g, dtype=dtype) * 0.02
        ).to(self._device)
        self._wo = torch.nn.Parameter(
            torch.randn(hidden_dim, hidden_dim, generator=g, dtype=dtype) * 0.02
        ).to(self._device)

        # 简化 MLP：gate/up/down（SwiGLU 简化为线性+ReLU）。
        self._mlp_gate = torch.nn.Parameter(
            torch.randn(hidden_dim, hidden_dim, generator=g, dtype=dtype) * 0.02
        ).to(self._device)
        self._mlp_up = torch.nn.Parameter(
            torch.randn(hidden_dim, hidden_dim, generator=g, dtype=dtype) * 0.02
        ).to(self._device)
        self._mlp_down = torch.nn.Parameter(
            torch.randn(hidden_dim, hidden_dim, generator=g, dtype=dtype) * 0.02
        ).to(self._device)

        # final norm（RMSNorm 简化为 LayerNorm）。
        self._final_norm_weight = torch.nn.Parameter(
            torch.ones(hidden_dim, dtype=dtype)
        ).to(self._device)

    @property
    def device(self) -> torch.device:
        return self._device

    @property
    def num_layers(self) -> int:
        return self._num_layers

    @property
    def hidden_dim(self) -> int:
        return self._hidden_dim

    def forward(
        self,
        input_ids: torch.Tensor,
        kv_cache: torch.Tensor,
        start_step: int,
        step: int,
        is_context: bool,
    ) -> torch.Tensor:
        """模拟 FT 前向：写入 KV Cache 偏移位置，返回 hidden_states。

        流程：
            1. embedding lookup: [batch, step] -> [batch, step, hidden_dim]
            2. 简化 attention：计算 Q/K/V，将 K/V 写入 kv_cache 偏移位置
            3. 简化 MLP + residual
            4. final norm
            5. 返回 [batch, step, hidden_dim]

        KV Cache 写入语义（与真实 FT 一致）：
            kv_cache[layer, 0, start_step:start_step+step, batch, :] = K
            kv_cache[layer, 1, start_step:start_step+step, batch, :] = V
            这样 Attention 读取 [0 : start_step+step] 即可得完整上下文。
        """
        # 统一设备与 dtype，避免调用方传 CPU 张量时报错。
        input_ids = input_ids.to(self._device)
        kv_cache = kv_cache.to(self._device)

        batch = input_ids.shape[0]
        # 1. Embedding lookup
        # [batch, step] -> [batch, step, hidden_dim]
        hidden = torch.nn.functional.embedding(input_ids.long(), self._embedding)

        # 2. 简化 attention（仅在第 0 层写入，其余层复用同一份 K/V 以简化 Mock）
        #    真实 FT 每层独立 K/V；Mock 为节省显存只在第 0 层真实计算并广播写入所有层。
        q = hidden @ self._wq  # [batch, step, hidden_dim]
        k = hidden @ self._wk
        v = hidden @ self._wv

        # 写入 KV Cache 偏移位置：[layer, 0/1, start_step:start_step+step, batch, :]
        end_step = start_step + step
        # 对所有层写入相同的 K/V（Mock 简化；真实 FT 每层独立）
        kv_cache[:, 0, start_step:end_step, :, :] = k.transpose(0, 1).unsqueeze(0)
        kv_cache[:, 1, start_step:end_step, :, :] = v.transpose(0, 1).unsqueeze(0)

        # 简化 attention 输出：用当前 K/V 与历史 K/V 做缩放点积
        # 读取 [0:end_step] 的全部历史 K/V（连续显存保证上下文完整）
        all_k = kv_cache[0, 0, 0:end_step, :, :].transpose(0, 1)  # [batch, end_step, hidden_dim]
        all_v = kv_cache[0, 1, 0:end_step, :, :].transpose(0, 1)
        # [batch, step, hidden_dim] x [batch, hidden_dim, end_step] -> [batch, step, end_step]
        attn_scores = (q @ all_k.transpose(1, 2)) / (self._hidden_dim ** 0.5)
        # causal mask：当前 token 只能看历史（含自身）
        # step 个 query 对应 [start_step:end_step]，key 是 [0:end_step]
        causal = torch.ones(step, end_step, device=self._device, dtype=torch.bool)
        for i in range(step):
            causal[i, start_step + i + 1:] = False
        attn_scores = attn_scores.masked_fill(~causal.unsqueeze(0), float("-inf"))
        attn_weights = torch.softmax(attn_scores.float(), dim=-1).to(self._dtype)
        attn_out = attn_weights @ all_v  # [batch, step, hidden_dim]
        hidden = hidden + attn_out @ self._wo

        # 3. 简化 MLP + residual（SwiGLU 简化）
        gate = torch.relu(hidden @ self._mlp_gate)
        up = hidden @ self._mlp_up
        mlp_out = (gate * up) @ self._mlp_down
        hidden = hidden + mlp_out

        # 4. final norm（RMSNorm 简化为按 hidden_dim 归一化 + 缩放）
        normed = hidden / (hidden.norm(dim=-1, keepdim=True) + 1e-6)
        hidden = normed * self._final_norm_weight

        return hidden.to(self._dtype)
