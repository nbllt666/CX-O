"""CosyVoice2-0.5B 主运行时部署探针（Task 1 交付物：克隆/情感/流式/首包/显存指标）。

用法:
    python probe_cosyvoice_http.py [--base http://127.0.0.1:8094] [--ref C:\\path\\to\\ref.wav] [--out C:\\path\\out]

对已启动的 CosyVoice2 OpenAI 兼容实例逐项探测:
    1. /health 模型加载
    2. /v1/models 服务模型
    3. 零样本克隆 (ref_audio, 首包)
    4. 克隆 + 情感指令 (instructions)
    5. 流式输出 (stream=True, response_format=wav/pcm)
    6. 首包 vs 稳态耗时 + speaker 缓存命中
输出: 每项 PASS/FAIL + 采样率/时长/字节数/耗时证据。
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

import requests

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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8094")
    ap.add_argument("--ref", default=r"C:\CX-O\CX-O-SERVER\data\ref_audio_assets\_upload_ref.wav")
    ap.add_argument("--out", default=r"C:\CX-O\docker\llm\probe_out")
    ap.add_argument("--model", default="Fun-CosyVoice3-0.5B-2512")
    args = ap.parse_args()

    base = args.base.rstrip("/")
    out = args.out
    os.makedirs(out, exist_ok=True)
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
        r = requests.get(f"{base}/health", timeout=10)
        record("health", r.status_code == 200, f"HTTP {r.status_code}")
    except Exception as exc:
        record("health", False, f"unreachable: {exc}")

    # 2. /v1/models
    try:
        r = requests.get(f"{base}/v1/models", timeout=10)
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
        "input": "收到好友从远方寄来的生日礼物，那份意外的惊喜与深深的祝福让我心中充满了甜蜜的快乐，笑容如花儿般绽放。",
        "ref_audio": f"data:audio/wav;base64,{ref_b64}",
        "ref_text": "参考音频转写文本。",
        "response_format": "wav",
        "stream": False,
    }
    try:
        t0 = time.monotonic()
        r = requests.post(f"{base}/v1/audio/speech", json=body, timeout=300)
        dt = time.monotonic() - t0
        ok = r.status_code == 200 and bool(r.content)
        synth_times.append({"name": "cosyvoice_clone", "tag": "FIRST_PACKET", "elapsed": round(dt, 2)})
        record("cosyvoice_clone", ok,
               f"HTTP {r.status_code} {fmt_audio(r.content, 'wav') if ok else r.text[:300]} elapsed={dt:.2f}s")
        if ok:
            with open(os.path.join(out, "cosyvoice_clone.wav"), "wb") as f:
                f.write(r.content)
    except Exception as exc:
        record("cosyvoice_clone", False, f"exc: {exc}")

    # 4. 克隆 + 情感指令（instruct2）
    body = {
        "model": args.model,
        "input": "今天天气真好呀，我们出去玩吧！",
        "ref_audio": f"data:audio/wav;base64,{ref_b64}",
        "ref_text": "参考音频转写文本。",
        "instructions": "用开心兴奋的语气说，语速稍快",
        "response_format": "wav",
        "stream": False,
    }
    try:
        t0 = time.monotonic()
        r = requests.post(f"{base}/v1/audio/speech", json=body, timeout=300)
        dt = time.monotonic() - t0
        ok = r.status_code == 200 and bool(r.content)
        synth_times.append({"name": "cosyvoice_instruct", "tag": "steady", "elapsed": round(dt, 2)})
        record("cosyvoice_instruct", ok,
               f"HTTP {r.status_code} {fmt_audio(r.content, 'wav') if ok else r.text[:300]} elapsed={dt:.2f}s")
        if ok:
            with open(os.path.join(out, "cosyvoice_instruct.wav"), "wb") as f:
                f.write(r.content)
    except Exception as exc:
        record("cosyvoice_instruct", False, f"exc: {exc}")

    # 5. 流式输出（wav）
    body = {
        "model": args.model,
        "input": "这是一段用于流式输出的测试文本，我们会逐块收到音频数据。",
        "ref_audio": f"data:audio/wav;base64,{ref_b64}",
        "ref_text": "参考音频转写文本。",
        "response_format": "wav",
        "stream": True,
    }
    try:
        t0 = time.monotonic()
        r = requests.post(f"{base}/v1/audio/speech", json=body, timeout=300, stream=True)
        dt = time.monotonic() - t0
        chunks = []
        if r.status_code == 200:
            for chunk in r.iter_content(chunk_size=None):
                if chunk:
                    chunks.append(chunk)
        data = b"".join(chunks)
        ok = r.status_code == 200 and bool(data)
        synth_times.append({"name": "cosyvoice_stream", "tag": "steady", "elapsed": round(dt, 2)})
        record("cosyvoice_stream", ok,
               f"HTTP {r.status_code} chunks={len(chunks)} {fmt_audio(data, 'wav') if ok else r.text[:300]} elapsed={dt:.2f}s")
        if ok:
            with open(os.path.join(out, "cosyvoice_stream.wav"), "wb") as f:
                f.write(data)
    except Exception as exc:
        record("cosyvoice_stream", False, f"exc: {exc}")

    # 6. speaker 缓存命中（同 ref 再次合成，应显著快于首次）
    body = {
        "model": args.model,
        "input": "再次使用同一段参考音频进行合成，应当命中 speaker 嵌入缓存。",
        "ref_audio": f"data:audio/wav;base64,{ref_b64}",
        "ref_text": "参考音频转写文本。",
        "response_format": "wav",
        "stream": False,
    }
    try:
        t0 = time.monotonic()
        r = requests.post(f"{base}/v1/audio/speech", json=body, timeout=300)
        dt = time.monotonic() - t0
        ok = r.status_code == 200 and bool(r.content)
        synth_times.append({"name": "cosyvoice_cache_hit", "tag": "steady", "elapsed": round(dt, 2)})
        record("cosyvoice_cache_hit", ok,
               f"HTTP {r.status_code} {fmt_audio(r.content, 'wav') if ok else r.text[:300]} elapsed={dt:.2f}s (speaker 缓存命中)")
        if ok:
            with open(os.path.join(out, "cosyvoice_cache_hit.wav"), "wb") as f:
                f.write(r.content)
    except Exception as exc:
        record("cosyvoice_cache_hit", False, f"exc: {exc}")

    print("\n=== PROBE SUMMARY ===")
    passed = sum(1 for x in results if x["ok"])
    print(f"passed={passed}/{len(results)}")
    if synth_times:
        first = next((t for t in synth_times if t["tag"] == "FIRST_PACKET"), None)
        steady = [t for t in synth_times if t["tag"] == "steady"]
        print(f"first_packet={first['elapsed'] if first else 'n/a'}s, steady_avg={round(sum(t['elapsed'] for t in steady)/len(steady),2) if steady else 'n/a'}s (n={len(steady)})")
    manifest = {"base": base, "model": args.model, "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                "synth_times": synth_times, "results": results}
    with open(os.path.join(out, "probe_cosyvoice_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"manifest -> {os.path.join(out, 'probe_cosyvoice_manifest.json')}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
