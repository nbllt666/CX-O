"""
伴奏渲染模块：歌谱和弦轨 → MIDI(SMF) → fluidsynth + SoundFont → 伴奏 WAV

实现要点（零新增第三方依赖）：
- 和弦标记解析：根音（含 #/b）+ 性质后缀（major/minor/dim/aug/sus/7 等扩展），
  按根音+三音+五音在八度内铺底（根音固定在 3 组，C3=48 起）
- MIDI 生成：标准库 struct 手写最小 SMF（format 0 / 单轨 / division=480），
  含速度元事件（FF 51）、音色事件（C0 program）、Note On/Off 与音轨结束（FF 2F）
- 渲染：子进程调用 `fluidsynth -ni -F <wav> -r 44100 <soundfont> <midi>`
  （fluidsynth 2.5+ 要求选项在位置参数之前，该顺序向后兼容 2.4 及更早版本）；
  SoundFont 缺失或 fluidsynth 不在 PATH 中时抛出 AccompanimentError，
  错误信息逐项列出全部缺失项
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from workstation.music.score import pitch_to_midi

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# MIDI division：每四分音符 tick 数
MIDI_DIVISION = 480
# Note On 力度
MIDI_VELOCITY = 64
# 伴奏音色（GM 0 = Acoustic Grand Piano）
MIDI_PROGRAM = 0
# fluidsynth 渲染默认采样率
DEFAULT_SAMPLE_RATE = 44100
# fluidsynth 子进程超时（秒）
DEFAULT_RENDER_TIMEOUT = 300.0


class AccompanimentError(Exception):
    """伴奏渲染失败（依赖缺失 / 子进程失败），消息含逐项可读原因"""


# ---------------------------------------------------------------------------
# 和弦解析
# ---------------------------------------------------------------------------

# 和弦标记：根音音名 + 可选升降号 + 性质后缀（可含转位低音，如 C/E）
_CHORD_PATTERN = re.compile(r"^([A-Ga-g])([#b]?)(.*)$")

# 性质 → 三和弦半音间隔（根音为 0，均在八度内）
_INTERVALS_MAJOR = (0, 4, 7)
_INTERVALS_MINOR = (0, 3, 7)
_INTERVALS_DIM = (0, 3, 6)
_INTERVALS_AUG = (0, 4, 8)
_INTERVALS_SUS2 = (0, 2, 7)
_INTERVALS_SUS4 = (0, 5, 7)


def _quality_intervals(suffix: str, original: str) -> tuple[int, int, int]:
    """
    由性质后缀推断三和弦半音间隔；扩展音（7/9/11/13/6）忽略，仅取三和弦铺底。

    Raises:
        ValueError: 后缀无法识别时，消息含原始和弦标记
    """
    low = suffix.strip().lower()
    if low == "" or low.startswith("maj"):
        return _INTERVALS_MAJOR
    if low.startswith("dim") or low == "o":
        return _INTERVALS_DIM
    if low.startswith("aug") or low == "+":
        return _INTERVALS_AUG
    if low.startswith("sus2"):
        return _INTERVALS_SUS2
    if low.startswith("sus"):
        return _INTERVALS_SUS4
    if low.startswith("min"):
        return _INTERVALS_MINOR
    if low.startswith("m"):
        # m / m7 / m6 / m9 等（maj 已在上面拦截）；m7b5 等半减和弦取减三和弦
        if "b5" in low:
            return _INTERVALS_DIM
        return _INTERVALS_MINOR
    if low[0].isdigit():
        # 7 / 9 / 11 / 13 / 6 / add9 等扩展：铺底按大三和弦
        return _INTERVALS_MAJOR
    raise ValueError(f"无法识别的和弦性质: {original!r}（后缀 {suffix!r} 不支持）")


def chord_to_midi_notes(symbol: str) -> list[int]:
    """
    和弦标记转 MIDI 音号列表（根音+三音+五音，根音固定 3 组：C3=48 起，八度内铺底）。

    支持写法：C、Am、G7、F#m、Bbmaj7、Bdim、Caug、Dsus4、C/E（转位取斜线前）。

    Args:
        symbol: 和弦标记字符串

    Returns:
        3 个 MIDI 音号（升序）

    Raises:
        ValueError: 和弦标记非法时
    """
    if not isinstance(symbol, str) or not symbol.strip():
        raise ValueError(f"非法和弦标记: {symbol!r}（必须是非空字符串）")
    body = symbol.strip().split("/", 1)[0].strip()  # 转位和弦取斜线前部分
    match = _CHORD_PATTERN.match(body)
    if not match:
        raise ValueError(f"非法和弦标记: {symbol!r}（期望形如 C / Am / G7 / F#m / Bbmaj7）")
    name, accidental, suffix = match.groups()
    root = pitch_to_midi(f"{name.upper()}{accidental}3")
    return [root + interval for interval in _quality_intervals(suffix, symbol)]


# ---------------------------------------------------------------------------
# 最小 SMF（Standard MIDI File）写入
# ---------------------------------------------------------------------------


def _vlq(value: int) -> bytes:
    """MIDI 变长数值（VLQ）编码，大端、除末字节外最高位置 1"""
    if value < 0:
        raise ValueError(f"VLQ 不支持负数: {value}")
    stack = [value & 0x7F]
    value >>= 7
    while value > 0:
        stack.append((value & 0x7F) | 0x80)
        value >>= 7
    return bytes(reversed(stack))


def score_to_midi_bytes(
    score: dict,
    *,
    division: int = MIDI_DIVISION,
    velocity: int = MIDI_VELOCITY,
    program: int = MIDI_PROGRAM,
) -> bytes:
    """
    将规范化歌谱 dict 的和弦轨编码为最小 SMF（format 0，单轨）字节串。

    每个和弦按其 beats 持续区间铺底（根音+三音+五音同时 Note On/Off），
    和弦顺序衔接（前一和弦结束即后一和弦开始）。速度取自 score["bpm"]。

    Args:
        score: 规范化歌谱 dict（含 bpm、chords: [{chord, beats}]）
        division: 每四分音符 tick 数
        velocity: Note On 力度
        program: GM 音色号（0=钢琴）

    Returns:
        SMF 文件字节内容

    Raises:
        ValueError: 和弦标记非法或 bpm 非法时
    """
    raw_bpm = score.get("bpm", 120)
    bpm = float(raw_bpm if raw_bpm is not None else 120)
    if bpm <= 0:
        raise ValueError(f"非法 bpm: {bpm}（必须大于 0）")
    chords = score.get("chords") or []

    events = bytearray()
    # 速度元事件：FF 51 03 <微秒/四分音符，3 字节大端>
    tempo = int(round(60_000_000 / bpm))
    events += b"\x00\xff\x51\x03" + tempo.to_bytes(3, "big")
    # 音色事件：C0 program
    events += b"\x00" + bytes([0xC0, program & 0x7F])

    prev_tick = 0
    for chord_event in chords:
        symbol = chord_event.get("chord") if isinstance(chord_event, dict) else None
        notes = chord_to_midi_notes(symbol or "")
        beats = float(chord_event.get("beats", 0) or 0)
        duration_ticks = max(1, int(round(beats * division)))
        start_tick = prev_tick
        # Note On 组（首事件 delta = 距上一事件的 tick 差，其余 delta 0）
        for idx, note in enumerate(notes):
            delta = (start_tick - prev_tick) if idx == 0 else 0
            events += _vlq(delta) + bytes([0x90, note & 0x7F, velocity & 0x7F])
        end_tick = start_tick + duration_ticks
        # Note Off 组
        for idx, note in enumerate(notes):
            delta = (end_tick - start_tick) if idx == 0 else 0
            events += _vlq(delta) + bytes([0x80, note & 0x7F, 0])
        prev_tick = end_tick

    # 音轨结束元事件
    events += b"\x00\xff\x2f\x00"

    header = (
        b"MThd"
        + (6).to_bytes(4, "big")
        + (0).to_bytes(2, "big")  # format 0
        + (1).to_bytes(2, "big")  # 单轨
        + division.to_bytes(2, "big")
    )
    track = b"MTrk" + len(events).to_bytes(4, "big") + bytes(events)
    return header + track


# ---------------------------------------------------------------------------
# fluidsynth 渲染
# ---------------------------------------------------------------------------


def check_render_dependencies(soundfont_path: str, fluidsynth_cmd: str = "fluidsynth") -> list[str]:
    """
    检查伴奏渲染依赖，返回缺失项描述列表（空列表表示全部就绪）。

    逐项检查：SoundFont 配置与文件存在性、fluidsynth 可执行文件是否在 PATH 中。
    """
    problems: list[str] = []
    if not soundfont_path:
        problems.append("SoundFont 未配置（music.soundfont_path 为空），请配置为 .sf2 文件路径")
    elif not os.path.isfile(soundfont_path):
        problems.append(f"SoundFont 文件不存在: {soundfont_path}")
    if shutil.which(fluidsynth_cmd) is None:
        problems.append(
            f"fluidsynth 可执行文件未找到: {fluidsynth_cmd!r} 不在 PATH 中，"
            "请安装 FluidSynth 并将其加入 PATH"
        )
    return problems


def render_accompaniment(
    score: dict,
    soundfont_path: str,
    output_path: str | os.PathLike,
    *,
    fluidsynth_cmd: str = "fluidsynth",
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    timeout: float = DEFAULT_RENDER_TIMEOUT,
) -> Path:
    """
    将歌谱和弦轨渲染为伴奏 WAV。

    流程：和弦轨 → 最小 SMF（落盘为 output 同名 .mid，保留便于排查）→
    子进程 `fluidsynth -ni -F <wav> -r <sample_rate> <soundfont> <midi>`
    （fluidsynth 2.5+ 要求选项在位置参数之前，该顺序向后兼容 2.4 及更早版本）。

    Args:
        score: 规范化歌谱 dict（含 bpm、chords）
        soundfont_path: SoundFont(.sf2) 文件路径
        output_path: 输出 WAV 路径（父目录自动创建）
        fluidsynth_cmd: fluidsynth 可执行文件（注入点，便于测试）
        sample_rate: 渲染采样率
        timeout: 子进程超时秒数

    Returns:
        输出 WAV 的 Path

    Raises:
        AccompanimentError: 依赖缺失（逐项列出）或渲染失败时
    """
    problems = check_render_dependencies(soundfont_path, fluidsynth_cmd)
    if problems:
        raise AccompanimentError("伴奏渲染依赖缺失:\n" + "\n".join(f"  - {p}" for p in problems))

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    midi_path = out.with_suffix(".mid")
    midi_path.write_bytes(score_to_midi_bytes(score))

    # fluidsynth 2.5+ 要求选项在位置参数（soundfont/midi 路径）之前；
    # 2.4 及更早版本同样支持此顺序，故新语法向后兼容。
    # 详见 .trae/documents/20260723_模块0_fluidsynth参数顺序适配.md
    cmd = [
        fluidsynth_cmd,
        "-ni",
        "-F",
        str(out),
        "-r",
        str(sample_rate),
        str(soundfont_path),
        str(midi_path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise AccompanimentError(f"fluidsynth 渲染超时（>{timeout}s）") from exc
    except OSError as exc:
        raise AccompanimentError(f"fluidsynth 启动失败: {exc}") from exc

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise AccompanimentError(f"fluidsynth 渲染失败（退出码 {proc.returncode}）: {detail}")
    if not out.is_file() or out.stat().st_size == 0:
        raise AccompanimentError(f"fluidsynth 未产出有效 WAV 文件: {out}")
    return out
