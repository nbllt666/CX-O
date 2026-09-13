"""全双工语音链路延迟探测器（WS voice.dual_stream）。

链路：客户端实时节奏流式发送 16k/mono/16bit PCM 帧（base64）→ 容器 ASR（always_send
全转发，容器内 fsmn-vad 流式分句）→ LLM（agent 主模型）→ TTS（CosyVoice3，24k PCM 下行）。

探测口径（相对本轮音频流开始 t0，单位 ms）：
  asr_first_partial     首个 voice.partial（容器 ASR 首个中间结果）
  asr_final             voice.partial 且 is_final=true（容器流式分句定稿 = 用户说完）
  vad_speech_end        服务端 VAD speech_end（仅兜底路径，仅诊断记录，不作主锚点）
  prefill_started       voice.prefill_started（投机预填启动）
  tts_first_audio       首个 voice.tts_chunk 且带 audio_data（首包 TTS 音频）
  tts_done              voice.tts_chunk is_final=true 或回合静默超时
主指标 = **asr_final → tts_first_audio**（容器分句定稿 → 首包音频；全双工真实口径，
服务端 VAD 不参与判定）。辅指标 = stream_start → tts_first_audio（完整轮次）。

事件分类对服务端消息格式容错：type 或 action 字段任一命中、data 为 dict 或
JSON 字符串均可（voice.partial 为裸 dict、tts_chunk 为 StreamMessage）。

Mock 模式（config.mock.enabled）下探测器不可用（无 WS stub），由 suite 跳过并标记。
"""
from __future__ import annotations

import base64
import json
import os
import threading
import time
import uuid
import wave
from typing import Any, Callable, Dict, List, Optional

from evalkit.config import EVALKIT_ROOT, EvalConfig

DEFAULT_ASSET = os.path.join(EVALKIT_ROOT, "evalkit", "assets", "utterance_16k.wav")
WS_EVENT_STAGES = ("asr_first_partial", "asr_final", "prefill_started", "tts_first_audio", "tts_done", "vad_speech_end")


class WsProbeError(RuntimeError):
    """全双工探测不可用（连接失败/init 失败/音频资产缺失）。"""


def resolve_utterance_wav(config: EvalConfig) -> str:
    """解析本轮语音资产路径：config 指定优先，否则打包资产。"""
    path = config.latency.ws_full_duplex.utterance_wav
    if path and os.path.exists(path):
        return path
    if os.path.exists(DEFAULT_ASSET):
        return DEFAULT_ASSET
    raise WsProbeError(f"语音资产不存在: config.latency.ws_full_duplex.utterance_wav={path!r} 与打包资产均缺失")


def _pcm_frames(wav_path: str, frame_ms: int) -> List[bytes]:
    """读 16k/mono/16bit wav 并切为 frame_ms 对应字节的 PCM 帧（960B@30ms）。"""
    with wave.open(wav_path, "rb") as w:
        if w.getframerate() != 16000 or w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise WsProbeError(
                f"语音资产须为 16k/mono/16bit PCM: {wav_path} 实为 {w.getframerate()}Hz/{w.getnchannels()}ch/{w.getsampwidth()*8}bit"
            )
        pcm = w.readframes(w.getnframes())
    frame_bytes = int(16000 * frame_ms / 1000) * 2
    return [pcm[i : i + frame_bytes] for i in range(0, len(pcm), frame_bytes)]


def _classify(msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """将服务端消息归类为探测器事件。返回 {"event": 名称, "is_final": bool, "text": str} 或 None。

    容错：StreamMessage 的判别字段在 action（type="stream"），裸 dict 消息（voice.partial/
    vad_status）判别字段在 type——拼接两者做子串匹配；data 为 dict 或 JSON 字符串均可。
    """
    kind = f"{msg.get('action') or ''} {msg.get('type') or ''}"
    data = msg.get("data")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except (json.JSONDecodeError, ValueError):
            data = {}
    data = data if isinstance(data, dict) else {}

    if "voice.partial" in kind:
        return {"event": "asr_first_partial", "is_final": bool(data.get("is_final")), "text": str(data.get("text", ""))}
    if "vad_status" in kind:
        status = str(data.get("status") or msg.get("status") or "")
        if status == "speech_end":
            return {"event": "vad_speech_end", "is_final": True, "text": ""}
        return None
    if "prefill_started" in kind:
        return {"event": "prefill_started", "is_final": False, "text": str(data.get("partial_text", ""))}
    if "tts_chunk" in kind:
        has_audio = bool(data.get("audio_data"))
        if has_audio:
            return {"event": "tts_first_audio", "is_final": bool(msg.get("is_final")), "text": str(data.get("text_segment", ""))}
        if msg.get("is_final") or data.get("is_final"):
            return {"event": "tts_done", "is_final": True, "text": ""}
        return None
    if kind.strip() == "error" or "error" in kind and msg.get("error"):
        return {"event": "server_error", "is_final": True, "text": json.dumps(msg, ensure_ascii=False)[:300]}
    return None


def summarize_ws_turns(turns: List[Dict[str, Any]]) -> Dict[str, Any]:
    """纯函数：多轮事件 → 各阶段统计（相对流开始）+ 主指标统计。

    每轮 turn 结构: {"turn_index": int, "timings": {stage: ms 或 None}, "timeout": bool,
                    "error": str 或 None, "asr_text": str,
                    "speech_end_offset_ms": float（能量法"说完"时刻，相对 t0）}
    统计口径与 percentile 线性插值法一致（suite 的 percentile 可复用此处输入）。
    返回 {"stages": {...}, "first_partial_to_first_audio": {...},
          "speech_end_to_first_audio": {...}, "asr_final_to_first_audio": {...},
          "stream_to_first_audio": {...}, "segmentation_wait": {...},
          "timeouts": int, "errors": int}

    主指标 **first_partial_to_first_audio** = 首个 ASR 中间结果（投机预填起点）→ 首包
    TTS 音频——逐句投机响应模式的真实体感（用户说完→出声口径在此模式下恒 0/负，
    因首包早于整段说完，仅作辅助）。segmentation_wait = asr_final − speech_end（诊断）。
    """
    def _stats(values: List[float]) -> Dict[str, Any]:
        if not values:
            return {"count": 0}
        vs = sorted(values)

        def pct(p: float) -> float:
            if len(vs) == 1:
                return vs[0]
            idx = p / 100 * (len(vs) - 1)
            lo, hi = int(idx), min(int(idx) + 1, len(vs) - 1)
            frac = idx - lo
            return round(vs[lo] * (1 - frac) + vs[hi] * frac, 1)

        return {
            "count": len(vs),
            "mean": round(sum(vs) / len(vs), 1),
            "p50": pct(50),
            "p95": pct(95),
            "min": round(vs[0], 1),
            "max": round(vs[-1], 1),
        }

    stages: Dict[str, List[float]] = {k: [] for k in WS_EVENT_STAGES}
    partial2audio: List[float] = []
    speech2audio: List[float] = []
    final2audio: List[float] = []
    stream2audio: List[float] = []
    seg_wait: List[float] = []
    timeouts = errors = 0
    for t in turns:
        if t.get("error"):
            errors += 1
            continue
        if t.get("timeout"):
            timeouts += 1
        timings = t.get("timings") or {}
        for k in WS_EVENT_STAGES:
            v = timings.get(k)
            if isinstance(v, (int, float)):
                stages[k].append(float(v))
        first = timings.get("tts_first_audio")
        speech_end = t.get("speech_end_offset_ms")
        if isinstance(first, (int, float)):
            stream2audio.append(float(first))
            if isinstance(speech_end, (int, float)):
                speech2audio.append(max(0.0, float(first) - float(speech_end)))
        final = timings.get("asr_final")
        if isinstance(final, (int, float)) and isinstance(first, (int, float)):
            # 投机预填下首包可能先于 is_final 消息到达——负差值钳 0（定稿即出声）
            final2audio.append(max(0.0, float(first) - float(final)))
            if isinstance(speech_end, (int, float)):
                seg_wait.append(max(0.0, float(final) - float(speech_end)))
        # 主指标：首个 partial（投机预填起点）→ 首包——逐句投机响应模式的真实体感。
        # "说完（能量）→ 首包"在边说边响应模式下恒 0/负（首包早于整段说完），仅辅助。
        pfirst = timings.get("asr_first_partial")
        if isinstance(pfirst, (int, float)) and isinstance(first, (int, float)):
            partial2audio.append(max(0.0, float(first) - float(pfirst)))
    return {
        "stages": {k: _stats(v) for k, v in stages.items()},
        "first_partial_to_first_audio": _stats(partial2audio),
        "speech_end_to_first_audio": _stats(speech2audio),
        "asr_final_to_first_audio": _stats(final2audio),
        "stream_to_first_audio": _stats(stream2audio),
        "segmentation_wait": _stats(seg_wait),
        "timeouts": timeouts,
        "errors": errors,
    }


def _speech_end_offset_ms(wav_path: str) -> float:
    """能量法定位"说完"时刻：30ms 帧 RMS，最后一个超阈帧的结束时刻（ms）。

    阈值 = max(300, 峰值RMS×5%)；全静音返回 0。这是用户体感锚点——
    容器分句（asr_final）要等这段语音结束后由 fsmn-vad 触发。
    纯 Python 实现（逐帧平方均值），避免引入 numpy 运行时依赖。
    """
    with wave.open(wav_path, "rb") as w:
        rate = w.getframerate()
        samples = w.readframes(w.getnframes())
    # 逐 2 字节解析为 int16（小端），再按 30ms 帧算 RMS
    frame = int(rate * 0.03)
    ints = [int.from_bytes(samples[i : i + 2], "little", signed=True) for i in range(0, len(samples) - 1, 2)]
    total_frames = max(1, len(ints) // frame)
    peak = 0.0
    rms_list: List[float] = []
    for fi in range(total_frames):
        seg = ints[fi * frame : (fi + 1) * frame]
        if not seg:
            break
        rms = (sum(v * v for v in seg) / len(seg)) ** 0.5
        rms_list.append(rms)
        if rms > peak:
            peak = rms
    thr = max(300.0, peak * 0.05)
    last = 0
    for i, v in enumerate(rms_list):
        if v > thr:
            last = i + 1
    return round(last * (frame / rate) * 1000.0, 1)


class FullDuplexProbe:
    """对运行中主服务执行全双工语音轮次探测（同步 websockets 客户端）。"""

    def __init__(self, config: EvalConfig, connect_factory: Optional[Callable[[str], Any]] = None):
        self.config = config
        self._connect_factory = connect_factory  # 测试注入：lambda url: ws 连接对象
        self._speech_end_cache: Dict[str, float] = {}

    def _speech_end_offset(self, wav_path: str) -> float:
        """能量法"说完"时刻（按资产缓存）。"""
        if wav_path not in self._speech_end_cache:
            self._speech_end_cache[wav_path] = _speech_end_offset_ms(wav_path)
        return self._speech_end_cache[wav_path]

    def _ws_url(self, agent_id: str) -> str:
        base = self.config.target.base_url.rstrip("/")
        if base.startswith("https://"):
            base = "wss://" + base[len("https://"):]
        elif base.startswith("http://"):
            base = "ws://" + base[len("http://"):]
        # websocket 路由挂在 /api 前缀下（server/api/app.py:97），真实端点为 /api/ws/{agent_id}
        return f"{base}/api/ws/{agent_id}"

    def run_turn(self, agent_id: str, turn_index: int) -> Dict[str, Any]:
        """执行一轮全双工探测：连接 → init → 实时节奏流式发帧 → 并发收包记录事件。

        关键：收包必须与送流**并发**（后台线程），否则 WS 缓冲会把服务端在送流期间
        产生的 partial/prefill/首包全部积压到送流结束后才被读到——时间戳整体虚高
        到流结束（实测教训：先发后收曾把 500ms 级真实首包测成 995ms）。
        """
        cfg = self.config.latency.ws_full_duplex
        wav_path = resolve_utterance_wav(self.config)
        frames = _pcm_frames(wav_path, cfg.frame_ms)
        speech_end_offset = self._speech_end_offset(wav_path)
        rid = uuid.uuid4().hex

        try:
            from websockets.sync.client import connect
        except ImportError as exc:  # pragma: no cover
            raise WsProbeError("缺少 websockets 库（requirements.txt 已声明）") from exc

        url = self._ws_url(agent_id)
        try:
            try:
                # proxy=None：直连目标（绕过系统代理——代理会扭曲延迟测量且常拒绝 ws://）。
                # 旧版 websockets 无 proxy 参数时回退（其本就不走代理）。
                ws = (self._connect_factory(url) if self._connect_factory
                      else connect(url, open_timeout=15, close_timeout=5, proxy=None))
            except TypeError:
                ws = connect(url, open_timeout=15, close_timeout=5)
        except Exception as exc:
            return {"turn_index": turn_index, "timings": {}, "timeout": False,
                    "error": f"WS 连接失败: {exc}", "asr_text": "",
                    "speech_end_offset_ms": speech_end_offset}

        # ---- 共享状态（recv 线程写，主线程读）----
        timings: Dict[str, float] = {}
        asr_texts: List[str] = []
        state: Dict[str, Any] = {
            "initialized": False, "t0": None, "error": None, "last_msg_t": time.perf_counter(),
        }
        init_event = threading.Event()
        done_event = threading.Event()
        quiet_after_first_audio = 6.0

        def _recv_loop() -> None:
            """收包线程：init 应答置位 init_event；t0 后记录事件时刻，触发收尾。"""
            hard_deadline = time.perf_counter() + cfg.turn_timeout_seconds + 20.0
            while not done_event.is_set():
                now = time.perf_counter()
                if now > hard_deadline:
                    done_event.set()
                    break
                try:
                    raw = ws.recv(timeout=0.2)
                except TimeoutError:
                    t0 = state["t0"]
                    if (t0 is not None and "tts_first_audio" in timings
                            and time.perf_counter() - state["last_msg_t"] >= quiet_after_first_audio):
                        timings.setdefault("tts_done", round((time.perf_counter() - t0) * 1000.0, 1))
                        done_event.set()
                    continue
                except Exception as exc:
                    state["recv_closed"] = str(exc)[:120]
                    t0 = state["t0"]
                    if t0 is not None:
                        timings.setdefault("tts_done", round((time.perf_counter() - t0) * 1000.0, 1))
                    done_event.set()
                    break
                now = time.perf_counter()
                try:
                    msg = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue
                kind = f"{msg.get('action') or ''} {msg.get('type') or ''}".strip()
                data = msg.get("data")
                if isinstance(data, str):
                    try:
                        data = json.loads(data)
                    except (json.JSONDecodeError, ValueError):
                        data = {}
                data = data if isinstance(data, dict) else {}

                if not state["initialized"]:
                    status = str(data.get("status") or msg.get("status") or "")
                    if "error" in kind.lower() or status.lower() in ("error", "failed"):
                        state["error"] = f"init 失败: {json.dumps(msg, ensure_ascii=False)[:200]}"
                        done_event.set()
                        return
                    if kind or status:
                        # init 响应 / connected / ping——下行链路可用
                        state["initialized"] = True
                        init_event.set()
                    continue

                if "error" in kind.lower() and msg.get("error"):
                    t0 = state["t0"]
                    if t0 is not None:
                        timings.setdefault("tts_done", round((now - t0) * 1000.0, 1))
                    state["error"] = f"服务端错误: {json.dumps(msg, ensure_ascii=False)[:200]}"
                    done_event.set()
                    return

                ev = _classify(msg)
                if ev is None:
                    state["last_msg_t"] = now
                    continue
                state["last_msg_t"] = now
                t0 = state["t0"]
                if t0 is None:
                    continue
                name = ev["event"]
                if name == "asr_first_partial":
                    asr_texts.append(ev["text"])
                    timings.setdefault("asr_first_partial", round((now - t0) * 1000.0, 1))
                    if ev["is_final"]:
                        timings.setdefault("asr_final", round((now - t0) * 1000.0, 1))
                elif name in timings:
                    if name == "tts_done":
                        done_event.set()
                else:
                    timings[name] = round((now - t0) * 1000.0, 1)
                if "tts_first_audio" in timings and time.perf_counter() - state["last_msg_t"] >= quiet_after_first_audio:
                    timings.setdefault("tts_done", round((time.perf_counter() - t0) * 1000.0, 1))
                    done_event.set()

        recv_thread = threading.Thread(target=_recv_loop, name=f"wsprobe-recv-{turn_index}", daemon=True)
        recv_thread.start()

        # ---- init 握手（recv 线程代收应答）----
        ws.send(json.dumps({"request_id": rid, "action": "voice.dual_stream",
                            "data": {"init": True, "agent_id": agent_id}}))
        if not init_event.wait(timeout=15):
            done_event.set()
            try:
                ws.close()
            except Exception:
                pass
            recv_thread.join(timeout=2)
            return {"turn_index": turn_index, "timings": {}, "timeout": False,
                    "error": state.get("error") or "WS init 握手失败（15s 无初始化响应）",
                    "asr_text": "", "speech_end_offset_ms": speech_end_offset}

        # ---- 实时节奏流式发帧（recv 线程并发记录事件）----
        t0 = time.perf_counter()
        state["t0"] = t0
        for idx, frame in enumerate(frames):
            ws.send(json.dumps({"request_id": rid, "action": "voice.dual_stream",
                                "data": {"audio": base64.b64encode(frame).decode("ascii")}}))
            if cfg.real_time_pacing:
                target = t0 + (idx + 1) * cfg.frame_ms / 1000.0
                delay = target - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)

        # ---- 等待收尾（tts_done / 静默收尾 / 整体超时）----
        remaining = cfg.turn_timeout_seconds - (time.perf_counter() - t0)
        done_event.wait(timeout=max(0.1, remaining))
        done_event.set()  # 通知 recv 线程退出
        recv_thread.join(timeout=2)
        try:
            ws.close()
        except Exception:
            pass

        if "tts_done" not in timings:
            timings["tts_done"] = round((time.perf_counter() - t0) * 1000.0, 1)
        error = state.get("error")
        return {
            "turn_index": turn_index,
            "timings": timings,
            "timeout": "tts_first_audio" not in timings,
            "error": error,
            "asr_text": " ".join(asr_texts)[-200:],
            "speech_end_offset_ms": speech_end_offset,
        }
