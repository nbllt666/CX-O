"""ELP-Orpheus FT 引擎音频后处理 Kernel 集合。

模块关系：
    - kernels.crossfade -> Audio Crossfade Kernel（相邻 Chunk PCM 边界线性淡入淡出）
    - 调用方：StreamingPipeline 在 SNAC 解码出 PCM 后调用，抹平流式拼接痕迹（< 1ms）

设计决策：
    - 优先 Triton 单 kernel 融合实现（GPU 1，与 SNAC 解码器同卡零拷贝）；
    - Triton 不可用时（如 Windows）自动回退 PyTorch 向量化实现，功能等价。
"""
from .crossfade import (
    ChunkCrossfader,
    crossfade_overlap,
    crossfade_overlap_triton,
)

__all__ = [
    "crossfade_overlap",
    "crossfade_overlap_triton",
    "ChunkCrossfader",
]
