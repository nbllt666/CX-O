"""ASR 直测：对候选语音文件找能产出 ≥2 字符 partial 的测试音频。

连接 ASR 流式 WS，发送 30ms 帧，打印 partial 文本。
"""
import asyncio
import json
import os
import wave

import numpy as np
import websockets

ASR_WS = "ws://127.0.0.1:8005/ws/asr/stream"

# VoxCPM 参考音频：2026-09-05 引擎目录迁移至 CXO-ModelStation/engines/ 后，
# 原硬编码 C:\CX-O\VoxCPM-main\... 失效。改为环境变量 CXO_VOXCPM_REF_AUDIO
# 可配置，缺省回退迁移后新路径。
VOXCPM_REF_AUDIO = os.environ.get(
    "CXO_VOXCPM_REF_AUDIO",
    r"C:\CX-O\CXO-ModelStation\engines\VoxCPM-main\examples\reference_speaker.wav",
)

CANDIDATES = [
    r"C:\CX-O\docker\llm\cosyvoice_tmp\warmup_ref.wav",
    r"C:\CX-O\.trae\test_reports\test_zh_changle.wav",
    r"C:\CX-O\third_party\cosyvoice-official\asset\cross_lingual_prompt.wav",
    VOXCPM_REF_AUDIO,
    r"C:\CX-O\docker\asr\sensevoice\runtime\llama.cpp\tests\sample.wav",
]


def load_16k_pcm(path: str) -> bytes:
    with wave.open(path, "rb") as wf:
        sr = wf.getframerate()
        pcm = wf.readframes(wf.getnframes())
    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
    if sr != 16000:
        n_out = int(len(x) * 16000 / sr)
        xi = np.interp(np.linspace(0, len(x) - 1, n_out), np.arange(len(x)), x)
        x = xi
    peak = max(np.max(np.abs(x)), 1)
    x = x / peak * 0.9
    return (x * 32767).astype(np.int16).tobytes()


async def test_asr(path: str) -> list[str]:
    pcm = load_16k_pcm(path)
    frame_bytes = int(16000 * 0.03) * 2
    frames = [pcm[i : i + frame_bytes] for i in range(0, len(pcm), frame_bytes)]
    partials = []
    try:
        async with websockets.connect(ASR_WS, max_size=None, ping_interval=20, ping_timeout=10) as ws:
            for f in frames:
                await ws.send(f)
                await asyncio.sleep(0.03)
            await ws.send(json.dumps({"action": "final"}))
            deadline = asyncio.get_event_loop().time() + 3.0
            while asyncio.get_event_loop().time() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                except asyncio.TimeoutError:
                    break
                try:
                    msg = json.loads(raw)
                    partials.append(f"{msg.get('text')}[final={msg.get('is_final')}]")
                except Exception:
                    pass
    except Exception as e:
        partials.append(f"ERR: {e}")
    return partials


async def main():
    for path in CANDIDATES:
        try:
            res = await test_asr(path)
            ok = any(("final=False" in r and len(r.split("[")[0].strip()) >= 2) for r in res)
            print(f"{'✅' if ok else '❌'} {path}")
            print(f"    {res}")
        except Exception as e:
            print(f"❌ {path}: {e}")


if __name__ == "__main__":
    asyncio.run(main())
