"""
edge-tts 参考音频生成脚本
========================
用 edge-tts 生成与 Orpheus TTS 样本相同文本的参考音频，用于音质对比。

使用方式:
    python tests/test_tools/e2e/generate_edgetts_reference.py

输出:
    c:/CX-O/.trae/test_reports/audio_sample_edgetts_reference.wav
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import edge_tts

# 输出文件
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_DIR = _PROJECT_ROOT / ".trae" / "test_reports"
OUTPUT_FILE = OUTPUT_DIR / "audio_sample_edgetts_reference.mp3"
OUTPUT_FILE_WAV = OUTPUT_DIR / "audio_sample_edgetts_reference.wav"

# 与 Orpheus 样本相同的文本（从 CX-O-SERVER app.log 提取的 LLM 完整响应）
REFERENCE_TEXT = "您好！我是一个AI助手，很高兴为您服务。您有什么需要我帮忙的吗？"

# edge-tts 中文语音（晓晓，女声，自然亲切，适合对比 Orpheus tara）
VOICE = "zh-CN-XiaoxiaoNeural"


async def generate_reference() -> None:
    """用 edge-tts 生成参考音频。"""
    print("=" * 60)
    print("edge-tts 参考音频生成")
    print(f"  文本: {REFERENCE_TEXT}")
    print(f"  语音: {VOICE}（zh-CN 晓晓，女声）")
    print("=" * 60)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. 生成 MP3
    print(f"正在生成 MP3: {OUTPUT_FILE}")
    communicate = edge_tts.Communicate(REFERENCE_TEXT, VOICE)
    await communicate.save(str(OUTPUT_FILE))
    file_size = OUTPUT_FILE.stat().st_size
    print(f"已保存: {OUTPUT_FILE} ({file_size} bytes)")

    # 2. 转换为 WAV（用 ffmpeg 或 pydub，若不可用则保留 MP3）
    try:
        from pydub import AudioSegment
        print(f"正在转换为 WAV: {OUTPUT_FILE_WAV}")
        audio = AudioSegment.from_mp3(str(OUTPUT_FILE))
        # 转换为 24kHz 16-bit mono（与 Orpheus 输出对齐）
        audio = audio.set_frame_rate(24000).set_channels(1).set_sample_width(2)
        audio.export(str(OUTPUT_FILE_WAV), format="wav")
        wav_size = OUTPUT_FILE_WAV.stat().st_size
        print(f"已保存: {OUTPUT_FILE_WAV} ({wav_size} bytes, 24kHz 16-bit mono)")
    except ImportError:
        print("pydub 未安装，保留 MP3 格式（可用 Windows Media Player 播放）")
    except Exception as e:
        print(f"WAV 转换失败（{e}），保留 MP3 格式")

    print()
    print("=" * 60)
    print("参考音频生成完成")
    print(f"  文本长度: {len(REFERENCE_TEXT)} 字符")
    print(f"  文本内容: {REFERENCE_TEXT}")
    print()
    print("对比评测建议:")
    print(f"  1. 先听 Orpheus 激进配置样本: audio_sample_aggressive.wav")
    print(f"  2. 再听 edge-tts 参考样本: {OUTPUT_FILE.name} 或 {OUTPUT_FILE_WAV.name}")
    print(f"  3. 对比重点:")
    print(f"     - 整体音质自然度（edge-tts 是云端高质量 TTS）")
    print(f"     - 词组衔接平滑度（Orpheus char_threshold=2 切片粒度较细）")
    print(f"     - 韵律一致性（Orpheus 多段合成可能音调不一致）")
    print(f"     - chunk 边界 artifacts（Orpheus 254 chunks 拼接）")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(generate_reference())
