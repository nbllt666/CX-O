"""评测 agent_interrupt_user 的 LLM 三态判定准确率（语音结束 / 打断判定 E2E）。

目的
----
评测 agent_interrupt_user 的 LLM 三态判定（CONTINUE / IGNORE / INTERRUPT）
作为语音结束 / 打断判定的准确率：
- 误触发率：标注"不应打断"场景被误插话打断的比例
- 正确判定结束率：标注"应打断 / 需回复"场景在完整音频播放完毕后被正确打断的比例

场景标注集（SB-3）：5 类场景，均用 TTS 合成真实语音音频（noise 用程序化合成）：
  complete_question  完整提问      应打断=是  需回复=是
  paused_long        带停顿长句    应打断=否  需回复=是（说完后）
  self_talk          自言自语      应打断=否  需回复=否
  short_phrases      连续短句      应打断=否  需回复=是（说完后）
  noise              环境噪音      应打断=否  需回复=否

评测流程（已批准 spec，禁止偏离）：
  1. 服务探测：GET {BASE}/api/stats 或 /api/health 可达；不可达 exit 77（SKIP）
  2. ADMIN_API_KEY 检查：环境变量为空则打印提示并 FAIL（exit 1）
  3. enabled=false 基线轮（F9）：5 场景各跑一轮双流链路，断言收集到 0 个
     voice.interrupted(reason=agent_interrupt) 事件（验证关闭时无插话打断）
  4. 前置启用（SB-1）：POST /api/stats/interrupt/enable
     body {"enabled": true, "speech_end_fallback": true}，header X-API-Key，
     校验返回 data.enabled=true 且 data.speech_end_fallback=true；失败则 FAIL（exit 1）
  5. 评测主轮：5 场景各跑一轮双流链路，每场景前 / 后 GET /api/stats/interrupt
     快照，delta 作为该场景判定分布；收集 voice.partial / voice.interrupted /
     vad_status / vad_frame / voice.tts_chunk
  6. 率计算（F4）：误触发率 = 误触发场景数 ÷ 总场景数(5)；
     正确判定结束率 = 正确判定结束场景数 ÷ 需回复场景数(3)
  7. 恢复（Q5）：POST /api/stats/interrupt/enable body {"enabled": false}
  8. 输出 reports/llm_vad_accuracy_<ts>.json（含 services / 基线轮 / 每场景 / 汇总）

退出码：0=PASS / 77=SKIP（服务不可达）/ 其他=FAIL。
"""
import argparse
import asyncio
import base64
import io
import json
import os
import sys
import time
import wave

import httpx
import numpy as np
import websockets

# Windows 终端 GBK 输出会因 emoji/特殊字符崩溃，统一 UTF-8 容错（参考 voice_chat_e2e.py）
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = "http://127.0.0.1:8000"
from _e2e_agent import E2E_AGENT_ID, reset_agent_state, restore_agent_state
WS_URL = f"ws://127.0.0.1:8000/api/ws/{E2E_AGENT_ID}"
REF_ASSET = "ref_034ed0259d8043db"
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")

FRAME_MS = 30            # 音频帧时长（毫秒）
TAIL_SILENCE_S = 0.8     # 尾部静音窗口：确认完整音频播放完毕后的 VAD 结束判定
PAUSE_SILENCE_S = 0.6    # 停顿场景中段插入静音时长（≥500ms，满足 spec 要求）
RECV_WINDOW_S = 25.0     # WS 接收窗口（秒）：覆盖 LLM 判定（~8s）+ 回复合成余量
LEAD_SILENCE_S = 0.6     # 先导静音（秒）：每个场景(含基线轮/每轮)Speech 前预置，冲刷远程 ASR
                         # 残留缓冲/跨场景串扰，再触发判定——隔离"上一场景尾音被误识为当前语音"。

ADMIN_KEY = os.environ.get("ADMIN_API_KEY", "")

# 场景标注集（SB-3）：ground truth
# mode 说明：
#   tts        单段 TTS 合成整句
#   tts_paused 两段 TTS 合成，中段插入 ≥500ms 静音再续接（带停顿长句）
#   tts_short  多段短句 TTS 合成拼接，短停顿间隔（连续短句）
#   noise      程序化生成环境噪音 / 咳嗽样音频，无有效语义
SCENES = [
    {"key": "complete_question", "mode": "tts", "text": "今天天气怎么样？",
     "should_interrupt": True, "need_reply": True},
    {"key": "paused_long", "mode": "tts_paused",
     "text": ("我想问一下，明天下午的安排是什么", "还有需要准备什么材料吗"),
     "should_interrupt": False, "need_reply": True},
    {"key": "self_talk", "mode": "tts", "text": "唉，今天好累啊",
     "should_interrupt": False, "need_reply": False},
    {"key": "short_phrases", "mode": "tts_short", "text": ("嗯……", "然后呢？"),
     "should_interrupt": False, "need_reply": True},
    {"key": "noise", "mode": "noise", "text": "",
     "should_interrupt": False, "need_reply": False},
]


def wav_info(wav_bytes: bytes):
    """读取 WAV 基本参数（采样率 / 声道数 / 帧数）。"""
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        return wf.getframerate(), wf.getnchannels(), wf.getnframes()


def to_16k_pcm(wav_bytes: bytes) -> bytes:
    """任意采样率/声道 WAV → 16kHz 单声道 int16 PCM（复用 voice_chat_e2e.py 逻辑）。"""
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        sr = wf.getframerate()
        nch = wf.getnchannels()
        pcm = wf.readframes(wf.getnframes())
    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
    if nch > 1:
        x = x[::nch]
    if sr != 16000:
        n_out = int(len(x) * 16000 / sr)
        x = np.interp(np.linspace(0, len(x) - 1, n_out), np.arange(len(x)), x)
    x = np.clip(x, -32768, 32767)
    return x.astype(np.int16).tobytes()


async def step_tts(client: httpx.AsyncClient, text: str) -> bytes:
    """TTS 合成一段文本，返回 WAV bytes（复用 voice_chat_e2e.py step_tts）。"""
    r = await client.post(
        f"{BASE}/api/tts/synthesize",
        json={"text": text, "ref_asset_id": REF_ASSET},
    )
    r.raise_for_status()
    data = r.json()
    assert data.get("status") == "success", data
    return base64.b64decode(data["audio_data"])


def gen_noise_wav() -> bytes:
    """程序化生成环境噪音 / 咳嗽样音频（正弦脉冲 + 随机噪声基底，无有效语义）。

    参考 gen_test_audio.py 的正弦 / 脉冲合成思路：随机噪声做基底，叠加几段
    短促衰减正弦脉冲模拟咳嗽声，固定随机种子保证可复现。
    """
    sr = 16000
    dur = 2.0
    n = int(sr * dur)
    rng = np.random.default_rng(42)
    # 低频随机噪声基底（微弱背景噪音）
    base = rng.uniform(-1.0, 1.0, n) * 0.05
    # 咳嗽样脉冲：短促衰减正弦（900/700/1100/850Hz）
    for start, freq in [(0.2, 900), (0.5, 700), (0.9, 1100), (1.4, 850)]:
        i0 = int(start * sr)
        length = int(0.15 * sr)
        if i0 + length < n:
            idx = np.arange(length, dtype=np.float64)
            pulse = 0.4 * np.sin(2 * np.pi * freq * idx / sr) * np.exp(-idx / (0.03 * sr))
            base[i0:i0 + length] += pulse
    x = np.clip(base * 32767, -32768, 32767)
    pcm = x.astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


async def build_scene_pcm(client: httpx.AsyncClient, scene: dict) -> tuple:
    """按场景 mode 生成 16k PCM 音频与文本描述。

    返回 (pcm_16k, text_desc)：
    - tts：单段 TTS 合成 → to_16k_pcm
    - tts_paused：两段 TTS 合成，中段插入 ≥500ms 静音再拼接（带停顿长句）
    - tts_short：多段短句 TTS 合成，短停顿间隔拼接（连续短句）
    - noise：程序化噪音（复用 to_16k_pcm 统一转 16k PCM）
    """
    mode = scene["mode"]
    if mode == "tts":
        wav = await step_tts(client, scene["text"])
        return to_16k_pcm(wav), scene["text"]
    if mode == "tts_paused":
        texts = scene["text"]
        pcm_a = to_16k_pcm(await step_tts(client, texts[0]))
        pcm_b = to_16k_pcm(await step_tts(client, texts[1]))
        # 中段插入静音（≥500ms）：模拟用户组织语言时的停顿
        silence = b"\x00" * (int(16000 * PAUSE_SILENCE_S) * 2)
        return pcm_a + silence + pcm_b, " / ".join(texts)
    if mode == "tts_short":
        texts = scene["text"]
        parts = [to_16k_pcm(await step_tts(client, t)) for t in texts]
        # 短停顿间隔拼接（模拟连续短句的思考间隙）
        gap = b"\x00" * (int(16000 * 0.25) * 2)
        return gap.join(parts), " / ".join(texts)
    if mode == "noise":
        wav = gen_noise_wav()
        return to_16k_pcm(wav), "[程序化环境噪音]"
    raise ValueError(f"未知场景 mode: {mode}")


async def run_dual_stream(pcm_16k: bytes, tag: str) -> dict:
    """跑一轮 WS 双流链路，收集全部相关事件。

    消息协议与 voice_chat_e2e.py 一致：init → 音频帧 → 尾部静音 → 接收窗口。
    收集：
      - partials：voice.partial 识别文本
      - interrupted：voice.interrupted 事件列表（含 reason 与相对时间）
      - vad_events：vad_status / vad_frame 事件（仅记录，不跨量纲比较）
      - tts_chunks：voice.tts_chunk 回复块（含到达时间，用于 early_reply 判定）
      - prefills：voice.prefill_started 事件（主管线 LLM 回复生成已启动，【标签解耦】后
        作为 need_reply 场景"收到回复"的可观测信号——TTS 运行时不可用时仍可判定）
      - send_done_rel：完整音频帧 + 尾部静音全部发送完成的相对时刻
        （完整音频播放完毕基准，spec Q3：VAD 中途 speech_end 不作为场景结束判据）
    失败时返回含 ws_error 的 dict。
    """
    sr = 16000
    frame_bytes = int(sr * FRAME_MS / 1000) * 2
    # 先导静音：语气开始前预置 LEAD_SILENCE 静音帧，冲刷远程 ASR 残留缓冲，
    # 避免上一场景尾音被误识为本场景 Speech（跨场景串扰），隔离各场景判定。
    lead = b"\x00" * (int(sr * LEAD_SILENCE_S) * 2)
    frames = [pcm_16k[i:i + frame_bytes] for i in range(0, len(pcm_16k), frame_bytes)]
    frames = [lead[i:i + frame_bytes] for i in range(0, len(lead), frame_bytes)] + frames
    silence = b"\x00" * (int(sr * TAIL_SILENCE_S) * 2)
    req_id = f"llm-vad-{tag}-{int(time.time() * 1000)}"

    partials = []
    interrupted = []
    vad_events = []
    tts_chunks = []
    prefills = []
    reply_text = ""

    try:
        async with websockets.connect(WS_URL, max_size=2**24, open_timeout=10) as ws:
            await ws.send(json.dumps({
                "action": "voice.dual_stream", "request_id": req_id,
                "data": {"init": True, "agent_id": E2E_AGENT_ID, "ref_asset_id": REF_ASSET},
            }))
            await asyncio.sleep(0.3)

            t_send = time.monotonic()
            # 发送完整音频帧（按真实播放节奏，帧间隔 = 帧时长）
            for f in frames:
                await ws.send(json.dumps({
                    "action": "voice.dual_stream", "request_id": req_id,
                    "data": {"audio": base64.b64encode(f).decode("ascii"), "sample_rate": sr},
                }))
                await asyncio.sleep(0.03)
            # 尾部静音：完整音频播放完毕后的结束判定窗口
            for _ in range(3):
                await ws.send(json.dumps({
                    "action": "voice.dual_stream", "request_id": req_id,
                    "data": {"audio": base64.b64encode(silence).decode("ascii"), "sample_rate": sr},
                }))
                await asyncio.sleep(0.03)
            # 完整音频 + 尾部静音发送完成时刻：作为"播放完毕"基准
            send_done_at = time.monotonic()
            send_done_rel = round(send_done_at - t_send, 3)

            # 接收窗口：持续收事件直到窗口结束（LLM 判定可能 ~8s，不允许 5s 静默早退）
            deadline = send_done_at + RECV_WINDOW_S
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=min(5.0, remaining))
                except asyncio.TimeoutError:
                    continue
                except websockets.exceptions.ConnectionClosed:
                    break
                now = time.monotonic() - t_send
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                mtype = msg.get("type", "") or msg.get("action", "")
                data = msg.get("data", {}) or {}

                if mtype == "voice.partial":
                    text = data.get("text") or data.get("partial_text") or ""
                    if text:
                        partials.append(text)
                elif mtype == "voice.interrupted":
                    # reason 字段位于 data.reason（spec 强调）
                    interrupted.append({
                        "reason": data.get("reason", ""),
                        "time": round(now, 3),
                    })
                elif mtype == "voice.tts_chunk":
                    audio_b64 = data.get("audio_data") or data.get("audio") or ""
                    size = 0
                    if audio_b64:
                        try:
                            size = len(base64.b64decode(audio_b64))
                        except Exception:
                            size = 0
                    tts_chunks.append({
                        "time": round(now, 3),
                        "size": size,
                        "is_final": bool(data.get("is_final")),
                    })
                    seg = data.get("text_segment") or data.get("text") or ""
                    if seg:
                        reply_text += seg
                elif mtype == "voice.prefill_started":
                    prefills.append({
                        "time": round(now, 3),
                        "text": data.get("text", ""),
                    })
                elif mtype in ("vad_status", "vad_frame"):
                    # VAD 仅记录事件，不跨量纲比较（spec Q3）
                    vad_events.append({
                        "type": mtype,
                        "data": data,
                        "time": round(now, 3),
                    })
                # voice.prefill_started 等其余事件忽略
            try:
                await ws.send(json.dumps({
                    "action": "voice.dual_stream", "request_id": req_id, "data": {"end": True},
                }))
            except Exception:
                pass
    except Exception as e:
        return {
            "error": True, "ws_error": str(e),
            "partials": [], "interrupted": [], "vad_events": [], "tts_chunks": [],
            "prefills": [], "reply_text": "", "send_done_rel": 0.0,
        }

    return {
        "error": False, "ws_error": None,
        "partials": partials,
        "interrupted": interrupted,
        "vad_events": vad_events,
        "tts_chunks": tts_chunks,
        "prefills": prefills,
        "reply_text": reply_text,
        "send_done_rel": send_done_rel,
    }


async def probe_service(client: httpx.AsyncClient) -> dict:
    """探测后端服务可达性。

    优先 GET /api/stats（无鉴权，已确认存在），再尝试 /api/health。
    返回 {"reachable": bool, "probed": [成功探测到的端点]}。
    """
    probed = []
    reachable = False
    for url in (f"{BASE}/api/stats", f"{BASE}/api/health"):
        try:
            r = await client.get(url, timeout=8)
            # 有 HTTP 响应（含 404/403）即视为服务可达；仅 5xx 视为不可用
            if r.status_code < 500:
                reachable = True
                probed.append(url)
                break
        except Exception:
            continue
    return {"reachable": reachable, "probed": probed, "base": BASE, "ws_url": WS_URL}


async def set_interrupt_enabled(client: httpx.AsyncClient, body: dict):
    """POST /api/stats/interrupt/enable 热更新打断启用状态。

    成功返回响应 data（{"enabled": ..., "speech_end_fallback": ...}）；
    请求失败（非 2xx / 异常）返回 None。
    """
    try:
        r = await client.post(
            f"{BASE}/api/stats/interrupt/enable",
            headers={"X-API-Key": ADMIN_KEY},
            json=body,
            timeout=15,
        )
        if r.status_code != 200:
            print(f"  [WARN] enable 请求失败 status={r.status_code} body={r.text[:200]}")
            return None
        return r.json().get("data")
    except Exception as e:
        print(f"  [WARN] enable 请求异常: {e}")
        return None


async def get_interrupt_stats(client: httpx.AsyncClient):
    """GET /api/stats/interrupt 获取判定统计快照；失败返回 None。

    返回结构（与后端 agent_interrupt_user.get_stats 一致）：
      {"total_judgments", "decisions": {INTERRUPT/CONTINUE/IGNORE},
       "interrupts_triggered", "replies_triggered"}
    """
    try:
        r = await client.get(
            f"{BASE}/api/stats/interrupt",
            headers={"X-API-Key": ADMIN_KEY},
            timeout=15,
        )
        if r.status_code != 200:
            print(f"  [WARN] GET /api/stats/interrupt status={r.status_code}")
            return None
        return r.json().get("data")
    except Exception as e:
        print(f"  [WARN] GET /api/stats/interrupt 异常: {e}")
        return None


def stats_delta(before: dict, after: dict) -> dict:
    """计算场景后统计 - 场景前统计的 delta（Q4：无 reset 端点，用 delta 隔离）。"""
    return {
        "total_judgments": after["total_judgments"] - before["total_judgments"],
        "decisions": {
            k: after["decisions"].get(k, 0) - before["decisions"].get(k, 0)
            for k in ("INTERRUPT", "CONTINUE", "IGNORE")
        },
        "interrupts_triggered": after.get("interrupts_triggered", 0) - before.get("interrupts_triggered", 0),
        "replies_triggered": after.get("replies_triggered", 0) - before.get("replies_triggered", 0),
    }


def sum_deltas(deltas: list) -> dict:
    """多轮 delta 求和（--rounds > 1 时使用）。"""
    if not deltas:
        return {
            "total_judgments": 0,
            "decisions": {"INTERRUPT": 0, "CONTINUE": 0, "IGNORE": 0},
            "interrupts_triggered": 0,
            "replies_triggered": 0,
        }
    return {
        "total_judgments": sum(d["total_judgments"] for d in deltas),
        "decisions": {
            k: sum(d["decisions"].get(k, 0) for d in deltas)
            for k in ("INTERRUPT", "CONTINUE", "IGNORE")
        },
        "interrupts_triggered": sum(d.get("interrupts_triggered", 0) for d in deltas),
        "replies_triggered": sum(d.get("replies_triggered", 0) for d in deltas),
    }


def judge_scene(scene: dict, runs: list) -> dict:
    """基于场景标注与多轮运行事件，判定误触发 / 正确判定结束 / early_reply。

    归因口径（Q1/Q2/Q3 + F4）：
    - 完整播放完毕基准：send_done_rel（音频帧 + 尾部静音全部发送完成）为分界，
      interrupted.time < send_done_rel 视为播放过程中；>= 视为完整播放完毕后。
    - 正确判定结束：标注"应打断"场景（complete_question）出现 agent_interrupt
      即正确（用户明确提问，立即插话正确）；标注仅"需回复"场景
      （paused_long / short_phrases）按"收到回复"判定——主管线 LLM 回复生成已启动
      （voice.prefill_started）或产出回复音频（voice.tts_chunk）即视为收到回复
      （【标签解耦】打断与回复已独立，回复由主 LLM 管线产出，不再以 agent_interrupt
      事件充当回复信号）。
    - 误触发：标注"不应打断"且"不需回复"场景（self_talk / noise）出现任何
      agent_interrupt 即误触发；标注"不应打断"但"需回复"场景（paused_long /
      short_phrases）在播放过程中（完整播放完毕前）被打断视为误触发
      （用户在组织语言中被误打断）。
    - early_reply：带停顿长句 / 连续短句在 VAD 中途 speech_end 后、完整播放完毕前
      出现的提前 tts_chunk（prefill 触发），仅记录，不计入两率（spec Q3）。
    """
    agent_interrupts = []
    before_end_any = False   # 播放过程中出现过 agent_interrupt
    after_end_any = False    # 完整播放完毕后出现过 agent_interrupt
    early_reply_all = []
    # 【标签解耦】回复判定：该场景是否"收到回复"——主管线 LLM 回复生成已启动
    # （voice.prefill_started）或产出回复音频（voice.tts_chunk）。
    # 用 prefill 而非 agent_interrupt：打断与回复已解耦，回复由主 LLM 管线产出；
    # TTS 运行时不可用时 prefill 仍可观测（评测环境 Qwen3 TTS 8091/8093 未在线）。
    replied = (
        any(run.get("prefills") for run in runs if not run.get("error"))
        or any(run.get("tts_chunks") for run in runs if not run.get("error"))
    )

    for idx, run in enumerate(runs):
        if run.get("error"):
            continue
        ai = [e for e in run.get("interrupted", []) if e.get("reason") == "agent_interrupt"]
        send_done = run.get("send_done_rel", 0.0)
        for e in ai:
            rec = dict(e)
            rec["round"] = idx
            agent_interrupts.append(rec)
        if any(e["time"] < send_done for e in ai):
            before_end_any = True
        if any(e["time"] >= send_done for e in ai):
            after_end_any = True

        # early_reply：仅带停顿长句 / 连续短句场景判定
        if scene["mode"] in ("tts_paused", "tts_short"):
            # VAD 中途 speech_end（完整播放完毕前出现的 speech_end）
            mid_ends = [
                e["time"] for e in run.get("vad_events", [])
                if e.get("type") == "vad_status"
                and e.get("data", {}).get("status") == "speech_end"
                and e["time"] < send_done
            ]
            for c in run.get("tts_chunks", []):
                # 完整播放完毕前到达，且发生在某个 VAD 中途 speech_end 之后
                if c["time"] < send_done and any(se <= c["time"] for se in mid_ends):
                    rec = dict(c)
                    rec["round"] = idx
                    early_reply_all.append(rec)

    # 误触发判定
    misinterrupt = False
    if not scene["should_interrupt"]:
        if not scene["need_reply"]:
            # 自言自语 / 环境噪音：任何时刻的打断都算误触发
            misinterrupt = bool(agent_interrupts)
        else:
            # 带停顿长句 / 连续短句：播放过程中被打断才算误触发（组织语言中）
            misinterrupt = before_end_any

    # 正确判定结束判定
    correct_end = False
    if scene["need_reply"] or scene["should_interrupt"]:
        if scene["should_interrupt"]:
            # 应打断场景：出现打断即正确（用户明确提问，立即插话）
            correct_end = bool(agent_interrupts)
        else:
            # 【标签解耦】仅需回复场景：按"收到回复"判定（主管线 voice.tts_chunk 产出），
            # 不再依赖 agent_interrupt 事件——打断与回复已解耦，回复由主 LLM 管线产出。
            correct_end = replied

    return {
        "agent_interrupt_events": agent_interrupts,
        "before_end_any": before_end_any,
        "after_end_any": after_end_any,
        "early_reply": early_reply_all,
        "misinterrupt": misinterrupt,
        "correct_end": correct_end,
    }


async def main(argv=None) -> int:
    """评测主流程。返回退出码：0=PASS / 77=SKIP / 1=FAIL。"""
    parser = argparse.ArgumentParser(
        description="评测 agent_interrupt_user 的 LLM 三态判定准确率（语音结束/打断判定 E2E）",
    )
    parser.add_argument("--rounds", type=int, default=1,
                        help="主轮每场景重复次数（默认 1，多轮取 delta 累计与事件合并）")
    parser.add_argument("--probe", action="store_true",
                        help="仅探测后端服务可达性，不执行评测")
    args = parser.parse_args(argv)
    if args.rounds < 1:
        args.rounds = 1

    print("=== LLM 三态判定准确率评测 (agent_interrupt_user) ===")
    print(f"BASE={BASE} | WS={WS_URL} | rounds={args.rounds}")
    print()

    report = {
        "script": "test_llm_vad_accuracy",
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "admin_key_configured": bool(ADMIN_KEY),
    }

    async with httpx.AsyncClient(timeout=120, trust_env=False, proxy=None) as client:
        # ── 1. 服务探测 ──
        services = await probe_service(client)
        report["services"] = services
        if not services["reachable"]:
            print(f"[SKIP] 后端服务不可达 {BASE}（/api/stats 与 /api/health 均无响应），"
                  f"无法评测（exit 77）")
            return 77
        print(f"[OK] 后端服务可达 {BASE}（探测端点: {services['probed']}）")

        if args.probe:
            # --probe 仅探测：服务可达即 PASS（dry-run 验证用）
            print("[PROBE] 服务探测通过，--probe 模式退出（exit 0）")
            return 0

        # ── 2. ADMIN_API_KEY 检查 ──
        if not ADMIN_KEY:
            print("[FAIL] 后端未配置 ADMIN_API_KEY 环境变量，无法调用 "
                  "/api/stats/interrupt* 管理端点（exit 1）")
            print("       请在启动后端的进程中设置 ADMIN_API_KEY 后重试")
            return 1
        print(f"[OK] ADMIN_API_KEY 已配置（长度 {len(ADMIN_KEY)}）")

        # ── 3. enabled=false 基线轮（F9） ──
        print()
        print("[基线轮 F9] 先确保 agent_interrupt 关闭，再对 5 类场景各跑一轮双流 ...")
        # 基线轮必须在 enabled=false 下运行：先热更新关闭（后端可能初始 enabled=true）
        pre_close = await set_interrupt_enabled(client, {"enabled": False})
        if pre_close is None:
            print("[FAIL] 基线前置：无法将 agent_interrupt 置为关闭（exit 1）")
            return 1
        print(f"  [OK] agent_interrupt 已关闭 enabled={pre_close.get('enabled')}")

        baseline_ok = True
        baseline_scenes = {}
        for sc in SCENES:
            pcm, desc = await build_scene_pcm(client, sc)
            run = await run_dual_stream(pcm, f"base-{sc['key']}")
            if run.get("error"):
                print(f"  [ERROR] {sc['key']}: WS 运行失败 {run.get('ws_error')}")
                baseline_ok = False
                continue
            agent_ints = [e for e in run["interrupted"] if e.get("reason") == "agent_interrupt"]
            baseline_scenes[sc["key"]] = {
                "scene": sc["key"],
                "text": desc,
                "agent_interrupt_count": len(agent_ints),
                "agent_interrupt_events": run["interrupted"],
                "partial": run["partials"][-1] if run["partials"] else "",
                "tts_chunk_count": len(run["tts_chunks"]),
            }
            flag = "OK" if len(agent_ints) == 0 else "FAIL"
            print(f"  [{flag}] {sc['key']}: agent_interrupt 事件 = {len(agent_ints)} 个"
                  f"（应全部为 0）")
            if len(agent_ints) > 0:
                baseline_ok = False
        report["baseline"] = {"ok": baseline_ok, "scenes": baseline_scenes}
        if not baseline_ok:
            print("[FAIL] 基线轮：enabled=false 时仍出现 agent_interrupt 打断事件，"
                  "存在插话穿透（exit 1）")
            return 1
        print("[OK] 基线轮通过：enabled=false 时无 agent_interrupt 插话打断")

        # ── 4. 前置启用（SB-1） ──
        print()
        print("[SB-1] 启用 agent_interrupt（enabled=true, speech_end_fallback=true） ...")
        enable_data = await set_interrupt_enabled(
            client, {"enabled": True, "speech_end_fallback": True})
        if enable_data is None:
            print("[FAIL] 自动开启失败，请手动改 CX-O-SERVER/config.json 重启后端（exit 1）")
            return 1
        if not enable_data.get("enabled") or not enable_data.get("speech_end_fallback"):
            print(f"[FAIL] 自动开启失败，请手动改 CX-O-SERVER/config.json 重启后端（exit 1）；"
                  f"返回={enable_data}")
            return 1
        print(f"  [OK] agent_interrupt 已启用 enabled={enable_data.get('enabled')} "
              f"speech_end_fallback={enable_data.get('speech_end_fallback')}")

        # ── 5. 评测主轮：5 场景逐轮双流 + 前后 stats 快照 delta ──
        print()
        print("[主轮] agent_interrupt 已启用，逐场景评测 ...")
        main_scenes = []
        all_scenes_ok = True
        for sc in SCENES:
            deltas = []
            runs = []
            for _ in range(args.rounds):
                before = await get_interrupt_stats(client)
                pcm, desc = await build_scene_pcm(client, sc)
                run = await run_dual_stream(pcm, f"main-{sc['key']}")
                after = await get_interrupt_stats(client)
                if before is None or after is None:
                    print(f"  [ERROR] {sc['key']}: 统计快照获取失败，场景统计不可用")
                    all_scenes_ok = False
                    break
                deltas.append(stats_delta(before, after))
                runs.append(run)

            if not runs or any(r.get("error") for r in runs):
                print(f"  [ERROR] {sc['key']}: WS 运行失败，场景评测失败")
                all_scenes_ok = False
                continue

            total_delta = sum_deltas(deltas)
            verdict = judge_scene(sc, runs)
            merged_run = {
                "partials": [p for r in runs for p in r.get("partials", [])],
                "interrupted": [e for r in runs for e in r.get("interrupted", [])],
                "vad_events": [e for r in runs for e in r.get("vad_events", [])],
                "tts_chunks": [e for r in runs for e in r.get("tts_chunks", [])],
                "reply_text": "".join(r.get("reply_text", "") for r in runs),
            }
            scene_rec = {
                "key": sc["key"],
                "text": desc,
                "should_interrupt": sc["should_interrupt"],
                "need_reply": sc["need_reply"],
                "stats_delta": total_delta,
                "voice_interrupted": merged_run["interrupted"],
                "partial_text": merged_run["partials"][-1] if merged_run["partials"] else "",
                "reply_text": merged_run["reply_text"],
                "early_reply": verdict["early_reply"],
                "misinterrupt": verdict["misinterrupt"],
                "correct_end": verdict["correct_end"],
                "tts_chunk_count": len(merged_run["tts_chunks"]),
                "vad_event_count": len(merged_run["vad_events"]),
            }
            main_scenes.append(scene_rec)
            print(f"  [{sc['key']}] 判定delta total={total_delta['total_judgments']} "
                  f"decisions={total_delta['decisions']} "
                  f"interrupts={total_delta['interrupts_triggered']} "
                  f"replies={total_delta['replies_triggered']} | "
                  f"误触发={'是' if verdict['misinterrupt'] else '否'} "
                  f"正确结束={'是' if verdict['correct_end'] else '否'} "
                  f"early_reply={len(verdict['early_reply'])}")
        report["scenes"] = main_scenes

        # ── 6. 率计算（F4） ──
        total_scenes = len(SCENES)
        misinterrupt_scenes = [s["key"] for s in main_scenes if s["misinterrupt"]]
        need_reply_scenes = [s["key"] for s in SCENES if s["need_reply"]]
        correct_end_scenes = [s["key"] for s in main_scenes if s["correct_end"]]
        # 正确判定结束率只统计需回复场景中的正确结束（分母=3）
        correct_end_in_need_reply = [k for k in correct_end_scenes if k in need_reply_scenes]
        misinterrupt_rate = round(len(misinterrupt_scenes) / total_scenes, 4)
        correct_end_rate = round(len(correct_end_in_need_reply) / len(need_reply_scenes), 4)
        summary = {
            "total_scenes": total_scenes,
            "misinterrupt_scenes": misinterrupt_scenes,
            "misinterrupt_rate": misinterrupt_rate,
            "need_reply_scenes": need_reply_scenes,
            "correct_end_scenes": correct_end_in_need_reply,
            "correct_end_rate": correct_end_rate,
        }
        report["summary"] = summary

        # ── 7. 恢复（Q5） ──
        print()
        print("[Q5] 恢复 agent_interrupt 状态（enabled=false） ...")
        reset_data = await set_interrupt_enabled(client, {"enabled": False})
        if reset_data is None:
            print("  [WARN] 恢复失败，请手动改 CX-O-SERVER/config.json 恢复")
            report["enabled_reset"] = {"error": "reset failed"}
        else:
            report["enabled_reset"] = reset_data
            print(f"  [OK] 已恢复 enabled={reset_data.get('enabled')}")

        # ── 8. 输出报告 + 汇总 ──
        os.makedirs(OUT_DIR, exist_ok=True)
        rp = os.path.join(OUT_DIR, f"llm_vad_accuracy_{time.strftime('%Y%m%d_%H%M%S')}.json")
        with open(rp, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"报告: {rp}")

        print()
        print("===== 汇总 =====")
        print(f"总场景: {summary['total_scenes']} | 需回复场景: {summary['need_reply_scenes']}")
        print(f"误触发场景: {summary['misinterrupt_scenes']} "
              f"误触发率={summary['misinterrupt_rate']}")
        print(f"正确判定结束场景: {summary['correct_end_scenes']} "
              f"正确判定结束率={summary['correct_end_rate']}")

        # 流程性失败：WS 运行失败 / 统计快照失败 → FAIL
        if not all_scenes_ok:
            print("[FAIL] 存在场景运行失败（WS 或统计快照），评测不完整（exit 1）")
            return 1
        # 结果性判定：误触发率=0 且正确判定结束率=100% 视为达标
        if misinterrupt_rate == 0 and correct_end_rate == 1.0:
            print("[PASS] LLM 三态判定准确率评测达标（无误触发、正确判定结束率 100%）（exit 0）")
            return 0
        print(f"[FAIL] 评测指标不达标：误触发率={misinterrupt_rate}，"
              f"正确判定结束率={correct_end_rate}（exit 1）")
        return 1


if __name__ == "__main__":
    reset_agent_state()
    try:
        sys.exit(asyncio.run(main()))
    finally:
        restore_agent_state()
