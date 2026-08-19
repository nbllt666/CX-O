"""音质对比：用非静音正弦波 ref 测流式/非流式 RMS、peak、时长、RTF（消除静音 ref 不稳定）。"""
import asyncio
import base64
import io
import time
import wave

import httpx
import numpy as np


def make_sine_wav(path, sr=16000, dur=1.0, freq=440.0, amp=0.3):
    t = np.arange(int(sr * dur), dtype=np.float32) / sr
    tone = amp * np.sin(2 * np.pi * freq * t).astype(np.float32)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes((tone * 32767).astype(np.int16).tobytes())


async def main() -> None:
    import os
    tmp = r"C:\CX-O\docker\llm\cosyvoice_tmp"
    os.makedirs(tmp, exist_ok=True)
    ref_path = os.path.join(tmp, "sine_ref.wav")
    make_sine_wav(ref_path)
    with open(ref_path, "rb") as f:
        ref_b64 = base64.b64encode(f.read()).decode("ascii")

    async with httpx.AsyncClient(timeout=300, trust_env=False, proxy=None) as client:
        await client.get("http://127.0.0.1:8094/health")
        body = {
            "model": "Fun-CosyVoice3-0.5B-2512",
            "input": "这是一段用于音质对比的语音合成测试文本。",
            "ref_audio": f"data:audio/wav;base64,{ref_b64}",
            "ref_text": "参考音频转写文本。",
            "response_format": "wav",
        }
        # 非流式
        for i in range(2):
            t0 = time.monotonic()
            r = await client.post("http://127.0.0.1:8094/v1/audio/speech", json=body)
            dt = time.monotonic() - t0
            with wave.open(io.BytesIO(r.content), "rb") as wf:
                a = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).astype(np.float32) / 32767
                dur = wf.getnframes() / wf.getframerate()
            rms = float(np.sqrt(np.mean(a**2)))
            peak = float(np.abs(a).max())
            print(f"[NOSTREAM#{i}] HTTP {r.status_code} dur={dur:.2f}s elapsed={dt:.2f}s RTF={round(dt/dur,2)} RMS={rms:.4f} peak={peak:.3f}")
        # 流式
        sb = dict(body)
        sb["stream"] = True
        for i in range(3):
            t0 = time.monotonic()
            first = None
            parts = []
            async with client.stream("POST", "http://127.0.0.1:8094/v1/audio/speech", json=sb) as r:
                async for chunk in r.aiter_bytes():
                    if first is None:
                        first = time.monotonic() - t0
                    parts.append(chunk)
            total = time.monotonic() - t0
            full = b"".join(parts)
            pcm = full[44:]
            a = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32767
            rms = float(np.sqrt(np.mean(a**2)))
            peak = float(np.abs(a).max())
            dur = a.size / 24000.0
            d = np.abs(np.diff(a))
            jump = float(d.max())
            print(f"[STREAM#{i}] first_chunk={first:.2f}s total={total:.2f}s dur={dur:.2f}s RTF={round(total/dur,2)} RMS={rms:.4f} peak={peak:.3f} maxjump={jump:.3f}")


if __name__ == "__main__":
    asyncio.run(main())
