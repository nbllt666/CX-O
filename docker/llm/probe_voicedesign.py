"""Qwen3-TTS VoiceDesign 探针（Task 0 交付物：VoiceDesign 能力矩阵）。

用法:
    python probe_voicedesign.py [--base http://127.0.0.1:8091] [--out C:\\path\\out]

对已启动的 vLLM-Omni Qwen3-TTS VoiceDesign 实例逐项探测:
    1. /health 模型加载
    2. /v1/models 服务模型
    3. VoiceDesign 单句合成 (task_type=VoiceDesign + instructions 自然语言声音描述)
    4. 自然语言情感/风格指令叠加 (instructions 带情绪)
    5. 流式输出 (stream_format=audio)
    6. 变速 (speed != 1.0)
    7. 输出格式 (wav/pcm/mp3/flac/opus)
输出: 每项 PASS/FAIL + 采样率/时长/字节数证据。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import wave

import httpx

SAMPLE_RATE = 24000


def fmt_audio(data: bytes, resp_format: str) -> str:
    """返回音频证据描述：格式 + 采样率 + 时长。"""
    if resp_format == "wav":
        try:
            with wave.open(io.BytesIO(data), "rb") as wf:
                return (
                    f"wav rate={wf.getframerate()} ch={wf.getnchannels()} "
                    f"dur={round(wf.getnframes() / wf.getframerate(), 2)}s "
                    f"bytes={len(data)}"
                )
        except Exception as exc:
            return f"wav(bytes={len(data)}, parse_fail={exc})"
    if resp_format == "pcm":
        return f"pcm bytes={len(data)} dur~{round(len(data) / (SAMPLE_RATE * 2), 2)}s"
    return f"{resp_format} bytes={len(data)}"


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8091")
    ap.add_argument("--out", default=r"C:\CX-O\docker\llm\probe_out")
    ap.add_argument("--model", default="Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign")
    args = ap.parse_args()

    base = args.base.rstrip("/")
    out = args.out
    os.makedirs(out, exist_ok=True)
    client = httpx.AsyncClient(timeout=300.0, trust_env=False)
    results: list[dict] = []

    def record(name: str, ok: bool, detail: str) -> None:
        results.append({"name": name, "ok": ok, "detail": detail})
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")

    # 1. /health
    try:
        r = await client.get(f"{base}/health", timeout=10)
        record("health", r.status_code == 200, f"HTTP {r.status_code}")
    except Exception as exc:
        record("health", False, f"unreachable: {exc}")

    # 2. /v1/models
    try:
        r = await client.get(f"{base}/v1/models", timeout=10)
        models = [m["id"] for m in r.json().get("data", [])]
        record("v1/models", r.status_code == 200 and args.model in models, f"models={models}")
    except Exception as exc:
        record("v1/models", False, f"exc: {exc}")

    # 3. VoiceDesign 单句合成（instructions 自然语言声音描述）
    body = {
        "model": args.model,
        "input": "你好，欢迎使用统一语音合成服务。",
        "task_type": "VoiceDesign",
        "instructions": "A warm, friendly female voice with a gentle tone",
        "language": "Chinese",
        "response_format": "wav",
    }
    try:
        r = await client.post(f"{base}/v1/audio/speech", json=body, timeout=120)
        if r.status_code == 200 and r.content:
            record("voicedesign_wav", True, f"HTTP 200 {fmt_audio(r.content, 'wav')}")
            with open(os.path.join(out, "voicedesign_warm_female.wav"), "wb") as f:
                f.write(r.content)
        else:
            record("voicedesign_wav", False, f"HTTP {r.status_code} {r.text[:300]}")
    except Exception as exc:
        record("voicedesign_wav", False, f"exc: {exc}")

    # 4. 情绪指令叠加（instructions 带情绪）
    body["instructions"] = "A deep male voice speaking with strong anger and excitement"
    body["input"] = "这是测试情绪指令的合成，我非常生气！"
    try:
        r = await client.post(f"{base}/v1/audio/speech", json=body, timeout=120)
        if r.status_code == 200 and r.content:
            record("voicedesign_emotion", True, f"HTTP 200 {fmt_audio(r.content, 'wav')}")
            with open(os.path.join(out, "voicedesign_angry.wav"), "wb") as f:
                f.write(r.content)
        else:
            record("voicedesign_emotion", False, f"HTTP {r.status_code} {r.text[:300]}")
    except Exception as exc:
        record("voicedesign_emotion", False, f"exc: {exc}")

    # 5. 流式输出
    body = {
        "model": args.model,
        "input": "这是一段流式输出的测试文本。",
        "task_type": "VoiceDesign",
        "instructions": "A calm, soothing female voice",
        "language": "Chinese",
        "response_format": "pcm",
        "stream": True,
        "stream_format": "audio",
    }
    try:
        chunks = 0
        total = 0
        async with client.stream("POST", f"{base}/v1/audio/speech", json=body, timeout=120) as resp:
            if resp.status_code != 200:
                record("voicedesign_stream", False, f"HTTP {resp.status_code} {(await resp.aread())[:150]}")
            else:
                async for raw in resp.aiter_bytes():
                    if raw:
                        chunks += 1
                        total += len(raw)
        record("voicedesign_stream", chunks > 1 and total > 0,
               f"chunks={chunks} pcm bytes={total}")
    except Exception as exc:
        record("voicedesign_stream", False, f"exc: {exc}")

    # 6. 变速 speed=1.5
    body = {
        "model": args.model,
        "input": "这是一段测试变速能力的文本。",
        "task_type": "VoiceDesign",
        "instructions": "A neutral, clear voice",
        "language": "Chinese",
        "response_format": "wav",
        "speed": 1.5,
    }
    try:
        r = await client.post(f"{base}/v1/audio/speech", json=body, timeout=120)
        if r.status_code == 200 and r.content:
            record("voicedesign_speed", True, f"HTTP 200 {fmt_audio(r.content, 'wav')} (vLLM 支持 speed)")
            with open(os.path.join(out, "voicedesign_speed1.5.wav"), "wb") as f:
                f.write(r.content)
        else:
            record("voicedesign_speed", False, f"HTTP {r.status_code} {r.text[:300]}")
    except Exception as exc:
        record("voicedesign_speed", False, f"exc: {exc}")

    # 7. 输出格式（mp3/flac/opus）
    for fmt in ("mp3", "flac", "opus"):
        body = {
            "model": args.model,
            "input": "这是一段多格式输出的测试。",
            "task_type": "VoiceDesign",
            "instructions": "A neutral, clear female voice",
            "language": "Chinese",
            "response_format": fmt,
        }
        try:
            r = await client.post(f"{base}/v1/audio/speech", json=body, timeout=120)
            record(f"voicedesign_{fmt}", (r.status_code == 200 and bool(r.content)),
                   f"HTTP {r.status_code} {fmt_audio(r.content, fmt) if r.content else r.text[:150]}")
        except Exception as exc:
            record(f"voicedesign_{fmt}", False, f"exc: {exc}")

    # 汇总
    passed = sum(1 for x in results if x["ok"])
    print(f"\n=== PROBE SUMMARY ===\npassed={passed}/{len(results)}")
    with open(os.path.join(out, "probe_voicedesign_manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"model": args.model, "results": results}, f, ensure_ascii=False, indent=2)
    print(f"manifest -> {os.path.join(out, 'probe_voicedesign_manifest.json')}")
    await client.aclose()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())