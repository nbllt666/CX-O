"""Qwen3-TTS vLLM-Omni 部署探针（Task 0 交付物：可复现部署验证记录）。

用法:
    python probe_qwen3_tts.py [--base http://127.0.0.1:8091] [--ref C:\\path\\to\\ref.wav] [--out C:\\path\\out]

对已启动的 vLLM-Omni Qwen3-TTS 实例逐项探测:
    1. /health 模型加载
    2. /v1/models 服务模型
    3. /v1/audio/voices 预置音色
    4. 单句合成 (wav/pcm/mp3/flac/opus)
    5. 自然语言情感/风格指令 (instructions)
    6. 流式输出 (stream_format=audio, response_format=pcm/wav)
    7. 参考音频输入 (ref_audio+ref_text, base64) —— 记录 CustomVoice 是否接受
    8. 变速 (speed != 1.0) —— 记录 vLLM 是否支持调速
输出: 每项 PASS/FAIL/UNSUPPORTED + 采样率/时长/字节数证据。
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import wave

import httpx

SAMPLE_RATE = 24000


def fmt_audio(data: bytes, resp_format: str) -> str:
    """返回音频证据描述：格式 + 采样率 + 时长。"""
    if resp_format == "wav":
        try:
            with wave.open(__import__("io").BytesIO(data), "rb") as wf:
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
    ap.add_argument("--ref", default=r"C:\CX-O\CX-O-SERVER\data\ref_audio_assets\_upload_ref.wav")
    ap.add_argument("--out", default=r"C:\CX-O\docker\llm\probe_out")
    ap.add_argument("--model", default="Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign")
    args = ap.parse_args()

    base = args.base.rstrip("/")
    out = args.out
    os.makedirs(out, exist_ok=True)
    # trust_env=False: 直连本地服务，避免 Windows 系统代理把 localhost 请求代理出去导致 502
    client = httpx.AsyncClient(timeout=300.0, trust_env=False)
    results: list[dict] = []

    def record(name: str, ok: bool, detail: str) -> None:
        results.append({"name": name, "ok": ok, "detail": detail})
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")

    def b64(path: str) -> str:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("ascii")

    # 1. /health
    try:
        r = await client.get(f"{base}/health", timeout=10)
        record("health", r.status_code == 200, f"HTTP {r.status_code}")
    except Exception as exc:
        record("health", False, f"unreachable: {exc}")

    # 2. /v1/models
    try:
        r = await client.get(f"{base}/v1/models", timeout=10)
        models = [m["id"] for m in r.json().get("data", [])] if r.status_code == 200 else []
        record("v1/models", r.status_code == 200 and bool(models), f"HTTP {r.status_code} models={models}")
    except Exception as exc:
        record("v1/models", False, str(exc))

    # 3. /v1/audio/voices
    try:
        r = await client.get(f"{base}/v1/audio/voices", timeout=10)
        voices = r.json().get("voices", []) if r.status_code == 200 else []
        record("v1/audio/voices", r.status_code == 200, f"HTTP {r.status_code} voices={voices[:12]}")
    except Exception as exc:
        record("v1/audio/voices", False, str(exc))

    # 4. 单句合成各输出格式
    for resp_format in ("wav", "pcm", "mp3", "flac", "opus"):
        body = {
            "model": args.model,
            "input": "你好，我是通义千问，很高兴认识你。",
            "voice": "vivian",
            "language": "Chinese",
            "response_format": resp_format,
        }
        try:
            r = await client.post(f"{base}/v1/audio/speech", json=body, timeout=120)
            if r.status_code == 200 and r.content:
                record(f"synthesize_{resp_format}", True,
                       f"HTTP 200 {fmt_audio(r.content, resp_format)}")
                with open(os.path.join(out, f"synth_{resp_format}.{resp_format}"), "wb") as f:
                    f.write(r.content)
            else:
                record(f"synthesize_{resp_format}", False,
                       f"HTTP {r.status_code} body={r.text[:200]}")
        except Exception as exc:
            record(f"synthesize_{resp_format}", False, f"exc: {exc}")

    # 5. 自然语言情感/风格指令
    body = {
        "model": args.model,
        "input": "今天天气真好呀，我们出去玩吧！",
        "voice": "ryan",
        "language": "Chinese",
        "instructions": "用开心兴奋的语气说，语速稍快",
        "response_format": "wav",
    }
    try:
        r = await client.post(f"{base}/v1/audio/speech", json=body, timeout=120)
        ok = r.status_code == 200 and bool(r.content)
        record("synthesize_instruction", ok,
               f"HTTP {r.status_code} {fmt_audio(r.content, 'wav') if ok else r.text[:200]}")
        if ok:
            with open(os.path.join(out, "synth_instruction.wav"), "wb") as f:
                f.write(r.content)
    except Exception as exc:
        record("synthesize_instruction", False, f"exc: {exc}")

    # 6a. 流式 PCM
    body = {
        "model": args.model,
        "input": "这是一段用于流式输出的测试文本，我们会逐块收到音频数据。",
        "voice": "vivian",
        "language": "Chinese",
        "response_format": "pcm",
        "stream": True,
        "stream_format": "audio",
    }
    try:
        async with client.stream("POST", f"{base}/v1/audio/speech", json=body, timeout=120) as resp:
            if resp.status_code != 200:
                record("stream_pcm", False, f"HTTP {resp.status_code}")
            else:
                chunks: list[bytes] = []
                async for chunk in resp.aiter_bytes():
                    chunks.append(chunk)
                data = b"".join(chunks)
                record("stream_pcm", bool(data),
                       f"HTTP 200 chunks={len(chunks)} {fmt_audio(data, 'pcm')}")
                with open(os.path.join(out, "stream_out.pcm"), "wb") as f:
                    f.write(data)
    except Exception as exc:
        record("stream_pcm", False, f"exc: {exc}")

    # 6b. 流式 WAV
    body["response_format"] = "wav"
    try:
        async with client.stream("POST", f"{base}/v1/audio/speech", json=body, timeout=120) as resp:
            if resp.status_code != 200:
                record("stream_wav", False, f"HTTP {resp.status_code} {(await resp.aread())[:120]}")
            else:
                chunks = []
                async for chunk in resp.aiter_bytes():
                    chunks.append(chunk)
                data = b"".join(chunks)
                record("stream_wav", bool(data),
                       f"HTTP 200 chunks={len(chunks)} {fmt_audio(data, 'wav')}")
                with open(os.path.join(out, "stream_out.wav"), "wb") as f:
                    f.write(data)
    except Exception as exc:
        record("stream_wav", False, f"exc: {exc}")

    # 8. 变速 speed=1.5（非流式）——放在 ref_audio 之前，避免 ref_audio 崩溃引擎影响本项
    body = {
        "model": args.model,
        "input": "这是一段测试变速能力的文本。",
        "voice": "vivian",
        "language": "Chinese",
        "response_format": "wav",
        "speed": 1.5,
    }
    try:
        r = await client.post(f"{base}/v1/audio/speech", json=body, timeout=120)
        if r.status_code == 200 and r.content:
            record("speed_control", True,
                   f"HTTP 200 {fmt_audio(r.content, 'wav')} (vLLM 支持 speed)")
            with open(os.path.join(out, "speed1.5.wav"), "wb") as f:
                f.write(r.content)
        else:
            record("speed_control", False,
                   f"HTTP {r.status_code} {r.text[:300]} (vLLM 不支持 speed)")
    except Exception as exc:
        record("speed_control", False, f"exc: {exc}")

    # 7. 参考音频输入 (ref_audio+ref_text, data URL) —— 最后执行：vLLM VoiceDesign 不支持 ref_audio 消费
    #    （带 refs 的语音克隆由 CosyVoice2 cosyvoice 运行时承接，不走 vLLM）
    ref_b64 = b64(args.ref) if args.ref and os.path.exists(args.ref) else ""
    body = {
        "model": args.model,
        "input": "这段声音应当模仿参考音频中的音色。",
        "language": "Chinese",
        "response_format": "wav",
        "ref_audio": f"data:audio/wav;base64,{ref_b64}",
        "ref_text": "参考音频的转写文本。",
    }
    try:
        r = await client.post(f"{base}/v1/audio/speech", json=body, timeout=120)
        if r.status_code == 200 and r.content:
            record("ref_audio_vllm", True,
                   f"HTTP 200 {fmt_audio(r.content, 'wav')} (vLLM 接受 ref_audio)")
            with open(os.path.join(out, "ref_clone.wav"), "wb") as f:
                f.write(r.content)
        else:
            record("ref_audio_vllm", False,
                   f"HTTP {r.status_code} {r.text[:300]} "
                   "(vLLM VoiceDesign 拒绝 ref_audio：语音克隆由 CosyVoice2 承接)")
    except Exception as exc:
        record("ref_audio_vllm", False, f"exc: {exc}")

    await client.aclose()

    print("\n=== PROBE SUMMARY ===")
    passed = sum(1 for x in results if x["ok"])
    print(f"passed={passed}/{len(results)}")
    manifest = {"base": base, "model": args.model, "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                "results": results}
    with open(os.path.join(out, "probe_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"manifest -> {os.path.join(out, 'probe_manifest.json')}")


if __name__ == "__main__":
    import asyncio

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
