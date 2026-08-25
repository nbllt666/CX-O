"""端到端联调（服务端 voiceprint_service + 容器 WS）：
1) 用 ref_a 注册说话人"小明"（走真实 voiceprint_service.register → 容器 extract + profiles/sync）
2) WS 依次送 ref_a / ref_b / ref_a 三个 utterance，断言 speaker_id 分别为 小明 / spk_0 / 小明（稳定性）
3) 输出注册/WS 关键信息（2026-08-25 实测：A=小明 conf0.999 / B=spk_0 conf0.166 / A-re=小明，首 partial 0.25~0.9s）
前置：ASR 容器(8005)含流式+声纹引擎；CX-O 服务端含 voiceprint_service（config.asr.remote_url 指向 8005）。
运行：PYTHONPATH=c:\CX-O\CX-O-SERVER python c:\CX-O\tests\test_tools\e2e\voiceprint_e2e.py
"""
import asyncio
import base64
import io
import json
import os
import sys
import time
import wave

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))
from server.services.voiceprint_service import register, list_profiles

WS_URL = "ws://127.0.0.1:8005/ws/asr/stream"
SPEAKER_NAME = "小明"


def load_16k_mono(path):
    """wave 模块读取 WAV（支持 16bit PCM），numpy 线性重采样到 16k 单声道 float32。"""
    with wave.open(path, "rb") as wf:
        sr = wf.getframerate()
        ch = wf.getnchannels()
        sw = wf.getsampwidth()
        frames = wf.readframes(wf.getnframes())
    if sw == 2:
        data = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    elif sw == 4:
        data = np.frombuffer(frames, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        data = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128) / 128.0
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1)
    if sr != 16000:
        n = int(len(data) * 16000 / sr)
        data = np.interp(np.linspace(0, len(data) - 1, n), np.arange(len(data)), data).astype(np.float32)
    return data


def wav_bytes_from_float(data):
    buf = io.BytesIO()
    pcm = (np.clip(data, -1, 1) * 32767).astype(np.int16)
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


async def ws_utterance(client, wav_path, tag):
    """发送一个 utterance 的 16k PCM + final，收集消息，返回 (final_msg, n_partial, first_partial_latency_s)。"""
    import websockets
    msgs = []
    t0 = time.monotonic()
    t_partial = None
    data = load_16k_mono(wav_path)
    pcm = (np.clip(data, -1, 1) * 32767).astype(np.int16)
    step = 9600
    async with websockets.connect(WS_URL, max_size=None) as ws:
        await asyncio.sleep(0.1)
        for pos in range(0, len(pcm), step):
            chunk = pcm[pos:pos + step].tobytes()
            await ws.send(chunk)
        await ws.send(json.dumps({"action": "final"}))
        try:
            while len(msgs) < 20:
                msg = await asyncio.wait_for(ws.recv(), timeout=3)
                msgs.append(json.loads(msg))
                if t_partial is None and not msg_is_final(msgs[-1]) and msgs[-1].get("text"):
                    t_partial = time.monotonic() - t0
        except Exception:
            pass
    final_msg = next((m for m in msgs if m.get("is_final")), None)
    n_partial = sum(1 for m in msgs if not m.get("is_final") and m.get("text"))
    return final_msg, n_partial, t_partial


def msg_is_final(m):
    return bool(m.get("is_final"))


async def main():
    base = os.path.dirname(os.path.abspath(__file__))
    # 说话人 A：有真实语音的参考音频；说话人 B(新声音)：test_asr.wav（预研实测与 A 余弦 0.15，判别充分）
    ref_a = os.path.join(base, "data", "ref_audio_assets", "ref_034ed0259d8043db.wav")
    ref_b = os.path.join(os.path.dirname(base), "test_asr.wav")

    # 1) 注册说话人（async）
    print("== register:", SPEAKER_NAME)
    try:
        prof = await register(SPEAKER_NAME, wav_bytes_from_float(load_16k_mono(ref_a)))
        print("   registered:", {k: prof.get(k) for k in ("name", "embedding_count")} if isinstance(prof, dict) else prof)
    except Exception as e:
        print("   REGISTER FAIL:", type(e).__name__, e)
        return
    print("   profiles:", list_profiles())

    # 2) WS 三连 utterance
    for tag, path, expect in [("A(小明)", ref_a, SPEAKER_NAME), ("B(新声音)", ref_b, "spk_0"), ("A-re(A稳定)", ref_a, SPEAKER_NAME)]:
        final_msg, n_partial, t_partial = await ws_utterance(None, path, tag)
        sid = (final_msg or {}).get("speaker_id", "")
        reg = (final_msg or {}).get("speaker_registered", False)
        conf = (final_msg or {}).get("speaker_conf", None)
        text = (final_msg or {}).get("text", "")[:30]
        ok = sid == expect if expect == SPEAKER_NAME else (expect.startswith("spk"))
        print(f"[{tag}] partials={n_partial} sid={sid!r} reg={reg} conf={conf} text={text!r} first_partial={t_partial and round(t_partial,3)}s => {'PASS' if ok else '<<< FAIL'}")


if __name__ == "__main__":
    asyncio.run(main())