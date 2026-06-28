"""SNAC 解码器：离散 SNAC token -> PCM 音频波形。

模块关系：
    - snac_decoder.SNACDecoder（本文件）-> PyTorch 实现的 SNAC 神经音频编解码解码器
    - snac_decoder.weights_loader.SNACWeightsLoader -> 从 Orpheus/SNAC checkpoint 提取权重
    - 调用方：Audio Head 产出的 SNAC token 序列喂给本解码器，得到 24kHz PCM 波形

设计决策（核心）：
    1. 绑定 GPU 1（与 FT 引擎、Audio Head 同卡）：
       Orpheus TTS 全链路（FT 骨干 -> Audio Head -> SNAC 解码器）都在 GPU 1 上，
       避免跨卡数据传输（PCIe 拷贝毫秒级开销会吃掉 sub-300ms 延迟预算）。
       SNAC 解码器输入是 Audio Head 输出的 token id（小张量），输出是 PCM 波形
       （大张量，seq_len * hop_length 个样本），若与 Audio Head 不同卡，需跨卡拷贝
       PCM，开销不可忽视。同卡则零拷贝，PCM 直接喂给下游 Crossfade Kernel。
    2. torch.compile(mode="max-autotune") 编译加速：
       SNAC 解码器主体是大量 1D 卷积（转置卷积上采样 + 普通卷积精修），1D 卷积是
       compute-bound 的密集算子，torch.compile + inductor 能做算子融合（Conv+GELU+
       Conv 融合为一个 kernel）、layout 优化与 autotune（自动选择最优 kernel 配置）。
       max-autotune 模式额外对每个卷积尝试多组配置择优，对 1D 卷积栈收益显著。
       首次调用承担编译开销（数秒~数十秒），后续走编译内核，单次解码延迟显著降低。
    3. SNAC 与 EnCodec/SoundStream 同属神经音频编解码家族：
       编码端将连续音频量化为多 codebook 离散 token，解码端用 Embedding 查表 + 转置
       卷积上采样还原为 PCM。本实现遵循该范式。
"""

from __future__ import annotations

from typing import List, Optional

import torch
import torch.nn as nn
import torch.nn.functional as F


# ============================================================================
# hop_length 因子分解
# ============================================================================
# SNAC 解码器需要把每个 token 上采样为 hop_length 个 PCM 样本。采用多级转置卷积
# 逐步上采样（而非一次性大 stride），每级 stride 较小，卷积感受野能覆盖局部细节，
# 重建音质更好。因此需把 hop_length 分解为 n_conv_layers 个因子的乘积。
# 例如 hop_length=480, n_conv_layers=4 -> [4, 4, 5, 6]，每级 ConvTranspose1d 的 stride
# 分别为 4/4/5/6，乘积恰好 480。
# ============================================================================
def _factorize_hop_length(hop_length: int, num_factors: int) -> List[int]:
    """将 hop_length 分解为 num_factors 个因子的乘积。

    Args:
        hop_length: 总上采样倍数（每个 token 对应的 PCM 样本数）。
        num_factors: 期望的分级数（= 1D 转置卷积层数）。

    Returns:
        长度为 num_factors 的因子列表，乘积 == hop_length。

    策略：
        - 先做质因数分解（从小到大尝试小质数，便于后续合并/拆分）。
        - 若质因数多于 num_factors：反复把最小的两个合并（保持因子分布均衡，避免单级
          stride 过大导致重建质量下降）。
        - 若少于 num_factors：用 1 补齐（stride=1 的转置卷积相当于不升采样的精修层，
          不影响总上采样倍数）。
    """
    if hop_length < 1:
        raise ValueError(f"hop_length 必须 >=1，收到 {hop_length}")
    if num_factors < 1:
        raise ValueError(f"num_factors 必须 >=1，收到 {num_factors}")

    # 质因数分解（覆盖常见 SNAC/EnCodec 帧移的全部小质数）。
    primes = [2, 3, 5, 7, 11, 13, 17, 19, 23]
    factors: List[int] = []
    n = hop_length
    for p in primes:
        while n % p == 0:
            factors.append(p)
            n //= p
    if n > 1:
        # 剩余的大质数/合数直接作为一个因子保留。
        factors.append(n)

    # 合并：质因数过多时，反复合并最小的两个，保持分布均衡。
    while len(factors) > num_factors:
        factors.sort()
        a = factors.pop(0)
        b = factors.pop(0)
        factors.append(a * b)

    # 补齐：质因数不足时，用 1 补齐（stride=1 的转置卷积，不升采样）。
    while len(factors) < num_factors:
        factors.append(1)

    factors.sort()
    return factors


class SNACDecoder(nn.Module):
    """SNAC 解码器：离散 token -> PCM 音频波形。

    设计决策：
        - 绑定 GPU 1（与 FT 引擎、Audio Head 同卡，避免跨卡数据传输）。
        - 使用 torch.compile(mode="max-autotune") 编译加速（SNAC 含大量 1D 卷积，
          编译优化收益大：算子融合 + autotune 最优 kernel）。
        - 输入 SNAC token 序列 [batch, num_codebooks, seq_len]，输出 PCM 波形 [batch, samples]。
    """

    def __init__(
        self,
        num_codebooks: int = 4,
        vocab_size: int = 4096,
        embedding_dim: int = 128,
        hidden_dim: int = 1024,
        n_conv_layers: int = 4,
        target_sample_rate: int = 24000,
        hop_length: int = 480,
        gpu_id: int = 1,
    ) -> None:
        """初始化 SNAC 解码器。

        Args:
            num_codebooks: SNAC codebook 数量。
            vocab_size: 每个 codebook 的离散 token 数。
            embedding_dim: token embedding 维度。
            hidden_dim: 卷积隐藏维度。
            n_conv_layers: 1D 转置卷积层数（每级上采样一个因子）。
            target_sample_rate: 输出 PCM 采样率（24000Hz）。
            hop_length: 帧移（每个 token 对应的 PCM 样本数）。
            gpu_id: 绑定的 GPU（默认 1，与 FT 引擎、Audio Head 同卡）。
        """
        super().__init__()

        self._num_codebooks = num_codebooks
        self._vocab_size = vocab_size
        self._embedding_dim = embedding_dim
        self._hidden_dim = hidden_dim
        self._n_conv_layers = n_conv_layers
        self._target_sample_rate = target_sample_rate
        self._hop_length = hop_length
        self._gpu_id = gpu_id

        # 1. 绑定 GPU：
        #    Orpheus TTS 全链路（FT 骨干 + Audio Head + SNAC 解码器）都在 GPU 1 上，
        #    避免跨卡 PCIe 拷贝吃掉 sub-300ms 延迟预算。无 GPU 环境（开发/CI）回退 CPU。
        if torch.cuda.is_available() and gpu_id < torch.cuda.device_count():
            self._device = torch.device(f"cuda:{gpu_id}")
        else:
            self._device = torch.device("cpu")

        # 2. Token Embedding：每个 codebook 一张独立的查表。
        #    SNAC 用多个 codebook 表达不同粒度的音频信息（粗粒度 -> 细粒度），
        #    每个 codebook 独立 embedding 后求和合并，是 EnCodec/SoundStream 的标准做法。
        self.embeddings = nn.ModuleList(
            [nn.Embedding(vocab_size, embedding_dim) for _ in range(num_codebooks)]
        )

        # 3. 通道投影：embedding_dim -> hidden_dim（1x1 卷积等价于逐帧线性映射）。
        #    把查表得到的低维 embedding 投影到卷积栈的工作维度 hidden_dim。
        self.proj = nn.Conv1d(embedding_dim, hidden_dim, kernel_size=1)

        # 4. 上采样栈：n_conv_layers 级转置卷积，每级 stride = 一个因子，乘积 = hop_length。
        #    为什么用多级小 stride 而非单级大 stride：单级大 stride 卷积感受野无法覆盖
        #    局部细节，重建音质差；多级小 stride 逐级放大，每级卷积可在当前分辨率精修。
        self._upsample_strides = _factorize_hop_length(hop_length, n_conv_layers)
        self.upsample_blocks = nn.ModuleList()
        for stride in self._upsample_strides:
            # ConvTranspose1d(kernel=stride, stride=stride, padding=0) 恰好把长度乘以 stride：
            #   out = (in - 1) * stride + kernel = (in - 1) * stride + stride = in * stride
            # 保证各级长度精确相乘，最终 samples = seq_len * hop_length（无边界误差）。
            up = nn.ConvTranspose1d(
                hidden_dim, hidden_dim,
                kernel_size=stride, stride=stride, padding=0,
            )
            # 精修卷积：kernel=3, padding=1，长度不变，仅做局部特征精修。
            refine = nn.Conv1d(
                hidden_dim, hidden_dim,
                kernel_size=3, padding=1,
            )
            self.upsample_blocks.append(nn.ModuleDict({"up": up, "refine": refine}))

        # 5. 输出头：hidden_dim -> 1（单声道），再 tanh 限幅到 [-1, 1]。
        self.final = nn.Conv1d(hidden_dim, 1, kernel_size=1)

        # 迁移到绑定设备。
        self.to(self._device)

        # 6. torch.compile 状态：懒编译。
        #    首次 decode 调用时才触发编译，避免 __init__ 阶段承担编译开销。
        #    _compiled_fn: 编译后的 forward 可调用对象（None 表示尚未编译）。
        #    _compile_disabled: 编译失败后置 True，后续直接走 eager forward，避免反复重试。
        self._compiled_fn: Optional[callable] = None
        self._compile_disabled: bool = False

    # ------------------------------------------------------------------
    # 前向：解码 SNAC token 序列为 PCM 波形
    # ------------------------------------------------------------------
    def forward(self, snac_tokens: torch.Tensor) -> torch.Tensor:
        """前向：解码 SNAC token 序列为 PCM 波形。

        Args:
            snac_tokens: [batch, num_codebooks, seq_len] 离散 SNAC token 序列。

        Returns:
            pcm: [batch, samples] PCM 音频波形（float32，范围 [-1, 1]）。

        逻辑：
            1. 每个 codebook 的 token 通过 Embedding 查表 ->
               [batch, num_codebooks, seq_len, embedding_dim]
            2. 合并 codebooks（求和）-> [batch, seq_len, embedding_dim]
            3. 转置为 [batch, embedding_dim, seq_len] 供 1D 卷积处理
            4. 通道投影到 hidden_dim
            5. 经过若干 1D 转置卷积（上采样）+ 1D 卷积（精修），逐步上采样到 PCM 采样率
            6. 最终输出头 + tanh -> [batch, samples] 单声道 PCM
        """
        # 设备对齐：保证输入与权重同设备（避免跨设备隐式拷贝触发性能毛刺）。
        snac_tokens = snac_tokens.to(self._device)

        # 形状校验：[batch, num_codebooks, seq_len]。
        if snac_tokens.dim() != 3:
            raise ValueError(
                f"snac_tokens 期望 3D [batch, num_codebooks, seq_len]，收到 shape="
                f"{tuple(snac_tokens.shape)}"
            )
        if snac_tokens.shape[1] != self._num_codebooks:
            raise ValueError(
                f"snac_tokens 的 codebook 维度({snac_tokens.shape[1]}) 与 num_codebooks"
                f"({self._num_codebooks}) 不一致"
            )

        # 转为 long 索引（Embedding 查表要求）。
        tokens_long = snac_tokens.to(torch.long)

        # 1. 每个 codebook 独立查表 + 求和合并。
        #    查表结果: [batch, seq_len, embedding_dim]（Embedding 输入末维，自动省略 codebook 维）。
        #    多 codebook 求和：EnCodec/SoundStream 标准做法，等价于"粗细粒度信息叠加"。
        emb = self.embeddings[0](tokens_long[:, 0, :])
        for i in range(1, self._num_codebooks):
            emb = emb + self.embeddings[i](tokens_long[:, i, :])
        # emb: [batch, seq_len, embedding_dim]

        # 2. 转为 channels-first：[batch, embedding_dim, seq_len]，供 Conv1d 处理。
        x = emb.transpose(1, 2).contiguous()

        # 3. 通道投影：embedding_dim -> hidden_dim。
        x = self.proj(x)  # [batch, hidden_dim, seq_len]
        x = F.gelu(x)

        # 4. 逐级上采样 + 精修。
        #    每级：转置卷积（长度 * stride）-> GELU -> 精修卷积（长度不变）-> GELU。
        for block in self.upsample_blocks:
            x = block["up"](x)       # 上采样：长度乘以 stride
            x = F.gelu(x)
            x = block["refine"](x)   # 精修：kernel=3 pad=1，长度不变
            x = F.gelu(x)

        # 5. 输出头：hidden_dim -> 1（单声道），tanh 限幅到 [-1, 1]。
        x = self.final(x)            # [batch, 1, samples]
        pcm = x.squeeze(1)           # [batch, samples]
        pcm = torch.tanh(pcm)        # 限幅到 [-1, 1]，避免 PCM 削顶失真
        return pcm

    # ------------------------------------------------------------------
    # 编译后的解码接口
    # ------------------------------------------------------------------
    def decode(self, snac_tokens: torch.Tensor) -> torch.Tensor:
        """编译后的解码接口（torch.compile 包装）。

        首次调用触发 torch.compile 编译（max-autotune），后续调用走编译后的优化内核。

        为什么用 torch.compile(mode="max-autotune")：
            SNAC 解码器主体是大量 1D 卷积（转置卷积上采样 + 普通卷积精修），1D 卷积是
            compute-bound 密集算子。inductor 后端可做算子融合（Conv+GELU 融合为单 kernel）、
            layout 优化；max-autotune 额外对每个卷积尝试多组配置择优，对 1D 卷积栈收益显著。
            首次调用承担编译开销，后续走编译内核，单次解码延迟显著降低。

        为什么编译失败要回退到 eager：
            Windows + CPU 环境（或无 triton/inductor 的环境）下，torch.compile 可能因后端
            不可用或动态形状触发 Recompilation 失败。为保证解码器在任何环境下都可用，
            编译失败时静默回退到 eager forward，仅损失编译加速收益，不丧失功能。
        """
        # 懒编译：首次调用时构造编译后的 forward。
        if self._compiled_fn is None and not self._compile_disabled:
            try:
                # 编译 forward（含全部 1D 卷积的热路径），max-autotune 触发 autotuning。
                self._compiled_fn = torch.compile(
                    self.forward, mode="max-autotune"
                )
            except Exception:
                # 编译构造失败（如 inductor 后端不可用）：禁用编译，回退 eager。
                self._compile_disabled = True
                self._compiled_fn = None

        # 优先走编译内核；编译被禁用时直接走 eager forward。
        fn = self._compiled_fn if self._compiled_fn is not None else self.forward
        try:
            return fn(snac_tokens)
        except Exception:
            # 运行期编译/执行失败（如动态形状触发 recompilation 失败、后端异常）：
            # 一次性回退 eager，并禁用后续编译，避免每步都重试编译拖慢推理。
            if not self._compile_disabled:
                self._compile_disabled = True
                self._compiled_fn = None
            return self.forward(snac_tokens)

    # ------------------------------------------------------------------
    # 预热 torch.compile
    # ------------------------------------------------------------------
    def warmup_compile(
        self, sample_seq_len: int = 100, batch_size: int = 1
    ) -> None:
        """预热 torch.compile（用 dummy 输入触发首次编译）。

        在引擎启动时调用，避免首次实际解码承担编译开销。

        为什么需要预热：
            torch.compile 首次调用会同步触发整图编译 + autotune（数秒~数十秒），
            若放在首次真实解码路径上，会引入不可控的首帧延迟毛刺，破坏 sub-300ms
            端到端延迟预算。引擎启动阶段用 dummy 输入预编译，把编译开销挪到启动期，
            使首帧真实解码与后续解码延迟一致。

        Args:
            sample_seq_len: 预热用 dummy token 序列长度（默认 100）。
            batch_size: 预热用 dummy 批大小（默认 1，流式 TTS 单批）。
        """
        # 构造 dummy SNAC token：随机 token id，形状 [batch, num_codebooks, seq_len]。
        # 注意：torch.compile 默认按输入 shape 动态特化，预热 shape 应与真实推理 shape
        # 接近（尤其是 num_codebooks 维度必须一致），否则真实推理时会触发重新编译。
        dummy = torch.randint(
            0, self._vocab_size,
            (batch_size, self._num_codebooks, sample_seq_len),
            device=self._device, dtype=torch.long,
        )
        # 第一次调用触发编译（承担编译开销）。
        _ = self.decode(dummy)
        # 第二次调用确认走编译内核稳定路径（避免首次编译内核的冷启动抖动）。
        _ = self.decode(dummy)

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------
    @property
    def device(self) -> torch.device:
        """解码器绑定的设备（GPU 1 或 CPU 回退）。"""
        return self._device

    @property
    def hop_length(self) -> int:
        """帧移（每个 token 对应的 PCM 样本数）。"""
        return self._hop_length

    @property
    def target_sample_rate(self) -> int:
        """输出 PCM 采样率。"""
        return self._target_sample_rate

    @property
    def num_codebooks(self) -> int:
        """SNAC codebook 数量。"""
        return self._num_codebooks

    @property
    def upsample_strides(self) -> List[int]:
        """各级转置卷积的 stride 列表（乘积 == hop_length）。"""
        return list(self._upsample_strides)

    @property
    def compile_enabled(self) -> bool:
        """torch.compile 是否处于启用状态（未禁用即视为启用）。"""
        return not self._compile_disabled
