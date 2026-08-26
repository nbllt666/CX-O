"""流式 TTS 音频质量检查：拼接流式块后统计 RMS/时长/峰值。"""
import io
import json
import os
import urllib.request
import base64
import struct
import math
import sys

# H10: 参考音频路径允许环境变量覆盖；不再裸 open 不漏句柄
REF = os.environ.get(
    "CXO_REF_AUDIO",
    r"C:\CX-O\CX-O-SERVER\data\ref_audio_assets\_upload_ref.wav",
)


def main():
    text = "今天天气不错适合出门走走。"
    with open(REF, "rb") as fh:
        ref_b64 = base64.b64encode(fh.read()).decode()
    body = {
        "input": text,
        "ref_audio": "data:audio/wav;base64," + ref_b64,
        "ref_text": ["参考音频转写文本。"],
        "stream": True,
        "response_format": "wav",
    }
    req = urllib.request.Request(
        "http://127.0.0.1:8094/v1/audio/speech",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    resp = urllib.request.urlopen(req)
    # 流式 WAV：跳过 44 字节头后的 PCM 依次拼接
    chunks = []
    total = 0
    while True:
        block = resp.read(4096)
        if not block:
            break
        total += len(block)
        chunks.append(block)
    raw = b"".join(chunks)
    # 解析 WAV 头
    assert raw[:4] == b"RIFF", raw[:16]
    data_size = struct.unpack("<I", raw[40:44])[0]
    pcm = raw[44:44 + data_size]
    n_samples = len(pcm) // 2
    samples = struct.unpack("<%dh" % n_samples, pcm)
    rms = math.sqrt(sum(x * x for x in samples) / n_samples)
    peak = max(abs(x) for x in samples)
    sr = struct.unpack("<I", raw[24:28])[0]
    dur = n_samples / sr
    print(f"sr={sr} dur_s={dur:.2f} rms={rms:.1f} peak={peak} bytes={len(pcm)}")


if __name__ == "__main__":
    main()
