"""双流式链路延迟测量：真实语音 ref_a 30ms 推流，测 T2(voice.partial)/T3(prefill)/T5(首个 TTS 音频流块)。
统计 P50/P95（ms）。用于闭环 spec Task 9.7 全链延迟（对比旧 SenseVoice 基线 465.61ms P50 全链 / ASR partial ~190ms）。
"""
import asyncio
import base64
import json
import statistics
import sys
import time
import wave

import numpy as np

WS_URL = "ws://127.0.0.1:8000/api/ws/default"
AUDIO = r"C:\CX-O\CX-O-SERVER\data\ref_audio_assets\ref_034ed0259d8043db.wav"
ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 else 5


def load_16k():
    with wave.open(AUDIO, "rb") as wf:
        sr = wf.getframerate(); ch = wf.getnchannels(); sw = wf.getsampwidth()
        frames = wf.readframes(wf.getnframes())
    data = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1)
    if sr != 16000:
        n = int(len(data) * 16000 / sr)
        data = np.interp(np.linspace(0, len(data) - 1, n), np.arange(len(data)), data).astype(np.float32)
    return data


async def one_round(i):
    import websockets
    pcm = (np.clip(load_16k(), -1, 1) * 32767).astype(np.int16)
    t_send = None
    timing = {"t2": None, "t3": None, "t5": None}
    async with websockets.connect(WS_URL, max_size=None) as ws:
        await ws.send(json.dumps({"action": "voice.dual_stream", "request_id": f"lat-{i}",
                                  "data": {"init": True, "agent_id": "default"}}))
        await asyncio.sleep(0.25)

        async def recv_loop():
            try:
                while True:
                    m = json.loads(await asyncio.wait_for(ws.recv(), timeout=25))
                    now = time.monotonic()
                    if t_send is None:
                        continue
                    kind = m.get("type") or m.get("action") or ""
                    if kind == "voice.partial" and timing["t2"] is None:
                        timing["t2"] = (now - t_send) * 1000
                    elif "prefill_started" in kind and timing["t3"] is None:
                        timing["t3"] = (now - t_send) * 1000
                    elif kind in ("stream", "voice.tts_chunk") and timing["t5"] is None:
                        d = m.get("data", {}) or {}
                        if d.get("audio_data") or d.get("audio"):
                            timing["t5"] = (now - t_send) * 1000
            except Exception:
                pass

        rtask = asyncio.create_task(recv_loop())
        step = 960
        for pos in range(0, len(pcm), step):
            await ws.send(json.dumps({"action": "voice.dual_stream", "request_id": f"lat-{i}",
                                      "data": {"audio": base64.b64encode(pcm[pos:pos + step].tobytes()).decode("ascii"),
                                               "sample_rate": 16000}}))
            await asyncio.sleep(0.03)
        t_send = time.monotonic()  # 首帧已送出，开始计时（以第一帧后为 T0）
        for _ in range(12):
            await ws.send(json.dumps({"action": "voice.dual_stream", "request_id": f"lat-{i}",
                                      "data": {"audio": base64.b64encode(b"\x00" * 1920).decode("ascii"),
                                               "sample_rate": 16000}}))
            await asyncio.sleep(0.03)
        await asyncio.sleep(9.0)
        rtask.cancel()
    ok = all(timing.get(k) is not None for k in ("t2", "t3", "t5"))
    print(f"[{'OK ' if ok else 'FAIL'}] r{i}: t2={timing['t2'] and round(timing['t2'],1)} t3={timing['t3'] and round(timing['t3'],1)} t5={timing['t5'] and round(timing['t5'],1)} ms")
    return timing


async def main():
    rows = []
    for i in range(ROUNDS):
        rows.append(await one_round(i))
    ok_rows = [r for r in rows if all(r.get(k) is not None for k in ("t2", "t3", "t5"))]
    print(f"== rounds={ROUNDS} valid={len(ok_rows)}")
    for k, name in (("t2", "T2_ASR_partial"), ("t3", "T3_prefill"), ("t5", "T5_tts_first")):
        vals = [r[k] for r in ok_rows]
        if vals:
            print(f"  {name}: P50={round(statistics.median(vals),1)}ms P95={round(sorted(vals)[int(len(vals)*0.95)-1],1)}ms n={len(vals)}")
    if ok_rows:
        end2end = [r["t5"] for r in ok_rows]
        print(f"  端到端(T0→T5): P50={round(statistics.median(end2end),1)}ms (旧基线 WS P50=465.61ms)")


if __name__ == "__main__":
    asyncio.run(main())