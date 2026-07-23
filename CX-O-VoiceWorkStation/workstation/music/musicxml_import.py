"""
MusicXML 导入模块：将 MusicXML 字节流转换为内部歌谱 JSON

解析规则（基于 music21）：
- BPM 取首个 MetronomeMark，缺省 120
- 拍号取首个 TimeSignature，缺省 "4/4"
- 调取首个 KeySignature，缺省 "C"
- 旋律取首个 Part（无分谱时取整个流）的音符：
  音高（music21 降号写法 "-" 归一为 "b"，与内部科学音高记谱一致）、
  时值按四分音符=1 拍换算、歌词取首条逐字
- 和声标记（ChordSymbol）转 chords，时长缺失时回退 4.0 拍
- 休止符不生成旋律条目
"""
from __future__ import annotations

try:
    from music21 import (
        chord as m21chord,
        converter,
        harmony,
        key as m21key,
        meter,
        note as m21note,
        tempo,
    )
except ImportError as exc:  # pragma: no cover - 仅在依赖缺失环境触发
    raise ImportError(
        "music21 未安装，无法使用 MusicXML 导入功能。请执行: pip install music21"
    ) from exc

# 无 BPM 标记时的默认速度
_DEFAULT_BPM = 120
# 和弦标记缺省持续节拍（一小节 4/4）
_DEFAULT_CHORD_BEATS = 4.0


class MusicXMLImportError(Exception):
    """MusicXML 导入失败（文件损坏或内容不支持），消息含可读原因"""


def _extract_bpm(stream) -> float:
    """提取首个 MetronomeMark 的 BPM，缺省返回 120"""
    marks = list(stream.recurse().getElementsByClass(tempo.MetronomeMark))
    for mark in marks:
        number = mark.number
        if number:
            value = float(number)
            return int(value) if value.is_integer() else value
    return _DEFAULT_BPM


def _extract_time_signature(stream) -> str:
    """提取首个拍号（如 4/4），缺省返回 4/4"""
    sigs = list(stream.recurse().getElementsByClass(meter.TimeSignature))
    if sigs and sigs[0].ratioString:
        return sigs[0].ratioString
    return "4/4"


def _extract_key(stream) -> str:
    """提取首个调号主音名，缺省返回 C"""
    sigs = list(stream.recurse().getElementsByClass(m21key.KeySignature))
    if sigs:
        try:
            tonic = sigs[0].asKey().tonic
            if tonic is not None and tonic.name:
                # music21 降号写法和音名统一为 b
                return tonic.name.replace("-", "b")
        except Exception:
            pass
    return "C"


def _normalize_pitch_name(name_with_octave: str) -> str:
    """music21 音高名（降号用 -，如 B-4）归一为内部写法（Bb4）"""
    return name_with_octave.replace("-", "b")


def _extract_melody(stream) -> list[dict]:
    """
    提取单旋律声部音符：音高 / 节拍（四分音符=1 拍）/ 歌词逐字。

    取首个 Part 为旋律声部；无分谱时在整个流上提取。
    休止符跳过；纵向和弦取最高音作为旋律音。
    """
    parts = stream.parts
    melody_source = parts[0] if len(parts) > 0 else stream

    melody: list[dict] = []
    for element in melody_source.recurse():
        # 和声标记（ChordSymbol 是 Chord 子类）不属于旋律，须先排除
        if isinstance(element, harmony.Harmony):
            continue
        if isinstance(element, m21note.Note):
            pitch_obj = element.pitch
        elif isinstance(element, m21chord.Chord):
            # 纵向和弦取最高音作为旋律音
            pitch_obj = element.pitches[-1]
        else:
            continue  # 休止符与其他元素不生成旋律条目

        beats = float(element.duration.quarterLength)
        if beats <= 0:
            continue
        melody.append(
            {
                "pitch": _normalize_pitch_name(pitch_obj.nameWithOctave),
                "beats": beats,
                "lyric": element.lyric or "",
            }
        )
    return melody


def _extract_chords(stream) -> list[dict]:
    """提取和声标记（ChordSymbol）转 chords；时长缺失时回退 4.0 拍"""
    chords: list[dict] = []
    for symbol in stream.recurse().getElementsByClass(harmony.ChordSymbol):
        figure = (symbol.figure or "").strip()
        if not figure:
            # figure 缺失时回退根音名，保证和弦标记非空
            figure = symbol.root().name.replace("-", "b") if symbol.root() else ""
        if not figure:
            continue
        beats = float(symbol.duration.quarterLength)
        if beats <= 0:
            beats = _DEFAULT_CHORD_BEATS
        chords.append({"chord": figure, "beats": beats})
    return chords


def _extract_title(stream) -> str:
    """提取曲名（MusicXML movement-title 映射到 movementName），缺省返回「未命名歌谱」"""
    metadata = stream.metadata
    if metadata is not None:
        for attr in ("title", "movementName"):
            value = getattr(metadata, attr, None)
            if value:
                return str(value)
    return "未命名歌谱"


def musicxml_to_score(xml_bytes: bytes) -> dict:
    """
    将 MusicXML 字节流转换为内部歌谱 dict（未规范化，可再经 validate_score 校验）。

    Args:
        xml_bytes: MusicXML 文件字节内容

    Returns:
        歌谱 dict（title/bpm/time_signature/key/melody/chords）

    Raises:
        MusicXMLImportError: 文件损坏、格式不支持或无旋律音符时，消息含可读原因
    """
    if not xml_bytes:
        raise MusicXMLImportError("MusicXML 内容为空")

    try:
        stream = converter.parse(xml_bytes, format="musicxml")
    except MusicXMLImportError:
        raise
    except Exception as exc:
        raise MusicXMLImportError(f"MusicXML 解析失败: {exc}") from exc

    melody = _extract_melody(stream)
    if not melody:
        raise MusicXMLImportError("未能从文件中提取到旋律音符（单旋律声部为空）")

    return {
        "title": _extract_title(stream),
        "bpm": _extract_bpm(stream),
        "time_signature": _extract_time_signature(stream),
        "key": _extract_key(stream),
        "melody": melody,
        "chords": _extract_chords(stream),
    }
