# -*- coding: utf-8 -*-
"""验证首 partial 幻觉过滤：发送干净音频，检查 partial 是否含 'Yeah。' 且不触发 pipeline。"""
import asyncio, base64, json, time, wave, numpy as np, websockets

WS_URL = "ws://127.0.0.1:8000/api/ws/default"
REF_ASSET = "ref_034ed0259d8043db"

with wave.open(r"C:\CX-O\tests\test_tools\e2e\reports\voice_e2e_user.wav", "rb") as wf:
    sr, nch, nf = wf.getframerate(), wf.getnchannels(), wf.getnframes()
    raw = wf.readframes(nf)
x = np.frombuffer(raw, dtype=np.int16).astype(np.float64)
if nch > 1:
    x = x[::nch]
if sr != 16000:
    n_out = int(len(x) * 16000 / sr)
    x = np.interp(np.linspace(0, len(x) - 1, n_out), np.arange(len(x)), x)
pcm = np.clip(x, -32768, 32767).astype(np.int16).tobytes()
fb = int(16000 * 0.03) * 2
frames = [pcm[i:i + fb] for i in range(0, len(pcm), fb)]
silence = b"\x00" * (int(16000 * 0.6) * 2)
req = "diag-filter"


async def main():
    async with websockets.connect(WS_URL, max_size=2**24, open_timeout=10) as ws:
        await ws.send(json.dumps({"action": "voice.dual_stream", "request_id": req,
                                  "data": {"init": True, "agent_id": "default", "ref_asset_id": REF_ASSET}}))
        await asyncio.sleep(0.3)
        t0 = time.monotonic()
        for f in frames:
            await ws.send(json.dumps({"action": "voice.dual_stream", "request_id": req,
                                      "data": {"audio": base64.b64encode(f).decode(), "sample_rate": 16000}}))
            await asyncio.sleep(0.03)
        for _ in range(3):
            await ws.send(json.dumps({"action": "voice.dual_stream", "request_id": req,
                                      "data": {"audio": base64.b64encode(silence).decode(), "sample_rate": 16000}}))
            await asyncio.sleep(0.03)
        partials = []
        prefill = []
        tts = []
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=3.0))
            except asyncio.TimeoutError:
                break
            act = msg.get("action", "") or msg.get("type", "")
            d = msg.get("data", {}) or {}
            if act == "voice.partial":
                t = d.get("text") or d.get("partial_text") or ""
                if t:
                    partials.append(t)
            elif act == "voice.prefill_started":
                prefill.append(d.get("text") or d.get("partial_text") or "")
            elif act == "voice.tts_chunk":
                tts.append(len(d.get("audio_data") or ""))
        print("partials:", partials)
        print("prefill(trigger texts):", prefill)
        print("tts_chunks:", tts)
        bad = [p for p in partials if p and "Yeah" in p]
        print("RESULT:", "FAIL - 仍见 Yeah 幻觉" if bad else "PASS - 无 Yeah 幻觉")
        if not prefill:
            print("WARN: 无 prefill（pipeline 未触发）")


asyncio.run(main())
