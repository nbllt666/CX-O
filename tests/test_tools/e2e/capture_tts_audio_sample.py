"""
音质主观评测样本生成脚本
========================
通过 WS 连接 CX-O-SERVER，发送测试音频，捕获所有 voice.tts_chunk 消息，
拼接为完整 WAV 文件供用户主观评测当前激进配置（char_threshold=2 + STREAM_BATCH_FRAMES=1）的音质。

使用方式:
    python tests/test_tools/e2e/capture_tts_audio_sample.py

输出:
    c:/CX-O/.trae/test_reports/audio_sample_aggressive.wav
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import sys
import time
import wave
from pathlib import Path

# 添加项目根到 sys.path（与 test_asr_llm_tts_latency.py 对齐）
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_PROJECT_ROOT / "tests" / "test_tools" / "e2e"))

import numpy as np
import websockets

# 服务地址
CXO_SERVER_WS = os.environ.get("CXO_SERVER_WS", "ws://127.0.0.1:8000/api/ws/{agent_id}")
AGENT_ID = os.environ.get("AGENT_ID", "default")  # 与 test_asr_llm_tts_latency.py 对齐

# 音频参数（与 test_asr_llm_tts_latency.py 对齐：真实中文语音裁剪前 1.0s）
AUDIO_SAMPLE_RATE = 16000
AUDIO_DURATION_S = 2.0
SPEECH_REF_PATH = os.environ.get(
    "SPEECH_REF_PATH",
    r"C:\CX-O\.trae\test_reports\test_zh_changle.wav",
)

# TTS 输出音频参数（CosyVoice3 固定输出 24kHz 16-bit mono）
TTS_SAMPLE_RATE = 24000
TTS_CHANNELS = 1
TTS_SAMPLE_WIDTH = 2  # 16-bit

# 输出文件
OUTPUT_DIR = _PROJECT_ROOT / ".trae" / "test_reports"
OUTPUT_FILE = OUTPUT_DIR / "audio_sample_cosyvoice3_ws.wav"


def generate_test_audio(duration_s: float = AUDIO_DURATION_S, sample_rate: int = AUDIO_SAMPLE_RATE) -> bytes:
    """生成 16kHz mono PCM 16-bit 测试音频（从真实中文语音裁剪前 1.0s）。

    正弦波/静音参考会被 SenseVoice 识别为单个 '.'（1 字），低于双流式语音
    2 字触发阈值，流水线不启动；改用真实中文语音并归一化，驱动 ASR 产出
    多字 Partial 文本触发 LLM→TTS 全链路（与 test_asr_llm_tts_latency.py 对齐）。
    """
    import wave as _wave

    with _wave.open(SPEECH_REF_PATH, "rb") as wf:
        sr = wf.getframerate()
        pcm = wf.readframes(wf.getnframes())
    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
    if sr != sample_rate:
        n_out = int(len(x) * sample_rate / sr)
        x = np.interp(np.linspace(0, len(x) - 1, n_out), np.arange(len(x)), x)
    peak = max(np.max(np.abs(x)), 1)
    x = x / peak * 0.9
    n_samples = int(duration_s * sample_rate)
    x = x[:n_samples] if len(x) > n_samples else x
    return (x * 32767).astype(np.int16).tobytes()


def generate_wav_bytes(pcm: bytes, sample_rate: int = AUDIO_SAMPLE_RATE) -> bytes:
    """将 PCM bytes 封装为 WAV 格式 bytes。"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def save_pcm_as_wav(pcm_bytes: bytes, output_path: Path, sample_rate: int = TTS_SAMPLE_RATE) -> None:
    """将原始 PCM bytes 保存为 WAV 文件。"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_path), "wb") as wf:
        wf.setnchannels(TTS_CHANNELS)
        wf.setsampwidth(TTS_SAMPLE_WIDTH)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    print(f"已保存音频样本: {output_path} ({len(pcm_bytes)} bytes PCM, {len(pcm_bytes)/sample_rate/2:.2f}s)")


async def capture_audio_sample() -> None:
    """通过 WS 连接捕获 TTS 音频样本。"""
    print("=" * 60)
    print("音质主观评测样本生成（CosyVoice3 + 真实参考资产 ref_8df9787c96124a5f）")
    print(f"  char_threshold=2 + STREAM_BATCH_FRAMES=1")
    print("=" * 60)

    # 1. 生成测试音频
    pcm = generate_test_audio()
    wav_bytes = generate_wav_bytes(pcm)
    audio_b64 = base64.b64encode(wav_bytes).decode("ascii")
    print(f"测试音频: {AUDIO_DURATION_S}s @ {AUDIO_SAMPLE_RATE}Hz, {len(wav_bytes)} bytes WAV")

    # 2. 连接 WS
    ws_url = CXO_SERVER_WS.format(agent_id=AGENT_ID)
    print(f"连接 WS: {ws_url}")

    t0 = time.monotonic()
    all_pcm = bytearray()
    chunk_count = 0
    text_segments = []
    first_chunk_t = None
    stream_ended = False

    async with websockets.connect(ws_url, max_size=2**24, open_timeout=10) as ws:
        # 3. 发送 init 消息
        # engine=cosyvoice3 + voice=真实参考资产（与 WS 全链路延迟测试一致）
        init_msg = {
            "action": "voice.dual_stream",
            "request_id": "audio-sample-capture",
            "data": {
                "init": True,
                "agent_id": AGENT_ID,
                "engine": "cosyvoice3",
                "voice": "ref_8df9787c96124a5f",
            },
        }
        await ws.send(json.dumps(init_msg))
        await asyncio.sleep(0.2)  # 等 init 处理

        # 4. 发送音频帧（T0）
        audio_msg = {
            "action": "voice.dual_stream",
            "request_id": "audio-sample-capture",
            "data": {
                "audio": audio_b64,
                "sample_rate": AUDIO_SAMPLE_RATE,
                "is_final": True,
            },
        }
        t_send = time.monotonic()
        await ws.send(json.dumps(audio_msg))
        print(f"已发送音频帧，等待 TTS 响应...")

        # 5. 接收所有 TTS chunk 直到流结束或超时
        deadline = time.monotonic() + 30.0  # 30s 超时（捕获完整音频）
        while time.monotonic() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
            except asyncio.TimeoutError:
                print(f"接收超时（5s 无消息），结束捕获")
                break

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            action = msg.get("action", "")
            msg_type = msg.get("type", "")
            now = time.monotonic()

            # 记录 T2/T3
            if msg_type == "voice.partial" or action == "voice.partial":
                print(f"  T2 voice.partial @ {(now-t_send)*1000:.1f}ms")
            elif msg_type == "voice.prefill_started" or action == "voice.prefill_started":
                print(f"  T3 voice.prefill_started @ {(now-t_send)*1000:.1f}ms")
            elif msg_type == "voice.tts_chunk" or action == "voice.tts_chunk":
                data = msg.get("data", {})
                audio_data_b64 = data.get("audio_data")
                text_segment = data.get("text_segment", "")
                is_final = msg.get("is_final", False)

                if audio_data_b64:
                    if first_chunk_t is None:
                        first_chunk_t = (now - t_send) * 1000
                        print(f"  T5 voice.tts_chunk 首块 @ {first_chunk_t:.1f}ms")

                    pcm_chunk = base64.b64decode(audio_data_b64)
                    all_pcm.extend(pcm_chunk)
                    chunk_count += 1
                    if text_segment:
                        text_segments.append(text_segment)
                    print(f"  chunk {chunk_count}: {len(pcm_chunk)} bytes PCM, text='{text_segment[:30]}', is_final={is_final}")

                if is_final:
                    print(f"  收到 is_final=True，流结束")
                    stream_ended = True
                    break

    # 6. 保存音频
    total_t = (time.monotonic() - t_send) * 1000
    print()
    print("=" * 60)
    print("捕获完成")
    print(f"  总耗时: {total_t:.1f}ms")
    print(f"  首块延迟: {first_chunk_t:.1f}ms" if first_chunk_t else "  首块延迟: N/A")
    print(f"  chunk 数: {chunk_count}")
    print(f"  PCM 总量: {len(all_pcm)} bytes ({len(all_pcm)/TTS_SAMPLE_RATE/TTS_SAMPLE_WIDTH:.2f}s 音频)")
    print(f"  文本片段: {len(text_segments)} 段")
    if text_segments:
        full_text = "".join(text_segments)
        print(f"  完整文本: '{full_text}'")
    print(f"  流正常结束: {stream_ended}")
    print("=" * 60)

    if all_pcm:
        save_pcm_as_wav(bytes(all_pcm), OUTPUT_FILE)
        print()
        print(f"音频样本已保存到: {OUTPUT_FILE}")
        print("请播放该文件进行主观评测。")
        print("评测重点：")
        print("  1. 整体音质是否自然（无机械感、无破碎）")
        print("  2. 词组间衔接是否平滑（char_threshold=2 切片粒度较细）")
        print("  3. 是否有明显的韵律断层或吃字")
        print("  4. 与 STREAM_BATCH_FRAMES=1 是否有 audible artifacts")
    else:
        print("未捕获到任何音频数据！")


if __name__ == "__main__":
    asyncio.run(capture_audio_sample())
