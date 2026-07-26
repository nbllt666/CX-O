"""
伴奏渲染模块：歌谱 v2 多轨 → SMF format 1 → fluidsynth + SoundFont → 伴奏 WAV

实现要点（零新增第三方依赖）：
- 和弦标记解析：根音（含 #/b）+ 性质后缀（major/minor/dim/aug/sus/7 等扩展），
  按根音+三音+五音在八度内铺底（根音固定在 3 组，C3=48 起）。chord_to_midi_notes
  保留供测试与历史兼容；多轨渲染以 accompaniment_tracks 为唯一渲染源。
- MIDI 生成：标准库 struct 手写 SMF format 1 多轨（division=480）。
  轨 0=速度/拍号元轨（tempo meta FF51 + 拍号 meta FF58 + EOT FF2F）；其后每乐器轨
  一个 MTrk：轨首 program change（Cn program）+ CC7（volume 直写）+ CC10（pan 直写），
  旋律轨（program 0–127）按轨序映射通道 0..n 跳过 9，打击乐轨（program=-1）固定通道 9、
  不写 program change，鼓键名经 inventory.resolve_drum_key 映射。auto 空 events 轨先经
  arranger.arrange_events 物化（与 arrange_track 命令同一实现，保证预览=渲染）。
- 渲染：子进程调用 `fluidsynth -ni -F <wav> -r 44100 <soundfont> <midi>`
  （fluidsynth 2.5+ 要求选项在位置参数之前，该顺序向后兼容 2.4 及更早版本）；
  SoundFont 缺失或 fluidsynth 不在 PATH 中时抛出 AccompanimentError，
  错误信息逐项列出全部缺失项。

接口签名严格匹配 voicews_music.pyi（契约唯一真相源）：
- score_to_midi_bytes(score: ScoreV2) -> bytes
- render_accompaniment(score: ScoreV2, out_wav_path: str) -> str
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from workstation.music.arranger import arrange_events
from workstation.music.inventory import resolve_drum_key
from workstation.music.score import pitch_to_midi

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# MIDI division：每四分音符 tick 数（每四分音符 480 tick）
MIDI_DIVISION = 480
# 默认 Note On 力度（events 未指定 velocity 时回退）
MIDI_VELOCITY = 64
# fluidsynth 渲染默认采样率
DEFAULT_SAMPLE_RATE = 44100
# fluidsynth 子进程超时（秒）
DEFAULT_RENDER_TIMEOUT = 300.0
# 打击乐轨固定通道（GM 鼓组保留通道 9，旋律轨映射时跳过）
_DRUM_CHANNEL = 9


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


def _encode_time_signature(time_signature: str) -> bytes:
    """拍号字符串 → meta event 数据字节（FF 58 04 nn dd cc bb）。

    nn=每小节拍数，dd=拍单位（2^dd 为分母），cc=每拍 MIDI clock 数（24），
    bb=每四分音符的 32 分音符数（8）。如 "4/4" → 04 02 18 08。
    """
    parts = time_signature.split("/") if isinstance(time_signature, str) else []
    numerator = int(parts[0]) if len(parts) == 2 and parts[0].isdigit() else 4
    denominator = int(parts[1]) if len(parts) == 2 and parts[1].isdigit() else 4
    dd = 0
    d = denominator
    while d > 1:
        d //= 2
        dd += 1
    return bytes([numerator & 0xFF, dd & 0xFF, 24, 8])


def _encode_tempo_track(bpm: float, time_signature: str) -> bytes:
    """编码轨 0（速度/拍号元轨）：tempo meta + time_signature meta + EOT（无音符）"""
    events = bytearray()
    tempo = int(round(60_000_000 / bpm))
    # tempo meta: delta=0, FF 51 03 <微秒/四分音符，3 字节大端>
    events += b"\x00\xff\x51\x03" + tempo.to_bytes(3, "big")
    # time signature meta: delta=0, FF 58 04 nn dd cc bb
    events += b"\x00\xff\x58\x04" + _encode_time_signature(time_signature)
    # end of track
    events += b"\x00\xff\x2f\x00"
    return b"MTrk" + len(events).to_bytes(4, "big") + bytes(events)


def _allocate_channels(tracks: list[dict]) -> list[int]:
    """分配 MIDI 通道：旋律轨（program>=0）按序映射 0..n 跳过 9，
    打击乐轨（program=-1）固定通道 9。多打击乐轨共享通道 9（GM 标准）。"""
    channels: list[int] = []
    next_melodic = 0
    for track in tracks:
        if track.get("program", 0) == -1:
            channels.append(_DRUM_CHANNEL)
        else:
            if next_melodic == _DRUM_CHANNEL:
                next_melodic = _DRUM_CHANNEL + 1
            channels.append(next_melodic)
            next_melodic += 1
            if next_melodic == _DRUM_CHANNEL:
                next_melodic = _DRUM_CHANNEL + 1
    return channels


def _materialize_track_events(
    track: dict, chords: list[dict], time_signature: str
) -> list[dict]:
    """物化轨 events：auto 且空 events 轨经 arranger.arrange_events 生成；
    manual 或已物化轨直接用 events 字段。保证预览=渲染（与 arrange_track 命令同源）。"""
    if track.get("mode") == "auto" and not track.get("events"):
        return arrange_events(
            chords,
            track.get("style", ""),
            track.get("program", 0),
            time_signature,
        )
    return list(track.get("events") or [])


def _encode_instrument_track(
    track: dict,
    channel: int,
    chords: list[dict],
    time_signature: str,
    division: int,
) -> bytes:
    """编码单条乐器轨 MTrk：轨首 program/CC7/CC10 + Note On/Off + EOT。

    旋律轨（program 0–127）写 program change；打击乐轨（program=-1）不写 program change，
    全部事件走通道 9，鼓键名经 resolve_drum_key 映射。音高经 pitch_to_midi 解析。
    offset/beats → tick 按 division 换算（四分音符=1 拍=division tick）。
    """
    program = int(track.get("program", 0))
    volume = int(track.get("volume", 100))
    pan = int(track.get("pan", 64))
    is_drum = program == -1
    chan = channel & 0x0F

    # 收集 (tick, data_bytes) 事件，按 tick 排序后编码 delta time
    timed: list[tuple[int, bytes]] = []

    # 轨首控制事件（tick=0）
    if not is_drum:
        # program change: 0xCn program
        timed.append((0, bytes([0xC0 | chan, program & 0x7F])))
    # CC7 volume: 0xBn 0x07 volume
    timed.append((0, bytes([0xB0 | chan, 0x07, volume & 0x7F])))
    # CC10 pan: 0xBn 0x0A pan
    timed.append((0, bytes([0xB0 | chan, 0x0A, pan & 0x7F])))

    # 音符事件
    events = _materialize_track_events(track, chords, time_signature)
    for ev in events:
        pitch_str = ev.get("pitch", "")
        pitch = resolve_drum_key(pitch_str) if is_drum else pitch_to_midi(pitch_str)
        velocity = int(ev.get("velocity", MIDI_VELOCITY))
        beats = float(ev.get("beats", 0) or 0)
        offset = float(ev.get("offset", 0) or 0)
        start_tick = max(0, int(round(offset * division)))
        duration_ticks = max(1, int(round(beats * division)))
        end_tick = start_tick + duration_ticks
        # Note On
        timed.append(
            (start_tick, bytes([0x90 | chan, pitch & 0x7F, velocity & 0x7F]))
        )
        # Note Off
        timed.append((end_tick, bytes([0x80 | chan, pitch & 0x7F, 0x00])))

    # 按 tick 稳定排序（同 tick 内保持插入序：控制事件先于音符）
    timed.sort(key=lambda item: item[0])

    # 编码 delta time + 事件
    events_bytes = bytearray()
    prev_tick = 0
    for tick, data in timed:
        delta = max(0, tick - prev_tick)
        events_bytes += _vlq(delta) + data
        prev_tick = tick
    # end of track
    events_bytes += b"\x00\xff\x2f\x00"
    return b"MTrk" + len(events_bytes).to_bytes(4, "big") + bytes(events_bytes)


def score_to_midi_bytes(score: dict, *, division: int = MIDI_DIVISION) -> bytes:
    """
    歌谱 v2 → SMF format 1 多轨 MIDI 字节流。

    结构：轨 0=速度/拍号元轨（tempo meta FF51 + 拍号 meta FF58，无音符）；
    其后每乐器轨一个 MTrk、独立通道（旋律轨按轨序映射通道 0..n 跳过 9），
    轨首写 program change + CC7(volume 直写) + CC10(pan 直写)；
    program=-1 打击乐轨全部事件写通道 9、不写 program change，鼓键名经
    inventory.resolve_drum_key 映射。auto 空 events 轨先经 arranger.arrange_events
    物化（与 arrange_track 命令同一实现，保证预览=渲染）。

    Args:
        score: 规范化歌谱 v2 dict（经 validate_score；含 bpm、time_signature、
               accompaniment_tracks）。accompaniment_tracks 为空时仅产出元轨（ntrks=1）。
        division: 每四分音符 tick 数（默认 480）

    Returns:
        SMF format 1 字节内容

    Raises:
        ValueError: bpm 非法或音高/鼓键名解析失败时（调用方须先经 validate_score；
                    本函数不重复全量校验，仅对渲染必需项做防御性断言）
    """
    raw_bpm = score.get("bpm", 120)
    bpm = float(raw_bpm if raw_bpm is not None else 120)
    if bpm <= 0:
        raise ValueError(f"非法 bpm: {bpm}（必须大于 0）")
    time_signature = score.get("time_signature") or "4/4"
    tracks = list(score.get("accompaniment_tracks") or [])
    chords = list(score.get("chords") or [])

    # 轨 0 元轨（速度/拍号）
    tempo_track = _encode_tempo_track(bpm, time_signature)
    # 乐器轨（每轨独立 MTrk + 通道）
    channels = _allocate_channels(tracks)
    instrument_tracks = [
        _encode_instrument_track(
            track, channels[i], chords, time_signature, division
        )
        for i, track in enumerate(tracks)
    ]

    ntrks = 1 + len(instrument_tracks)
    header = (
        b"MThd"
        + (6).to_bytes(4, "big")
        + (1).to_bytes(2, "big")  # format 1
        + ntrks.to_bytes(2, "big")
        + division.to_bytes(2, "big")
    )
    return header + tempo_track + b"".join(instrument_tracks)


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
    out_wav_path: str,
    *,
    soundfont_path: str | None = None,
    fluidsynth_cmd: str = "fluidsynth",
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    timeout: float = DEFAULT_RENDER_TIMEOUT,
) -> str:
    """
    多轨 MIDI → 单次 fluidsynth 渲染 WAV。

    流程：score_to_midi_bytes（format 1 多轨，落盘为 out_wav_path 同名 .mid，
    保留便于排查）→ 子进程
    `fluidsynth -ni -F <wav> -r <sample_rate> <soundfont> <midi>`
    （fluidsynth 2.5+ 要求选项在位置参数之前，该顺序向后兼容 2.4 及更早版本）。

    soundfont_path 缺省（None）时从 music-config 的 soundfont_path 读取
    （空串=未配置，按现状行为报错提示）；调用方也可显式注入。

    Args:
        score: 规范化歌谱 v2 dict（经 validate_score；含 bpm、accompaniment_tracks）
        out_wav_path: 输出 WAV 路径（父目录自动创建）
        soundfont_path: SoundFont(.sf2) 文件路径；None 时从 config 读取
        fluidsynth_cmd: fluidsynth 可执行文件（注入点，便于测试）
        sample_rate: 渲染采样率
        timeout: 子进程超时秒数

    Returns:
        输出 WAV 路径（str）

    Raises:
        AccompanimentError: 依赖缺失（逐项列出）或渲染失败时（现状行为延续）
    """
    if soundfont_path is None:
        # lazy import 避免模块加载期耦合；仅在未显式注入时回退到配置
        from workstation.config import get_settings

        soundfont_path = get_settings().music.soundfont_path

    problems = check_render_dependencies(soundfont_path, fluidsynth_cmd)
    if problems:
        raise AccompanimentError(
            "伴奏渲染依赖缺失:\n" + "\n".join(f"  - {p}" for p in problems)
        )

    out = Path(out_wav_path)
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
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise AccompanimentError(f"fluidsynth 渲染超时（>{timeout}s）") from exc
    except OSError as exc:
        raise AccompanimentError(f"fluidsynth 启动失败: {exc}") from exc

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise AccompanimentError(
            f"fluidsynth 渲染失败（退出码 {proc.returncode}）: {detail}"
        )
    if not out.is_file() or out.stat().st_size == 0:
        raise AccompanimentError(f"fluidsynth 未产出有效 WAV 文件: {out}")
    return str(out)
