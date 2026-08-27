"""TTS→ASR 真实业务逻辑端到端测试。

与 test_asr_llm_tts_latency.py（440Hz 正弦波）不同，本脚本使用 Orpheus TTS
生成的真实中文语音作为 ASR 输入，验证"像真实用户说话一样"的完整业务链路：

  阶段1  TTS 生成：POST /v1/audio/speech（长乐音色，非流式 WAV）
  阶段2  ASR 服务层直测：POST /asr/recognize（base64 WAV → 识别文本）
  阶段3  WS 业务链路：/ws voice.dual_stream（init → PCM 音频块 → end），
         收集 voice.partial / voice.prefill_started / voice.tts_chunk
  阶段4  文本比对 + 报告落盘

用法:
    python test_tts_asr_business_e2e.py
    python test_tts_asr_business_e2e.py --text "你好，今天天气真不错。" --voice 长乐
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import sys
import time

import numpy as np
import requests

# --------------------------------------------------------------------------- #
# 服务地址（与 docker-compose.yml / vite.config.ts 对齐）
# --------------------------------------------------------------------------- #
TTS_BASE = os.environ.get("TTS_BASE", "http://127.0.0.1:5060")
ASR_BASE = os.environ.get("ASR_BASE", "http://127.0.0.1:8005")
CXO_WS = os.environ.get("CXO_WS", "ws://127.0.0.1:8000/ws")

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_OUTPUT_DIR = os.path.join(_PROJECT_ROOT, ".trae", "test_reports")

TARGET_SAMPLE_RATE = 16000  # WS 链路要求 16kHz PCM
CHUNK_MS = 100              # 与前端 chunkInterval 一致
NO_PROXY = {"http": None, "https": None}


def log(level: str, msg: str, t0: float | None = None) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    elapsed = f" elapsed={time.monotonic() - t0:.2f}s" if t0 is not None else ""
    print(f"[{ts}] [{level}] {msg}{elapsed}", flush=True)


# --------------------------------------------------------------------------- #
# 音频工具
# --------------------------------------------------------------------------- #
def wav_to_float(wav_bytes: bytes) -> tuple[np.ndarray, int]:
    """WAV bytes → (float32 单声道数组, 采样率)。"""
    import io
    import wave

    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        sr = wf.getframerate()
        ch = wf.getnchannels()
        sw = wf.getsampwidth()
        frames = wf.readframes(wf.getnframes())

    dtype = {1: np.uint8, 2: np.int16, 4: np.int32}[sw]
    arr = np.frombuffer(frames, dtype=dtype)
    if dtype == np.uint8:
        audio = (arr.astype(np.float32) - 128) / 128.0
    elif dtype == np.int16:
        audio = arr.astype(np.float32) / 32768.0
    else:
        audio = arr.astype(np.float32) / 2147483648.0
    if ch > 1:
        audio = audio.reshape(-1, ch).mean(axis=1)
    return audio, sr


def resample_linear(audio: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    if src_sr == dst_sr:
        return audio
    n = int(len(audio) * dst_sr / src_sr)
    idx = np.linspace(0, len(audio) - 1, n)
    return np.interp(idx, np.arange(len(audio)), audio).astype(np.float32)


def float_to_pcm16(audio: np.ndarray) -> bytes:
    clipped = np.clip(audio, -1.0, 1.0)
    return (clipped * 32767).astype(np.int16).tobytes()


def text_similarity(expected: str, actual: str) -> float:
    """去标点空白后的字符级命中率（actual 覆盖 expected 的比例）。"""
    import re

    def norm(s: str) -> str:
        return re.sub(r"[\s，。！？,.!?'\"、~～…·—\-<>《》|]+", "", s)

    e, a = norm(expected), norm(actual)
    if not e:
        return 0.0
    hit = sum(1 for ch in e if ch in a)
    return hit / len(e)


# --------------------------------------------------------------------------- #
# 阶段1：TTS 生成真实语音
# --------------------------------------------------------------------------- #
def tts_generate(text: str, voice: str) -> bytes:
    t0 = time.monotonic()
    log("INFO", f"阶段1 TTS 生成: voice={voice} text={text!r}")
    resp = requests.post(
        f"{TTS_BASE}/v1/audio/speech",
        json={"input": text, "voice": voice, "stream": False, "response_format": "wav", "speed": 1.0},
        timeout=600.0,
        proxies=NO_PROXY,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"TTS HTTP {resp.status_code}: {resp.text[:300]}")
    wav = resp.content
    if len(wav) < 100 or wav[:4] != b"RIFF":
        raise RuntimeError(f"TTS 返回非 WAV 数据: {wav[:80]!r}")
    log("INFO", f"阶段1 TTS 生成完成: {len(wav)} bytes", t0)
    return wav


# --------------------------------------------------------------------------- #
# 阶段2：ASR 服务层直测
# --------------------------------------------------------------------------- #
def asr_http_recognize(wav_bytes: bytes, language: str = "zh") -> dict:
    t0 = time.monotonic()
    log("INFO", "阶段2 ASR 服务层直测: POST /asr/recognize")
    resp = requests.post(
        f"{ASR_BASE}/asr/recognize",
        json={"audio": base64.b64encode(wav_bytes).decode("ascii"), "language": language, "use_itn": True},
        timeout=120.0,
        proxies=NO_PROXY,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"ASR HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    log("INFO", f"阶段2 ASR 识别结果: {data.get('text', '')!r}", t0)
    return data


# --------------------------------------------------------------------------- #
# 阶段3：WS 业务链路（voice.dual_stream）
# --------------------------------------------------------------------------- #
async def ws_dual_stream_round(pcm16: bytes, expected_text: str, voice: str) -> dict:
    import websockets

    result: dict = {
        "connected": False,
        "partials": [],
        "final_text": "",
        "prefill_text": "",
        "tts_chunks": 0,
        "tts_audio_bytes": 0,
        "messages_seen": {},
        "error": None,
    }
    session_id = f"biz-e2e-{int(time.time())}"
    agent_id = "default"
    request_id = f"{session_id}-r0"

    t0 = time.monotonic()
    log("INFO", f"阶段3 WS 业务链路: {CXO_WS} session={session_id}")
    try:
        async with websockets.connect(CXO_WS, max_size=2**24, open_timeout=10) as ws:
            result["connected"] = True
            # 读 connected 问候
            try:
                greet = json.loads(await asyncio.wait_for(ws.recv(), timeout=3))
                log("INFO", f"  WS 已连接: {greet.get('type')}")
            except asyncio.TimeoutError:
                pass

            # init
            await ws.send(json.dumps({
                "action": "voice.dual_stream",
                "request_id": request_id,
                "data": {
                    "init": True,
                    "session_id": session_id,
                    "agent_id": agent_id,
                    "request_id": request_id,
                    "engine": "orpheus",
                    "voice": voice,
                },
            }))
            await asyncio.sleep(0.3)

            # 分块推送 PCM（模拟前端 100ms 间隔）
            chunk_size = TARGET_SAMPLE_RATE * 2 * CHUNK_MS // 1000  # 16bit=2B
            sent = 0
            for off in range(0, len(pcm16), chunk_size):
                chunk = pcm16[off:off + chunk_size]
                await ws.send(json.dumps({
                    "action": "voice.dual_stream",
                    "request_id": request_id,
                    "data": {
                        "type": "audio",
                        "audio": base64.b64encode(chunk).decode("ascii"),
                        "session_id": session_id,
                        "agent_id": agent_id,
                        "request_id": request_id,
                    },
                }))
                sent += 1
                await asyncio.sleep(CHUNK_MS / 1000.0)
            log("INFO", f"  音频推送完成: {sent} 块 / {len(pcm16)} bytes", t0)

            # end
            await ws.send(json.dumps({
                "action": "voice.dual_stream",
                "request_id": request_id,
                "data": {"end": True, "session_id": session_id, "agent_id": agent_id, "request_id": request_id},
            }))

            # 收集回推消息（最多 30s；收到 tts is_final 则提前结束）
            deadline = time.monotonic() + 30.0
            while time.monotonic() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                except asyncio.TimeoutError:
                    if result["tts_chunks"] > 0:
                        break
                    continue
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                mtype = msg.get("type", "")
                action = msg.get("action", "")
                key = action or mtype
                result["messages_seen"][key] = result["messages_seen"].get(key, 0) + 1
                data = msg.get("data", {}) or {}

                if key == "voice.partial":
                    txt = data.get("text", "")
                    if txt:
                        result["partials"].append(txt)
                        result["final_text"] = txt
                elif key == "voice.prefill_started":
                    result["prefill_text"] = data.get("partial_text") or data.get("text", "")
                elif key == "voice.tts_chunk":
                    ad = data.get("audio_data")
                    if ad:
                        result["tts_chunks"] += 1
                        result["tts_audio_bytes"] += len(ad) * 3 // 4
                    if msg.get("is_final") or data.get("is_final"):
                        break
                elif key in ("error", "response"):
                    err = msg.get("error") or data.get("error") or data
                    result["error"] = f"WS error: {str(err)[:200]}"
                    break

            log("INFO", f"  WS 收信完成: partials={len(result['partials'])} "
                        f"prefill={'有' if result['prefill_text'] else '无'} "
                        f"tts_chunks={result['tts_chunks']}", t0)
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {str(e)[:200]}"
        log("ERROR", f"  WS 链路异常: {result['error']}", t0)
    return result


# --------------------------------------------------------------------------- #
# 报告
# --------------------------------------------------------------------------- #
def write_report(lines: list[str]) -> str:
    os.makedirs(DEFAULT_OUTPUT_DIR, exist_ok=True)
    path = os.path.join(DEFAULT_OUTPUT_DIR, f"tts_asr_business_e2e_{time.strftime('%Y%m%d_%H%M%S')}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


async def run(text: str, voice: str) -> bool:
    t_all = time.monotonic()
    lines: list[str] = [
        "# TTS→ASR 真实业务逻辑端到端测试报告",
        "",
        f"> 测试时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"> TTS 输入文本: {text}",
        f"> TTS 音色: {voice}",
        "",
    ]
    ok = True

    # 阶段1
    try:
        wav = tts_generate(text, voice)
        audio_f, sr = wav_to_float(wav)
        lines += ["## 阶段1 TTS 生成", "", f"- WAV: {len(wav)} bytes, {sr}Hz, {len(audio_f)/sr:.2f}s ✅", ""]
    except Exception as e:
        log("ERROR", f"阶段1 失败: {e}")
        lines += ["## 阶段1 TTS 生成", "", f"- ❌ {e}", ""]
        lines.append("**总体结论: ❌ 失败（TTS 阶段）**")
        return False

    # 阶段2
    asr_text = ""
    try:
        asr_resp = asr_http_recognize(wav)
        asr_text = asr_resp.get("text", "")
        sim = text_similarity(text, asr_text)
        lines += [
            "## 阶段2 ASR 服务层直测（POST /asr/recognize）", "",
            f"- 识别文本: {asr_text}",
            f"- 与 TTS 输入相似度: {sim:.0%} {'✅' if sim >= 0.6 else '❌'}", "",
        ]
        if sim < 0.6:
            ok = False
    except Exception as e:
        log("ERROR", f"阶段2 失败: {e}")
        lines += ["## 阶段2 ASR 服务层直测", "", f"- ❌ {e}", ""]
        ok = False

    # 阶段3
    pcm16 = float_to_pcm16(resample_linear(audio_f, sr, TARGET_SAMPLE_RATE))
    ws_res = await ws_dual_stream_round(pcm16, text, voice)
    ws_sim = text_similarity(text, ws_res["final_text"]) if ws_res["final_text"] else 0.0
    lines += [
        "## 阶段3 WS 业务链路（/ws voice.dual_stream）", "",
        f"- WS 连接: {'✅' if ws_res['connected'] else '❌'}",
        f"- ASR partial 消息数: {len(ws_res['partials'])}",
        f"- ASR 最终识别文本: {ws_res['final_text'] or '（无）'}",
        f"- 与 TTS 输入相似度: {ws_sim:.0%} {'✅' if ws_sim >= 0.6 else '❌'}",
        f"- LLM prefill 文本: {ws_res['prefill_text'] or '（无）'}",
        f"- TTS 回推音频块: {ws_res['tts_chunks']} 块 / 约 {ws_res['tts_audio_bytes']} bytes",
    ]
    if ws_res["messages_seen"]:
        seen = ", ".join(f"{k}×{v}" for k, v in sorted(ws_res["messages_seen"].items()))
        lines.append(f"- 消息类型统计: {seen}")
    if ws_res["error"]:
        lines.append(f"- 错误: {ws_res['error']}")
        ok = False
    lines.append("")
    if not ws_res["final_text"]:
        ok = False
        lines.append("- ⚠️ 未收到任何 voice.partial（ASR 链路未产出识别文本）")
        lines.append("")

    # 阶段4 总结
    lines += [
        "## 总体结论", "",
        "| 检查项 | 结果 |", "|--------|------|",
        f"| TTS 生成真实语音 | {'✅' if True else '❌'} |",
        f"| ASR 服务层识别 | {'✅' if asr_text else '❌'} |",
        f"| WS 链路 ASR partial | {'✅' if ws_res['final_text'] else '❌'} |",
        f"| WS 链路 LLM prefill | {'✅' if ws_res['prefill_text'] else '⚠️'} |",
        f"| WS 链路 TTS 回推 | {'✅' if ws_res['tts_chunks'] > 0 else '⚠️'} |",
        "",
        f"**总体: {'✅ 通过' if ok else '❌ 存在失败项'}**（耗时 {time.monotonic() - t_all:.1f}s）",
        "",
    ]
    path = write_report(lines)
    log("INFO", f"报告已保存: {path}")
    log("INFO", f"总体结论: {'通过' if ok else '存在失败项'}", t_all)
    return ok


def main() -> None:
    parser = argparse.ArgumentParser(description="TTS→ASR 真实业务逻辑 E2E 测试")
    parser.add_argument("--text", default="你好，我是你的智能助手，今天天气真不错。", help="TTS 合成文本")
    parser.add_argument("--voice", default="长乐", help="TTS 音色")
    args = parser.parse_args()

    ok = asyncio.run(run(args.text, args.voice))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
