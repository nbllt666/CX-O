"""Decode 阶段单 token 延迟基准测试。

验证 CUDA Graphs 开启后 Decode 单 token 延迟 < 1ms。
对比：CUDA Graphs ON vs OFF。

可独立运行：
    python tests/benchmark_decode.py
也可作为 pytest 接口被 tests/test_cuda_graph.py 导入调用。

注意：真实 FT 在开发环境可能未编译，本脚本用 MockFTLlama 跑基准，结果标注 'mock'，
真实性能验证需在双卡 Linux 服务器 + FT 编译环境进行。
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import time

import torch

# 支持直接 `python tests/benchmark_decode.py` 运行：将项目根目录加入 sys.path。
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_THIS_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from ft_engine import OrpheusFTEngine  # noqa: E402


# ============================================================================
# 辅助函数
# ============================================================================

def _is_cuda(engine: OrpheusFTEngine) -> bool:
    """判断引擎是否运行在 CUDA 设备上（决定是否需要 synchronize）。"""
    return getattr(engine, "device", torch.device("cpu")).type == "cuda"


def _maybe_synchronize(engine: OrpheusFTEngine) -> None:
    """GPU 上同步 CUDA 流，确保计时准确；CPU 上为空操作。

    为什么需要同步：CUDA kernel launch 是异步的，time.perf_counter() 只记录
    launch 时刻而非 kernel 完成时刻。不 sync 会得到远小于真实延迟的数值，
    使基准失去意义。
    """
    if _is_cuda(engine):
        torch.cuda.synchronize(engine.device)


def _percentile(sorted_vals: list[float], p: float) -> float:
    """计算已排序序列的 p 百分位（线性插值），避免引入 numpy 依赖。"""
    if not sorted_vals:
        return float("nan")
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    k = (len(sorted_vals) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return float(sorted_vals[f])
    return float(sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f))


def _stats(latencies: list[float]) -> dict:
    """由延迟列表计算 mean/p99/min（单位 ms）。"""
    if not latencies:
        return {"mean_ms": float("nan"), "p99_ms": float("nan"), "min_ms": float("nan")}
    s = sorted(latencies)
    mean = sum(s) / len(s)
    return {
        "mean_ms": mean,
        "p99_ms": _percentile(s, 99),
        "min_ms": float(s[0]),
    }


def _extract_engine_config(engine: OrpheusFTEngine) -> dict:
    """从引擎提取构造参数，用于创建 CUDA Graphs ON/OFF 对比引擎。

    benchmark_decode_latency 需对比 ON/OFF 两种配置，因此从传入引擎提取参数
    重建两个实例（仅 cuda_graph 不同），保证对比变量唯一。
    """
    return {
        "checkpoint_path": engine._checkpoint_path,
        "gpu_id": engine._gpu_id,
        "tensor_para_size": engine._tensor_para_size,
        "pipeline_para_size": engine._pipeline_para_size,
        "data_type": engine._data_type,
        "max_seq_len": engine._max_seq_len,
        "max_batch_size": engine._max_batch_size,
        "hidden_dim": engine._hidden_dim,
        "num_layers": engine._num_layers,
        "vocab_size": engine._vocab_size,
    }


def _measure_decode_single_token(
    engine: OrpheusFTEngine, num_warmup: int, num_iters: int
) -> list[float]:
    """测量单 token Decode 延迟，返回每次迭代延迟列表（ms）。

    流程：
        1. 每次迭代先 reset + prefill 少量 token 填充 KV Cache（不计入计时）。
        2. 计时一次 generation_forward(max_new_tokens=1)（单 token Decode 全路径）。
        3. warmup 迭代不计入统计。

    为什么每次 reset + prefill：generation_forward 会推进 current_seq_len，
    多次迭代后会超出 max_seq_len 越界。每次 reset + 少量 prefill 保证状态可控，
    且 prefill 在计时区外，不影响 Decode 延迟测量。
    """
    cfg = _extract_engine_config(engine)
    vocab = cfg["vocab_size"]
    batch = cfg["max_batch_size"]
    prefill_len = 4  # 预填 4 个 token 作为上下文

    # warmup（不计入统计）：让 JIT/Mock 路径稳定，避免首次冷启动毛刺。
    for _ in range(num_warmup):
        engine.reset_cache()
        prefill_ids = torch.randint(0, vocab, (batch, prefill_len), dtype=torch.long)
        engine.context_forward(prefill_ids, engine.kv_cache, 0, prefill_len)
        start_token = torch.randint(0, vocab, (batch, 1), dtype=torch.long)
        _maybe_synchronize(engine)
        engine.generation_forward(
            start_token=start_token,
            kv_cache=engine.kv_cache,
            current_step=engine.current_seq_len,
            max_new_tokens=1,
        )
        _maybe_synchronize(engine)

    # 正式测量：每次 reset+prefill 后计时单 token Decode。
    latencies: list[float] = []
    for _ in range(num_iters):
        engine.reset_cache()
        prefill_ids = torch.randint(0, vocab, (batch, prefill_len), dtype=torch.long)
        engine.context_forward(prefill_ids, engine.kv_cache, 0, prefill_len)
        start_token = torch.randint(0, vocab, (batch, 1), dtype=torch.long)

        _maybe_synchronize(engine)
        t0 = time.perf_counter()
        engine.generation_forward(
            start_token=start_token,
            kv_cache=engine.kv_cache,
            current_step=engine.current_seq_len,
            max_new_tokens=1,
        )
        _maybe_synchronize(engine)
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000.0)

    return latencies


# ============================================================================
# 基准测试主接口
# ============================================================================

def benchmark_decode_latency(
    engine: OrpheusFTEngine, num_warmup: int = 10, num_iters: int = 100
) -> dict:
    """基准测试 Decode 单 token 延迟。

    对比 CUDA Graphs ON vs OFF 下的单 token Decode 延迟（mean/p99/min），
    计算加速比，并判断是否达标（cuda_graph_on mean_ms < 1.0ms）。

    Args:
        engine: OrpheusFTEngine 实例（作为配置模板，内部据此创建 ON/OFF 两个引擎）。
        num_warmup: warmup 迭代次数（不计入统计）。
        num_iters: 正式测量迭代次数。

    Returns:
        {
            'cuda_graph_on': {'mean_ms', 'p99_ms', 'min_ms'},
            'cuda_graph_off': {'mean_ms', 'p99_ms', 'min_ms'},
            'speedup': float,            # OFF mean / ON mean
            'target_met': bool,          # cuda_graph_on mean_ms < 1.0
            'backend': str,              # 'ft' 或 'mock'
            'mock': bool                 # 是否为 Mock 路径（真实性能需 FT 环境）
        }
    """
    cfg = _extract_engine_config(engine)

    # 创建 CUDA Graphs ON / OFF 两个引擎，仅 cuda_graph 不同，其余参数一致。
    on_engine = OrpheusFTEngine(cuda_graph=True, **cfg)
    off_engine = OrpheusFTEngine(cuda_graph=False, **cfg)

    # 测量 ON/OFF 延迟。
    on_lat = _measure_decode_single_token(on_engine, num_warmup, num_iters)
    off_lat = _measure_decode_single_token(off_engine, num_warmup, num_iters)

    on_stats = _stats(on_lat)
    off_stats = _stats(off_lat)

    # 加速比：OFF mean / ON mean（>1 表示 ON 更快）。
    speedup = (
        off_stats["mean_ms"] / on_stats["mean_ms"]
        if on_stats["mean_ms"] > 0
        else float("inf")
    )

    # 达标判定：CUDA Graphs ON 下单 token Decode mean < 1ms。
    target_met = on_stats["mean_ms"] < 1.0

    backend = on_engine.backend
    is_mock = backend == "mock"

    return {
        "cuda_graph_on": on_stats,
        "cuda_graph_off": off_stats,
        "speedup": speedup,
        "target_met": target_met,
        "backend": backend,
        "mock": is_mock,
    }


def benchmark_prefill_latency(
    engine: OrpheusFTEngine, chunk_lens: list[int]
) -> dict:
    """基准测试 Prefill（Context Encoding）延迟。

    验证第二 Chunk 增量 Prefill < 5ms（对比 vLLM 50ms+）。

    为什么关注第二 Chunk：
        第一 Chunk 是冷启动 Prefill（含初始化开销），第二 Chunk 起为增量 Prefill，
        复用已写入的连续 KV Cache，FT 只对新 token 做前向，是稳定态性能的代表指标。

    Args:
        engine: OrpheusFTEngine 实例。
        chunk_lens: 各 Chunk 的 token 长度列表，如 [3, 4, 20, 5]。

    Returns:
        {
            'chunk_latencies_ms': list[float],  # 各 Chunk 增量 Prefill 延迟
            'second_chunk_ms': float,           # 第二 Chunk 延迟（重点指标）
            'target_met': bool,                 # second_chunk_ms < 5.0
            'backend': str,
            'mock': bool
        }
    """
    cfg = _extract_engine_config(engine)
    vocab = cfg["vocab_size"]
    batch = cfg["max_batch_size"]
    max_seq_len = cfg["max_seq_len"]

    # warmup：完整跑一遍各 Chunk，让 JIT/Mock 路径稳定。
    engine.reset_cache()
    step = 0
    for cl in chunk_lens:
        if step + cl > max_seq_len:
            break
        ids = torch.randint(0, vocab, (batch, cl), dtype=torch.long)
        engine.context_forward(ids, engine.kv_cache, step, cl)
        step += cl

    # 正式测量：reset 后增量 Prefill 各 Chunk，分别计时。
    engine.reset_cache()
    latencies: list[float] = []
    step = 0
    for cl in chunk_lens:
        if step + cl > max_seq_len:
            # 超出 KV Cache 容量，停止测量（避免越界）。
            break
        ids = torch.randint(0, vocab, (batch, cl), dtype=torch.long)
        _maybe_synchronize(engine)
        t0 = time.perf_counter()
        engine.context_forward(ids, engine.kv_cache, step, cl)
        _maybe_synchronize(engine)
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000.0)
        step += cl

    second_chunk_ms = latencies[1] if len(latencies) >= 2 else float("nan")
    target_met = (
        len(latencies) >= 2
        and not math.isnan(second_chunk_ms)
        and second_chunk_ms < 5.0
    )

    return {
        "chunk_latencies_ms": latencies,
        "second_chunk_ms": second_chunk_ms,
        "target_met": target_met,
        "backend": engine.backend,
        "mock": engine.backend == "mock",
    }


# ============================================================================
# 命令行入口
# ============================================================================

def _format_stats(stats: dict) -> str:
    """格式化统计字典为可读字符串。"""
    return (
        f"mean={stats['mean_ms']:.4f}ms, "
        f"p99={stats['p99_ms']:.4f}ms, "
        f"min={stats['min_ms']:.4f}ms"
    )


def main() -> None:
    """命令行入口：运行基准测试并打印报告。"""
    parser = argparse.ArgumentParser(
        description="ELP-Orpheus Decode/Prefill 延迟基准"
    )
    parser.add_argument(
        "--checkpoint",
        default="/dev/null/mocked",
        help="FT checkpoint 路径（Mock 路径不实际读取）",
    )
    parser.add_argument(
        "--gpu-id", type=int, default=99, help="GPU 索引（99=CPU 回退，开发环境用）"
    )
    parser.add_argument(
        "--max-seq-len", type=int, default=32, help="KV Cache 最大序列长度"
    )
    parser.add_argument("--hidden-dim", type=int, default=64, help="隐藏维度（Mock 用）")
    parser.add_argument("--num-layers", type=int, default=2, help="层数（Mock 用）")
    parser.add_argument(
        "--vocab-size", type=int, default=100, help="词表大小（Mock 用）"
    )
    parser.add_argument("--warmup", type=int, default=10, help="warmup 迭代次数")
    parser.add_argument("--iters", type=int, default=100, help="正式测量迭代次数")
    parser.add_argument(
        "--chunk-lens",
        nargs="+",
        type=int,
        default=[3, 4, 20, 5],
        help="各 Chunk token 长度列表",
    )
    args = parser.parse_args()

    # 构造引擎（开发环境默认走 Mock，真实 FT 需编译）。
    engine = OrpheusFTEngine(
        checkpoint_path=args.checkpoint,
        gpu_id=args.gpu_id,
        data_type="fp16",
        cuda_graph=True,
        max_seq_len=args.max_seq_len,
        max_batch_size=1,
        hidden_dim=args.hidden_dim,
        num_layers=args.num_layers,
        vocab_size=args.vocab_size,
    )

    print("=" * 70)
    print("ELP-Orpheus Decode / Prefill 延迟基准测试")
    print("=" * 70)
    mock_hint = "（Mock，真实性能需 FT 编译环境）" if engine.backend == "mock" else ""
    print(f"后端: {engine.backend}{mock_hint}")
    print()

    # 1. Decode 单 token 延迟基准
    print("-" * 70)
    print("[1] Decode 单 token 延迟（目标: CUDA Graphs ON mean < 1ms）")
    print("-" * 70)
    decode_result = benchmark_decode_latency(engine, args.warmup, args.iters)
    print(f"  CUDA Graphs ON : {_format_stats(decode_result['cuda_graph_on'])}")
    print(f"  CUDA Graphs OFF: {_format_stats(decode_result['cuda_graph_off'])}")
    print(f"  加速比        : {decode_result['speedup']:.3f}x")
    print(f"  达标 (<1ms)   : {'是' if decode_result['target_met'] else '否'}")
    print()

    # 2. Prefill 增量延迟基准
    print("-" * 70)
    print("[2] Prefill 增量延迟（目标: 第二 Chunk < 5ms，对比 vLLM 50ms+）")
    print("-" * 70)
    prefill_result = benchmark_prefill_latency(engine, args.chunk_lens)
    for i, lat in enumerate(prefill_result["chunk_latencies_ms"]):
        chunk_len = args.chunk_lens[i] if i < len(args.chunk_lens) else "?"
        marker = "  <- 第二 Chunk（重点指标）" if i == 1 else ""
        print(f"  Chunk {i + 1} (len={chunk_len}): {lat:.4f}ms{marker}")
    print(f"  第二 Chunk 延迟: {prefill_result['second_chunk_ms']:.4f}ms")
    print(f"  达标 (<5ms)    : {'是' if prefill_result['target_met'] else '否'}")
    print()

    if decode_result.get("mock") or prefill_result.get("mock"):
        print("注意: 当前为 Mock 路径，延迟数值不代表真实 FT 性能。")
        print("      真实性能验证需在双卡 Linux 服务器 + FT 编译环境进行。")

    print("=" * 70)


if __name__ == "__main__":
    main()
