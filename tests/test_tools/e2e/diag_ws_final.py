"""验证 WS 双流式全链路：用真实参考音频（24kHz→16kHz 合理重采样）驱动 ASR→LLM→TTS。"""
import asyncio
import base64
import json
import time
import wave
import io as _io

import numpy as np
import websockets

WS_URL = "ws://127.0.0.1:8000/api/ws/default"
# 使用真实 16kHz 语音音频（cosyvoice 预热参考音频，有实际语音内容）
REF_PATH = r"C:\CX-O\docker\llm\cosyvoice_tmp\warmup_ref.wav"


def resample_24k_to_16k(src_int16: np.ndarray) -> np.ndarray:
    """24kHz→16kHz 有理数降采样（2:3），np.interp 浮点插值。"""
    n_in = len(src_int16)
    n_out = int(n_in * 16000 / 24000)
    x = src_int16.astype(np.float64)
    xi = np.interp(np.linspace(0, n_in - 1, n_out), np.arange(n_in), x).astype(np.float64)
    return xi


def load_16k_pcm() -> bytes:
    with wave.open(REF_PATH, "rb") as wf:
        sr = wf.getframerate()
        pcm = wf.readframes(wf.getnframes())
    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
    if sr == 24000:
        x = resample_24k_to_16k(x)
    # 归一化到 int16 范围，确保能量充足
    peak = max(np.max(np.abs(x)), 1)
    x = x / peak * 0.8
    return (x * 32767).astype(np.int16).tobytes()


async def main():
    pcm = load_16k_pcm()
    sr = 16000
    frame_ms = 30
    frame_bytes = int(sr * frame_ms / 1000) * 2
    frames = [pcm[i : i + frame_bytes] for i in range(0, len(pcm), frame_bytes)]
    # 验证能量
    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    print(f"PCM: {len(x)} samples, energy={float(np.mean(x*x)):.0f}, max={float(np.abs(x).max())}")
    # 计算第一帧能量
    seg = x[:frame_bytes // 2]
    print(f"First frame: energy={float(np.mean(seg*seg)):.0f}")

    silence = b"\x00" * (int(sr * 0.6) * 2)

    async with websockets.connect(WS_URL, max_size=2**24, open_timeout=10) as ws:
        init_msg = {
            "action": "voice.dual_stream",
            "request_id": "diag-ws-final",
            "data": {
                "init": True,
                "agent_id": "default",
                "engine": "cosyvoice3",
                "voice": "ref_8df9787c96124a5f",
            },
        }
        await ws.send(json.dumps(init_msg))
        await asyncio.sleep(0.3)

        t_send = time.monotonic()
        # 实时节奏发送语音帧（30ms 间隔，模拟真实客户端）
        for f in frames:
            b64 = base64.b64encode(f).decode("ascii")
            await ws.send(json.dumps({
                "action": "voice.dual_stream",
                "request_id": "diag-ws-final",
                "data": {"audio": b64, "sample_rate": sr},
            }))
            await asyncio.sleep(0.03)
        # 静音帧触发 VAD speech→silence 翻转
        for _ in range(3):
            b64 = base64.b64encode(silence).decode("ascii")
            await ws.send(json.dumps({
                "action": "voice.dual_stream",
                "request_id": "diag-ws-final",
                "data": {"audio": b64, "sample_rate": sr},
            }))
            await asyncio.sleep(0.03)
        print(f"[t_send] {len(frames)} frames @30ms + 3 silence, t={t_send:.3f}")

        deadline = time.monotonic() + 10.0
        n = 0
        while time.monotonic() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            except asyncio.TimeoutError:
                print("[timeout]")
                break
            n += 1
            now = time.monotonic()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                print(f"[{n}] {now-t_send:6.0f}ms RAW: {raw[:200]}")
                continue
            mtype = msg.get("type", "")
            action = msg.get("action", "")
            data = msg.get("data", {})
            summary = ""
            if data.get("audio_data"):
                import base64 as _b64
                try:
                    d = _b64.b64decode(data["audio_data"])
                    summary = f" audio={len(d)}B"
                except Exception:
                    summary = " audio(base64)"
            elif data.get("text"):
                summary = f" text='{data['text']}'"
            elif "is_speaking" in data:
                summary = f" speaking={data['is_speaking']}"
            print(f"[{n}] {now-t_send:6.0f}ms '{mtype}' {summary}")
            if action == "voice.tts_chunk" or mtype == "voice.tts_chunk":
                print("=== GOT TTS CHUNK ===")
                break


if __name__ == "__main__":
    asyncio.run(main())