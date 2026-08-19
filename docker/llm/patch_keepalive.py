"""在 cosyvoice 容器 server.py 内注入 GPU 保活线程（1024x1024 GEMM @ 20ms，幂等）。"""
import io

p = "/workspace/server.py"
s = io.open(p, "r", encoding="utf-8", newline="").read()

if "_start_gpu_keepalive" in s:
    print("already patched, skip")
    raise SystemExit(0)

keepalive_code = '''
def _start_gpu_keepalive() -> None:
    """后台 GPU 保活：周期性执行 1024x1024 bf16 GEMM，保持 GPU 高频。

    背景（2026-08-17 全链路 TTFT 优化）：WS 全链路请求间隔 ~1.5s（ASR/LLM/TTS
    串联），GPU 在请求间隙降频到 ~210MHz（nvidia-smi 实测 idle 32C），下一请求
    首块须等待升频 -> 0.34s/0.70s 冷热交替，P95 超标。保活线程每 ~20ms 执行一次
    1024x1024 GEMM（实测可将 SM 时钟稳定在 ~1710MHz，接近 2100MHz 上限；更小的
    4x4/256x256 无法阻止降频）。仅占 ~5% GPU，不影响真实请求。
    """
    try:
        import threading as _threading
        import torch as _torch
        if not _torch.cuda.is_available():
            return
        _dev = _torch.device("cuda:0")
        _a = _torch.randn(1024, 1024, device=_dev, dtype=_torch.bfloat16)
        _b = _torch.randn(1024, 1024, device=_dev, dtype=_torch.bfloat16)
        _stop = _threading.Event()
        def _pulse():
            while not _stop.is_set():
                with _torch.inference_mode():
                    (_a @ _b).sum().item()
                _stop.wait(0.02)  # 20ms 脉冲，保持 GPU 高频
        _t = _threading.Thread(target=_pulse, daemon=True, name="gpu-keepalive")
        _t.start()
        print("[KeepAlive] GPU keepalive started (1024x1024 GEMM @ 20ms)")
    except Exception as exc:
        print(f"[WARN] GPU keepalive failed (ignore): {exc}")
'''

old = "    if not args.no_warmup:\n        _run_warmup(cosyvoice, args)\n\n    import uvicorn"
new = "    if not args.no_warmup:\n        _run_warmup(cosyvoice, args)\n\n    # GPU keepalive: prevent downclock between requests\n    _start_gpu_keepalive()\n\n    import uvicorn"
assert old in s, "warmup section not found"
s = s.replace(old, new)

marker = "# ============================================================================\n# 启动\n# ============================================================================\ndef main() -> None:"
assert marker in s, "main marker not found"
s = s.replace(marker, keepalive_code + "\n\n" + marker, 1)

io.open(p, "w", encoding="utf-8", newline="").write(s)
print("patched OK")
