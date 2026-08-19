"""验证 CosyVoice3 TTS 是否真正流式多块输出（chunk 数、首块延迟）。"""
import io
import time
import wave
import requests
import numpy as np

TTS_URL = "http://127.0.0.1:8094/v1/audio/speech"
REF = r"C:\CX-O\docker\llm\cosyvoice_tmp\warmup_ref.wav"


def load_ref_b64() -> str:
    with open(REF, "rb") as f:
        return "data:audio/wav;base64," + __import__("base64").b64encode(f.read()).decode()


def main():
    ref_b64 = load_ref_b64()
    n_chunks = 0
    total_bytes = 0
    first = None
    t0 = time.monotonic()
    with requests.post(
        TTS_URL,
        json={
            "input": "你好，我是AI助手，今天天气不错，适合出去走走。",
            "ref_audio": ref_b64,
            "ref_text": "参考音频",
            "stream": True,
            "response_format": "wav",
        },
        stream=True,
        timeout=60,
        proxies={"http": None, "https": None},
    ) as r:
        print(f"status={r.status_code}")
        if r.status_code != 200:
            print(r.text[:300])
            return
        for chunk in r.iter_content(chunk_size=4096):
            if chunk:
                if first is None:
                    first = time.monotonic() - t0
                    print(f"first chunk at {first*1000:.0f}ms, len={len(chunk)}B")
                n_chunks += 1
                total_bytes += len(chunk)
    print(f"total chunks={n_chunks}, total_bytes={total_bytes}, duration={time.monotonic()-t0:.2f}s")
    print(f"结论: {'✅ 真正流式多块' if n_chunks > 5 else '⚠️ 块数偏少'} (chunks={n_chunks})")


if __name__ == "__main__":
    main()
