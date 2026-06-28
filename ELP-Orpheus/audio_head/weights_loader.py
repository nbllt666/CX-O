"""Audio Head 权重加载器：从 Orpheus 原始 checkpoint 提取并加载权重。

模块关系：
    - scripts/convert_checkpoint.py -> 转换 HF checkpoint 为 FT 格式（Llama 骨干）
    - audio_head.weights_loader（本文件）-> 从 HF checkpoint 提取 Audio Head 权重
    - 调用方：部署脚本 / 测试通过本模块加载 Audio Head 权重

设计决策：
    1. Audio Head 权重在 HF checkpoint 中以 'audio_head' 相关键名存在（与 Llama 骨干
       权重共存于同一 checkpoint）。本模块负责过滤出 audio_head 相关键并加载，跳过
       Llama backbone 权重（backbone 由 FT C++ 引擎独立加载）。
    2. 支持严格/非严格匹配：strict=True 要求键名完全对应，strict=False 允许部分匹配
       （用于 checkpoint 结构与 AudioHead 模块不完全一致时的容错加载）。
    3. 提供随机初始化方法，用于无 checkpoint 的开发/测试场景。
"""

from __future__ import annotations

import os
from typing import Dict

import torch

from .audio_head import AudioHead


class AudioHeadWeightsLoader:
    """从 Orpheus 原始 checkpoint 提取 Audio Head 权重并加载到 AudioHead 模块。

    Orpheus 的 Audio Head 权重在 HF checkpoint 中通常以 'audio_head' 或 'lm_head'
    相关键名存在。本类负责识别、提取并加载这些权重，跳过 Llama backbone 权重。

    为什么单独抽出权重加载器：
        Audio Head 与 Llama 骨干的权重存储在同一 checkpoint 中，但加载方式不同——
        骨干权重由 FT C++ 引擎从转换后的 .bin 文件加载，Audio Head 权重由 PyTorch
        直接加载。将提取逻辑集中在本类中，避免在多处重复实现过滤逻辑，且便于在
        checkpoint 结构变更时单点修改。
    """

    # Audio Head 权重在 checkpoint 中的键名前缀（Orpheus HF checkpoint 约定）。
    # 匹配以下前缀的键将被提取为 Audio Head 权重：
    #   - "audio_head."   ：Orpheus 官方 Audio Head 命名
    #   - "lm_head."      ：部分 Orpheus 变体将 Audio Head 命名为 lm_head
    _AUDIO_HEAD_PREFIXES = ("audio_head.", "lm_head.")

    @staticmethod
    def extract_from_hf_checkpoint(checkpoint_path: str) -> Dict[str, torch.Tensor]:
        """从 HF checkpoint 提取 Audio Head 权重。

        识别 audio_head 相关的键（如 'audio_head.weight'、'audio_head.linear1.weight'、
        'lm_head.weight' 等），跳过 Llama backbone 权重（如 'model.layers.*'）。

        Args:
            checkpoint_path: Orpheus HF checkpoint 文件或目录路径。
                - 若为目录：尝试加载 pytorch_model.bin / model.safetensors。
                - 若为文件：直接加载该文件。

        Returns:
            Dict[str, torch.Tensor]: Audio Head 权重字典，键名为去掉前缀后的模块路径
                （如 'fc1.weight'），值为参数张量。

        Raises:
            FileNotFoundError: checkpoint 路径不存在。
            RuntimeError: checkpoint 中未找到任何 audio_head 相关权重。
        """
        if not os.path.exists(checkpoint_path):
            raise FileNotFoundError(
                f"Checkpoint 路径不存在: {checkpoint_path}"
            )

        # 加载 checkpoint：支持目录（HF 标准布局）或单文件。
        raw_state_dict = AudioHeadWeightsLoader._load_checkpoint(checkpoint_path)

        # 过滤出 audio_head 相关的权重。
        extracted: Dict[str, torch.Tensor] = {}
        for key, value in raw_state_dict.items():
            for prefix in AudioHeadWeightsLoader._AUDIO_HEAD_PREFIXES:
                if key.startswith(prefix):
                    # 去掉前缀，得到 AudioHead 模块内的相对路径（如 'fc1.weight'）。
                    stripped_key = key[len(prefix):]
                    extracted[stripped_key] = value
                    break

        if not extracted:
            raise RuntimeError(
                f"Checkpoint 中未找到 Audio Head 权重（已搜索前缀 "
                f"{AudioHeadWeightsLoader._AUDIO_HEAD_PREFIXES}）。"
                f"请确认 checkpoint 为 Orpheus 模型。"
            )

        return extracted

    @staticmethod
    def load_into_audio_head(
        audio_head: AudioHead,
        checkpoint_path: str,
        strict: bool = False,
    ) -> None:
        """将提取的权重加载到 AudioHead 模块。

        Args:
            audio_head: AudioHead 实例。
            checkpoint_path: Orpheus HF checkpoint 路径。
            strict: 是否严格匹配键名。
                - True：要求提取的权重键与 AudioHead 模块完全对应，多余/缺失均报错。
                - False：允许部分匹配，仅加载匹配的键（用于结构不完全一致时的容错）。

        Raises:
            FileNotFoundError: checkpoint 路径不存在。
            RuntimeError: checkpoint 中未找到 audio_head 权重，或 strict=True 下键不匹配。
        """
        # 从 checkpoint 提取 Audio Head 权重。
        extracted = AudioHeadWeightsLoader.extract_from_hf_checkpoint(checkpoint_path)

        # 将提取的权重移动到 AudioHead 所在设备。
        device = audio_head.device
        extracted = {k: v.to(device) for k, v in extracted.items()}

        # 加载到模块：strict=False 时仅加载匹配的键，跳过不匹配的。
        # load_state_dict 返回 missing_keys 和 unexpected_keys，非严格模式下忽略。
        audio_head.load_state_dict(extracted, strict=strict)

    @staticmethod
    def init_random(audio_head: AudioHead) -> None:
        """随机初始化（用于无 checkpoint 的开发/测试场景）。

        用 PyTorch 默认初始化策略重新初始化 AudioHead 的所有参数。
        适用于：
            - 开发阶段无 Orpheus checkpoint 时的功能验证。
            - 单元测试中需要确定结构的 AudioHead 但不需要真实权重。

        Args:
            audio_head: AudioHead 实例。
        """
        # 对所有子模块应用默认初始化。
        for module in audio_head.modules():
            if isinstance(module, torch.nn.Linear):
                # Kaiming 均匀初始化（PyTorch Linear 默认）：适合 ReLU/GELU 激活。
                torch.nn.init.kaiming_uniform_(
                    module.weight, a=5 ** 0.5
                )
                if module.bias is not None:
                    # bias 初始化为 0，与 PyTorch 默认一致。
                    torch.nn.init.zeros_(module.bias)

    @staticmethod
    def _load_checkpoint(checkpoint_path: str) -> Dict[str, torch.Tensor]:
        """加载 checkpoint 文件为 state_dict（内部方法）。

        支持：
            - 目录路径：优先查找 pytorch_model.bin，其次 model.safetensors。
            - 文件路径：直接加载（支持 .bin / .safetensors / .pt）。

        Args:
            checkpoint_path: checkpoint 文件或目录路径。

        Returns:
            Dict[str, torch.Tensor]: 原始 state_dict（包含 backbone + audio_head 全部权重）。

        Raises:
            FileNotFoundError: 路径不存在或目录下未找到 checkpoint 文件。
        """
        if os.path.isdir(checkpoint_path):
            # 目录：按 HF 标准布局查找 checkpoint 文件。
            candidates = [
                "pytorch_model.bin",
                "model.safetensors",
                "pytorch_model.safetensors",
            ]
            file_path = None
            for name in candidates:
                candidate = os.path.join(checkpoint_path, name)
                if os.path.exists(candidate):
                    file_path = candidate
                    break

            if file_path is None:
                raise FileNotFoundError(
                    f"目录 {checkpoint_path} 下未找到 checkpoint 文件"
                    f"（已查找 {candidates}）。"
                )
        else:
            file_path = checkpoint_path

        # 根据扩展名选择加载方式。
        if file_path.endswith(".safetensors"):
            # safetensors 格式：零拷贝加载，更安全。
            try:
                from safetensors.torch import load_file
                state_dict = load_file(file_path)
            except ImportError:
                # safetensors 未安装时回退到 torch.load（部分 safetensors 文件也兼容）。
                state_dict = torch.load(file_path, map_location="cpu")
        else:
            # .bin / .pt 格式：标准 torch.load。
            state_dict = torch.load(file_path, map_location="cpu")

        return state_dict
