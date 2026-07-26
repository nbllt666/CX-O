"""
自动编排生成器（模块1_自动编排器 · 纯函数）

按和弦骨架 + 节奏型生成伴奏轨事件（score v2 accompaniment_tracks[].events[] 形状）。
确定性纯函数：同输入同输出，无副作用，无 IO。

接口签名严格匹配 voicews_music.pyi（契约唯一真相源）：
- resolve_style(style: str, program: int) -> str
- arrange_events(chords, style, program, time_signature="4/4") -> list[dict]

节奏型枚举（applies_to 见 inventory.INVENTORY.styles）：
- block_chords（柱式和弦，melodic）：和弦全体音符齐发，beats=和弦 beats
- arpeggio（八分分解，melodic）：和弦音按八分音符依次琶音循环填满和弦时长
- root_eighth（根音八分，melodic）：根音按八分音符重复（低八度铺底，C1 区）
- rock_4beat（鼓组四拍型，percussion）：kick 1/3 拍、snare 2/4 拍、closed_hihat 八分铺底

和弦解析：C/C7/Cmaj7/Am/Fdim/Gaug 等；根音按绝对音高生成（契约无 key 参数，不做移调）。
旋律轨 pitch=科学音高记谱（C2 区，C2=36）；打击乐轨 pitch=GM 鼓键名字符串。

偏离说明（rules-4 §4.3 契约优先）：
任务描述预期 arrange_events(chords, style, key, program) 签名含 key 参数，
但冻结契约 voicews_music.pyi 签名为 (chords, style, program, time_signature="4/4")，
无 key 参数。本实现严格匹配契约签名，不做移调（根音按绝对音高生成）。
如后续需移调，应经 s0601 契约变更流程在 .pyi 增补 key 参数后实现。
"""
from __future__ import annotations

from typing import Any

from workstation.music.inventory import INVENTORY, get_style

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 根音字母 → 半音偏移（以 C 为 0）
_CHORD_ROOTS: dict[str, int] = {
    "C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11,
}

# 和弦后缀 → 相对根音的半音偏移列表
# ""=大三和弦（根+大三度+纯五度）；m=小三；7=属七；maj7=大七；dim=减三；aug=增三
_CHORD_INTERVALS: dict[str, list[int]] = {
    "": [0, 4, 7],
    "m": [0, 3, 7],
    "7": [0, 4, 7, 10],
    "maj7": [0, 4, 7, 11],
    "dim": [0, 3, 6],
    "aug": [0, 4, 8],
}

# 半音偏移（0-11）→ 音名（升号记谱）
_PITCH_NAMES: list[str] = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# 默认力度（MIDI velocity，契约 events 元素 velocity default=64）
_DEFAULT_VELOCITY: int = 64

# 旋律轨和弦音默认八度（C2 区，对齐任务描述"和弦音八度默认用 2 区"）
_MELODIC_OCTAVE: int = 2

# root_eighth 根音低八度（C1 区，对齐 inventory.styles description "低八度铺底，适合贝斯轨"）
_BASS_OCTAVE: int = 1

# 八分音符节拍数（四分音符=1 拍）
_EIGHTH_BEATS: float = 0.5

# 鼓击排序权重（同 offset 内稳定排序用，kick 优先于 snare 优先于 hihat）
_DRUM_SORT_ORDER: dict[str, int] = {
    "kick": 0, "snare": 1, "closed_hihat": 2, "open_hihat": 3,
    "crash": 4, "ride": 5, "tom_high": 6, "tom_mid": 7, "tom_low": 8, "clap": 9,
}


# ---------------------------------------------------------------------------
# 内部辅助：和弦解析
# ---------------------------------------------------------------------------


def _parse_chord(chord: str) -> tuple[int, list[int]]:
    """
    解析和弦标记 → (根音半音偏移 0-11, 和弦音相对偏移列表)。

    支持格式：C / C# / Cb / Cm / C7 / Cmaj7 / Cdim / Caug / Am / G7 / Fmaj7 等。
    根音字母大小写不敏感（Am 的 A 与 C 的 C 均按大写字母查表）。

    Args:
        chord: 和弦标记字符串

    Returns:
        (根音半音偏移, 和弦音相对根音的半音偏移列表)

    Raises:
        ValueError: 和弦标记非法或后缀不支持时
    """
    if not isinstance(chord, str) or not chord:
        raise ValueError(f"非法和弦标记: {chord!r}（必须非空字符串）")
    root_letter = chord[0].upper()
    if root_letter not in _CHORD_ROOTS:
        raise ValueError(
            f"非法和弦标记: {chord!r}（根音必须是 C/D/E/F/G/A/B 之一）"
        )
    root = _CHORD_ROOTS[root_letter]
    rest = chord[1:]
    # 升降号
    if rest and rest[0] in ("#", "b"):
        if rest[0] == "#":
            root += 1
        else:
            root -= 1
        rest = rest[1:]
    suffix = rest
    if suffix not in _CHORD_INTERVALS:
        available = "、".join(repr(k) if k else "''(大三)" for k in _CHORD_INTERVALS)
        raise ValueError(
            f"不支持的和弦后缀: {suffix!r}（和弦标记: {chord!r}；可用后缀: {available}）"
        )
    return root % 12, list(_CHORD_INTERVALS[suffix])


def _semitone_to_pitch_name(semitone: int, octave: int) -> str:
    """半音偏移（0-11）+ 八度 → 科学音高记谱（如 0, 2 → 'C2'；0, 1 → 'C1'）"""
    name = _PITCH_NAMES[semitone % 12]
    return f"{name}{octave}"


def _build_chord_pitches(root_semitone: int, intervals: list[int], octave: int) -> list[str]:
    """
    根音半音 + 相对偏移列表 → 科学音高记谱列表。

    和弦音可能跨八度（如 A2 和弦的三音 C3 在下一八度），按半音累加自然跨八度处理。
    """
    pitches: list[str] = []
    for interval in intervals:
        total = root_semitone + interval
        note_octave = octave + (total // 12)
        note_semitone = total % 12
        pitches.append(_semitone_to_pitch_name(note_semitone, note_octave))
    return pitches


def _parse_beats_per_measure(time_signature: str) -> int:
    """解析拍号得每小节拍数（如 '4/4' → 4, '3/4' → 3, '6/8' → 6）"""
    if not isinstance(time_signature, str):
        return 4
    parts = time_signature.split("/")
    if len(parts) != 2:
        return 4
    try:
        n = int(parts[0])
        return n if n > 0 else 4
    except (ValueError, TypeError):
        return 4


# ---------------------------------------------------------------------------
# 内部辅助：events 构造
# ---------------------------------------------------------------------------


def _make_event(pitch: str, beats: float, offset: float, velocity: int = _DEFAULT_VELOCITY) -> dict[str, Any]:
    """构造单个 event dict（形状 = score v2 accompaniment_tracks[].events[] 元素）"""
    return {
        "pitch": pitch,
        "beats": beats,
        "offset": offset,
        "velocity": velocity,
    }


def _round(x: float) -> float:
    """浮点规整到 6 位小数，避免累加误差导致 offset 不精确"""
    return round(x, 6)


# ---------------------------------------------------------------------------
# 节奏型生成器
# ---------------------------------------------------------------------------


def _gen_block_chords(chords: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    block_chords（柱式和弦）：和弦全体音符在 offset=和弦起点齐发，beats=和弦 beats。

    旋律轨（program>=0）专用，pitch=科学音高记谱（C2 区）。
    """
    events: list[dict[str, Any]] = []
    chord_offset = 0.0
    for chord in chords:
        chord_beats = float(chord["beats"])
        root, intervals = _parse_chord(chord["chord"])
        pitches = _build_chord_pitches(root, intervals, _MELODIC_OCTAVE)
        for pitch in pitches:
            events.append(_make_event(pitch, chord_beats, _round(chord_offset)))
        chord_offset += chord_beats
    events.sort(key=lambda e: (e["offset"], e["pitch"]))
    return events


def _gen_arpeggio(chords: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    arpeggio（八分分解）：和弦音按八分音符（beats=0.5）依次琶音，循环填满和弦时长。
    """
    events: list[dict[str, Any]] = []
    chord_offset = 0.0
    for chord in chords:
        chord_beats = float(chord["beats"])
        root, intervals = _parse_chord(chord["chord"])
        pitches = _build_chord_pitches(root, intervals, _MELODIC_OCTAVE)
        if not pitches:
            chord_offset += chord_beats
            continue
        step = _EIGHTH_BEATS
        i = 0
        while i * step < chord_beats - 1e-9:
            ev_offset = chord_offset + i * step
            remaining = chord_beats - i * step
            ev_beats = step if remaining >= step else remaining
            if ev_beats <= 0:
                break
            pitch = pitches[i % len(pitches)]
            events.append(_make_event(pitch, _round(ev_beats), _round(ev_offset)))
            i += 1
        chord_offset += chord_beats
    events.sort(key=lambda e: (e["offset"], e["pitch"]))
    return events


def _gen_root_eighth(chords: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    root_eighth（根音八分）：根音按八分音符（beats=0.5）重复，填满和弦时长。
    根音用低八度（C1 区），对齐 inventory.styles description "低八度铺底，适合贝斯轨"。
    """
    events: list[dict[str, Any]] = []
    chord_offset = 0.0
    for chord in chords:
        chord_beats = float(chord["beats"])
        root, _intervals = _parse_chord(chord["chord"])
        root_pitch = _semitone_to_pitch_name(root, _BASS_OCTAVE)
        step = _EIGHTH_BEATS
        i = 0
        while i * step < chord_beats - 1e-9:
            ev_offset = chord_offset + i * step
            remaining = chord_beats - i * step
            ev_beats = step if remaining >= step else remaining
            if ev_beats <= 0:
                break
            events.append(_make_event(root_pitch, _round(ev_beats), _round(ev_offset)))
            i += 1
        chord_offset += chord_beats
    events.sort(key=lambda e: (e["offset"], e["pitch"]))
    return events


def _gen_rock_4beat(chords: list[dict[str, Any]], time_signature: str) -> list[dict[str, Any]]:
    """
    rock_4beat（鼓组四拍型，percussion 专用）：
    每小节 beats_per_measure 拍，kick 在奇数拍（1/3/5...）、snare 在偶数拍（2/4/6...），
    closed_hihat 八分音符铺底（每 0.5 拍一击）。按全局拍位连续推进，跨和弦边界鼓型不中断。
    """
    beats_per_measure = _parse_beats_per_measure(time_signature)
    events: list[dict[str, Any]] = []
    global_offset = 0.0
    for chord in chords:
        chord_beats = float(chord["beats"])
        # kick / snare：每拍一个
        beat = 0.0
        while beat < chord_beats - 1e-9:
            remaining = chord_beats - beat
            dur = min(1.0, remaining)
            if dur <= 0:
                break
            global_beat = global_offset + beat
            beat_idx_in_measure = int(round(global_beat)) % beats_per_measure
            # 0-indexed：偶数拍（0,2,4...）= kick；奇数拍（1,3,5...）= snare
            if beat_idx_in_measure % 2 == 0:
                events.append(_make_event("kick", _round(dur), _round(global_beat)))
            else:
                events.append(_make_event("snare", _round(dur), _round(global_beat)))
            beat += 1.0
        # closed_hihat：每 0.5 拍一击
        hh = 0.0
        while hh < chord_beats - 1e-9:
            remaining = chord_beats - hh
            dur = min(0.5, remaining)
            if dur <= 0:
                break
            global_hh = global_offset + hh
            events.append(_make_event("closed_hihat", _round(dur), _round(global_hh)))
            hh += 0.5
        global_offset += chord_beats
    events.sort(key=lambda e: (e["offset"], _DRUM_SORT_ORDER.get(e["pitch"], 99)))
    return events


# ---------------------------------------------------------------------------
# 公开接口（签名严格匹配 voicews_music.pyi）
# ---------------------------------------------------------------------------


def resolve_style(style: str, program: int) -> str:
    """
    空 style 回退默认：program=-1 → "rock_4beat"；其余 → "block_chords"。
    非空 style 原样返回（合法性由 arrange_events 校验）。

    Args:
        style: 节奏型 id（空串触发回退）
        program: 轨 program（-1=打击乐轨，0-127=旋律轨）

    Returns:
        节奏型 id（非空）

    Raises:
        无
    """
    if style:
        return style
    if program == -1:
        return "rock_4beat"
    return "block_chords"


def arrange_events(
    chords: list[dict[str, Any]],
    style: str,
    program: int,
    time_signature: str = "4/4",
) -> list[dict[str, Any]]:
    """
    按和弦骨架 + 节奏型生成轨事件（确定性纯函数：同输入同输出，幂等）。

    Args:
        chords: 和弦骨架 [{chord, beats}]（空列表 → 返回空事件列表，不报错）
        style: 节奏型 id（空串先经 resolve_style 回退）
        program: 轨 program（-1=打击乐轨，仅可使用 applies_to=percussion 的节奏型；
                 其余仅可使用 applies_to=melodic 的节奏型）
        time_signature: 拍号（影响节奏型的小节对齐）

    Returns:
        events 列表（按 offset 升序，形状见 score v2 events 元素；
        打击乐轨 pitch 为 GM 鼓键名字符串）

    Raises:
        ValueError: style 不在节奏型枚举内，或与轨类型不匹配（applies_to 冲突）
                    ——错误消息附可用枚举清单（对应错误码 STYLE_UNKNOWN）
    """
    if not chords:
        return []
    resolved_style = resolve_style(style, program)
    style_def = get_style(resolved_style)
    if style_def is None:
        available = "、".join(s["id"] for s in INVENTORY["styles"])
        raise ValueError(
            f"未知节奏型: {resolved_style!r}（可用枚举: {available}）"
        )
    applies_to = style_def["applies_to"]
    if program == -1 and applies_to != "percussion":
        raise ValueError(
            f"节奏型 {resolved_style!r} 不适用于打击乐轨（applies_to={applies_to}，"
            f"program=-1 仅可使用 percussion 型节奏型）"
        )
    if program >= 0 and applies_to != "melodic":
        raise ValueError(
            f"节奏型 {resolved_style!r} 不适用于旋律轨（applies_to={applies_to}，"
            f"program>=0 仅可使用 melodic 型节奏型）"
        )
    # 分发到节奏型生成器
    if resolved_style == "block_chords":
        return _gen_block_chords(chords)
    if resolved_style == "arpeggio":
        return _gen_arpeggio(chords)
    if resolved_style == "root_eighth":
        return _gen_root_eighth(chords)
    if resolved_style == "rock_4beat":
        return _gen_rock_4beat(chords, time_signature)
    # 不应到达（已校验 style 存在）；防御性抛错
    raise ValueError(f"未实现的节奏型: {resolved_style!r}")
