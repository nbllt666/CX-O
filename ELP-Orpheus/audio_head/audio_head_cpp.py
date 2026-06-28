"""Audio Head C++/CUDA 算子的 Python 封装 + 工厂。

模块关系：
    - ft_engine/decoding_cpp/binding.cpp -> 编译产出 audio_head_cpp 扩展模块
    - audio_head.audio_head_cpp（本文件）-> Python 侧封装 AudioHeadCpp + AudioHeadFactory
    - 调用方：orpheus_engine / scheduler 通过 AudioHeadFactory.create("ft") 取得实例

设计决策：
    1. 为什么需要 Python 封装：
       C++ 扩展只懂 numpy 数组（host 指针），不懂 torch.Tensor / device / autograd。
       本封装做 torch<->numpy 桥接 + device 对齐，使上层调用与原 PyTorch AudioHead
       接口完全一致（generate_first_snac_token(hidden_states) -> torch.Tensor）。
    2. backend=="ft" 时优先用 C++ 扩展；编译不可用 / import 失败时回退到 Python AudioHead，
       保证无 CUDA / 未编译环境下功能与单测仍可运行（与 ft_binding.py 的 Mock 回退理念一致）。
    3. 权重以 .bin（FP16）形式存储，C++ 路径与 Python 回退路径共用同一份 .bin：
       - C++ 路径：load_weights(dir) 直接读 .bin 到显存/内存
       - Python 回退：load_weights(dir) 读 .bin 还原为 nn.Linear 的 weight/bias
       这样两条路径数值同源，便于 bit-exact 单测对齐。
    4. 零拷贝说明：本封装走 numpy（host）桥接，GPU 输入需 .cpu() 拷出、结果再 .to(device)
       拷回。真正的零拷贝发生在 FT 上游 decoding.cpp 直接持有 AudioHeadKernel 实例时
       （见 ft_engine/decoding_cpp/INTEGRATION_NOTES.md）。本封装面向 Python 调度路径。
"""

from __future__ import annotations

import os
from typing import Optional

import numpy as np
import torch

from .audio_head import AudioHead


# ============================================================================
# 尝试加载 C++ 扩展模块 audio_head_cpp。
# 失败原因：未编译（无 .pyd/.so）、ABI 不匹配、缺 pybind11 运行时等。
# 与 ft_binding._try_load_ft_module 风格一致：成功返回模块对象，失败返回 None。
# ============================================================================
def _try_load_cpp_module():
    try:
        import audio_head_cpp  # type: ignore
        if hasattr(audio_head_cpp, "AudioHeadCpp"):
            return audio_head_cpp
    except Exception:
        # 任何导入失败都静默回退到 Python 实现（保持上层可用）。
        pass
    return None


_CPP_MODULE = _try_load_cpp_module()
# 模块级常量：C++ 扩展是否可用（供上层与测试查询）。
AUDIO_HEAD_CPP_AVAILABLE: bool = _CPP_MODULE is not None


# ============================================================================
# .bin 权重导出 / 导入工具（C++ 路径与 Python 回退路径共用同一 .bin 格式）。
#
# .bin 布局（与 C++ AudioHeadKernel.load_weights 约定一致）：
#   fc1.bin      : FP16, shape [hidden_dim, intermediate_dim]（行主序）
#                  = PyTorch fc1.weight [intermediate_dim, hidden_dim] 的转置
#   fc2.bin      : FP16, shape [intermediate_dim, num_codebooks*snac_vocab_size]
#                  = PyTorch fc2.weight 的转置
#   fc1_bias.bin : FP16, shape [intermediate_dim]（可选）
#   fc2_bias.bin : FP16, shape [num_codebooks*snac_vocab_size]（可选）
#
# 为什么存转置：C++ GEMM 直接做 X @ W（行主序），W 按 [in, out] 存储省去运行时转置；
# PyTorch Linear 存 [out, in]，故导出时转置一次固化到 .bin。
# ============================================================================
def export_audio_head_weights_to_bin(audio_head: AudioHead,
                                     weights_dir: str) -> None:
    """将 PyTorch AudioHead 的权重导出为 C++ 侧读取的 .bin（FP16）格式。

    供部署 / 单测使用：把训练好的 AudioHead 权重固化为 C++ 可加载格式。

    Args:
        audio_head: 已加载权重的 AudioHead 实例。
        weights_dir: 输出目录（自动创建）。
    """
    os.makedirs(weights_dir, exist_ok=True)

    # fc1.weight: [intermediate, hidden] -> 转置 [hidden, intermediate] -> FP16
    fc1_w = audio_head.fc1.weight.detach().cpu().to(torch.float16)  # [I, H]
    fc1_w_t = fc1_w.t().contiguous().numpy()  # [H, I], float16
    fc1_w_t.tofile(os.path.join(weights_dir, "fc1.bin"))

    # fc2.weight: [out_dim, intermediate] -> 转置 [intermediate, out_dim] -> FP16
    fc2_w = audio_head.fc2.weight.detach().cpu().to(torch.float16)  # [out_dim, I]
    fc2_w_t = fc2_w.t().contiguous().numpy()  # [I, out_dim], float16
    fc2_w_t.tofile(os.path.join(weights_dir, "fc2.bin"))

    # bias（Linear 默认含 bias，导出以保证与 Python 数值对齐）
    if audio_head.fc1.bias is not None:
        b1 = audio_head.fc1.bias.detach().cpu().to(torch.float16).numpy()
        b1.tofile(os.path.join(weights_dir, "fc1_bias.bin"))
    if audio_head.fc2.bias is not None:
        b2 = audio_head.fc2.bias.detach().cpu().to(torch.float16).numpy()
        b2.tofile(os.path.join(weights_dir, "fc2_bias.bin"))


def _read_fp16_bin(path: str, shape: tuple) -> np.ndarray:
    """读取 FP16 .bin 并 reshape，返回 float32 numpy（供 Python 回退加载）。"""
    arr = np.fromfile(path, dtype=np.float16)
    expected = 1
    for s in shape:
        expected *= s
    if arr.size != expected:
        raise RuntimeError(
            f"权重文件 {path} 元素数 {arr.size} 与期望 {expected} (shape={shape}) 不符"
        )
    return arr.reshape(shape).astype(np.float32)


def load_bin_into_audio_head(audio_head: AudioHead, weights_dir: str) -> None:
    """从 .bin（FP16）还原权重到 PyTorch AudioHead（Python 回退路径用）。

    与 C++ AudioHeadKernel.load_weights 读同一份 .bin，保证两条路径数值同源。
    """
    # 从 Linear 自身形状推导维度（最可靠，避免依赖私有属性）。
    intermediate_dim, hidden_dim = audio_head.fc1.weight.shape  # [out, in]
    out_dim = audio_head.fc2.weight.shape[0]  # num_codebooks * snac_vocab

    # fc1.bin [hidden, intermediate] -> 转置回 PyTorch [intermediate, hidden]
    fc1 = _read_fp16_bin(os.path.join(weights_dir, "fc1.bin"),
                         (hidden_dim, intermediate_dim))
    audio_head.fc1.weight.data = torch.from_numpy(fc1.T.copy())

    # fc2.bin [intermediate, out_dim] -> 转置回 PyTorch [out_dim, intermediate]
    fc2 = _read_fp16_bin(os.path.join(weights_dir, "fc2.bin"),
                         (intermediate_dim, out_dim))
    audio_head.fc2.weight.data = torch.from_numpy(fc2.T.copy())

    # bias（可选）
    b1_path = os.path.join(weights_dir, "fc1_bias.bin")
    b2_path = os.path.join(weights_dir, "fc2_bias.bin")
    if os.path.exists(b1_path) and audio_head.fc1.bias is not None:
        b1 = _read_fp16_bin(b1_path, (intermediate_dim,))
        audio_head.fc1.bias.data = torch.from_numpy(b1.copy())
    if os.path.exists(b2_path) and audio_head.fc2.bias is not None:
        b2 = _read_fp16_bin(b2_path, (out_dim,))
        audio_head.fc2.bias.data = torch.from_numpy(b2.copy())


# ============================================================================
# AudioHeadCpp：C++/CUDA 算子的 Python 封装。
# ============================================================================
class AudioHeadCpp:
    """Audio Head C++/CUDA 算子封装，接口与 PyTorch AudioHead 完全一致。

    优先使用编译出的 audio_head_cpp C++ 扩展；不可用时回退到 Python AudioHead，
    保证无 CUDA / 未编译环境下功能与单测可运行。

    接口契约（与 AudioHead.generate_first_snac_token 一致）：
        generate_first_snac_token(hidden_states) -> torch.Tensor [batch, num_codebooks]

    属性：device / num_codebooks / snac_vocab_size（与 AudioHead 对齐）。
    """

    def __init__(
        self,
        hidden_dim: int = 3072,
        intermediate_dim: int = 1024,
        num_codebooks: int = 4,
        snac_vocab_size: int = 4096,
        gpu_id: int = 1,
        weights_dir: Optional[str] = None,
    ) -> None:
        self._hidden_dim = hidden_dim
        self._intermediate_dim = intermediate_dim
        self._num_codebooks = num_codebooks
        self._snac_vocab_size = snac_vocab_size
        self._gpu_id = gpu_id

        # 设备选择：与 AudioHead 一致（GPU 不可用时回退 CPU）。
        if torch.cuda.is_available() and gpu_id < torch.cuda.device_count():
            self._device = torch.device(f"cuda:{gpu_id}")
        else:
            self._device = torch.device("cpu")

        self._cpp_module = _CPP_MODULE
        self._cpp = None
        self._py_fallback: Optional[AudioHead] = None

        if self._cpp_module is not None:
            # C++ 路径：构造扩展实例。
            try:
                self._cpp = self._cpp_module.AudioHeadCpp(
                    hidden_dim=hidden_dim,
                    intermediate_dim=intermediate_dim,
                    num_codebooks=num_codebooks,
                    snac_vocab_size=snac_vocab_size,
                    gpu_id=gpu_id,
                )
            except Exception:
                # 构造失败（罕见，如维度非法）也回退到 Python。
                self._cpp = None
                self._cpp_module = None

        if self._cpp is None:
            # Python 回退：构造等价的 PyTorch AudioHead（接口完全一致）。
            self._py_fallback = AudioHead(
                hidden_dim=hidden_dim,
                snac_vocab_size=snac_vocab_size,
                num_codebooks=num_codebooks,
                intermediate_dim=intermediate_dim,
                gpu_id=gpu_id,
            )

        if weights_dir is not None:
            self.load_weights(weights_dir)

    # ------------------------------------------------------------------
    # 属性
    # ------------------------------------------------------------------
    @property
    def backend(self) -> str:
        """实际使用的后端："cpp" 或 "py-fallback"。"""
        return "cpp" if self._cpp is not None else "py-fallback"

    @property
    def device(self) -> torch.device:
        return self._device

    @property
    def num_codebooks(self) -> int:
        return self._num_codebooks

    @property
    def snac_vocab_size(self) -> int:
        return self._snac_vocab_size

    @property
    def hidden_dim(self) -> int:
        return self._hidden_dim

    @property
    def intermediate_dim(self) -> int:
        return self._intermediate_dim

    @property
    def weights_loaded(self) -> bool:
        """权重是否已加载。"""
        if self._cpp is not None:
            return bool(self._cpp.weights_loaded)
        # Python 回退：AudioHead 总有随机初始化权重，视为"已加载"。
        return True

    # ------------------------------------------------------------------
    # 权重加载
    # ------------------------------------------------------------------
    def load_weights(self, weights_dir: str) -> None:
        """从目录加载 .bin 权重（C++ 路径与 Python 回退路径共用同一 .bin）。"""
        if self._cpp is not None:
            self._cpp.load_weights(weights_dir)
        else:
            assert self._py_fallback is not None
            load_bin_into_audio_head(self._py_fallback, weights_dir)

    # ------------------------------------------------------------------
    # 前向
    # ------------------------------------------------------------------
    def generate_first_snac_token(self, hidden_states: torch.Tensor) -> torch.Tensor:
        """生成首个 SNAC token。

        与 audio_head.AudioHead.generate_first_snac_token 完全一致：
            - 取 hidden_states[:, -1, :] 作为输入
            - 输出 [batch, num_codebooks] torch.Tensor（int64，与 argmax 默认 dtype 一致）

        C++ 路径：torch -> numpy(可能 .cpu()) -> C++ forward -> numpy -> torch(回输入 device)。
        Python 回退路径：直接委托 AudioHead.generate_first_snac_token。

        为什么返回 int64 而非 int32：
            PyTorch torch.argmax 默认返回 int64。为与 AudioHead 输出 dtype 完全一致，
            将 C++ 的 int32 结果上转为 int64。
        """
        if self._cpp is None:
            assert self._py_fallback is not None
            return self._py_fallback.generate_first_snac_token(hidden_states)

        # 取最后一个 token：[batch, seq, hidden] -> [batch, hidden]
        hs_last = hidden_states[:, -1, :]

        # torch -> numpy（保留 dtype：fp16->float16 numpy, fp32->float32 numpy）。
        # 若输入在 GPU 上需先 .cpu()（C++ 扩展接收 host 指针）。
        np_in = hs_last.detach().cpu().numpy()

        # C++ forward：返回 numpy int32 [batch, num_codebooks]。
        np_out = self._cpp.forward(np_in)

        # numpy -> torch，上转 int64 以匹配 PyTorch argmax dtype，并对齐输入 device。
        out = torch.from_numpy(np_out).to(torch.int64)
        return out.to(hidden_states.device)


# ============================================================================
# AudioHeadFactory：后端工厂。
# ============================================================================
class AudioHeadFactory:
    """Audio Head 后端工厂。

    backend 选择：
        - "ft":   返回 AudioHeadCpp（内部优先 C++ 扩展，不可用则回退 Python AudioHead）。
                  这是 FT 引擎路径的首选：C++ 算子可在 FT decoding.cpp 内零拷贝调用。
        - "mock": 返回纯 PyTorch AudioHead（开发/测试用，与 ft_binding.MockFTLlama 对应）。

    为什么用工厂而非直接构造：
        上层调度（orpheus_engine / scheduler）只关心"取一个能生成首 token 的 head"，
        不应感知 C++ 编译状态。工厂集中处理回退逻辑，便于在编译状态变化时单点修改。
    """

    @staticmethod
    def create(backend: str = "ft", **kwargs) -> object:
        """创建 Audio Head 实例。

        Args:
            backend: "ft"（C++ 优先 + Python 回退）或 "mock"（纯 Python）。
            **kwargs: 透传给具体实现（hidden_dim/intermediate_dim/num_codebooks/
                      snac_vocab_size/gpu_id/weights_dir 等）。

        Returns:
            AudioHeadCpp（backend=="ft"）或 AudioHead（backend=="mock"）。
        """
        if backend == "ft":
            return AudioHeadCpp(**kwargs)
        elif backend == "mock":
            return AudioHead(**kwargs)
        else:
            raise ValueError(
                f"未知 backend={backend!r}，支持 'ft' / 'mock'"
            )


__all__ = [
    "AudioHeadCpp",
    "AudioHeadFactory",
    "AUDIO_HEAD_CPP_AVAILABLE",
    "export_audio_head_weights_to_bin",
    "load_bin_into_audio_head",
]
