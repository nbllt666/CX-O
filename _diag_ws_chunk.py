"""WS 逐 chunk 诊断：抓真实链路并逐个打印 chunk 峰值/削波，定位削波块。"""
import asyncio
import base64
import io
import json
import numpy as np
import wave
import websockets

WS = "ws://127.0.0.1:8000/api/ws/default"
SR = 24000


async def gen_audio():
    with wave.open(r"C:\CX-O\.trae\test_reports\test_zh_changle.wav", "rb") as wf:
        sr = wf.getframerate(); pcm = wf.readframes(wf.getnframes())
    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
    n = int(len(x) * 16000 / sr)
    x = np.interp(np.linspace(0, len(x)-1, n), np.arange(len(x)), x)
    x = x / max(np.abs(x).max(), 1) * 0.9
    x = x[:32000] if len(x) > 32000 else x
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes((x*32767).astype(np.int16).tobytes())
    return base64.b64encode(buf.getvalue()).decode()


async def main():
    b64 = await gen_audio()
    async with websockets.connect(WS, max_size=2**24, open_timeout=10) as ws:
        await ws.send(json.dumps({"action":"voice.dual_stream","request_id":"diag","data":{"init":True,"agent_id":"default","engine":"cosyvoice3","voice":"ref_8df9787c96124a5f"}}))
        await asyncio.sleep(0.2)
        raw = base64.b64decode(b64)
        frame = int(16000*0.03)*2
        frames = [raw[i:i+frame] for i in range(0, len(raw), frame)]
        sil = b"\x00"*frame

        async def recv_loop():
            idx = 0
            clips = 0
            t0 = asyncio.get_event_loop().time()
            while asyncio.get_event_loop().time()-t0 < 25:
                try:
                    m = json.loads(await asyncio.wait_for(ws.recv(), timeout=3))
                except Exception:
                    continue
                if (m.get("type")=="voice.tts_chunk" or m.get("action")=="voice.tts_chunk"):
                    d = m.get("data", {})
                    ab = d.get("audio_data")
                    if ab:
                        pcm = base64.b64decode(ab)
                        try:
                            x = np.frombuffer(pcm, dtype="<i2").astype(np.int64)
                        except ValueError:
                            print(f"  chunk#{idx} ODD-LEN bytes={len(pcm)} (non-int16!) peak=??")
                            idx += 1
                            continue
                        if len(x):
                            pk = abs(x).max()
                            cp = int((x>=32766).sum()+(x<=-32766).sum())
                            clips += cp
                            print(f"  chunk#{idx} bytes={len(pcm)} peak={pk} clip={cp}")
                        idx += 1
                    if m.get("is_final"):
                        break
            print(f"  total_chunks={idx} total_clip={clips}")

        recv_task = asyncio.create_task(recv_loop())
        for f in frames:
            await ws.send(json.dumps({"action":"voice.dual_stream","request_id":"diag","data":{"audio":base64.b64encode(f).decode("ascii"),"sample_rate":16000}}))
            await asyncio.sleep(0.03)
        for _ in range(20):
            await ws.send(json.dumps({"action":"voice.dual_stream","request_id":"diag","data":{"audio":base64.b64encode(sil).decode("ascii"),"sample_rate":16000}}))
            await asyncio.sleep(0.03)
        try:
            await asyncio.wait_for(asyncio.shield(recv_task), timeout=22)
        except asyncio.TimeoutError:
            pass


asyncio.run(main())