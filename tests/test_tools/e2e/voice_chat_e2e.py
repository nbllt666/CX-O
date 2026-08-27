"""模拟语音聊天全链路 E2E：复用 TTS 与 ASR。

链路：TTS 合成用户语音 → WS 双流(ASR→LLM→TTS) → 收集 TTS 回复音频块。
同时单测 ASR 识别 TTS 输出的一致性。
"""
import asyncio
import base64
import io
import json
import os
import sys
import time
import wave

import httpx
import numpy as np
import websockets

# Windows 终端 GBK 输出会因 emoji/特殊字符崩溃，统一 UTF-8 容错
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = "http://127.0.0.1:8000"
from _e2e_agent import E2E_AGENT_ID, reset_agent_state, restore_agent_state
WS_URL = f"ws://127.0.0.1:8000/api/ws/{E2E_AGENT_ID}"
REF_ASSET = "ref_034ed0259d8043db"
USER_TEXT = "你好，今天天气怎么样"
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")
FRAME_MS = 30


def wav_info(wav_bytes: bytes):
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        return wf.getframerate(), wf.getnchannels(), wf.getnframes()


def to_16k_pcm(wav_bytes: bytes) -> bytes:
    """任意采样率/声道 WAV → 16kHz 单声道 int16 PCM。"""
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        sr = wf.getframerate()
        nch = wf.getnchannels()
        pcm = wf.readframes(wf.getnframes())
    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
    if nch > 1:
        x = x[::nch]
    if sr != 16000:
        n_out = int(len(x) * 16000 / sr)
        x = np.interp(np.linspace(0, len(x) - 1, n_out), np.arange(len(x)), x)
    x = np.clip(x, -32768, 32767)
    return x.astype(np.int16).tobytes()


async def step_tts(client: httpx.AsyncClient, text: str) -> bytes:
    r = await client.post(f"{BASE}/api/tts/synthesize", json={"text": text, "ref_asset_id": REF_ASSET})
    r.raise_for_status()
    data = r.json()
    assert data.get("status") == "success", data
    return base64.b64decode(data["audio_data"])


async def step_asr(client: httpx.AsyncClient, wav_bytes: bytes):
    files = {"file": ("voice.wav", wav_bytes, "audio/wav")}
    r = await client.post(f"{BASE}/api/asr/speech-to-text", files=files)
    r.raise_for_status()
    return r.json()


async def step_dual_stream(pcm_16k: bytes):
    """WS 双流：init → 语音帧 → 静音 → 收集 partial/prefill/tts_chunk。"""
    sr = 16000
    frame_bytes = int(sr * FRAME_MS / 1000) * 2
    frames = [pcm_16k[i : i + frame_bytes] for i in range(0, len(pcm_16k), frame_bytes)]
    silence = b"\x00" * (int(sr * 0.6) * 2)
    req_id = f"voice-e2e-{int(time.time())}"

    partials = []
    tts_chunks = []
    timings = {}
    tts_first = None
    tts_total = 0
    reply_text = ""
    prefill_at = None

    async with websockets.connect(WS_URL, max_size=2**24, open_timeout=10) as ws:
        await ws.send(json.dumps({
            "action": "voice.dual_stream", "request_id": req_id,
            "data": {"init": True, "agent_id": E2E_AGENT_ID, "ref_asset_id": REF_ASSET},
        }))
        await asyncio.sleep(0.3)

        t_send = time.monotonic()
        for f in frames:
            await ws.send(json.dumps({
                "action": "voice.dual_stream", "request_id": req_id,
                "data": {"audio": base64.b64encode(f).decode("ascii"), "sample_rate": sr},
            }))
            await asyncio.sleep(0.03)
        for _ in range(3):
            await ws.send(json.dumps({
                "action": "voice.dual_stream", "request_id": req_id,
                "data": {"audio": base64.b64encode(silence).decode("ascii"), "sample_rate": sr},
            }))
            await asyncio.sleep(0.03)

        deadline = time.monotonic() + 25.0
        while time.monotonic() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
            except asyncio.TimeoutError:
                break
            now = time.monotonic() - t_send
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            action = msg.get("action", "")
            mtype = msg.get("type", "")
            data = msg.get("data", {}) or {}

            if action == "voice.partial" or mtype == "voice.partial":
                text = data.get("text") or data.get("partial_text") or ""
                if not partials:
                    timings["asr_first_partial_ms"] = int(now * 1000)
                if text:
                    partials.append(text)
            elif action == "voice.prefill_started" or mtype == "voice.prefill_started":
                if prefill_at is None:
                    prefill_at = now
            elif action == "voice.tts_chunk" or mtype == "voice.tts_chunk":
                if tts_first is None:
                    tts_first = now
                    timings["first_tts_chunk_ms"] = int(now * 1000)
                audio_b64 = data.get("audio_data") or data.get("audio") or ""
                if audio_b64:
                    try:
                        d = base64.b64decode(audio_b64)
                        tts_chunks.append(d)
                        tts_total += len(d)
                    except Exception:
                        pass
                seg = data.get("text_segment") or data.get("text") or ""
                if seg:
                    reply_text += seg
                if data.get("is_final"):
                    break
            elif action == "voice.interrupted" or mtype == "voice.interrupted":
                print(f"[WS] interrupted reason={data.get('reason')}")
                break
            elif mtype in ("voice.vad_status", "vad_status", "voice.vad_frame"):
                continue
        # 会话收尾
        try:
            await ws.send(json.dumps({
                "action": "voice.dual_stream", "request_id": req_id, "data": {"end": True},
            }))
        except Exception:
            pass

    timings["prefill_ms"] = int(prefill_at * 1000) if prefill_at is not None else None
    timings["tts_bytes"] = tts_total
    timings["partial_final"] = partials[-1] if partials else ""
    timings["reply_text"] = reply_text
    timings["tts_duration_s"] = round(tts_total / (2 * 24000), 2) if tts_total else 0  # 24kHz int16 估算
    return timings, b"".join(tts_chunks)


async def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    report = {}
    print(f"=== 模拟语音聊天全链路 E2E ===")
    print(f"用户语句: {USER_TEXT} | 参考音色: {REF_ASSET}")
    print()

    async with httpx.AsyncClient(timeout=120, trust_env=False, proxy=None) as client:
        # ── 1. TTS 合成用户语音 ──
        print("[1/4] TTS 合成用户语音 ...")
        wav_user = await step_tts(client, USER_TEXT)
        sr, nch, nframes = wav_info(wav_user)
        dur = nframes / sr
        report["tts_user"] = {"sample_rate": sr, "channels": nch, "duration_s": round(dur, 2)}
        user_path = os.path.join(OUT_DIR, "voice_e2e_user.wav")
        with open(user_path, "wb") as f:
            f.write(wav_user)
        print(f"      -> {sr}Hz/{nch}ch, {dur:.2f}s, 已存 {user_path}")

        # ── 2. ASR 识别 TTS 输出（验证 TTS→ASR 闭环） ──
        print("[2/4] ASR 识别 TTS 输出 ...")
        t0 = time.monotonic()
        asr_res = await step_asr(client, wav_user)
        asr_ms = int((time.monotonic() - t0) * 1000)
        report["asr"] = {"text": asr_res.get("text", ""), "latency_ms": asr_ms}
        print(f"      识别文本: {asr_res.get('text')!r} ({asr_ms}ms)")

        # ── 3. WS 双流全链路 ──
        print("[3/4] WS 双流全链路 (ASR→LLM→TTS) ...")
        pcm = to_16k_pcm(wav_user)
        timings, tts_pcm = await step_dual_stream(pcm)
        report["dual_stream"] = timings
        tts_path = os.path.join(OUT_DIR, "voice_e2e_reply.raw")
        with open(tts_path, "wb") as f:
            f.write(tts_pcm)
        print(f"      ASR partial: {timings.get('partial_final', '')!r}")
        print(f"      回复文本: {timings.get('reply_text', '')!r}")
        print(f"      first partial: {timings.get('asr_first_partial_ms')}ms | "
              f"prefill: {timings.get('prefill_ms')}ms | "
              f"first TTS chunk: {timings.get('first_tts_chunk_ms')}ms")
        print(f"      TTS 回复音频: {timings.get('tts_bytes')}B ≈ {timings.get('tts_duration_s')}s, 已存 {tts_path}")

    # ── 4. 结论 ──
    print()
    ok = True
    if not report.get("asr", {}).get("text"):
        print("[FAIL] ASR 未识别到文本"); ok = False
    if not report.get("dual_stream", {}).get("tts_bytes"):
        print("[FAIL] 双流未收到 TTS 回复音频"); ok = False
    if not report.get("dual_stream", {}).get("reply_text"):
        print("[WARN] 双流未收到回复文本段")
    print(f"[{'PASS' if ok else 'FAIL'}] 全链路语音聊天验证完成")
    report["pass"] = ok

    rp = os.path.join(OUT_DIR, f"voice_e2e_report_{time.strftime('%Y%m%d_%H%M%S')}.json")
    with open(rp, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"报告: {rp}")


if __name__ == "__main__":
    reset_agent_state()
    try:
        asyncio.run(main())
    finally:
        restore_agent_state()
