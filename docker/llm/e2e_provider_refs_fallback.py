"""Provider 真实运行时带 refs 降级路径 E2E 验证（Task 7 交付物补充）。

验证项：带 refs 首选 cosyvoice（8094）不可达 → 降级 qwen3_base（8093）真实合成，
修复 qwen3_base 请求格式（字符串 data URL ref_audio + 字符串 ref_text）后链路闭环。
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


def _cfg() -> dict:
    return {
        "enabled": True,
        "runtime": "voicedesign",
        "vllm": {
            "base_url": "http://127.0.0.1:8091",
            "model": "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
            "task_type": "VoiceDesign",
            "timeout_seconds": 60,
            "sample_rate": 24000,
        },
        "cosyvoice": {
            # 指向死端口，强制触发降级 qwen3_base
            "base_url": "http://127.0.0.1:19999",
            "model": "Fun-CosyVoice3-0.5B-2512",
            "timeout_seconds": 10,
            "sample_rate": 24000,
        },
        "qwen3_base": {
            "base_url": "http://127.0.0.1:8093",
            "model": "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
            "timeout_seconds": 120,
            "sample_rate": 24000,
        },
        "default": {"voice": "vivian", "language": "", "output_format": "wav", "speed": 1.0},
        "emotion_instruction": {"enabled": True, "max_length": 200, "fallback_neutral": True},
        "legacy_engine_removed": {"return_removed_error": True},
    }


async def main() -> None:
    ref_path = r"C:\CX-O\CX-O-SERVER\data\ref_audio_assets\_upload_ref.wav"

    def ref_resolver(asset_id):
        with open(ref_path, "rb") as f:
            data = f.read()
        with wave.open(io.BytesIO(data), "rb") as wf:
            rate = wf.getframerate()
            ch = wf.getnchannels()
        return {"data": data, "sample_rate": rate, "ref_text": "参考音频转写文本。", "channels": ch}

    provider = Qwen3TTSProvider(config=_cfg(), ref_resolver=ref_resolver)
    req = SynthesisRequest(
        text="这是一段带参考音频的降级链路测试文本，cosyvoice 不可达时应降级到 Qwen3-TTS Base。",
        refs=["ref_upload"],
        language="Chinese",
        output_format="wav",
    )
    try:
        t0 = time.monotonic()
        resp = await provider.synthesize(req)
        dt = time.monotonic() - t0
        ok = bool(resp.audio) and resp.runtime == "qwen3_base"
        print(f"[{'PASS' if ok else 'FAIL'}] refs_fallback_to_qwen3_base: "
              f"runtime={resp.runtime} {fmt_audio(resp.audio)} elapsed={dt:.2f}s")
    except Exception as exc:
        print(f"[FAIL] refs_fallback_to_qwen3_base: exc: {type(exc).__name__}: {exc}")
        ok = False

    await provider.close()

    manifest = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "results": [{"name": "refs_fallback_to_qwen3_base", "ok": ok}],
    }
    out_dir = os.path.join(r"C:\CX-O\docker\llm\probe_out")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "e2e_provider_refs_fallback_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    asyncio.run(main())