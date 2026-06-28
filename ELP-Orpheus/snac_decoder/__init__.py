"""ELP-Orpheus SNAC 解码器模块。

封装 SNAC 神经音频编解码解码器，将 Orpheus TTS 生成的离散 SNAC token 序列解码为
24kHz PCM 音频波形。

核心设计：
    - 绑定 GPU 1（与 FT 引擎、Audio Head 同卡，避免跨卡数据传输）。
    - 使用 torch.compile(mode="max-autotune") 编译加速（SNAC 含大量 1D 卷积，
      编译优化收益大：算子融合 + autotune 最优 kernel）。
    - 输入 [batch, num_codebooks, seq_len] 离散 token，输出 [batch, samples] PCM 波形。
"""

from .snac_decoder import SNACDecoder
from .weights_loader import SNACWeightsLoader

__all__ = ["SNACDecoder", "SNACWeightsLoader"]
