"""IndexTTS-2.5 OpenAI 兼容服务层（Task 0 交付物：IndexTTS 克隆+情感能力接入）。

将官方 IndexTTS-2.5（indextts.infer_v2_5.IndexTTS2）封装为 OpenAI 兼容的
/v1/audio/speech 接口，供后端 Qwen3TTSProvider 以 HTTP 方式调用。

请求形态（OpenAI 兼容 + 扩展）:
    POST /v1/audio/speech
    {
        "model": "IndexTTS-2.5",
        "input": "要合成的文本",
        "voice": "ref_audio 资产（可选，与 ref_audio 二选一）",
        "ref_audio": "参考音频 data URL（可选）",
        "ref_text": "参考音频转写（可选，提升克隆质量）",
        "instructions": "情感描述文本（emo_text 路径）",
        "response_format": "wav",
        "speed": 1.0,
        "language": "zh" | "en"
    }

响应: audio/wav（24kHz -> IndexTTS 输出 22050Hz，保留原样）

运行:
    # 需与 VoiceDesign 共置 GPU1 时，先设 CUDA_VISIBLE_DEVICES=1 隔离（避免 torch 在双卡都建 context），
    # 此时 --device cuda:0 指物理 GPU1
    set CUDA_VISIBLE_DEVICES=1
    <indextts25-venv>/python index_tts_server.py --model_dir C:\\CX-O\\models\\IndexTTS-2.5 \\
        --host 127.0.0.1 --port 8092 --device cuda:0 --bf16
"""
from __future__ import annotations

import argparse
import base64
import io
import os
import sys
import re
import tempfile
import time
import uuid
import wave
from typing import Optional

import numpy as np

from fastapi import Request
from fastapi.responses import JSONResponse, Response


def _decode_data_url(data_url: str) -> bytes:
    """解码 data:audio/...;base64,XXXX 为原始字节。"""
    if data_url.startswith("data:"):
        m = re.match(r"data:[^,]*;base64,(.*)", data_url, re.S)
        if m:
            return base64.b64decode(m.group(1))
    return base64.b64decode(data_url)


# 统一合成链路输出采样率（speech_synthesis_response.schema.json const 24000）
SYNTH_SAMPLE_RATE = 24000
# IndexTTS-2.5 原生输出采样率
INDEXTTS_NATIVE_SAMPLE_RATE = 22050


def _to_mono_float(wav: np.ndarray) -> np.ndarray:
    """把 infer 返回的 wav 归一化为 (samples,) float32 单声道。

    IndexTTS2.infer 非流式返回 wav_data = wav.numpy().T，形状为 (samples, channels)，
    必须按 axis=1（channel 维）压缩，否则把样本维当通道维压缩会得到 1 样本的空音频。
    """
    if wav.ndim == 2:
        # (samples, channels) -> 取 channel 均值（单声道时取第 0 列）
        wav = wav.mean(axis=1) if wav.shape[1] > 1 else wav[:, 0]
    wav = np.asarray(wav, dtype=np.float32).reshape(-1)
    return wav


def _resample_linear(samples: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """对 float32 单声道数组做线性插值重采样（src_rate -> dst_rate）。"""
    if src_rate == dst_rate or samples.size == 0:
        return samples
    n = samples.size
    out_len = max(1, int(round(n * dst_rate / src_rate)))
    pos = np.linspace(0.0, float(n - 1), num=out_len)
    j = np.floor(pos).astype(np.int64)
    frac = pos - j
    j = np.clip(j, 0, n - 1)
    k = np.clip(j + 1, 0, n - 1)
    return samples[j] * (1.0 - frac) + samples[k] * frac


def _encode_wav(sr: int, wav: np.ndarray) -> bytes:
    """将 float32/(samples,) 单声道归一化为 int16 并用标准库 wave 写 WAV。

    - 统一输出 24kHz（SYNTH_SAMPLE_RATE），匹配统一合成链路契约。
    - 使用标准库 wave 而非 soundfile，规避 libsndfile 兼容问题。
    """
    wav = _to_mono_float(wav)
    if sr != SYNTH_SAMPLE_RATE:
        wav = _resample_linear(wav, int(sr), SYNTH_SAMPLE_RATE)
        sr = SYNTH_SAMPLE_RATE
    maxv = float(np.abs(wav).max()) if wav.size else 0.0
    if maxv > 1.0:
        wav = wav / maxv
    wav16 = (wav * 32767.0).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(sr))
        wf.writeframes(wav16.tobytes())
    return buf.getvalue()


# ============================================================================
# FastAPI 应用
# ============================================================================
def create_app():
    import fastapi

    app = fastapi.FastAPI(title="IndexTTS-2.5 OpenAI-compatible TTS")

    @app.get("/health")
    async def health():
        if tts is None:
            return JSONResponse(status_code=503, content={"status": "unhealthy"})
        return {"status": "healthy", "model": "IndexTTS-2.5"}

    @app.get("/v1/models")
    async def models():
        return {"object": "list", "data": [{"id": "IndexTTS-2.5", "object": "model"}]}

    @app.post("/v1/audio/speech")
    async def speech(request: Request):
        try:
            data = await request.json()
        except Exception:
            data = dict(await request.form())
        text = str(data.get("input") or data.get("text") or "").strip()
        if not text:
            return JSONResponse(status_code=400, content={"error": {"message": "input is required"}})

        # Provider 发送 ref_audio 为列表（兼容多来源），取第一项
        ref_audio = data.get("ref_audio") or data.get("voice_audio")
        if isinstance(ref_audio, list):
            ref_audio = ref_audio[0] if ref_audio else None
        voice = data.get("voice")
        ref_text = data.get("ref_text") or data.get("ref_transcript") or ""
        instruction = data.get("instructions") or data.get("voice_description") or data.get("emo_text")
        lang = str(data.get("language") or "zh")
        if lang.lower() in ("zh", "chinese", "zh_cn", "zh-cn"):
            lang = "zh_CN"
        elif lang.lower() in ("en", "english", "en_us", "en-us"):
            lang = "en_US"

        # 参考音频来源：ref_audio（data URL/路径）优先，其次 voice（资产名，需通过 assets 目录）
        spk_path = None
        if ref_audio:
            tmp_dir = args.tmp_dir
            os.makedirs(tmp_dir, exist_ok=True)
            spk_path = os.path.join(tmp_dir, f"spk_{uuid.uuid4().hex}.wav")
            with open(spk_path, "wb") as f:
                f.write(_decode_data_url(ref_audio))
        elif voice:
            spk_path = os.path.join(args.assets_dir, f"{voice}.wav")
            if not os.path.exists(spk_path):
                return JSONResponse(
                    status_code=422,
                    content={"error": {"message": f"voice asset not found: {voice}"}},
                )

        t0 = time.monotonic()
        try:
            result = tts.infer(
                spk_audio_prompt=spk_path,
                text=text,
                output_path=None,
                lang=lang,
                emo_audio_prompt=None,
                emo_alpha=1.0,
                emo_vector=None,
                use_emo_text=bool(instruction),
                emo_text=instruction or None,
                use_random=False,
                text_normalization=True,
            )
        except Exception as exc:
            return JSONResponse(status_code=500, content={"error": {"message": str(exc)}})
        finally:
            if spk_path and ref_audio:
                try:
                    os.remove(spk_path)
                except OSError:
                    pass

        if result is None:
            return JSONResponse(status_code=500, content={"error": {"message": "synthesis returned empty"}})

        sr, wav = result  # (sampling_rate, numpy_array shape (samples, channels))
        # 统一输出 24kHz 单声道 int16 WAV（修正轴序 + 重采样 + 标准库 wave 编码）
        audio_bytes = _encode_wav(int(sr), wav)
        print(f"[IndexTTS] synthesized {len(text)} chars -> {len(audio_bytes)} bytes ({time.monotonic()-t0:.2f}s)")
        return Response(content=audio_bytes, media_type="audio/wav")

    return app


# ============================================================================
# 启动
# ============================================================================
def main() -> None:
    global args, tts

    ap = argparse.ArgumentParser()
    ap.add_argument("--model_dir", default=r"C:\CX-O\models\IndexTTS-2.5")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8092)
    ap.add_argument("--device", default="cuda:1")
    ap.add_argument("--bf16", action="store_true", default=True)
    ap.add_argument("--assets_dir", default=r"C:\CX-O\CX-O-SERVER\data\ref_audio_assets")
    ap.add_argument("--tmp_dir", default=r"C:\CX-O\docker\llm\index_tts_tmp")
    args = ap.parse_args()

    import torch
    # indextts 包位于第三方仓库（非 pip 安装），显式加入 sys.path 保证任意工作目录可启动
    _THIRD_PARTY = os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "third_party", "index-tts-official")
    )
    if os.path.isdir(_THIRD_PARTY) and _THIRD_PARTY not in sys.path:
        sys.path.insert(0, _THIRD_PARTY)
    from indextts.infer_v2_5 import IndexTTS2

    print(f">> Loading IndexTTS-2.5 from {args.model_dir} on {args.device} (bf16={args.bf16}) ...")
    t0 = time.monotonic()
    tts = IndexTTS2(
        cfg_path=os.path.join(args.model_dir, "config.yaml"),
        model_dir=args.model_dir,
        use_bf16=args.bf16 and torch.cuda.is_bf16_supported(),
        device=args.device,
        use_qwen_emo=True,
    )
    print(f">> Model loaded in {time.monotonic()-t0:.1f}s")

    import uvicorn

    print(f">> IndexTTS-2.5 serving on http://{args.host}:{args.port}")
    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="info")


tts = None
args = None

if __name__ == "__main__":
    main()