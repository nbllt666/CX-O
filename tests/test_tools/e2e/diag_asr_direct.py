"""直接测试 ASR 流式服务（ws://127.0.0.1:8005/ws/asr/stream）。

发送真实语音参考音频（PCM 16kHz），观察 ASR 返回的 partial/final 文本。
"""
import asyncio
import json
import wave

import websockets

ASR_WS = "ws://127.0.0.1:8005/ws/asr/stream"
REF_PATH = r"C:\CX-O\CX-O-SERVER\data\ref_audio_assets\ref_8df9787c96124a5f.wav"


async def main():
    import numpy as np

    # 读取 24kHz 参考音频并重采样到 16kHz
    with wave.open(REF_PATH, "rb") as wf:
        sr_in = wf.getframerate()
        n_in = wf.getnframes()
        pcm_in = wf.readframes(n_in)
    x_in = np.frombuffer(pcm_in, dtype=np.int16).astype(np.float32) / 32767.0
    n_out = int(n_in * 16000 / sr_in)
    x_out = np.interp(np.linspace(0, n_in - 1, n_out), np.arange(n_in), x_in).astype(np.float32)
    pcm = (x_out * 32767).astype(np.int16)

    # 拆 100ms 帧
    frame_bytes = int(16000 * 0.1) * 2
    frames = [pcm[i : i + frame_bytes].tobytes() for i in range(0, len(pcm), frame_bytes)]
    print(f"发送 {len(frames)} 帧 16kHz PCM (总 {len(pcm)} samples)")

    async with websockets.connect(ASR_WS, max_size=None, ping_interval=20, ping_timeout=10) as ws:
        # 发送所有语音帧
        for i, f in enumerate(frames):
            await ws.send(f)
        # 发送 final 信号
        await ws.send(json.dumps({"action": "final"}))
        print("已发送全部语音帧 + final 信号，等待 ASR 返回...")

        # 接收 5s 内的所有消息
        deadline = asyncio.get_event_loop().time() + 5.0
        n = 0
        while asyncio.get_event_loop().time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            except asyncio.TimeoutError:
                print("[timeout] no message")
                break
            n += 1
            print(f"[{n}] {raw[:200]}")
        print(f"共收到 {n} 条消息")


if __name__ == "__main__":
    asyncio.run(main())
