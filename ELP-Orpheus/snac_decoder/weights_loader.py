"""SNAC 解码器权重加载器。

模块关系：
    - snac_decoder.SNACDecoder -> 解码器本体（nn.Module）
    - snac_decoder.weights_loader.SNACWeightsLoader（本文件）-> 从 Orpheus/SNAC checkpoint
      提取解码器权重并加载到 SNACDecoder 实例
    - 调用方：引擎启动时调用 load_into_decoder 把权重灌入解码器

设计决策：
    1. checkpoint 格式自适应：Orpheus/SNAC 的权重可能以多种格式分发
       （HuggingFace 目录含 .safetensors/.bin、单文件 .pt/.safetensors）。本加载器统一
       处理：目录优先扫 .safetensors，其次 .bin/.pt；单文件按后缀分发。
    2. 权重名前缀剥离：在完整 Orpheus checkpoint 中，SNAC 解码器权重通常带前缀
       （如 "snac."、"model.snac."、"audio_codec."）。本加载器剥离这些前缀，使其与
       SNACDecoder.state_dict() 的键名对齐后加载。
    3. strict=False 默认：SNAC 解码器结构可能随版本演进，checkpoint 键集与当前模块
       略有出入时仍可加载（缺的权重保持模块随机初始化），便于开发期快速试错。
    4. 提供随机初始化（init_random）：开发/测试环境无 checkpoint 时，用合理初始化
       （Embedding 正态、卷积 Kaiming）填充权重，保证解码器可运行（输出虽为噪声但形状正确）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict

import torch
import torch.nn as nn

from .snac_decoder import SNACDecoder


# ============================================================================
# SNAC 权重在完整 checkpoint 中的常见前缀
# ============================================================================
# Orpheus 完整 checkpoint = Llama 骨干 + Audio Head + SNAC 解码器。SNAC 部分可能挂在
# 以下前缀下（不同发布版本/命名约定略有差异）。加载时按此列表顺序剥离前缀，使键名
# 与 SNACDecoder.state_dict() 对齐。
# ============================================================================
_SNAC_PREFIXES = (
    "model.snac.",
    "snac.",
    "model.audio_codec.",
    "audio_codec.",
    "model.snac_decoder.",
    "snac_decoder.",
)


def _load_state_dict(checkpoint_path: str) -> Dict[str, torch.Tensor]:
    """从 checkpoint 路径加载 state_dict（自适应目录/单文件、safetensors/bin/pt）。

    Args:
        checkpoint_path: checkpoint 目录或单文件路径。

    Returns:
        完整 checkpoint 的 state_dict（含全部子模块权重，未剥离前缀）。

    支持的输入形式：
        - 目录：扫描目录下所有 .safetensors（优先，按文件名排序）合并；若无则扫 .bin/.pt。
        - 单文件 .safetensors：用 safetensors.torch.load_file 加载。
        - 单文件 .bin/.pt：用 torch.load 加载。
    """
    p = Path(checkpoint_path)
    if not p.exists():
        raise FileNotFoundError(f"checkpoint 路径不存在: {checkpoint_path}")

    if p.is_dir():
        # 目录：优先 safetensors，其次 bin/pt。
        state: Dict[str, torch.Tensor] = {}
        safetensor_files = sorted(p.glob("*.safetensors"))
        if safetensor_files:
            try:
                from safetensors.torch import load_file
            except ImportError as e:
                raise ImportError(
                    "检测到 .safetensors 但未安装 safetensors，请 pip install safetensors"
                ) from e
            for f in safetensor_files:
                state.update(load_file(str(f)))
            return state

        bin_files = sorted(p.glob("*.bin")) + sorted(p.glob("*.pt"))
        if not bin_files:
            raise FileNotFoundError(
                f"checkpoint 目录下未找到权重文件（.safetensors/.bin/.pt）: {checkpoint_path}"
            )
        for f in bin_files:
            state.update(torch.load(str(f), map_location="cpu"))
        return state

    # 单文件。
    suffix = p.suffix.lower()
    if suffix == ".safetensors":
        try:
            from safetensors.torch import load_file
        except ImportError as e:
            raise ImportError(
                "检测到 .safetensors 但未安装 safetensors，请 pip install safetensors"
            ) from e
        return load_file(str(p))
    elif suffix in (".bin", ".pt", ".pth"):
        return torch.load(str(p), map_location="cpu")
    else:
        # 未知后缀也尝试 torch.load（可能是无后缀的 pickle）。
        return torch.load(str(p), map_location="cpu")


def _strip_snac_prefix(key: str) -> str:
    """剥离 SNAC 权重的命名空间前缀，对齐 SNACDecoder.state_dict() 键名。

    Args:
        key: checkpoint 中的原始键名，如 "model.snac.embeddings.0.weight"。

    Returns:
        剥离前缀后的键名，如 "embeddings.0.weight"；若无匹配前缀则原样返回。
    """
    for prefix in _SNAC_PREFIXES:
        if key.startswith(prefix):
            return key[len(prefix):]
    return key


class SNACWeightsLoader:
    """SNAC 解码器权重加载器。

    提供从 Orpheus/SNAC checkpoint 提取解码器权重、加载到 SNACDecoder 实例、以及
    随机初始化（开发/测试用）三类能力。
    """

    @staticmethod
    def extract_from_checkpoint(checkpoint_path: str) -> Dict[str, torch.Tensor]:
        """从 checkpoint 提取 SNAC 解码器权重。

        扫描完整 checkpoint 的 state_dict，挑出属于 SNAC 解码器的权重（按前缀判定），
        剥离前缀后返回，使键名与 SNACDecoder.state_dict() 对齐。

        Args:
            checkpoint_path: checkpoint 目录或单文件路径。

        Returns:
            解码器权重字典，键名已剥离前缀（如 "embeddings.0.weight"），
            值为 CPU 上的张量。若无匹配权重返回空字典。
        """
        raw = _load_state_dict(checkpoint_path)
        extracted: Dict[str, torch.Tensor] = {}
        for key, tensor in raw.items():
            # 仅挑带 SNAC 前缀的键（避免误捞 Llama/Audio Head 权重）。
            stripped = _strip_snac_prefix(key)
            if stripped != key:
                # 命中了前缀，属于 SNAC 解码器权重。
                extracted[stripped] = tensor
        return extracted

    @staticmethod
    def load_into_decoder(
        decoder: SNACDecoder,
        checkpoint_path: str,
        strict: bool = False,
    ) -> None:
        """加载权重到 SNACDecoder。

        Args:
            decoder: 目标 SNACDecoder 实例。
            checkpoint_path: checkpoint 目录或单文件路径。
            strict: 是否要求 checkpoint 权重与解码器 state_dict 完全一致。
                False（默认）：允许部分权重缺失/多余，缺失的保持解码器原权重
                （便于跨版本加载）；True：要求完全一致，否则抛错。

        Raises:
            RuntimeError: strict=True 且键集不匹配，或 checkpoint 中未找到任何 SNAC 权重。
        """
        extracted = SNACWeightsLoader.extract_from_checkpoint(checkpoint_path)
        if not extracted:
            if strict:
                raise RuntimeError(
                    f"checkpoint 中未找到 SNAC 解码器权重（已检查前缀 { _SNAC_PREFIXES }）"
                    f": {checkpoint_path}"
                )
            # strict=False 且无权重：静默返回（保持解码器随机初始化），仅打印提示。
            print(
                f"[SNACWeightsLoader] 警告：checkpoint 中未找到 SNAC 权重，"
                f"解码器保持当前权重: {checkpoint_path}"
            )
            return

        # 加载到解码器（load_state_dict 自动处理设备迁移）。
        missing, unexpected = decoder.load_state_dict(extracted, strict=strict)
        if missing:
            print(f"[SNACWeightsLoader] 缺失权重（保持随机初始化）: {missing}")
        if unexpected:
            print(f"[SNACWeightsLoader] checkpoint 中多余的权重（忽略）: {unexpected}")

    @staticmethod
    def init_random(decoder: SNACDecoder) -> None:
        """随机初始化解码器权重（开发/测试用）。

        用合理初始化填充解码器全部权重，使其可运行（输出为噪声但形状正确）：
            - Embedding：正态分布 N(0, 0.02)（与 Transformer 常规初始化一致）。
            - Conv1d / ConvTranspose1d：Kaiming 正态初始化（leaky_relu 非线性），
              偏置置零。
            - 其余模块保持 PyTorch 默认初始化。

        Args:
            decoder: 待初始化的 SNACDecoder 实例。
        """
        for module in decoder.modules():
            if isinstance(module, nn.Embedding):
                nn.init.normal_(module.weight, mean=0.0, std=0.02)
                # Embedding 无 bias。
            elif isinstance(module, (nn.Conv1d, nn.ConvTranspose1d)):
                # Kaiming 初始化适配卷积层（前向用 GELU，leaky_relu 近似）。
                nn.init.kaiming_normal_(module.weight, nonlinearity="leaky_relu")
                if module.bias is not None:
                    nn.init.zeros_(module.bias)
