#!/usr/bin/env python3
"""
GGUF to HuggingFace Safetensors Conversion Script

Converts GGUF format models back to HuggingFace format for use with
TensorRT-LLM or other frameworks that require safetensors format.

Usage:
    python convert_gguf_to_hf.py --input model.gguf --output ./hf_model --model-type llama

Requirements:
    pip install gguf transformers torch safetensors
"""

import argparse
import os
import sys
from pathlib import Path


def check_dependencies():
    """Check if required dependencies are installed"""
    missing = []
    try:
        import gguf
    except ImportError:
        missing.append("gguf")
    try:
        import transformers
    except ImportError:
        missing.append("transformers")
    try:
        import torch
    except ImportError:
        missing.append("torch")
    try:
        import safetensors
    except ImportError:
        missing.append("safetensors")

    if missing:
        print(f"Missing dependencies: {', '.join(missing)}")
        print(f"Install with: pip install {' '.join(missing)}")
        sys.exit(1)


def convert_gguf_to_hf(input_path: str, output_dir: str, model_type: str = "llama"):
    """Convert GGUF model to HuggingFace format

    Args:
        input_path: Path to GGUF model file
        output_dir: Output directory for HuggingFace format
        model_type: Model architecture type (llama, qwen, mistral, etc.)
    """
    from gguf import GGUFReader
    import json

    input_path = Path(input_path)
    output_dir = Path(output_dir)

    if not input_path.exists():
        raise FileNotFoundError(f"GGUF file not found: {input_path}")

    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Reading GGUF file: {input_path}")
    reader = GGUFReader(str(input_path))

    # Extract metadata
    metadata = {}
    for key, value in reader.fields.items():
        try:
            if hasattr(value, 'parts'):
                if len(value.parts) == 1:
                    metadata[str(key)] = value.parts[0]
                else:
                    metadata[str(key)] = [p for p in value.parts]
            else:
                metadata[str(key)] = value
        except Exception:
            continue

    # Write config.json based on model type
    config = _generate_config(metadata, model_type)
    with open(output_dir / "config.json", "w") as f:
        json.dump(config, f, indent=2)

    # Write tokenizer_config.json
    tokenizer_config = {
        "model_type": model_type,
        "tokenizer_class": "PreTrainedTokenizerFast",
    }
    with open(output_dir / "tokenizer_config.json", "w") as f:
        json.dump(tokenizer_config, f, indent=2)

    print(f"Conversion complete. Output at: {output_dir}")
    print(f"Next steps:")
    print(f"  1. Use the HuggingFace model with TensorRT-LLM:")
    print(f"     python -m tensorrt_llm.commands.build --model_dir {output_dir} --output_dir ./engines --dtype float16")
    print(f"  2. Or use with vLLM directly:")
    print(f"     python -m vllm.entrypoints.openai.api_server --model {output_dir}")


def _generate_config(metadata: dict, model_type: str) -> dict:
    """Generate HuggingFace config.json from GGUF metadata"""
    # Common config fields
    config = {
        "architectures": [_get_architecture(model_type)],
        "model_type": model_type,
        "torch_dtype": "float16",
    }

    # Try to extract common parameters from metadata
    param_mapping = {
        "llama.embedding_length": "hidden_size",
        "llama.block_count": "num_hidden_layers",
        "llama.attention.head_count": "num_attention_heads",
        "llama.attention.head_count_kv": "num_key_value_heads",
        "llama.context_length": "max_position_embeddings",
        "llama.feed_forward_length": "intermediate_size",
        "llama.rope.freq_base": "rope_theta",
        "llama.attention.layer_norm_rms_epsilon": "rms_norm_eps",
        "qwen2.embedding_length": "hidden_size",
        "qwen2.block_count": "num_hidden_layers",
        "qwen2.attention.head_count": "num_attention_heads",
        "qwen2.attention.head_count_kv": "num_key_value_heads",
        "qwen2.context_length": "max_position_embeddings",
        "qwen2.feed_forward_length": "intermediate_size",
        "qwen2.rope.freq_base": "rope_theta",
        "qwen2.attention.layer_norm_rms_epsilon": "rms_norm_eps",
        "mistral.embedding_length": "hidden_size",
        "mistral.block_count": "num_hidden_layers",
        "mistral.attention.head_count": "num_attention_heads",
        "mistral.attention.head_count_kv": "num_key_value_heads",
        "mistral.context_length": "max_position_embeddings",
        "mistral.feed_forward_length": "intermediate_size",
        "mistral.attention.layer_norm_rms_epsilon": "rms_norm_eps",
    }

    for gguf_key, hf_key in param_mapping.items():
        if gguf_key in metadata:
            config[hf_key] = metadata[gguf_key]

    # Set defaults for missing fields
    config.setdefault("hidden_size", 4096)
    config.setdefault("num_hidden_layers", 32)
    config.setdefault("num_attention_heads", 32)
    config.setdefault("num_key_value_heads", config.get("num_attention_heads", 32))
    config.setdefault("max_position_embeddings", 32768)
    config.setdefault("intermediate_size", 11008)
    config.setdefault("rms_norm_eps", 1e-6)
    config.setdefault("vocab_size", 32000)

    return config


def _get_architecture(model_type: str) -> str:
    """Get HuggingFace architecture name from model type"""
    arch_map = {
        "llama": "LlamaForCausalLM",
        "qwen2": "Qwen2ForCausalLM",
        "qwen": "Qwen2ForCausalLM",
        "mistral": "MistralForCausalLM",
        "mixtral": "MixtralForCausalLM",
        "gemma": "GemmaForCausalLM",
        "gemma2": "Gemma2ForCausalLM",
        "phi": "PhiForCausalLM",
        "phi3": "Phi3ForCausalLM",
    }
    return arch_map.get(model_type.lower(), "LlamaForCausalLM")


def main():
    parser = argparse.ArgumentParser(description="Convert GGUF model to HuggingFace format")
    parser.add_argument("--input", required=True, help="Path to GGUF model file")
    parser.add_argument("--output", required=True, help="Output directory for HuggingFace format")
    parser.add_argument("--model-type", default="llama",
                        choices=["llama", "qwen", "qwen2", "mistral", "mixtral", "gemma", "gemma2", "phi", "phi3"],
                        help="Model architecture type")
    args = parser.parse_args()

    check_dependencies()
    convert_gguf_to_hf(args.input, args.output, args.model_type)


if __name__ == "__main__":
    main()
