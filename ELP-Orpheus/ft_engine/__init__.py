"""ELP-Orpheus FT 引擎封装层。

封装 FasterTransformer (FT) Llama-3B 骨干引擎的加载与调用，暴露增量 KV Cache
接口供 Audio Head 与调度器使用。

核心设计：
    - FT C++ 引擎只跑到 Llama 最后一层，输出 hidden_states，不做 LM head（Audio Head
      由 Task 3 单独处理，与 FT 解耦）。
    - 预分配全局连续 KV Cache 张量 [num_layers, 2, max_seq_len, batch, hidden_dim]，
      通过 start_step/step 实现增量 Context Encoding，第二 Chunk Prefill < 5ms。
    - 开启 CUDA Graphs，Decode 单 token < 1ms。
"""

from .orpheus_engine import OrpheusFTEngine
from .ft_binding import FTLlamaBinding, FT_AVAILABLE, MockFTLlama
from .cuda_graph_config import CudaGraphConfig, OperatorOptimizer

__all__ = [
    "OrpheusFTEngine",
    "FTLlamaBinding",
    "FT_AVAILABLE",
    "MockFTLlama",
    "CudaGraphConfig",
    "OperatorOptimizer",
]
