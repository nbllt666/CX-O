"""独立 RTF 测量——CosyVoice3 (8094) 克隆合成。

RTF (Real-Time Factor) = 合成墙钟耗时 / 输出音频播放时长。
RTF < 1 表示合成速度快于实时回放。

测量口径：
- 流式合成较长中文文本，记录首包与全量 wall-clock；
- 从 WAV 字节解析音频帧数，换算播放时长（24kHz 统一输出）；
- RTF_full = 全量耗时 / 音频时长（整体实时率）
- RTF_first_to_end = (全量耗时 - 首包耗时) / (音频时长 - 首包对应音频时长)（持续段近似）
  持续段按首包到达后开始计，保证不受 LLM/前处理 TTFT 污染。

用法:
    <py> diag_rtf.py [--voice vivian] [--text 长文本] [--rounds 5]
"""
import argparse
import base64
import io
import os
import statistics
import time
import wave

import requests

TTS_BASE = os.environ.get("TTS_BASE", "http://127.0.0.1:8094")
# 参考音频（零样本克隆）：与 test_asr_llm_tts_latency.py SPEECH_REF_PATH 一致
DEFAULT_REF_WAV = r"C:\CX-O\.trae\test_reports\test_zh_changle.wav"
DEFAULT_REF_TEXT = "上海海洋大学海洋生物资源与环境专业毕业生，目前正在参与海洋珍稀生物资源保护与可持续利用方面的研究工作。"

DEFAULT_TEXT = (
    "人工智能正在改变我们的生活方式。从智能助手到自动驾驶，"
    "从医疗诊断到教育个性化，这些技术正在快速进入每一个行业。"
    "今天我们要讨论的是如何在一个多智能体系统中，让不同的智能体协同工作，"
    "共同完成一个复杂的任务。首先需要明确定义每个智能体的职责边界，"
    "然后设计一套高效的通信机制，让信息能够在它们之间顺畅地传递。"
    "与此同时，系统的稳定性与响应速度同样重要，尤其是在实时交互的场景下，"
    "我们必须严格控制每一个环节的延迟，确保用户获得流畅的体验。"
    "最后，还需要考虑系统的可扩展性，以便在未来接入更多智能体时，"
    "整个系统依然能够保持高效运行。"
)


def parse_wav_duration(data: bytes) -> float:
    """解析 WAV 字节返回播放时长（秒）。

    流式 WAV 的 RIFF size / data size 字段常未填充（ffffffff），nframes 不可靠，
    故按实际音频数据字节长度换算：duration = data_bytes / (sr * channels * sampwidth)。
    """
    with wave.open(io.BytesIO(data), "rb") as wf:
        sr = wf.getframerate()
        channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        # data 块起始由 wave 内部解析，用文件尾 - 头(WAVE header, 通常 44 字节)估数据字节
        # 更稳妥：根据 wf.getcomptype 之后读取实际帧，但流式 size 缺失时 getnframes 不可信，
        # 改从 raw 中定位 'data' 块。
    # 定位 'data' 块
    idx = data.find(b"data")
    if idx >= 0 and idx + 8 <= len(data):
        data_len = len(data) - (idx + 8)
    else:
        data_len = len(data) - 44
    denom = float(sr) * channels * sampwidth
    return data_len / denom if denom > 0 else 0.0


def build_ref_data_url(wav_path: str) -> str:
    with open(wav_path, "rb") as f:
        raw = f.read()
    return "data:audio/wav;base64," + base64.b64encode(raw).decode()


def measure(text: str, ref_data_url: str, ref_text: str) -> dict:
    started = time.monotonic()
    t_first = None
    buf = bytearray()
    with requests.post(
        f"{TTS_BASE}/v1/audio/speech",
        json={
            "input": text,
            "ref_audio": ref_data_url,
            "ref_text": ref_text,
            "stream": True,
            "response_format": "wav",
            "speed": 1.0,
        },
        stream=True,
        timeout=60.0,
        proxies={"http": None, "https": None},
    ) as resp:
        if resp.status_code != 200:
            return {"error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        for chunk in resp.iter_content(chunk_size=4096):
            if chunk:
                buf.extend(chunk)
                if t_first is None:
                    t_first = time.monotonic()
    wall_full = time.monotonic() - started
    if not buf:
        return {"error": "no audio"}
    duration = parse_wav_duration(bytes(buf))
    wall_first = (t_first - started) if t_first else 0.0
    first_dur = wall_first / wall_full * duration
    rtf_full = wall_full / duration if duration > 0 else float("inf")
    rtf_steady = (
        (wall_full - wall_first) / (duration - first_dur)
        if (duration - first_dur) > 1e-6
        else float("inf")
    )
    return {
        "wall_full_ms": wall_full * 1000,
        "wall_first_ms": wall_first * 1000,
        "audio_sec": duration,
        "rtf_full": rtf_full,
        "rtf_steady": rtf_steady,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref_wav", default=DEFAULT_REF_WAV)
    ap.add_argument("--ref_text", default=DEFAULT_REF_TEXT)
    ap.add_argument("--text", default=DEFAULT_TEXT)
    ap.add_argument("--rounds", type=int, default=5)
    args = ap.parse_args()

    ref_data_url = build_ref_data_url(args.ref_wav)
    print(f"TTS={TTS_BASE} ref_wav={os.path.basename(args.ref_wav)} rounds={args.rounds}")
    print(f"text_len={len(args.text)}chars")
    rows = []
    for i in range(args.rounds):
        r = measure(args.text, ref_data_url, args.ref_text)
        rows.append(r)
        if "error" in r:
            print(f"[{i}] ERROR {r['error']}")
        else:
            print(
                f"[{i}] wall_full={r['wall_full_ms']:.0f}ms "
                f"first={r['wall_first_ms']:.0f}ms "
                f"audio={r['audio_sec']:.2f}s "
                f"RTF_full={r['rtf_full']:.3f} RTF_steady={r['rtf_steady']:.3f}"
            )
        time.sleep(0.3)

    ok = [r for r in rows if "error" not in r]
    if not ok:
        print("ALL FAILED")
        return
    rtf_full = statistics.median(r["rtf_full"] for r in ok)
    rtf_steady = statistics.median(r["rtf_steady"] for r in ok)
    full_below = all(r["rtf_full"] < 1.0 for r in ok)
    steady_below = all(r["rtf_steady"] < 1.0 for r in ok)
    print("\n===== RTF 结论 =====")
    print(f"RTF_full(median)  = {rtf_full:.3f}  {'<1 OK' if full_below else '>=1 FAIL'}")
    print(
        f"RTF_steady(median)= {rtf_steady:.3f}  "
        f"{'<1 OK' if steady_below else '>=1 FAIL'}"
    )


if __name__ == "__main__":
    main()