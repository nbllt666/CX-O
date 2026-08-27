"""复刻 test_asr_llm_tts_latency.measure_ws_single 的精确流程，转储所有消息。

目的：定位 t3(prefill_started) 在测试中收不到、但 diag_ws_final 能收到的差异。
"""
import asyncio
import base64
import json
import time
import wave
import io as _io

import numpy as np
import websockets

from _e2e_agent import E2E_AGENT_ID, reset_agent_state, restore_agent_state

WS_URL = f"ws://127.0.0.1:8000/api/ws/{E2E_AGENT_ID}"
REF_PATH = r"C:\CX-O\docker\llm\cosyvoice_tmp\warmup_ref.wav"
AUDIO_SAMPLE_RATE = 16000


def load_test_audio_b64() -> str:
    """与 test generate_test_audio + generate_wav_bytes 一致。"""
    with wave.open(REF_PATH, "rb") as wf:
        sr = wf.getframerate()
        pcm = wf.readframes(wf.getnframes())
    x = np.frombuffer(pcm, dtype=np.int16)
    if sr != AUDIO_SAMPLE_RATE:
        n_out = int(len(x) * AUDIO_SAMPLE_RATE / sr)
        x64 = x.astype(np.float64)
        xi = np.interp(np.linspace(0, len(x) - 1, n_out), np.arange(len(x)), x64).astype(np.int16)
        pcm = xi.tobytes()
    else:
        pcm = x.tobytes()
    buf = _io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(AUDIO_SAMPLE_RATE)
        wf.writeframes(pcm)
    return base64.b64encode(buf.getvalue()).decode("ascii")


async def main():
    reset_agent_state()
    try:
        await _run()
    finally:
        await asyncio.to_thread(restore_agent_state)


async def _run():
    audio_b64 = load_test_audio_b64()
    round_index = 0

    with _io.BytesIO(base64.b64decode(audio_b64)) as raw:
        with wave.open(raw, "rb") as _wf:
            _sr = _wf.getframerate()
            _pcm = _wf.readframes(_wf.getnframes())

    _frame_ms = 30
    _frame_bytes = int(_sr * _frame_ms / 1000) * 2
    _frames = [_pcm[i : i + _frame_bytes] for i in range(0, len(_pcm), _frame_bytes)]
    _silence = b"\x00" * (int(_sr * 0.5) * 2)

    t_conn = time.monotonic()
    async with websockets.connect(WS_URL, max_size=2**24, open_timeout=10) as ws:
        print(f"[+{time.monotonic()-t_conn:6.0f}ms] connected")
        init_msg = {
            "action": "voice.dual_stream",
            "request_id": f"latency-test-{round_index}",
            "data": {
                "init": True,
                "agent_id": E2E_AGENT_ID,
                "engine": "cosyvoice3",
                "voice": "ref_8df9787c96124a5f",
            },
        }
        await ws.send(json.dumps(init_msg))
        await asyncio.sleep(0.2)

        t_send = time.monotonic()
        print(f"[+{(t_send-t_conn)*1000:.0f}ms] t_send, sending {len(_frames)} frames @30ms")
        for _f in _frames:
            await ws.send(json.dumps({
                "action": "voice.dual_stream",
                "request_id": f"latency-test-{round_index}",
                "data": {"audio": base64.b64encode(_f).decode("ascii"), "sample_rate": _sr},
            }))
            await asyncio.sleep(0.03)
        for _ in range(3):
            await ws.send(json.dumps({
                "action": "voice.dual_stream",
                "request_id": f"latency-test-{round_index}",
                "data": {"audio": base64.b64encode(_silence).decode("ascii"), "sample_rate": _sr},
            }))
            await asyncio.sleep(0.03)
        print(f"[+{(time.monotonic()-t_conn)*1000:.0f}ms] all frames sent")

        t2 = t3 = t5 = None
        n = 0
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            except asyncio.TimeoutError:
                print(f"[+{(time.monotonic()-t_conn)*1000:.0f}ms] RECV-TIMEOUT break (t2={t2}, t3={t3}, t5={t5})")
                break
            n += 1
            now = time.monotonic()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                print(f"[{n}] raw: {raw[:120]}")
                continue
            mtype = msg.get("type", "")
            action = msg.get("action", "")
            data = msg.get("data", {})
            audio_data = data.get("audio_data")
            summary = ""
            if audio_data:
                try:
                    d = base64.b64decode(audio_data)
                    summary = f" audio={len(d)}B"
                except Exception:
                    summary = " audio"
            elif data.get("text"):
                summary = f" text='{data.get('text')}'"
            elif "is_speaking" in data:
                summary = f" speaking={data.get('is_speaking')}"
            dt = (now - t_send) * 1000
            print(f"[{n}] {dt:7.1f}ms type='{mtype}' action='{action}'{summary}")

            if (mtype == "voice.partial" or action == "voice.partial") and t2 is None:
                t2 = dt
            elif (mtype == "voice.prefill_started" or action == "voice.prefill_started") and t3 is None:
                t3 = dt
            elif (mtype == "voice.tts_chunk" or action == "voice.tts_chunk") and t5 is None:
                if audio_data:
                    t5 = dt
                    print(f"=== GOT TTS CHUNK (t5={t5:.0f}ms) ===")
                    break
        print(f"RESULT: t2={t2}, t3={t3}, t5={t5}")


if __name__ == "__main__":
    asyncio.run(main())
