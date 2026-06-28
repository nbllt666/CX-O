"""ELP-Orpheus 自定义 Audio Head（PyTorch 实现）。

封装 Orpheus TTS 的 Audio Head 模块，接收 Llama 最后一层 hidden_states 的最后一个
token，生成首个 SNAC token。Audio Head 用 PyTorch 实现（非 TRT Plugin），参数量极小，
耗时 < 2ms，与 FT 骨干解耦，便于快速迭代。

核心设计：
    - 不写成 TRT Plugin（开发成本高易出错），用 PyTorch 实现几个 Linear 层 + GELU +
      argmax 量化，参数量不到 Llama-3B 的 1%，forward < 2ms。
    - 接收 hidden_states[:, -1, :]（形状 [batch, hidden_dim]），输出 [batch, num_codebooks]
      离散 SNAC token。
    - 绑定 GPU 1（与 FT 引擎同卡），hidden_states 零拷贝传递。
"""

from .audio_head import AudioHead
from .audio_head_cpp import AudioHeadCpp, AudioHeadFactory, AUDIO_HEAD_CPP_AVAILABLE
from .weights_loader import AudioHeadWeightsLoader

__all__ = [
    "AudioHead",
    "AudioHeadWeightsLoader",
    "AudioHeadCpp",
    "AudioHeadFactory",
    "AUDIO_HEAD_CPP_AVAILABLE",
]
