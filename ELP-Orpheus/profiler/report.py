"""ELP-Orpheus 统一报告生成器。

汇总各 stage 采样，计算 mean/p50/p99/max/min/count，对照北极星指标逐项达标，
输出 JSON / 终端表格。

设计决策：
    - 北极星指标（NORTH_STAR_TARGETS）：从 run_e2e.py 与 benchmark_decode.py 的
      目标推导（ft_decode < 1ms / second_chunk_prefill < 5ms / gemma_ttft ≤ 80ms /
      全链路 < 220ms 等），to_table 中逐项标 ✓/✗。
    - compute_stats 复用 benchmark_decode.py 的 _percentile 线性插值算法，
      保证 p50/p99 计算与现有基准一致。
    - to_table 对齐列，含 stage 名/mean/p99/max/count + 目标 + ✓/✗。
    - RTF（Real-Time Factor）= compute_ms / audio_duration_ms，< 1 表示实时。
    - vram / concurrency 字段由 set_vram / set_concurrency 填充。

参考：
    - tests/benchmark_decode.py 的 _stats / _percentile 实现
    - scripts/run_e2e.py 的 targets 达标验证与 _format_report
"""

from __future__ import annotations

import json
from typing import Optional

from .profiler import Profiler, _default_profiler


def _percentile(sorted_vals: list[float], p: float) -> float:
    """计算已排序序列的 p 百分位（线性插值）。

    复用 benchmark_decode.py 的算法，保证 p50/p99 计算一致。
    """
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


class Report:
    """统一报告生成器：汇总 stage 采样 + 北极星达标 + JSON/表格输出。

    用法：
        report = Report(profiler)
        report.add_stage_samples("ft_decode", [0.8, 0.9, 1.1])
        report.set_rtf(compute_ms=50, audio_duration_ms=100)
        print(report.to_table())
        report.to_json("report.json")
    """

    # 北极星指标目标（ms）：stage 名 -> 目标延迟。
    # 来源：run_e2e.py（全链路 < 220ms / 第二 chunk prefill < 5ms / gemma ttft ≤ 80ms）
    #       benchmark_decode.py（单 token decode < 1ms）
    # Task 7 收紧 300ms → 220ms（ASR80 + LLM TTFT60 + Router20 + TTS 首包60）。
    NORTH_STAR_TARGETS: dict[str, float] = {
        "asr": 80.0,            # ASR Partial 延迟（220ms 预算中 80ms）
        "llm_ttft": 60.0,       # LLM 首 token 延迟（220ms 预算中 60ms）
        "router": 20.0,         # Smoother/Router 分块（220ms 预算中 20ms）
        "ft_prefill": 5.0,      # 第二 Chunk 增量 Prefill（< 5ms，对比 vLLM 50ms+）
        "ft_decode": 1.0,       # 单 token Decode（CUDA Graphs ON < 1ms）
        "audio_head": 5.0,     # AudioHead 首 SNAC token
        "generation": 10.0,    # 自回归生成
        "snac_decode": 60.0,   # SNAC 解码（离散 token → PCM）
        "crossfade": 5.0,      # Crossfade 拼接（50ms 重叠）
        "first_packet": 220.0, # 首包延迟（全链路 < 220ms）
        "total": 220.0,         # 全链路总延迟
        "gemma_ttft": 80.0,    # Gemma TTFT（双卡隔离下 ≤ 80ms）
    }

    def __init__(self, profiler: Optional[Profiler] = None) -> None:
        """初始化。

        Args:
            profiler: 关联的 Profiler 实例；None 时用默认单例 _default_profiler。
        """
        self._profiler = profiler if profiler is not None else _default_profiler
        # stage 名 -> 采样列表（ms）
        self._stage_samples: dict[str, list[float]] = {}
        # RTF（Real-Time Factor）
        self._rtf: Optional[float] = None
        self._rtf_compute_ms: Optional[float] = None
        self._rtf_audio_ms: Optional[float] = None
        # 显存
        self._vram: dict = {}
        # 并发流
        self._concurrency: dict = {}

    def add_stage_samples(self, name: str, samples_ms: list[float]) -> None:
        """手动添加某 stage 的采样（ms）。

        若 profiler 中已有同名 stage 采样，会合并；也可独立于 profiler 手动添加。
        """
        existing = self._stage_samples.get(name, [])
        existing.extend(samples_ms)
        self._stage_samples[name] = existing

    def _collect_from_profiler(self) -> None:
        """从关联 Profiler 拉取所有 stage 采样（ms）。"""
        # 通过 clear 前的快照收集：遍历已知 stage 名。
        # 这里不主动 clear，由调用方决定。
        # 已知 stage 名取自 NORTH_STAR_TARGETS 与已添加的 stage。
        names = set(self._stage_samples.keys()) | set(self.NORTH_STAR_TARGETS.keys())
        for name in names:
            samples = self._profiler.get_samples(name)
            if samples:
                self.add_stage_samples(name, samples)

    def compute_stats(self, samples: list[float]) -> dict:
        """由采样列表计算 mean/p50/p99/max/min/count。

        参考 benchmark_decode.py 的 _stats / _percentile。
        """
        if not samples:
            return {
                "mean": 0.0,
                "p50": 0.0,
                "p99": 0.0,
                "max": 0.0,
                "min": 0.0,
                "count": 0,
            }
        s = sorted(samples)
        n = len(s)
        mean = sum(s) / n
        return {
            "mean": mean,
            "p50": _percentile(s, 50),
            "p99": _percentile(s, 99),
            "max": float(s[-1]),
            "min": float(s[0]),
            "count": n,
        }

    def set_rtf(self, compute_ms: float, audio_duration_ms: float) -> None:
        """设置 RTF（Real-Time Factor）= compute_ms / audio_duration_ms。

        RTF < 1 表示实时（计算快于播放）；RTF > 1 表示无法实时。
        """
        self._rtf_compute_ms = float(compute_ms)
        self._rtf_audio_ms = float(audio_duration_ms)
        self._rtf = (
            float(compute_ms) / float(audio_duration_ms)
            if audio_duration_ms > 0
            else float("inf")
        )

    def set_vram(self, peak_mb: float, fragmentation_pct: float) -> None:
        """设置显存峰值与碎片率。"""
        self._vram = {
            "peak_mb": float(peak_mb),
            "fragmentation_pct": float(fragmentation_pct),
        }

    def set_concurrency(self, num_streams: int, ttfa_list: list[float]) -> None:
        """设置并发流信息。

        Args:
            num_streams: 并发流数。
            ttfa_list: 所有流的 TTFA（Time To First Audio）采样（ms）。
        """
        self._concurrency = {
            "num_streams": int(num_streams),
            "ttfa_list": list(ttfa_list),
        }

    def check_targets(self) -> dict[str, bool]:
        """返回每个北极星指标的达标 bool（mean <= target）。

        仅检查有采样的 stage；无采样的 stage 视为未达标（False）。
        """
        result: dict[str, bool] = {}
        for name, target in self.NORTH_STAR_TARGETS.items():
            samples = self._stage_samples.get(name, [])
            if not samples:
                result[name] = False
                continue
            stats = self.compute_stats(samples)
            result[name] = stats["mean"] <= target
        return result

    def to_dict(self) -> dict:
        """返回所有 stage 的 stats + RTF + vram + concurrency + 达标。"""
        stages: dict[str, dict] = {}
        for name, samples in self._stage_samples.items():
            stages[name] = self.compute_stats(samples)

        return {
            "stages": stages,
            "rtf": self._rtf,
            "vram": dict(self._vram) if self._vram else None,
            "concurrency": dict(self._concurrency) if self._concurrency else None,
            "targets": self.check_targets(),
            "north_star_targets": dict(self.NORTH_STAR_TARGETS),
        }

    def to_json(self, path: Optional[str] = None) -> str:
        """JSON 输出。path 非 None 时同时写入文件，返回 JSON 字符串。"""
        data = self.to_dict()
        text = json.dumps(data, ensure_ascii=False, indent=2)
        if path is not None:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        return text

    def to_table(self) -> str:
        """终端表格输出：stage 名/mean/p99/max/count + 目标 + ✓/✗。

        对照北极星指标逐项标 ✓（达标）/✗（未达标 / 无采样）。
        """
        lines: list[str] = []
        lines.append("=" * 80)
        lines.append("ELP-Orpheus Profiler 报告（北极星指标达标对照）")
        lines.append("=" * 80)
        # 表头
        header = f"{'Stage':<16}{'mean(ms)':>10}{'p99(ms)':>10}{'max(ms)':>10}{'count':>8}{'target':>10}  {'status':>6}"
        lines.append(header)
        lines.append("-" * 80)

        targets = self.check_targets()
        # 按北极星目标顺序输出，再追加非目标 stage。
        ordered_names = list(self.NORTH_STAR_TARGETS.keys())
        extra = [n for n in self._stage_samples if n not in self.NORTH_STAR_TARGETS]
        ordered_names.extend(extra)

        for name in ordered_names:
            samples = self._stage_samples.get(name, [])
            stats = self.compute_stats(samples)
            target = self.NORTH_STAR_TARGETS.get(name)
            target_str = f"{target:.1f}" if target is not None else "N/A"
            status = "✓" if targets.get(name, False) else "✗"
            lines.append(
                f"{name:<16}{stats['mean']:>10.3f}{stats['p99']:>10.3f}"
                f"{stats['max']:>10.3f}{stats['count']:>8}{target_str:>10}  {status:>6}"
            )

        lines.append("-" * 80)
        # RTF
        if self._rtf is not None:
            rtf_ok = self._rtf < 1.0
            lines.append(
                f"RTF: {self._rtf:.4f} (compute={self._rtf_compute_ms:.1f}ms / "
                f"audio={self._rtf_audio_ms:.1f}ms) {'✓ 实时' if rtf_ok else '✗ 非实时'}"
            )
        # 显存
        if self._vram:
            lines.append(
                f"VRAM: peak={self._vram['peak_mb']:.1f}MB, "
                f"fragmentation={self._vram['fragmentation_pct']:.2f}%"
            )
        # 并发
        if self._concurrency:
            ttfa = self._concurrency.get("ttfa_list", [])
            if ttfa:
                ttfa_stats = self.compute_stats(ttfa)
                lines.append(
                    f"Concurrency: {self._concurrency['num_streams']} streams, "
                    f"TTFA mean={ttfa_stats['mean']:.3f}ms, p99={ttfa_stats['p99']:.3f}ms"
                )
        lines.append("=" * 80)
        return "\n".join(lines)
