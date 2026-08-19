"""CosyVoice vLLM 插件：在 vLLM 各进程（含 EngineCore 子进程）内注册 CosyVoice2ForCausalLM。

vLLM 0.26 的 EngineCore 为独立进程，主进程 ModelRegistry.register_model 不会传播。
通过 vllm.general_plugins entry point 让每个 vLLM 进程 import 本模块时完成注册。
"""

from vllm import ModelRegistry

from cosyvoice.vllm.cosyvoice2 import CosyVoice2ForCausalLM


def register() -> None:
    """vLLM general plugin 工厂函数：注册 CosyVoice2ForCausalLM。"""
    ModelRegistry.register_model("CosyVoice2ForCausalLM", CosyVoice2ForCausalLM)
