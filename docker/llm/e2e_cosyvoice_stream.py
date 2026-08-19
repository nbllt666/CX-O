"""Provider 真实运行时 CosyVoice3 流式路径 E2E 验证（Task 7 交付物补充）。

验证项：synthesize_stream 带 refs 首选 cosyvoice（8094）真实流式合成：
- chunk 顺序稳定（恰一个 start、一个 final）
- 首包延迟（首个音频块）与总时长
- 拼接后音频完整性
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
            "base_url": "http://127.0.0.1:8094",
            "model": "Fun-CosyVoice3-0.5B-2512",
            "timeout_seconds": 300,
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
    # 预热：httpx.AsyncClient 在 Windows 上首次构造耗时 7-22s（SSL CA 加载），
    # 生产由 main.py 启动预热承担；测试脚本预热一次避免把客户端构造误计入首包 TTFT。
    req0 = SynthesisRequest(
        text="预热连接。", refs=["ref_upload"], language="Chinese",
        stream=False, output_format="wav",
    )
    await provider.synthesize(req0)
    req = SynthesisRequest(
        text="这是一段用于流式验证的语音克隆测试文本，CosyVoice3 应逐块输出音频。",
        refs=["ref_upload"],
        language="Chinese",
        stream=True,
        output_format="wav",
    )
    results = []

    def record(name: str, ok: bool, detail: str) -> None:
        results.append({"name": name, "ok": ok, "detail": detail})
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")

    t0 = time.monotonic()
    chunks = []
    first_audio_t = None
    try:
        async for chunk in provider.synthesize_stream(req):
            if first_audio_t is None:
                first_audio_t = time.monotonic() - t0
            chunks.append(chunk)
    except Exception as exc:
        record("cosyvoice_stream", False, f"exc: {type(exc).__name__}: {exc}")
    else:
        n = len(chunks)
        starts = sum(1 for c in chunks if c.is_start)
        finals = sum(1 for c in chunks if c.is_final)
        total_bytes = sum(len(c.data) for c in chunks)
        audio_secs = total_bytes / (24000 * 2)
        ok = n >= 2 and starts == 1 and finals == 1 and chunks[-1].is_final
        record("cosyvoice_stream", ok,
               f"chunks={n} start={starts} final={finals} "
               f"first_audio={first_audio_t:.2f}s total={time.monotonic()-t0:.2f}s "
               f"audio≈{audio_secs:.2f}s bytes={total_bytes}")
        # 拼接验证音频可解码
        pcm = b"".join(c.data for c in chunks)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            wf.writeframes(pcm)
        record("cosyvoice_stream_audio_ok", len(pcm) > 0, f"reconstructable wav {len(pcm)} bytes")

    await provider.close()

    print("\n=== E2E COSYVOICE STREAM SUMMARY ===")
    passed = sum(1 for x in results if x["ok"])
    print(f"passed={passed}/{len(results)}")
    out_dir = os.path.join(r"C:\CX-O\docker\llm\probe_out")
    os.makedirs(out_dir, exist_ok=True)
    manifest = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "results": results}
    with open(os.path.join(out_dir, "e2e_cosyvoice_stream_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    asyncio.run(main())