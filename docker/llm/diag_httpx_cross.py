"""独立进程：最小 FastAPI 服务 + 独立 httpx 客户端，验证 httpx 跨进程流式首包是否延迟。

排除 CosyVoice 因素：服务端立即发首块（无 prefill），若 httpx 仍延迟则根因在 httpx。
"""
import asyncio
import subprocess
import sys
import time

import httpx


SERVER_SCRIPT = r"C:\CX-O\docker\llm\_min_stream_server.py"
PORT = 18100
URL = f"http://127.0.0.1:{PORT}/v1/audio/speech"


async def main():
    # 启动最小服务（独立进程）
    proc = subprocess.Popen(
        [sys.executable, SERVER_SCRIPT],
        cwd=r"C:\CX-O\docker\llm",
    )
    await asyncio.sleep(3.0)
    try:
        t0 = time.monotonic()
        async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
            async with client.stream("POST", URL, json={}) as resp:
                hdr = time.monotonic() - t0
                print(f"[{hdr:6.2f}s] HTTP {resp.status_code} headers")
                first = None
                n = 0
                async for raw in resp.aiter_bytes():
                    if first is None:
                        first = time.monotonic() - t0
                        print(f"[{first:6.2f}s] FIRST chunk: {len(raw)} bytes")
                    n += 1
                print(f"[{time.monotonic()-t0:6.2f}s] DONE headers={hdr:.2f}s first={first:.2f}s chunks={n}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    asyncio.run(main())
