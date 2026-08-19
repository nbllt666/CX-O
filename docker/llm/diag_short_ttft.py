"""短文本（3字）CosyVoice 首块延迟直测，复现 WS 路径的 TTS 行为。

WS 路径经 split_text_streaming 把回复切成 3-5 字短段，每段单独 HTTP POST 到
CosyVoice（ref_audio 为 ref_8df9787c96124a5f）。本脚本用同构短文本 + 1.5s 间隔
复现其首块分布，定位 0.34~0.59s 波动根因。
"""
import asyncio
import base64
import time
from pathlib import Path

import httpx

TTS = "http://127.0.0.1:8094/v1/audio/speech"
REF_PATH = Path(r"C:\CX-O\CX-O-SERVER\data\ref_audio_assets\ref_8df9787c96124a5f.wav")
REF_B64 = base64.b64encode(REF_PATH.read_bytes()).decode("ascii")
REF_TEXT = "参考音频转写文本。"


async def one(client: httpx.AsyncClient, text: str, idx: int):
    t0 = time.monotonic()
    first = None
    async with client.stream(
        "POST", TTS,
        json={"input": text,
              "ref_audio": f"data:audio/wav;base64,{REF_B64}",
              "ref_text": REF_TEXT,
              "stream": True, "response_format": "wav", "speed": 1.0},
        timeout=30.0,
    ) as resp:
        if resp.status_code != 200:
            body = b""
            async for b in resp.aiter_bytes():
                body += b
                if len(body) > 300:
                    break
            print(f"[{idx}] HTTP {resp.status_code}: {body[:200]!r}")
            return
        n = 0
        async for chunk in resp.aiter_bytes():
            n += len(chunk)
            if first is None:
                first = (time.monotonic() - t0) * 1000
            if n > 2000:
                break
    print(f"[{idx}] text={len(text)}字 first={first:.0f}ms")


async def main():
    # trust_env=False：禁用系统代理（Windows 上 httpx 默认走代理，导致 127.0.0.1 502）
    async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
        await one(client, "预热连接。", -1)
        await asyncio.sleep(0.5)
        texts = ["今天天气", "你好呀", "很不错", "太好了", "没问题", "可以的", "好的呢", "再见啦"]
        for i, t in enumerate(texts):
            await one(client, t, i)
            await asyncio.sleep(1.5)


asyncio.run(main())
