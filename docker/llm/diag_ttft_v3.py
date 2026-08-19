"""验证 token_min_hop_len 覆盖后的 Provider 级流式首包 TTFT。"""
import asyncio
import io
import os
import sys
import time
import wave

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "CX-O-SERVER"))

from server.qwen3_tts_provider import Qwen3TTSProvider, SynthesisRequest  # noqa: E402


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


async def run(provider, text: str) -> float:
    req = SynthesisRequest(text=text, refs=["ref_upload"], language="Chinese",
                           stream=True, output_format="wav")
    t0 = time.monotonic()
    first = None
    n = 0
    async for chunk in provider.synthesize_stream(req):
        if first is None:
            first = time.monotonic() - t0
            print(f"  first chunk at {first:.2f}s bytes={len(chunk.data)}")
        n += 1
    return first


async def main():
    ref_path = r"C:\CX-O\CX-O-SERVER\data\ref_audio_assets\_upload_ref.wav"
    def ref_resolver(asset_id):
        with open(ref_path, "rb") as f:
            data = f.read()
        with wave.open(io.BytesIO(data), "rb") as wf:
            rate = wf.getframerate()
            ch = wf.getnchannels()
        return {"data": data, "sample_rate": rate, "ref_text": "参考音频转写文本。", "channels": ch}

    provider = Qwen3TTSProvider(config=_cfg(), ref_resolver=ref_resolver)
    req0 = SynthesisRequest(text="预热连接。", refs=["ref_upload"], language="Chinese",
                            stream=False, output_format="wav")
    await provider.synthesize(req0)
    f1 = await run(provider, "这是一段用于流式验证的语音克隆测试文本，CosyVoice3 应逐块输出音频。")
    f2 = await run(provider, "今天天气不错，适合出去走走。")
    print(f"TTFT: run1={f1:.2f}s run2={f2:.2f}s")


if __name__ == "__main__":
    asyncio.run(main())