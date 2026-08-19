"""Provider 真实运行时无 refs 路径 E2E 验证（Task 7 交付物补充）。

验证项（无参考音频 → voicedesign 运行时）：
1. 无 refs + 情感指令 → voicedesign（8091）成功合成，runtime=voicedesign
2. health_check 对 voicedesign 连通性
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import sys
import time
import wave

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "CX-O-SERVER"))

from server.qwen3_tts_provider import (  # noqa: E402
    Qwen3TTSProvider,
    SynthesisRequest,
)


def fmt_audio(data: bytes) -> str:
    try:
        with wave.open(io.BytesIO(data), "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            return f"wav rate={rate} dur={round(frames / rate, 2)}s bytes={len(data)}"
    except Exception:
        return f"bytes={len(data)}"


async def main() -> None:
    results = []

    def record(name: str, ok: bool, detail: str) -> None:
        results.append({"name": name, "ok": ok, "detail": detail})
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")

    provider = Qwen3TTSProvider()

    # 1. 无 refs + 情感指令 → voicedesign
    req = SynthesisRequest(
        text="这是一段无参考音频的测试文本，用于验证 Provider 的 voicedesign 运行时路径。",
        tts_instruction="温柔甜美的少女声音，语速适中。",
        language="Chinese",
        output_format="wav",
    )
    try:
        t0 = time.monotonic()
        resp = await provider.synthesize(req)
        dt = time.monotonic() - t0
        ok = bool(resp.audio) and resp.runtime == "voicedesign"
        record("no_refs_to_voicedesign", ok,
               f"runtime={resp.runtime} {fmt_audio(resp.audio)} elapsed={dt:.2f}s")
    except Exception as exc:
        record("no_refs_to_voicedesign", False, f"exc: {type(exc).__name__}: {exc}")

    # 2. health_check voicedesign 连通性
    try:
        h = await provider.health_check()
        record("health_voicedesign", h.ok, f"runtime={h.runtime} detail={h.detail}")
    except Exception as exc:
        record("health_voicedesign", False, f"exc: {type(exc).__name__}: {exc}")

    await provider.close()

    print("\n=== E2E NOREFS SUMMARY ===")
    passed = sum(1 for x in results if x["ok"])
    print(f"passed={passed}/{len(results)}")
    manifest = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "results": results}
    out_dir = os.path.join(r"C:\CX-O\docker\llm\probe_out")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "e2e_provider_norefs_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    asyncio.run(main())