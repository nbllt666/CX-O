"""Qwen3-TTS Base 降级运行时部署探针（Task 2 交付物：克隆/流式/首包能力验证）。

用法:
    python probe_qwen3_base_http.py [--base http://127.0.0.1:8093] [--ref C:\\path\\to\\ref.wav] [--out C:\\path\\out]

对已启动的 vLLM-Omni Qwen3-TTS Base 实例逐项探测:
    1. /health 模型加载
    2. /v1/models 服务模型
    3. 零样本克隆 (ref_audio + ref_text, base64)
    4. 克隆 + 情感/风格指令 (instructions)
    5. 流式输出 (stream=True, response_format=pcm/wav)
    6. 首包 vs 稳态耗时对比
输出: 每项 PASS/FAIL/UNSUPPORTED + 采样率/时长/字节数/耗时证据。
"""
from __future__ import annotations

import argparse
import base64
import io
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
    ap.add_argument("--base", default="http://127.0.0.1:8093")
    ap.add_argument("--ref", default=r"C:\CX-O\CX-O-SERVER\data\ref_audio_assets\_upload_ref.wav")
    ap.add_argument("--out", default=r"C:\CX-O\docker\llm\probe_out")
    ap.add_argument("--model", default="Qwen/Qwen3-TTS-12Hz-1.7B-Base")
    args = ap.parse_args()

    base = args.base.rstrip("/")
    out = args.out
    os.makedirs(out, exist_ok=True)
    # trust_env=False: 直连本地服务，避免 Windows 系统代理把 localhost 请求代理出去导致 502
    client = httpx.AsyncClient(timeout=300.0, trust_env=False)
    results: list[dict] = []
    synth_times: list[dict] = []

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

    ref_b64 = b64(args.ref) if args.ref and os.path.exists(args.ref) else ""
    if not ref_b64:
        record("ref_audio_available", False, f"ref not found: {args.ref}")
    else:
        record("ref_audio_available", True, f"ref bytes={len(base64.b64decode(ref_b64))}")

    # 3. 零样本克隆（首个合成 = FIRST_PACKET）
    body = {
        "model": args.model,
        "input": "这段声音应当模仿参考音频中的音色。",
        "language": "Chinese",
        "response_format": "wav",
        "ref_audio": f"data:audio/wav;base64,{ref_b64}",
        "ref_text": "参考音频转写文本。",
    }
    try:
        t0 = time.monotonic()
        r = await client.post(f"{base}/v1/audio/speech", json=body, timeout=180)
        dt = time.monotonic() - t0
        ok = r.status_code == 200 and bool(r.content)
        synth_times.append({"name": "base_clone", "tag": "FIRST_PACKET", "elapsed": round(dt, 2)})
        record("base_clone", ok,
               f"HTTP {r.status_code} {fmt_audio(r.content, 'wav') if ok else r.text[:300]} elapsed={dt:.2f}s")
        if ok:
            with open(os.path.join(out, "base_clone.wav"), "wb") as f:
                f.write(r.content)
    except Exception as exc:
        record("base_clone", False, f"exc: {exc}")

    # 4. 克隆 + 情感/风格指令
    body = {
        "model": args.model,
        "input": "今天天气真好呀，我们出去玩吧！",
        "language": "Chinese",
        "response_format": "wav",
        "ref_audio": f"data:audio/wav;base64,{ref_b64}",
        "ref_text": "参考音频转写文本。",
        "instructions": "用开心兴奋的语气说，语速稍快",
    }
    try:
        t0 = time.monotonic()
        r = await client.post(f"{base}/v1/audio/speech", json=body, timeout=180)
        dt = time.monotonic() - t0
        ok = r.status_code == 200 and bool(r.content)
        synth_times.append({"name": "base_clone_instruct", "tag": "steady", "elapsed": round(dt, 2)})
        record("base_clone_instruct", ok,
               f"HTTP {r.status_code} {fmt_audio(r.content, 'wav') if ok else r.text[:300]} elapsed={dt:.2f}s")
        if ok:
            with open(os.path.join(out, "base_clone_instruct.wav"), "wb") as f:
                f.write(r.content)
    except Exception as exc:
        record("base_clone_instruct", False, f"exc: {exc}")

    # 5a. 流式 PCM（克隆）
    body = {
        "model": args.model,
        "input": "这是一段用于流式输出的测试文本，我们会逐块收到音频数据。",
        "language": "Chinese",
        "response_format": "pcm",
        "stream": True,
        "stream_format": "audio",
        "ref_audio": f"data:audio/wav;base64,{ref_b64}",
        "ref_text": "参考音频转写文本。",
    }
    try:
        async with client.stream("POST", f"{base}/v1/audio/speech", json=body, timeout=180) as resp:
            if resp.status_code != 200:
                record("base_stream_pcm", False, f"HTTP {resp.status_code}")
            else:
                chunks: list[bytes] = []
                async for chunk in resp.aiter_bytes():
                    chunks.append(chunk)
                data = b"".join(chunks)
                record("base_stream_pcm", bool(data),
                       f"HTTP 200 chunks={len(chunks)} {fmt_audio(data, 'pcm')}")
                with open(os.path.join(out, "base_stream_out.pcm"), "wb") as f:
                    f.write(data)
    except Exception as exc:
        record("base_stream_pcm", False, f"exc: {exc}")

    # 5b. 流式 WAV（克隆）
    body["response_format"] = "wav"
    try:
        async with client.stream("POST", f"{base}/v1/audio/speech", json=body, timeout=180) as resp:
            if resp.status_code != 200:
                record("base_stream_wav", False, f"HTTP {resp.status_code} {(await resp.aread())[:120]}")
            else:
                chunks = []
                async for chunk in resp.aiter_bytes():
                    chunks.append(chunk)
                data = b"".join(chunks)
                record("base_stream_wav", bool(data),
                       f"HTTP 200 chunks={len(chunks)} {fmt_audio(data, 'wav')}")
                with open(os.path.join(out, "base_stream_out.wav"), "wb") as f:
                    f.write(data)
    except Exception as exc:
        record("base_stream_wav", False, f"exc: {exc}")

    # 6. 变速 speed=1.5（非流式，克隆）
    body = {
        "model": args.model,
        "input": "这是一段测试变速能力的文本。",
        "language": "Chinese",
        "response_format": "wav",
        "speed": 1.5,
        "ref_audio": f"data:audio/wav;base64,{ref_b64}",
        "ref_text": "参考音频转写文本。",
    }
    try:
        t0 = time.monotonic()
        r = await client.post(f"{base}/v1/audio/speech", json=body, timeout=180)
        dt = time.monotonic() - t0
        ok = r.status_code == 200 and bool(r.content)
        record("base_speed_control", ok,
               f"HTTP {r.status_code} {fmt_audio(r.content, 'wav') if ok else r.text[:300]} elapsed={dt:.2f}s")
        if ok:
            with open(os.path.join(out, "base_speed1.5.wav"), "wb") as f:
                f.write(r.content)
    except Exception as exc:
        record("base_speed_control", False, f"exc: {exc}")

    await client.aclose()

    print("\n=== PROBE SUMMARY ===")
    passed = sum(1 for x in results if x["ok"])
    print(f"passed={passed}/{len(results)}")
    if synth_times:
        first = next((t for t in synth_times if t["tag"] == "FIRST_PACKET"), None)
        steady = [t for t in synth_times if t["tag"] == "steady"]
        print(f"first_packet={first['elapsed'] if first else 'n/a'}s, steady_avg={round(sum(t['elapsed'] for t in steady)/len(steady),2) if steady else 'n/a'}s (n={len(steady)})")
    manifest = {"base": base, "model": args.model, "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                "synth_times": synth_times, "results": results}
    with open(os.path.join(out, "probe_qwen3_base_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"manifest -> {os.path.join(out, 'probe_qwen3_base_manifest.json')}")


if __name__ == "__main__":
    import asyncio

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
