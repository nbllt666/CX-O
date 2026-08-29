#!/usr/bin/env python3
"""GGUF -> HuggingFace safetensors 真实权重转换器（TensorRT-LLM / vLLM 前置）。

功能（相对旧版"只写元数据即宣告完成"的假转换，本版为真正可用的转换器）：
  1. 遍历 GGUF 张量，逐张量反量化后按 HF 标准分片写出：
     model-0000X-of-0000N.safetensors + model.safetensors.index.json（含 total_size/weight_map）
     流式处理：内存中同时持有的反量化张量不超过 --max-shard-gb（默认 2GB）。
  2. GGUF 命名 -> HF 命名映射，按 general.architecture 自动选择 llama 族（含 qwen2/qwen3）
     或 gemma 族的命名规则；未命中映射的张量保留原名写入并计入 unmapped（不静默丢弃）。
  3. config.json 从 GGUF 元数据正确提取：统一走 _field_value(field)（基于 field.contents()）。
     旧版直接取 field.parts[0] 是错的——parts 是整个文件缓冲区的分片列表，字符串字段取到的是
     长度、多值字段取到的是偏移数组；且 numpy 数组直接进 json.dump 会 TypeError。
  4. tokenizer 不重建（诚实边界）：输出目录已有 tokenizer 文件则原样保留；没有则明确警告，
     提示从原始 HF 仓库复制后再用 vLLM/TRT-LLM 加载。

诚实边界（宁缺毋错，反量化能力以运行环境 gguf 库实际覆盖为准）：
  - 支持：F32/F16/F64/I8/I16/I32/I64 直接类型转换；BF16 与当前 gguf.dequantize 覆盖的
    量化格式（Q4_0/Q4_1/Q5_0/Q5_1/Q8_0/Q2_K~Q6_K/IQ 系列/MXFP4/NVFP4 等）反量化为 F32。
  - 不支持：当前环境 dequantize 未覆盖的量化格式（如 Q8_1/Q8_K/Q1_0）——跳过该张量、
    计入 skipped、整体判定"未完成"（退出码 2），绝不含混宣告成功。
  - 只有全部核心张量转换成功才打印 "Conversion complete"。

用法：
  python convert_gguf_to_hf.py --gguf model.gguf --out ./hf_model [--max-shard-gb 2.0]
  运行环境需已安装 gguf/numpy/safetensors 的 Python（本机为 cxa311 conda 环境）。
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

import numpy as np

# gguf 相关导入放模块级但做了防护：无 gguf 环境下 import 本模块不炸，只有真正执行时才报错
try:
    from gguf.constants import GGMLQuantizationType
    from gguf.quants import dequantize as gguf_dequantize

    try:
        # gguf 0.19: _type_traits 记录了 dequantize 实际支持的量化类型（Q8_0/K-quant/IQ 等）
        from gguf.quants import _type_traits as _QUANT_TRAITS

        _SUPPORTED_QUANTS = set(_QUANT_TRAITS)
    except Exception:
        _SUPPORTED_QUANTS = set()
    _GGUF_OK = True
except ImportError as _exc:  # pragma: no cover
    _GGUF_OK = False
    _GGUF_IMPORT_ERROR = _exc
    GGMLQuantizationType = None
    gguf_dequantize = None
    _SUPPORTED_QUANTS = set()


# ================================================================ 通用工具

def _log(level: str, msg: str) -> None:
    """统一终端输出格式：[时间] [级别] 消息"""
    print(f"[{time.strftime('%H:%M:%S')}] [{level}] {msg}", flush=True)


def _check_dependencies() -> None:
    """检查依赖。torch/transformers 不再必需（旧版误列；纯转换只需 gguf/numpy/safetensors）"""
    if not _GGUF_OK:
        _log("ERROR", f"gguf 导入失败: {_GGUF_IMPORT_ERROR}；请 pip install gguf")
        sys.exit(1)
    for name in ("numpy", "safetensors", "safetensors.numpy"):
        try:
            __import__(name)
        except ImportError:
            _log("ERROR", f"缺少依赖 {name}，请先 pip install {name}")
            sys.exit(1)


def _field_value(field):
    """从 GGUFReader 的 ReaderField 提取字段的真实数据值（修复旧版 parts 误用的核心函数）。

    ReaderField.parts 是整个文件数据缓冲区的分片列表；field.data 才是"本字段实际数据"
    在 parts 中的索引列表；field.types 记录类型（标量/字符串/数组）。
    这里统一委托 gguf 官方的 contents()：
      标量 -> int/float/bool；字符串 -> str；数组 -> list（元素同为原生类型）。
    返回值全部为 JSON 原生类型，杜绝 numpy 数组进 json.dump 报 TypeError 的问题。
    """
    if field is None or not getattr(field, "types", None):
        return None
    try:
        return field.contents()
    except Exception:
        # 极端兜底：单索引标量直接 tolist（仍保证 JSON 兼容）
        try:
            if len(field.data) == 1:
                return field.parts[field.data[0]].tolist()[0]
        except Exception:
            pass
    return None


def _get_meta(reader, key: str):
    """按 key 读取一条元数据，字段不存在时返回 None"""
    return _field_value(reader.fields.get(key))


def _prod64(shape) -> int:
    """元素个数（int64 防溢出），空形状返回 1"""
    if not shape:
        return 1
    return int(np.prod([int(d) for d in shape], dtype=np.int64))


# ================================================================ 命名映射

# 全局张量（llama/gemma 两族通用）
_SHARED_NAME_MAP = [
    (r"^token_embd(?:\.weight)?$", "model.embed_tokens.weight"),
    (r"^output_norm(?:\.weight)?$", "model.norm.weight"),
    (r"^output(?:\.weight)?$", "lm_head.weight"),
]

# llama 族（llama/qwen2/qwen3/mistral 等）的逐层张量命名
_LLAMA_LAYER_MAP = [
    (r"^blk\.(\d+)\.attn_norm(?:\.weight)?$", "model.layers.{i}.input_layernorm.weight"),
    (r"^blk\.(\d+)\.ffn_norm(?:\.weight)?$", "model.layers.{i}.post_attention_layernorm.weight"),
    (r"^blk\.(\d+)\.attn_q_norm(?:\.weight)?$", "model.layers.{i}.self_attn.q_norm.weight"),
    (r"^blk\.(\d+)\.attn_k_norm(?:\.weight)?$", "model.layers.{i}.self_attn.k_norm.weight"),
    (r"^blk\.(\d+)\.attn_q(?:\.weight)?$", "model.layers.{i}.self_attn.q_proj.weight"),
    (r"^blk\.(\d+)\.attn_k(?:\.weight)?$", "model.layers.{i}.self_attn.k_proj.weight"),
    (r"^blk\.(\d+)\.attn_v(?:\.weight)?$", "model.layers.{i}.self_attn.v_proj.weight"),
    (r"^blk\.(\d+)\.attn_output(?:\.weight)?$", "model.layers.{i}.self_attn.o_proj.weight"),
    (r"^blk\.(\d+)\.ffn_gate(?:\.weight)?$", "model.layers.{i}.mlp.gate_proj.weight"),
    (r"^blk\.(\d+)\.ffn_up(?:\.weight)?$", "model.layers.{i}.mlp.up_proj.weight"),
    (r"^blk\.(\d+)\.ffn_down(?:\.weight)?$", "model.layers.{i}.mlp.down_proj.weight"),
]

# gemma 族的逐层张量命名（Norm 结构与 llama 族不同；QKV/FFN 同构）
_GEMMA_LAYER_MAP = [
    (r"^blk\.(\d+)\.attn_norm(?:\.weight)?$", "model.layers.{i}.input_layernorm.weight"),
    (r"^blk\.(\d+)\.post_attention_norm(?:\.weight)?$", "model.layers.{i}.post_attention_layernorm.weight"),
    (r"^blk\.(\d+)\.pre_ffw_norm(?:\.weight)?$", "model.layers.{i}.pre_feedforward_layernorm.weight"),
    (r"^blk\.(\d+)\.post_ffw_norm(?:\.weight)?$", "model.layers.{i}.post_feedforward_layernorm.weight"),
    (r"^blk\.(\d+)\.attn_q(?:\.weight)?$", "model.layers.{i}.self_attn.q_proj.weight"),
    (r"^blk\.(\d+)\.attn_k(?:\.weight)?$", "model.layers.{i}.self_attn.k_proj.weight"),
    (r"^blk\.(\d+)\.attn_v(?:\.weight)?$", "model.layers.{i}.self_attn.v_proj.weight"),
    (r"^blk\.(\d+)\.attn_output(?:\.weight)?$", "model.layers.{i}.self_attn.o_proj.weight"),
    (r"^blk\.(\d+)\.ffn_gate(?:\.weight)?$", "model.layers.{i}.mlp.gate_proj.weight"),
    (r"^blk\.(\d+)\.ffn_up(?:\.weight)?$", "model.layers.{i}.mlp.up_proj.weight"),
    (r"^blk\.(\d+)\.ffn_down(?:\.weight)?$", "model.layers.{i}.mlp.down_proj.weight"),
]


def _build_name_mapper(family: str):
    """构建 GGUF 名 -> HF 名 的映射函数。返回 (map_name, 规则条数)"""
    rules = _SHARED_NAME_MAP + (_GEMMA_LAYER_MAP if family == "gemma" else _LLAMA_LAYER_MAP)
    compiled = [(re.compile(pattern), template) for pattern, template in rules]

    def map_name(gguf_name: str):
        for pattern, template in compiled:
            m = pattern.match(gguf_name)
            if m:
                # 层号规则捕获组为数字；全局规则无捕获组
                return template.format(i=m.group(1)) if m.groups() else template
        return None

    return map_name, len(compiled)


# ================================================================ 架构表

# gguf general.architecture -> HF model_type / architectures / 命名族
_ARCH_TABLE = {
    "llama": {"model_type": "llama", "architectures": "LlamaForCausalLM", "family": "llama"},
    "qwen2": {"model_type": "qwen2", "architectures": "Qwen2ForCausalLM", "family": "llama"},
    "qwen3": {"model_type": "qwen3", "architectures": "Qwen3ForCausalLM", "family": "llama"},
    "qwen3moe": {"model_type": "qwen3_moe", "architectures": "Qwen3MoeForCausalLM", "family": "llama"},
    "qwen2moe": {"model_type": "qwen2_moe", "architectures": "Qwen2MoeForCausalLM", "family": "llama"},
    "mistral": {"model_type": "mistral", "architectures": "MistralForCausalLM", "family": "llama"},
    "mixtral": {"model_type": "mixtral", "architectures": "MixtralForCausalLM", "family": "llama"},
    "phi2": {"model_type": "phi2", "architectures": "PhiForCausalLM", "family": "llama"},
    "phi3": {"model_type": "phi3", "architectures": "Phi3ForCausalLM", "family": "llama"},
    "gemma": {"model_type": "gemma", "architectures": "GemmaForCausalLM", "family": "gemma"},
    "gemma2": {"model_type": "gemma2", "architectures": "Gemma2ForCausalLM", "family": "gemma"},
    # gemma3 文本模型的 HF model_type 是 gemma3_text（多模态封装才是 gemma3）
    "gemma3": {"model_type": "gemma3_text", "architectures": "Gemma3ForCausalLM", "family": "gemma"},
    "gemma3n": {"model_type": "gemma3n", "architectures": "Gemma3NForCausalLM", "family": "gemma"},
    "gemma4": {"model_type": "gemma4", "architectures": "Gemma4ForCausalLM", "family": "gemma"},
}


# ================================================================ 张量转换

# 原样/直接类型转换的输出 dtype（F64 降为 F32；BF16 转 F32，见下）。
# 惰性构建：无 gguf 环境下 GGMLQuantizationType 为 None，模块级直接建 dict 会 AttributeError
_OUT_DTYPE_MAP = None


def _get_out_dtype_map() -> dict:
    global _OUT_DTYPE_MAP
    if _OUT_DTYPE_MAP is None:
        _OUT_DTYPE_MAP = {
            GGMLQuantizationType.F32: np.float32,
            GGMLQuantizationType.F16: np.float16,  # 保留 F16，无损
            GGMLQuantizationType.F64: np.float32,
            GGMLQuantizationType.I8: np.int8,
            GGMLQuantizationType.I16: np.int16,
            GGMLQuantizationType.I32: np.int32,
            GGMLQuantizationType.I64: np.int64,
            # safetensors.numpy 后端无 bf16 存储，BF16 统一转 F32
            GGMLQuantizationType.BF16: np.float32,
        }
    return _OUT_DTYPE_MAP


def _out_dtype(tensor_type):
    """决定输出 dtype；返回 None 表示当前环境无法处理该格式（诚实跳过）"""
    dtype_map = _get_out_dtype_map()
    if tensor_type in dtype_map:
        return dtype_map[tensor_type]
    if tensor_type in _SUPPORTED_QUANTS:
        return np.float32  # 反量化输出固定 float32
    return None


def _convert_array(data, tensor_type, expected_shape):
    """单张量转换核心（纯函数，便于测试）。返回 (arr, note, skip_reason) 三元组。

    - 成功: (np.ndarray, 精度说明或 None, None)
    - 不支持/异常: (None, None, 原因字符串)

    说明：GGUFReader 的 .data 已按小端字节序视图化（Windows 小端宿主无需 byteswap）；
    F16/F32 为带类型 numpy 视图，量化类型为 byte-shaped uint8（reader 已做
    quant_shape_to_byte_shape 变形），gguf.dequantize 接收后返回 float32 逻辑形状。
    """
    t = tensor_type
    note = None
    if t in (GGMLQuantizationType.F32, GGMLQuantizationType.F16):
        # reader 已给出带类型视图（小端），保持原精度直接写
        arr = np.ascontiguousarray(data)
    elif t == GGMLQuantizationType.F64:
        arr = np.ascontiguousarray(data).astype(np.float32)
        note = "F64 -> F32"
    elif t in (GGMLQuantizationType.I8, GGMLQuantizationType.I16,
               GGMLQuantizationType.I32, GGMLQuantizationType.I64):
        arr = np.ascontiguousarray(data)
    elif t == GGMLQuantizationType.BF16:
        # BF16 无法以 numpy 原生 dtype 存入 safetensors.numpy，走 dequantize 转 F32
        arr = gguf_dequantize(data, t)
        note = "BF16 -> F32"
    else:
        # 其余为量化类型：byte-shaped uint8 -> dequantize -> float32
        if t not in _SUPPORTED_QUANTS:
            return None, None, (f"不支持的量化格式 {t.name}（当前 gguf 环境 dequantize 未覆盖，"
                                f"覆盖范围见启动日志）")
        try:
            arr = gguf_dequantize(data, t)
        except Exception as exc:
            return None, None, f"dequantize 执行失败（{t.name}）: {exc}"

    if arr is None or tuple(arr.shape) != tuple(expected_shape):
        got = None if arr is None else tuple(arr.shape)
        return None, None, f"反量化后形状 {got} 与期望 {tuple(expected_shape)} 不一致（数据区读取异常）"
    return np.ascontiguousarray(arr, dtype=arr.dtype), note, None


# ================================================================ config 生成

# GGUF 元数据字段后缀 -> HF config.json 字段（实际读取时加 "{arch}." 前缀，并回退 "llama." 前缀）
_META_SUFFIX_TO_HF = [
    ("embedding_length", "hidden_size"),
    ("block_count", "num_hidden_layers"),
    ("attention.head_count", "num_attention_heads"),
    ("attention.head_count_kv", "num_key_value_heads"),
    ("feed_forward_length", "intermediate_size"),
    ("context_length", "max_position_embeddings"),
    ("rope.freq_base", "rope_theta"),
    ("attention.layer_norm_rms_epsilon", "rms_norm_eps"),
    ("attention.key_length", "head_dim"),
    ("attention.sliding_window", "sliding_window"),
]

# 缺失时仅告警不瞎填的关键字段（旧版会编造默认值，属于假转换行为，已移除）
_REQUIRED_CONFIG_KEYS = ("hidden_size", "num_hidden_layers", "num_attention_heads",
                         "intermediate_size", "max_position_embeddings")


def _build_config(reader, arch_raw: str, hf_info: dict, vocab_size, tie: bool, torch_dtype: str) -> dict:
    """从 GGUF 元数据构建 config.json（全部为 JSON 原生值）"""
    config = {
        "architectures": [hf_info["architectures"]],
        "model_type": hf_info["model_type"],
        "torch_dtype": torch_dtype,
        "tie_word_embeddings": tie,
    }
    prefix = f"{arch_raw}."
    for suffix, hf_key in _META_SUFFIX_TO_HF:
        val = _get_meta(reader, prefix + suffix)
        if val is None:
            # 旧版 GGUF（llama.cpp 较早版本）对多架构统一写 llama.* 前缀，做回退
            val = _get_meta(reader, "llama." + suffix)
        if val is not None:
            config[hf_key] = val

    # vocab_size：优先用 token_embd 实际行数（比元数据更可靠），其次元数据字段
    if vocab_size is not None:
        config["vocab_size"] = int(vocab_size)
    else:
        v = _get_meta(reader, prefix + "vocab_size") or _get_meta(reader, "llama.vocab_size")
        if v is not None:
            config["vocab_size"] = int(v)

    # 未写 head_count_kv 的老文件视为 MHA（结构推导，非编造）
    if "num_key_value_heads" not in config and "num_attention_heads" in config:
        config["num_key_value_heads"] = config["num_attention_heads"]

    # 特殊 token id（GGUF 内为标量，安全读取）
    for gguf_key, hf_key in (("tokenizer.ggml.eos_token_id", "eos_token_id"),
                             ("tokenizer.ggml.bos_token_id", "bos_token_id")):
        v = _get_meta(reader, gguf_key)
        if v is not None:
            config[hf_key] = int(v)

    # 关键字段缺失检查：只告警，不编造默认值
    missing = [k for k in _REQUIRED_CONFIG_KEYS if k not in config]
    if missing:
        _log("WARN", f"config.json 缺少关键字段 {missing}（GGUF 元数据中未找到），请人工核对补全")
    return config


# ================================================================ 分片规划

def _plan_shards(entries, max_bytes: int):
    """按文件顺序贪心打包分片（规划阶段不做反量化，仅按输出字节量计算）。
    单张量超过阈值时独占一个分片（不无限循环）。"""
    shards, cur, cur_bytes = [], [], 0
    for entry in entries:
        nb = entry["nbytes"]
        if cur and cur_bytes + nb > max_bytes:
            shards.append(cur)
            cur, cur_bytes = [], 0
        cur.append(entry)
        cur_bytes += nb
    if cur:
        shards.append(cur)
    return shards


# ================================================================ 主流程

def convert_gguf_to_hf(gguf_path, out_dir, max_shard_gb: float = 2.0, model_type=None) -> dict:
    """GGUF -> HF 转换主入口。返回统计 dict；存在跳过张量时 complete=False（由调用方决定退出码）。"""
    if not _GGUF_OK:
        raise RuntimeError(f"gguf 导入失败: {_GGUF_IMPORT_ERROR}；请 pip install gguf")

    from gguf import GGUFReader

    gguf_path = Path(gguf_path)
    out_dir = Path(out_dir)
    if not gguf_path.exists():
        raise FileNotFoundError(f"GGUF 文件不存在: {gguf_path}")
    out_dir.mkdir(parents=True, exist_ok=True)
    max_shard_bytes = max(1, int(max_shard_gb * (1024 ** 3)))

    # 清理本工具历史产物（2026-08-29 收窄为"清单内文件"）：不再 glob model*.safetensors
    # （会误删输出目录中 model 开头的用户文件）。清单来源（shards+index）：
    #   - 多分片：旧 model.safetensors.index.json 的 weight_map——本工具写出的权威文件清单；
    #   - 单分片：固定命名 model.safetensors（本工具确定性输出名）。
    # tokenizer 等用户文件一律不动；索引解析失败时跳过分片清理并告警（宁残留、不误删）。
    _stale: set = set()
    old_index = out_dir / "model.safetensors.index.json"
    if old_index.exists():
        _stale.add(old_index.name)
        try:
            _wm = json.loads(old_index.read_text(encoding="utf-8")).get("weight_map", {})
            _stale |= {Path(v).name for v in _wm.values() if isinstance(v, str)}
        except Exception as exc:
            _log("WARN", f"旧分片索引解析失败，跳过历史分片清理（仅删索引本身）: {exc}")
    _stale.add("model.safetensors")
    for name in sorted(_stale):
        old = out_dir / name
        if old.exists():
            old.unlink()
            _log("INFO", f"清理历史产物: {old.name}")

    _log("INFO", f"读取 GGUF: {gguf_path}")
    reader = GGUFReader(str(gguf_path))
    if not reader.tensors:
        raise ValueError("GGUF 文件中没有任何张量")

    quant_names = sorted(t.name for t in _SUPPORTED_QUANTS)
    _log("INFO", f"当前 gguf 环境 dequantize 支持的量化格式({len(quant_names)}): {', '.join(quant_names)}")

    # ---- 架构识别 ----
    arch_raw = _get_meta(reader, "general.architecture")
    if not arch_raw:
        arch_raw = "llama"
        _log("WARN", "元数据缺少 general.architecture，按 llama 处理，请人工核对 config.json")
    arch_raw = str(arch_raw)
    hf_info = _ARCH_TABLE.get(arch_raw.lower())
    if model_type:
        override = _ARCH_TABLE.get(str(model_type).lower())
        if override:
            hf_info = override
        else:
            # 未知架构：如实使用用户给的值 + llama 族命名，并显式告警
            hf_info = {"model_type": str(model_type), "architectures": None, "family": "llama"}
        _log("INFO", f"使用 --model-type 覆盖: {model_type}")
    if hf_info is None:
        hf_info = {"model_type": arch_raw.lower(), "architectures": None, "family": "llama"}
        _log("WARN", f"未知架构 '{arch_raw}'，model_type 按原样写入、命名按 llama 族处理，请人工核对")
    if hf_info["architectures"] is None:
        hf_info["architectures"] = arch_raw.capitalize() + "ForCausalLM"
        _log("WARN", f"architectures 为推测值 {hf_info['architectures']}，请人工核对 config.json")
    family = hf_info["family"]
    map_name, rule_count = _build_name_mapper(family)
    _log("INFO", f"架构: {arch_raw} -> model_type={hf_info['model_type']}, "
                 f"architectures={hf_info['architectures']}, 命名族={family}, 映射规则 {rule_count} 条")

    # ---- 第一遍：规划（命名映射 + 输出 dtype + 分片，不做反量化） ----
    entries = []
    skipped = []
    unmapped = []
    for idx, rt in enumerate(reader.tensors):
        np_shape = tuple(int(d) for d in reversed([int(x) for x in rt.shape]))
        if rt.n_elements == 0:
            skipped.append({"name": rt.name, "type": rt.tensor_type.name, "reason": "零元素张量"})
            continue
        out_dtype = _out_dtype(rt.tensor_type)
        if out_dtype is None:
            skipped.append({"name": rt.name, "type": rt.tensor_type.name,
                            "reason": f"不支持的量化格式 {rt.tensor_type.name}（当前 gguf 环境 "
                                      f"dequantize 未覆盖）"})
            continue
        hf_name = map_name(rt.name)
        if hf_name is None:
            unmapped.append(rt.name)
            hf_name = rt.name  # 保留原名写入，不静默丢弃
        entries.append({
            "index": idx, "gguf_name": rt.name, "hf_name": hf_name,
            "np_shape": np_shape, "out_dtype": out_dtype,
            "nbytes": _prod64(np_shape) * np.dtype(out_dtype).itemsize,
        })

    shards_plan = _plan_shards(entries, max_shard_bytes)
    _log("INFO", f"规划完成: 可转换 {len(entries)} 张量 / 跳过 {len(skipped)} / 未映射 {len(unmapped)}，"
                 f"分 {len(shards_plan)} 片（上限 {max_shard_gb} GB/片）")

    # ---- config.json ----
    has_lm_head = any(e["gguf_name"] in ("output.weight", "output") for e in entries)
    vocab_size = next((e["np_shape"][0] for e in entries if e["gguf_name"].startswith("token_embd")), None)
    out_dtypes = {e["out_dtype"] for e in entries}
    torch_dtype = "float16" if out_dtypes == {np.float16} else "float32"
    config = _build_config(reader, arch_raw, hf_info, vocab_size, tie=not has_lm_head, torch_dtype=torch_dtype)
    config_path = out_dir / "config.json"
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=True)
    _log("INFO", f"写出 config.json（{len(config)} 字段）")

    # ---- 第二遍：逐分片转换写盘（流式，峰值内存约等于单分片大小 + 转换临时量） ----
    from safetensors.numpy import save_file

    n_shards = len(shards_plan)
    weight_map = {}
    total_size = 0
    converted = 0
    notes = set()
    for si, shard in enumerate(shards_plan):
        fname = "model.safetensors" if n_shards == 1 else f"model-{si + 1:05d}-of-{n_shards:05d}.safetensors"
        tensors_out = {}
        for entry in shard:
            rt = reader.get_tensor(entry["index"])
            arr, note, skip = _convert_array(rt.data, rt.tensor_type, entry["np_shape"])
            if skip is not None:
                # 规划与执行判定不一致属内部错误，必须整体失败（不得假完成）
                raise RuntimeError(f"张量转换失败: {entry['gguf_name']}: {skip}")
            if note:
                notes.add(note)
            if entry["hf_name"] in tensors_out:
                raise RuntimeError(f"输出张量重名: {entry['hf_name']}")
            tensors_out[entry["hf_name"]] = arr
        save_file(tensors_out, str(out_dir / fname))
        for key in tensors_out:
            weight_map[key] = fname
        shard_bytes = sum(e["nbytes"] for e in shard)
        total_size += shard_bytes
        converted += len(shard)
        _log("INFO", f"写出分片 {fname}: {len(shard)} 张量, {shard_bytes / 1048576:.2f} MiB")

    for note in sorted(notes):
        _log("WARN", f"精度说明（全部受影响张量）: {note}")

    # ---- 分片索引（单分片时按 HF 惯例不写 index） ----
    index_path = None
    if n_shards > 1:
        index_path = out_dir / "model.safetensors.index.json"
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump({"metadata": {"total_size": total_size}, "weight_map": weight_map},
                      f, indent=2, ensure_ascii=True)
        _log("INFO", f"写出分片索引: {index_path.name}（weight_map {len(weight_map)} 项）")

    # ---- tokenizer 检查（GGUF 内嵌词表不重建，诚实边界） ----
    tok_files = ["tokenizer.json", "tokenizer_config.json", "special_tokens_map.json"]
    present = [name for name in tok_files if (out_dir / name).exists()]
    if present:
        _log("INFO", f"检测到已有 tokenizer 文件，原样保留: {', '.join(present)}")
    else:
        _log("WARN", "tokenizer 未生成（GGUF 内嵌词表不重建）。请从原始 HF 仓库复制 "
                     "tokenizer.json / tokenizer_config.json / special_tokens_map.json "
                     "到输出目录后，再用 vLLM/TRT-LLM 加载。")

    # ---- 摘要 ----
    complete = converted > 0 and not skipped
    _log("INFO", "================== 转换摘要 ==================")
    _log("INFO", f"转换张量: {converted} | 跳过: {len(skipped)} | 未映射: {len(unmapped)} | "
                 f"分片: {n_shards} | 总大小: {total_size / 1048576:.2f} MiB")
    for s in skipped:
        _log("ERROR", f"跳过张量 {s['name']} [{s['type']}]: {s['reason']}")
    for name in unmapped:
        _log("WARN", f"未映射张量（保留原名写入，未丢弃）: {name}")
    if complete:
        _log("INFO", "Conversion complete. 输出目录: " + str(out_dir))
        _log("INFO", "后续步骤: 1) 确认 tokenizer 文件齐全；"
                     "2) vLLM: vllm serve <输出目录>；"
                     "3) TRT-LLM: 用 tensorrt_llm.commands.build 以 --model_dir 指向输出目录构建引擎。")
    else:
        _log("ERROR", "Conversion incomplete: 存在无法转换/被跳过的张量，详见上方摘要。"
                      "不得将本目录交付加载。")

    return {
        "converted": converted,
        "skipped": skipped,
        "unmapped": unmapped,
        "shards": n_shards,
        "total_bytes": total_size,
        "complete": complete,
        "output_dir": str(out_dir),
        "config_path": str(config_path),
        "index_path": str(index_path) if index_path else None,
        "weight_map": weight_map,
    }


# ================================================================ CLI

def main() -> None:
    parser = argparse.ArgumentParser(description="GGUF -> HuggingFace safetensors 真实权重转换器")
    parser.add_argument("--gguf", "--input", dest="gguf", required=True, help="GGUF 模型文件路径")
    parser.add_argument("--out", "--output", dest="out", required=True, help="输出目录（HF 格式）")
    parser.add_argument("--max-shard-gb", type=float, default=2.0,
                        help="单个 safetensors 分片大小上限（GB），默认 2.0")
    parser.add_argument("--model-type", default=None,
                        help="手动指定架构（默认从 general.architecture 自动识别），如 qwen3/gemma3")
    args = parser.parse_args()

    _check_dependencies()
    try:
        stats = convert_gguf_to_hf(args.gguf, args.out, args.max_shard_gb, args.model_type)
    except Exception as exc:
        _log("ERROR", f"转换失败: {exc}")
        sys.exit(2)
    sys.exit(0 if stats["complete"] else 2)


if __name__ == "__main__":
    main()
