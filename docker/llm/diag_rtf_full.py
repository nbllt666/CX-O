"""全链路 RTF 测量：CosyVoice3 主路径 / VoiceDesign 无 refs / qwen3_base 降级。

RTF = 合成墙钟时间 / 音频时长。目标 RTF<1（快于实时）。
每次请求前预热连接（消除 httpx.AsyncClient 构造虚高）。
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import time
import wave

import httpx


SAMPLE_RATE = 24000


def audio_dur(data: bytes) -> float:
    try:
        with wave.open(io.BytesIO(data), "rb") as wf:
            return round(wf.getnframes() / wf.getframerate(), 2)
    except Exception:
        return 0.0


async def post_once(client, url: str, body: dict, label: str, results: list) -> None:
    t0 = time.monotonic()
    try:
        r = await client.post(url, json=body, timeout=300)
        dt = time.monotonic() - t0
        dur = audio_dur(r.content)
        rtf = round(dt / dur, 2) if dur > 0 else float("inf")
        ok = r.status_code == 200 and dur > 0
        results.append({"label": label, "ok": ok, "elapsed": round(dt, 2), "dur": dur, "rtf": rtf})
        print(f"[{'PASS' if ok else 'FAIL'}] {label}: HTTP {r.status_code} dur={dur}s elapsed={dt:.2f}s RTF={rtf}")
    except Exception as exc:
        results.append({"label": label, "ok": False, "detail": str(exc)})
        print(f"[FAIL] {label}: {type(exc).__name__}: {exc}")


async def main() -> None:
    ref_path = r"C:\CX-O\CX-O-SERVER\data\ref_audio_assets\_upload_ref.wav"
    with open(ref_path, "rb") as f:
        ref_b64 = base64.b64encode(f.read()).decode("ascii")

    results: list = []
    client = httpx.AsyncClient(timeout=300.0, trust_env=False, proxy=None)

    # 预热连接（一次性）
    await client.get("http://127.0.0.1:8094/health")
    await client.get("http://127.0.0.1:8091/health")
    await client.get("http://127.0.0.1:8093/health")

    # 1. CosyVoice3 带 refs 克隆（主路径，GPU0）
    cv_body = {
        "model": "Fun-CosyVoice3-0.5B-2512",
        "input": "带参考音频的语音克隆测试，应当走 CosyVoice3 主运行时。",
        "ref_audio": f"data:audio/wav;base64,{ref_b64}",
        "ref_text": "参考音频转写文本。",
        "response_format": "wav",
    }
    for i in range(2):
        await post_once(client, "http://127.0.0.1:8094/v1/audio/speech", cv_body, f"cosyvoice_clone_run{i+1}", results)

    # 2. VoiceDesign 无 refs 情感合成（GPU1）
    vd_body = {
        "model": "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
        "input": "这是一段无参考音频的测试文本，用于验证 voicedesign 运行时路径。",
        "language": "Chinese",
        "response_format": "wav",
        "task_type": "VoiceDesign",
        "instructions": "温柔甜美的少女声音，语速适中。",
        "voice": "vivian",
    }
    for i in range(2):
        await post_once(client, "http://127.0.0.1:8091/v1/audio/speech", vd_body, f"voicedesign_norefs_run{i+1}", results)

    # 3. qwen3_base 降级克隆（带 refs，GPU1）
    qb_body = {
        "model": "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
        "input": "带参考音频的降级链路测试，验证 qwen3_base 克隆能力。",
        "ref_audio": f"data:audio/wav;base64,{ref_b64}",
        "ref_text": "参考音频转写文本。",
        "response_format": "wav",
    }
    for i in range(2):
        await post_once(client, "http://127.0.0.1:8093/v1/audio/speech", qb_body, f"qwen3base_clone_run{i+1}", results)

    await client.aclose()

    print("\n=== RTF SUMMARY ===")
    ok = sum(1 for x in results if x.get("ok"))
    print(f"passed={ok}/{len(results)}")
    manifest = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "results": results}
    out_dir = r"C:\CX-O\docker\llm\probe_out"
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "rtf_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    asyncio.run(main())
