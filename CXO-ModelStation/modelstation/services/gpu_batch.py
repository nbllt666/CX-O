"""按显存自适应 batch size（So-VITS-SVC 与 MeloTTS 训练共用）。

设计要点（本机实测依据）：
- 显存探测必须在**引擎侧 python** 内完成（只有该解释器装了 torch+cuda），
  训练启动前探一次设备级空闲显存（`torch.cuda.mem_get_info`，已扣除 vLLM 等占用量）。
- 估算式：``batch = clamp((free_GB - reserve_GB) / per_sample_GB, 1, max_batch)``；
  ``per_sample_GB`` 取本机实测保守值（so-vits ≈0.5、MeloTTS ≈0.8，含模型常驻前的余量）。
- 估算失败（无 GPU/超时/解析失败）一律回退到调用方给的保守默认值，绝不阻塞训练启动。
- **红线**：自适应只调 batch，不得打开 cudnn.benchmark（实测那样会让每步退化到分钟级）。
- OOM 兜底：训练侧捕获 OOM 特征串后按 ``batch //= 2`` 重试一次（见各 trainer）。

放置位置说明：两个 trainer 都要用，故独立成模块（非一次性操作，避免重复实现）。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# 引擎侧探测脚本：输出单行 JSON（free/total，单位字节）
_PROBE_SCRIPT = (
    "import json,torch;"
    "f,t=torch.cuda.mem_get_info();"
    "print(json.dumps({'free':f,'total':t}))"
)

# 探测超时（秒）：冷启动导入 torch 约数秒，给足余量
_PROBE_TIMEOUT = 90.0

# OOM 特征串（大小写不敏感匹配；覆盖 torch/cuda 常见文案）
_OOM_SIGNATURES = ("out of memory", "cuda error: out of memory", "cublas_status_alloc_failed")


def is_oom_signature(text: str) -> bool:
    """输出文本是否命中显存不足特征（供训练监控判定是否降批重试）。"""
    if not text:
        return False
    low = text.lower()
    return any(sig in low for sig in _OOM_SIGNATURES)


async def probe_free_vram_gb(
    python_path: str, env: Optional[dict] = None, timeout: float = _PROBE_TIMEOUT
) -> Optional[float]:
    """探测设备空闲显存（GB）。任何失败返回 None（调用方回退保守默认值）。"""
    try:
        proc = await asyncio.create_subprocess_exec(
            python_path, "-c", _PROBE_SCRIPT,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env if env is not None else {**os.environ},
            creationflags=0,
        )
    except (OSError, ValueError) as exc:
        logger.warning(f"显存探测进程启动失败（回退默认 batch）: {exc}")
        return None
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        logger.warning("显存探测超时（回退默认 batch）")
        return None
    if proc.returncode != 0:
        tail = (stderr or b"").decode("utf-8", errors="replace").strip().splitlines()
        logger.warning(f"显存探测失败（回退默认 batch）: {tail[-1] if tail else proc.returncode}")
        return None
    try:
        payload = json.loads((stdout or b"").decode("utf-8", errors="replace").strip().splitlines()[-1])
        return float(payload["free"]) / 1e9
    except Exception as exc:
        logger.warning(f"显存探测结果不可解析（回退默认 batch）: {exc}")
        return None


def estimate_batch_size(free_vram_gb: float, per_sample_gb: float,
                        reserve_gb: float, max_batch: int) -> int:
    """按空闲显存估算 batch（纯函数，便于单测）。"""
    if per_sample_gb <= 0:
        return 1
    usable = float(free_vram_gb) - float(reserve_gb)
    if usable <= 0:
        return 1
    estimated = int(usable / per_sample_gb)
    return max(1, min(int(max_batch), estimated))


async def resolve_auto_batch_size(
    python_path: str,
    per_sample_gb: float,
    reserve_gb: float,
    max_batch: int,
    fallback: int,
    env: Optional[dict] = None,
) -> tuple[int, str]:
    """解析自适应 batch：返回 (batch, 说明文本)。

    探测失败/无 GPU 时返回 (fallback, 原因)；成功时说明文本含空闲显存与估算依据，
    便于在训练日志与 train_meta 中复现该决策。
    """
    free = await probe_free_vram_gb(python_path, env=env)
    if free is None:
        return int(fallback), f"显存探测不可用，回退保守默认 batch={int(fallback)}"
    batch = estimate_batch_size(free, per_sample_gb, reserve_gb, max_batch)
    return batch, (
        f"按显存自适应: 空闲={free:.1f}GB, 每样本≈{per_sample_gb}GB, 保留={reserve_gb}GB, "
        f"上限={int(max_batch)} → batch={batch}"
    )