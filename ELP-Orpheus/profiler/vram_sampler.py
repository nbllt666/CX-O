"""ELP-Orpheus 显存与碎片率采样器。

后台线程周期性采样 torch.cuda.memory_allocated / memory_reserved，
计算碎片率（fragmentation_pct = (reserved - allocated) / reserved * 100）。

设计决策：
    - 用 threading.Thread（daemon=True）后台采样，不阻塞主线程。
    - 用 threading.Event 控制停止，wait(interval) 实现可中断的周期采样。
    - 无 CUDA / 无 torch 时返回空采样，不抛错（开发环境友好）。
    - 碎片率反映显存分配器碎片化程度：值越高表示 reserved 中未用比例越大，
      可能导致 OOM（显存够用但分配失败）。

参考：
    - scripts/run_e2e.py 的 GPU 同步策略（torch.cuda.synchronize）
"""

from __future__ import annotations

import threading
import time
from typing import Optional


class VramSampler:
    """显存与碎片率后台采样器。

    用法：
        sampler = VramSampler(gpu_id=1, interval_sec=0.5)
        sampler.start()
        ...  # 跑推理
        sampler.stop()
        print(sampler.to_dict())
    """

    def __init__(self, gpu_id: int = 1, interval_sec: float = 1.0) -> None:
        """初始化。

        Args:
            gpu_id: 采样的 GPU 索引（默认 1，与 run_e2e.py 的 GPU1=Orpheus TTS 一致）。
            interval_sec: 采样间隔（秒）。
        """
        self._gpu_id = gpu_id
        self._interval = max(0.001, float(interval_sec))
        self._samples: list[dict] = []
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def _has_cuda(self) -> bool:
        """检测 CUDA 是否可用（torch 已安装且 device_count > gpu_id）。"""
        try:
            import torch  # type: ignore
            return (
                torch.cuda.is_available()
                and self._gpu_id < torch.cuda.device_count()
            )
        except Exception:
            return False

    def start(self) -> None:
        """启动后台采样线程（daemon=True，随主线程退出）。"""
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._sample_loop, daemon=True)
        self._thread.start()

    def _sample_loop(self) -> None:
        """采样循环：每 interval_sec 采样一次，直到 stop。"""
        has_cuda = self._has_cuda()
        while not self._stop_event.is_set():
            try:
                if has_cuda:
                    import torch  # type: ignore
                    with torch.cuda.device(self._gpu_id):
                        allocated_bytes = torch.cuda.memory_allocated(self._gpu_id)
                        reserved_bytes = torch.cuda.memory_reserved(self._gpu_id)
                    allocated_mb = allocated_bytes / (1024.0 * 1024.0)
                    reserved_mb = reserved_bytes / (1024.0 * 1024.0)
                    frag = (
                        (reserved_mb - allocated_mb) / reserved_mb * 100.0
                        if reserved_mb > 0
                        else 0.0
                    )
                    self._samples.append(
                        {
                            "t": time.time(),
                            "allocated_mb": allocated_mb,
                            "reserved_mb": reserved_mb,
                            "fragmentation_pct": frag,
                        }
                    )
                # 无 CUDA：不采样（保持空列表），不抛错。
            except Exception:
                # 采样中异常（如 GPU 掉卡）不终止线程，跳过本次。
                pass
            # 可中断等待：stop() 调用后立即退出，不必等满 interval。
            self._stop_event.wait(self._interval)

    def stop(self) -> None:
        """停止采样线程并等待退出。"""
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None

    def get_samples(self) -> list[dict]:
        """返回所有采样点：[{t, allocated_mb, reserved_mb, fragmentation_pct}, ...]。"""
        return list(self._samples)

    def peak_mb(self) -> float:
        """峰值显存（allocated_mb 最大值）。无采样返回 0.0。"""
        if not self._samples:
            return 0.0
        return max(s["allocated_mb"] for s in self._samples)

    def fragmentation_pct(self) -> float:
        """平均碎片率（(reserved - allocated) / reserved * 100）。无采样返回 0.0。"""
        if not self._samples:
            return 0.0
        return sum(s["fragmentation_pct"] for s in self._samples) / len(self._samples)

    def to_dict(self) -> dict:
        """返回 {"peak_mb", "fragmentation_pct", "samples"}。"""
        return {
            "peak_mb": self.peak_mb(),
            "fragmentation_pct": self.fragmentation_pct(),
            "samples": self.get_samples(),
        }
