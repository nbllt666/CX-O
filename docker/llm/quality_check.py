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
    # with 包裹确保响应句柄在读取完毕后必然关闭（修复：原裸 urlopen 无 close 漏句柄）
    with urllib.request.urlopen(req) as resp:
        # 流式 WAV：头后 PCM 依次拼接
        chunks = []
        total = 0
        while True:
            block = resp.read(4096)
            if not block:
                break
            total += len(block)
            chunks.append(block)
    raw = b"".join(chunks)
    # 解析 WAV 头：RIFF chunk 表遍历（从 12 字节起逐 chunk：id(4)+size(4)+body），
    # 定位 data chunk 偏移与大小，兼容 fmt 扩展头/JUNK 等非 44 字节布局；
    # 采样率从 fmt chunk 数据内偏移 +4 读取（替代旧 raw[24:28] 硬编码）。
    assert raw[:4] == b"RIFF", raw[:16]
    pos = 12  # 跳过 'RIFF'+riff_size+'WAVE' 共 12 字节
    data_off = None
    data_size = 0
    sr = None
    while pos + 8 <= len(raw):
        cid = raw[pos:pos + 4]
        csize = struct.unpack("<I", raw[pos + 4:pos + 8])[0]
        body = raw[pos + 8:pos + 8 + csize]
        if cid == b"fmt " and len(body) >= 8:
            # fmt 数据布局：audio_format(2)+channels(2)+sample_rate(4)+...
            sr = struct.unpack("<I", body[4:8])[0]
        elif cid == b"data":
            data_off = pos + 8
            data_size = csize
            break
        pos += 8 + csize + (csize & 1)  # chunk 按 2 字节对齐（奇数 size 补 1 填充字节）
    assert data_off is not None, "WAV 中未找到 data chunk"
    pcm = raw[data_off:data_off + data_size]  # size 无效/占位时 Python 切片自动截到文件尾
    n_samples = len(pcm) // 2
    if n_samples == 0:
        # backlog（issue 08）: 空/极短 PCM 时除零（sum/0）。直接跳过分析。
        print("empty pcm, skip analysis")
        return
    samples = struct.unpack("<%dh" % n_samples, pcm)
    rms = math.sqrt(sum(x * x for x in samples) / n_samples)
    peak = max(abs(x) for x in samples)
    dur = n_samples / sr
    print(f"sr={sr} dur_s={dur:.2f} rms={rms:.1f} peak={peak} bytes={len(pcm)}")


if __name__ == "__main__":
    main()
