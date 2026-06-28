"""ELP-Orpheus 并发流负载测试。

并发跑 num_streams 个流，每流 num_iters 轮，采集 TTFA（Time To First Audio），
计算 p50/p99/max/rtf，组装成 Report。

设计决策：
    - 用 concurrent.futures.ThreadPoolExecutor 并发执行流（模拟多路 TTS 并发）。
    - 每流调用 stream_fn(stream_id) 返回该流本轮 TTFA（ms），汇总后计算统计。
    - rtf = mean_ttfa / target_ttfa（默认 target=300ms，全链路预算）。
    - to_report 将 TTFA 采样注入 Report 的 first_packet stage，与北极星指标对照。

参考：
    - scripts/run_e2e.py 的并发工作负载（threading.Thread 启动 TTS 工作负载）
    - tests/benchmark_decode.py 的 _stats / _percentile 统计
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from .report import Report, _percentile


class ConcurrentRunner:
    """并发流负载测试器。

    用法：
        runner = ConcurrentRunner(num_streams=4)
        def stream_fn(stream_id):
            # 模拟 TTS 流，返回 TTFA（ms）
            return 50.0
        result = runner.run(stream_fn, num_iters=100)
        print(result["p99"])
        report = runner.to_report()
        print(report.to_table())
    """

    # 全链路 TTFA 目标（ms），用于 rtf 计算。
    _TARGET_TTFA_MS = 300.0

    def __init__(self, num_streams: int = 4) -> None:
        """初始化。

        Args:
            num_streams: 并发流数（默认 4，对应双卡 4 路 TTS 并发）。
        """
        self._num_streams = max(1, int(num_streams))
        self._per_stream_ttfa: list[list[float]] = []
        self._all_ttfa: list[float] = []

    def run(self, stream_fn: Callable[[int], float], num_iters: int = 100) -> dict:
        """并发跑 num_streams 流 × num_iters 轮。

        Args:
            stream_fn: 接收 stream_id 返回本轮 TTFA（ms）的可调用对象。
            num_iters: 每流迭代轮数。

        Returns:
            collect() 的结果字典。
        """
        self._per_stream_ttfa = [[] for _ in range(self._num_streams)]
        n_iters = max(1, int(num_iters))

        def _run_stream(stream_id: int) -> None:
            for _ in range(n_iters):
                ttfa = float(stream_fn(stream_id))
                self._per_stream_ttfa[stream_id].append(ttfa)

        with ThreadPoolExecutor(max_workers=self._num_streams) as executor:
            futures = [
                executor.submit(_run_stream, i) for i in range(self._num_streams)
            ]
            for f in futures:
                f.result()

        # 汇总所有 TTFA
        self._all_ttfa = [
            ttfa for stream in self._per_stream_ttfa for ttfa in stream
        ]
        return self.collect()

    def collect(self) -> dict:
        """返回汇总字典：per_stream_ttfa / all_ttfa / p50 / p99 / max / rtf。"""
        if not self._all_ttfa:
            return {
                "per_stream_ttfa": [],
                "all_ttfa": [],
                "p50": 0.0,
                "p99": 0.0,
                "max": 0.0,
                "rtf": 0.0,
            }
        s = sorted(self._all_ttfa)
        p50 = _percentile(s, 50)
        p99 = _percentile(s, 99)
        mean = sum(s) / len(s)
        rtf = mean / self._TARGET_TTFA_MS if self._TARGET_TTFA_MS > 0 else float("inf")
        return {
            "per_stream_ttfa": [list(stream) for stream in self._per_stream_ttfa],
            "all_ttfa": list(self._all_ttfa),
            "p50": p50,
            "p99": p99,
            "max": float(s[-1]),
            "rtf": rtf,
        }

    def to_report(self) -> Report:
        """将并发测试结果组装成 Report 对象。

        TTFA 采样注入 first_packet stage（与北极星指标 first_packet < 220ms 对照），
        同时设置 concurrency 与 rtf。
        """
        report = Report()
        result = self.collect()
        all_ttfa = result["all_ttfa"]
        if all_ttfa:
            report.add_stage_samples("first_packet", all_ttfa)
        report.set_concurrency(self._num_streams, all_ttfa)
        if all_ttfa:
            mean = sum(all_ttfa) / len(all_ttfa)
            report.set_rtf(compute_ms=mean, audio_duration_ms=self._TARGET_TTFA_MS)
        return report
