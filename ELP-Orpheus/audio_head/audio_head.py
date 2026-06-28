"""Orpheus 自定义 Audio Head（PyTorch 实现，非 TRT Plugin）。

模块关系：
    - ft_engine.orpheus_engine.OrpheusFTEngine -> FT 骨干，输出 hidden_states
    - audio_head.audio_head.AudioHead（本文件）-> 消费 hidden_states 生成首个 SNAC token
    - 调用方：scheduler / orpheus_engine.generation_forward 通过本模块决定下一个 token

设计决策（核心）：
    1. 为什么用 PyTorch 而非 TRT Plugin：
       Audio Head 结构与损失函数迭代频繁，若下沉进 TRT Plugin，每次结构调整都要重编译
       引擎（TRT plugin 编译链复杂、调试困难、易出错）。Audio Head 参数量极小（仅几个
       Linear 层），PyTorch forward 在 GPU 上 < 2ms，与 TRT Plugin 的性能差距可忽略，
       但迭代效率提升数倍。因此 FT 骨干用 C++ 极致优化，Audio Head 用 PyTorch 快速迭代，
       两者解耦。
    2. Audio Head 接收 Llama 最后一层 hidden_states 的最后一个 token，生成首个 SNAC token。
       SNAC token 是离散音频 token，通过 Linear 投影到 SNAC 码本维度 + argmax 量化得到。
    3. 绑定 GPU 1（与 FT 引擎同卡），hidden_states 直接在 GPU 1 上，零拷贝传递。
"""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F


class AudioHead(nn.Module):
    """Orpheus 自定义 Audio Head（PyTorch 实现，非 TRT Plugin）。

    设计决策：
        - 不写成 TRT Plugin（开发成本高易出错），用 PyTorch 实现
        - 参数量极小（仅几个 Linear 层），耗时 < 2ms
        - 接收 Llama 最后一层 hidden_states 的最后一个 token，生成首个 SNAC token
        - SNAC token 是离散音频 token，通过 Linear 投影到 SNAC 码本维度 + argmax 量化

    为什么用 PyTorch 而非 TRT Plugin：
        Audio Head 结构（Linear 层数、激活类型、codebook 数）在研发阶段频繁调整。TRT
        Plugin 每次改动需重写 C++ kernel + 重新编译 engine，单次迭代成本高且易引入 ABI
        错误。PyTorch 实现下，结构调整只需改 Python 代码即可即时验证。Audio Head 参数量
        不到 Llama-3B 的 1%，PyTorch forward < 2ms，性能损失可忽略，换来的是 10x 迭代效率。
    """

    def __init__(
        self,
        hidden_dim: int = 3072,
        snac_vocab_size: int = 4096,
        num_codebooks: int = 4,
        intermediate_dim: int = 1024,
        gpu_id: int = 1,
    ) -> None:
        """初始化 Audio Head。

        Args:
            hidden_dim: Llama 隐藏维度（输入维度，Llama-3B = 3072）。
            snac_vocab_size: SNAC 码本大小（每个 codebook 的离散 token 数）。
            num_codebooks: SNAC codebook 数量（Orpheus 生成多层 SNAC token）。
            intermediate_dim: 中间层维度（控制参数量与表达力的平衡点）。
            gpu_id: 目标 GPU 物理索引（Orpheus 绑定 GPU 1，与 FT 引擎同卡）。
        """
        super().__init__()

        self._hidden_dim = hidden_dim
        self._snac_vocab_size = snac_vocab_size
        self._num_codebooks = num_codebooks
        self._intermediate_dim = intermediate_dim
        self._gpu_id = gpu_id

        # 设备选择：优先指定 GPU（与 FT 引擎同卡，hidden_states 零拷贝传递）；
        # GPU 不可用时回退 CPU，保证无 GPU 环境下仍可运行测试。
        if torch.cuda.is_available() and gpu_id < torch.cuda.device_count():
            self._device = torch.device(f"cuda:{gpu_id}")
        else:
            self._device = torch.device("cpu")

        # ------------------------------------------------------------------
        # 网络结构：两层 Linear + GELU 激活 + reshape + argmax
        # ------------------------------------------------------------------
        # 为什么是两层而非一层：
        #   单层 Linear(hidden_dim -> num_codebooks*snac_vocab_size) 参数量巨大且无非线性，
        #   无法学习 hidden_states 到 SNAC 码本的复杂映射。两层结构中间加 GELU 非线性，
        #   既控制参数量（intermediate_dim 远小于 hidden_dim*snac_vocab_size），又提供
        #   足够表达力。GELU 比 ReLU 更平滑，梯度更稳定，适合量化任务。
        self.fc1 = nn.Linear(hidden_dim, intermediate_dim)
        self.fc2 = nn.Linear(
            intermediate_dim, num_codebooks * snac_vocab_size
        )

        # 将参数移动到目标设备。
        self.to(self._device)

    @property
    def device(self) -> torch.device:
        """Audio Head 绑定的设备。"""
        return self._device

    @property
    def num_codebooks(self) -> int:
        """SNAC codebook 数量。"""
        return self._num_codebooks

    @property
    def snac_vocab_size(self) -> int:
        """SNAC 码本大小。"""
        return self._snac_vocab_size

    def forward(self, hidden_states_last: torch.Tensor) -> torch.Tensor:
        """前向：生成首个 SNAC token。

        Args:
            hidden_states_last: [batch, hidden_dim] Llama 最后一层最后一个 token 的
                隐藏状态（由 OrpheusFTEngine.context_forward 返回的 hidden_states
                取 [:, -1, :] 得到）。

        Returns:
            snac_tokens: [batch, num_codebooks] 首个 SNAC token（每个 codebook 一个
                离散 token，取值范围 [0, snac_vocab_size)）。

        逻辑：
            Linear(hidden_dim -> intermediate_dim) -> GELU 激活
            -> Linear(intermediate_dim -> num_codebooks*snac_vocab_size)
            -> reshape [batch, num_codebooks, snac_vocab_size]
            -> argmax(dim=-1) -> [batch, num_codebooks]

        为什么用 argmax 而非 Gumbel-softmax / 采样：
            首个 SNAC token 是确定性的起始 token（自回归生成的第一步），用 argmax 取
            码本中最近邻的离散 token，保证首 token 稳定可复现。后续 token 由 FT 自回归
            生成，不在本模块处理。
        """
        # 统一输入设备（hidden_states 来自 FT 引擎，已在同一 GPU 上，此步通常无开销）。
        hidden_states_last = hidden_states_last.to(self._device)

        # Linear(hidden_dim -> intermediate_dim)
        x = self.fc1(hidden_states_last)  # [batch, intermediate_dim]
        # GELU 激活：比 ReLU 更平滑，梯度更稳定。
        x = F.gelu(x)
        # Linear(intermediate_dim -> num_codebooks * snac_vocab_size)
        logits = self.fc2(x)  # [batch, num_codebooks * snac_vocab_size]

        # reshape 为 [batch, num_codebooks, snac_vocab_size]
        batch = hidden_states_last.shape[0]
        logits = logits.view(batch, self._num_codebooks, self._snac_vocab_size)

        # argmax 量化：每个 codebook 取概率最大的离散 token。
        snac_tokens = torch.argmax(logits, dim=-1)  # [batch, num_codebooks]

        return snac_tokens

    def generate_first_snac_token(self, hidden_states: torch.Tensor) -> torch.Tensor:
        """便捷方法：从完整 hidden_states 取最后一个 token 生成首个 SNAC token。

        封装 forward，自动从 FT 引擎输出的完整 hidden_states 中提取最后一个 token。

        Args:
            hidden_states: [batch, seq_len, hidden_dim] FT 引擎输出
                （OrpheusFTEngine.context_forward 返回值的第一个元素）。

        Returns:
            snac_tokens: [batch, num_codebooks] 首个 SNAC token。

        为什么取最后一个 token：
            自回归生成中，最后一个 token 的 hidden_state 包含了完整上下文信息
            （attention 已聚合 [0:seq_len] 全部历史），是预测下一个输出 token 的
            正确输入。Audio Head 基于此预测首个 SNAC token。
        """
        # 取最后一个 token 的隐藏状态：[batch, seq_len, hidden_dim] -> [batch, hidden_dim]
        hidden_states_last = hidden_states[:, -1, :]
        return self.forward(hidden_states_last)
