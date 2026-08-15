"""IndexTTS-2.5 HTTP 探针：通过已运行的服务验证克隆+情感能力。

用法:
    python probe_indextts25_http.py [--base http://127.0.0.1:8092]
"""
import base64
import io
import json
import os
import wave

import httpx

BASE = "http://127.0.0.1:8092"
REF_WAV = r"C:\CX-O\CX-O-SERVER\data\ref_audio_assets\_upload_ref.wav"
OUT_DIR = r"C:\CX-O\docker\llm\probe_out"
os.makedirs(OUT_DIR, exist_ok=True)


def fmt_wav(data: bytes) -> str:
    try:
        with wave.open(io.BytesIO(data), "rb") as wf:
            return (f"wav rate={wf.getframerate()} ch={wf.getnchannels()} "
                    f"dur={round(wf.getnframes() / wf.getframerate(), 2)}s bytes={len(data)}")
    except Exception as exc:
        return f"wav(bytes={len(data)}, parse_fail={exc})"


def b64(path: str) -> str:
    with open(path, "rb") as f:
        return "data:audio/wav;base64," + base64.b64encode(f.read()).decode("ascii")


async def main() -> None:
    client = httpx.AsyncClient(timeout=300.0, trust_env=False)
    results: list[dict] = []

    def record(name: str, ok: bool, detail: str) -> None:
        results.append({"name": name, "ok": ok, "detail": detail})
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")

    # 1. health
    r = await client.get(f"{BASE}/health", timeout=10)
    record("health", r.status_code == 200, f"HTTP {r.status_code}")

    # 2. models
    r = await client.get(f"{BASE}/v1/models", timeout=10)
    record("models", r.status_code == 200, f"{r.json()}")

    # 3. 基本克隆（ref_audio）
    r = await client.post(f"{BASE}/v1/audio/speech", json={
        "model": "IndexTTS-2.5",
        "input": "你好，这是一个测试语音克隆的样本。",
        "ref_audio": b64(REF_WAV),
        "language": "zh",
        "response_format": "wav",
    }, timeout=300)
    ok3 = bool(r.status_code == 200 and r.content)
    record("basic_clone", ok3,
           f"HTTP {r.status_code} {fmt_wav(r.content) if r.content else r.text[:200]}")
    if ok3:
        with open(os.path.join(OUT_DIR, "indextts_basic_clone.wav"), "wb") as f:
            f.write(r.content)

    # 4. 情感文本控制（instructions -> emo_text）
    r = await client.post(f"{BASE}/v1/audio/speech", json={
        "model": "IndexTTS-2.5",
        "input": "我非常生气，这太让人愤怒了！",
        "ref_audio": b64(REF_WAV),
        "instructions": "愤怒地大声说话",
        "language": "zh",
        "response_format": "wav",
    }, timeout=300)
    ok4 = bool(r.status_code == 200 and r.content)
    record("emo_text_angry", ok4,
           f"HTTP {r.status_code} {fmt_wav(r.content) if r.content else r.text[:200]}")
    if ok4:
        with open(os.path.join(OUT_DIR, "indextts_emo_angry.wav"), "wb") as f:
            f.write(r.content)

    # 5. 情感文本 - 悲伤
    r = await client.post(f"{BASE}/v1/audio/speech", json={
        "model": "IndexTTS-2.5",
        "input": "这真是一个令人悲伤的消息。",
        "ref_audio": b64(REF_WAV),
        "instructions": "悲伤地轻声诉说",
        "language": "zh",
        "response_format": "wav",
    }, timeout=300)
    ok5 = bool(r.status_code == 200 and r.content)
    record("emo_text_sad", ok5,
           f"HTTP {r.status_code} {fmt_wav(r.content) if r.content else r.text[:200]}")
    if ok5:
        with open(os.path.join(OUT_DIR, "indextts_emo_sad.wav"), "wb") as f:
            f.write(r.content)

    # 6. 英文
    r = await client.post(f"{BASE}/v1/audio/speech", json={
        "model": "IndexTTS-2.5",
        "input": "Hello, this is a test of cross-lingual voice cloning.",
        "ref_audio": b64(REF_WAV),
        "language": "en",
        "response_format": "wav",
    }, timeout=300)
    ok6 = bool(r.status_code == 200 and r.content)
    record("english_clone", ok6,
           f"HTTP {r.status_code} {fmt_wav(r.content) if r.content else r.text[:200]}")
    if ok6:
        with open(os.path.join(OUT_DIR, "indextts_english.wav"), "wb") as f:
            f.write(r.content)

    # 汇总
    passed = sum(1 for x in results if x["ok"])
    print(f"\n=== PROBE SUMMARY ===\npassed={passed}/{len(results)}")
    with open(os.path.join(OUT_DIR, "probe_indextts25_http_manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"base": BASE, "results": results}, f, ensure_ascii=False, indent=2)
    print(f"manifest -> {os.path.join(OUT_DIR, 'probe_indextts25_http_manifest.json')}")
    await client.aclose()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())