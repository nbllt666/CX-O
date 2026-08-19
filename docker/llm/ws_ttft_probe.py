"""最小 WS 探针：模拟生产 voice.dual_stream 新会话首次请求，触发 LLM 记录 DIAG-TTFT。

用途（Task A4 验证辅助）：
- 连接 CX-O-SERVER WS 端点（/api/ws/default），发送 voice.dual_stream init + 一段测试音频。
- 触发生产实时语音链路（ASR→LLM），使服务端走 build_messages(is_realtime_voice=True) +
  VLLMClient.stream_chat，在服务端日志留下 [DIAG-TTFT] first token at Xms 证据。
- 说明：TTS(8094) 未在本任务范围，TTS 失败不影响 LLM 请求与 DIAG-TTFT 记录。

用法:
    python docker/llm/ws_ttft_probe.py
"""
import asyncio
import base64
import io
import json
import sys
import time
import wave

import numpy as np
import websockets

WS_URL = "ws://127.0.0.1:8000/api/ws/default"
SAMPLE_RATE = 16000
WAV_PATH = r"c:\CX-O\test_asr.wav"  # 真实语音样本（24kHz 3.93s，含人声）


def load_wav_b64(path: str) -> tuple:
    """读取 WAV 文件并返回 (base64, sample_rate)。"""
    import wave
    with wave.open(path, "rb") as wf:
        sr = wf.getframerate()
        nframes = wf.getnframes()
        pcm = wf.readframes(nframes)
    return base64.b64encode(pcm).decode("ascii"), sr


def gen_wav_b64(duration_s: float = 1.0) -> str:
    """生成 16kHz mono 16-bit 正弦波测试音频并返回 base64 WAV（回退用）。"""
    n = int(duration_s * SAMPLE_RATE)
    t = np.linspace(0, duration_s, n, endpoint=False, dtype=np.float32)
    wave_data = 0.5 * np.sin(2 * np.pi * 440 * t)
    pcm = (wave_data * 32767).astype(np.int16).tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm)
    return base64.b64encode(buf.getvalue()).decode("ascii")


async def main():
    print(f"连接 WS: {WS_URL}")
    async with websockets.connect(WS_URL, max_size=2**24, open_timeout=10) as ws:
        # init
        await ws.send(json.dumps({
            "action": "voice.dual_stream",
            "request_id": "ttft-probe",
            "data": {"init": True, "agent_id": "default"},
        }))
        await asyncio.sleep(0.2)

        # 发送音频（触发 ASR→LLM）：优先用真实语音样本，回退正弦波
        t0 = time.monotonic()
        try:
            audio_b64, audio_sr = load_wav_b64(WAV_PATH)
            print(f"使用真实语音样本: {WAV_PATH} ({audio_sr}Hz)")
        except Exception:
            audio_b64, audio_sr = gen_wav_b64(), SAMPLE_RATE
            print(f"回退正弦波 ({audio_sr}Hz)")
        await ws.send(json.dumps({
            "action": "voice.dual_stream",
            "request_id": "ttft-probe",
            "data": {"audio": audio_b64, "sample_rate": audio_sr, "is_final": True},
        }))
        print(f"音频已发送，等待服务端响应...")

        # 接收消息（观察链路信号），最多 40s；单次 recv 超时 15s（避免 WS 提前关闭
        # 导致服务端 pipeline 取消、LLM stream 未完成而漏记 DIAG-TTFT）
        deadline = time.monotonic() + 40.0
        while time.monotonic() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=15.0)
            except asyncio.TimeoutError:
                print(f"接收超时（15s 无消息），结束捕获")
                break
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            now = (time.monotonic() - t0) * 1000
            action = msg.get("action", "")
            msg_type = msg.get("type", "")
            data = msg.get("data", {})
            print(f"[{now:7.1f}ms] action={action} type={msg_type} text={data.get('partial_text', data.get('text', ''))[:30]}")
            if action == "voice.prefill_started":
                print(f"  → LLM pipeline 已启动，等待 DIAG-TTFT 记录...")
            if action == "voice.tts_chunk":
                print(f"  → 收到 TTS chunk")
    print("探针结束。请检查 CX-O-SERVER 日志中的 [DIAG-TTFT] first token 时间。")


if __name__ == "__main__":
    asyncio.run(main())
