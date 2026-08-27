"""WS 双流式全链路诊断脚本：连接后发送 init+audio，转储服务端所有消息。

用途：定位 WS 模式下 voice.prefill_started / voice.tts_chunk 是否送达，
以及服务端实际发送的消息类型与时间线。
"""
import asyncio
import base64
import json
import time

import numpy as np
import websockets

from _e2e_agent import E2E_AGENT_ID, reset_agent_state, restore_agent_state

WS_URL = f"ws://127.0.0.1:8000/api/ws/{E2E_AGENT_ID}"
SAMPLE_RATE = 16000


def make_audio(duration_s: float = 1.0) -> str:
    # 使用真实语音参考音频（24kHz→16kHz 重采样）作为 ASR 输入，
    # 合成音调无法被 SenseVoice 识别为多字符文本，无法驱动流水线。
    import io
    import wave

    import numpy as np

    # 读取真实语音参考音频
    ref_path = r"C:\CX-O\CX-O-SERVER\data\ref_audio_assets\ref_8df9787c96124a5f.wav"
    with wave.open(ref_path, "rb") as wf:
        sr_in = wf.getframerate()
        n_in = wf.getnframes()
        pcm_in = wf.readframes(n_in)
    x_in = np.frombuffer(pcm_in, dtype=np.int16).astype(np.float32) / 32767.0
    # 重采样到 16kHz（线性插值）
    n_out = int(n_in * SAMPLE_RATE / sr_in)
    x_out = np.interp(
        np.linspace(0, n_in - 1, n_out), np.arange(n_in), x_in
    ).astype(np.float32)
    pcm = (x_out * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm.tobytes())
    return base64.b64encode(buf.getvalue()).decode("ascii")


async def main():
    reset_agent_state()
    try:
        await _run()
    finally:
        await asyncio.to_thread(restore_agent_state)


async def _run():
    audio_b64 = make_audio()
    import io
    import wave as _wave
    import numpy as np

    raw = base64.b64decode(audio_b64)
    with _wave.open(io.BytesIO(raw), "rb") as wf:
        sr = wf.getframerate()
        pcm = wf.readframes(wf.getnframes())

    # 30ms 帧（匹配 WebRTC VAD 帧大小），模拟真实客户端连续发送；
    # 末尾跟 600ms 静音触发 VAD speech→silence 翻转（is_last → ASR final）。
    frame_ms = 30
    frame_bytes = int(sr * frame_ms / 1000) * 2  # 16-bit mono
    speech_frames = [pcm[i : i + frame_bytes] for i in range(0, len(pcm), frame_bytes)]
    # 静音 600ms
    silence = b"\x00" * (int(sr * 0.6) * 2)

    async with websockets.connect(WS_URL, max_size=2**24, open_timeout=10) as ws:
        init_msg = {
            "action": "voice.dual_stream",
            "request_id": "diag-ws-dump",
            "data": {
                "init": True,
                "agent_id": E2E_AGENT_ID,
                "engine": "cosyvoice3",
                "voice": "ref_8df9787c96124a5f",
            },
        }
        await ws.send(json.dumps(init_msg))
        await asyncio.sleep(0.3)

        t_send = time.monotonic()
        # 发送语音帧
        for f in speech_frames:
            msg = {
                "action": "voice.dual_stream",
                "request_id": "diag-ws-dump",
                "data": {
                    "audio": base64.b64encode(f).decode("ascii"),
                    "sample_rate": sr,
                },
            }
            await ws.send(json.dumps(msg))
        # 发送静音帧触发 VAD 翻转
        for _ in range(2):
            msg = {
                "action": "voice.dual_stream",
                "request_id": "diag-ws-dump",
                "data": {
                    "audio": base64.b64encode(silence).decode("ascii"),
                    "sample_rate": sr,
                },
            }
            await ws.send(json.dumps(msg))
        print(f"[t_send] sent {len(speech_frames)} x {frame_ms}ms speech frames + 2 silence frames at {t_send:.3f}")

        deadline = time.monotonic() + 10.0
        n = 0
        while time.monotonic() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            except asyncio.TimeoutError:
                print("[timeout] no message in 2s")
                break
            n += 1
            now = time.monotonic()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                print(f"[{n}] {now - t_send:6.0f}ms RAW(非JSON): {raw[:200]}")
                continue
            mtype = msg.get("type", "")
            action = msg.get("action", "")
            data = msg.get("data", {})
            audio_data = data.get("audio_data")
            summary = ""
            if audio_data:
                import base64 as _b64
                try:
                    decoded = _b64.b64decode(audio_data)
                    summary = f" audio_len={len(decoded)}B"
                except Exception:
                    summary = " audio(base64)"
            elif isinstance(data, dict) and data.get("text"):
                summary = f" text='{data.get('text')}'"
            elif isinstance(data, dict) and data.get("status"):
                summary = f" status='{data.get('status')}'"
            elif isinstance(data, dict) and "is_speaking" in data:
                summary = f" is_speaking={data.get('is_speaking')}"
            print(f"[{n}] {now - t_send:6.0f}ms type='{mtype}' action='{action}'{summary}")
            if mtype == "voice.tts_chunk" or action == "voice.tts_chunk":
                break


if __name__ == "__main__":
    asyncio.run(main())
