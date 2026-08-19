"""测量 SenseVoice 流式 ASR 的首个 Partial 延迟。

连接 ASR 流式 WS，以 30ms 节奏发送 test_zh_changle 音频（0.5s 裁剪），
记录第一个 partial 到达时间。
"""
import asyncio
import json
import time
import wave

import numpy as np
import websockets

ASR_WS = "ws://127.0.0.1:8005/ws/asr/stream"
REF = r"C:\CX-O\.trae\test_reports\test_zh_changle.wav"
SR = 16000


def load_pcm() -> bytes:
    with wave.open(REF, "rb") as wf:
        sr = wf.getframerate()
        pcm = wf.readframes(wf.getnframes())
    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
    if sr != SR:
        n_out = int(len(x) * SR / sr)
        x = np.interp(np.linspace(0, len(x) - 1, n_out), np.arange(len(x)), x)
    peak = max(np.max(np.abs(x)), 1)
    x = x / peak * 0.9
    # 裁剪测试：可改为 0.5 / 1.0 / 3.24s
    n = int(3.24 * SR)  # 全长 3.24s
    return (x[:n] * 32767).astype(np.int16).tobytes()


async def main():
    pcm = load_pcm()
    fb = int(SR * 0.03) * 2
    frames = [pcm[i : i + fb] for i in range(0, len(pcm), fb)]
    print(f"frames={len(frames)}")
    async with websockets.connect(ASR_WS, max_size=None, ping_interval=20, ping_timeout=10) as ws:
        t0 = time.monotonic()
        for f in frames:
            await ws.send(f)
            await asyncio.sleep(0.03)
        # 静音帧
        sil = b"\x00" * fb
        for _ in range(20):
            await ws.send(sil)
            await asyncio.sleep(0.03)
        print(f"[+{(time.monotonic()-t0)*1000:.0f}ms] all frames sent")
        deadline = time.monotonic() + 3.0
        n = 0
        while time.monotonic() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
            except asyncio.TimeoutError:
                break
            n += 1
            dt = (time.monotonic() - t0) * 1000
            try:
                msg = json.loads(raw)
                print(f"[{n}] {dt:6.0f}ms text='{msg.get('text')}' final={msg.get('is_final')}")
            except Exception:
                print(f"[{n}] {dt:6.0f}ms raw={raw[:80]}")


if __name__ == "__main__":
    asyncio.run(main())
