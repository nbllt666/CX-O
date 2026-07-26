"""
音乐枚举清单一元真源（模块0_歌谱契约核心 · 新增）

持有三类枚举常量数据（形状经冻结契约 music-inventory.schema.json 实例校验）：
- instrument_groups: GM 标准 16 组 × 8 = 128 音色（组序与 program 区间固定对应，
  instruments[i].program = program_range[0] + i 严格对应）
- styles: 编排节奏型枚举（block_chords/arpeggio/root_eighth=melodic，rock_4beat=percussion）
- drum_keys: GM 鼓键名 → MIDI 音号映射（打击乐轨 events.pitch 的合法取值）

调用方：music_list_instruments 工具、arranger、validate_score 鼓键名校验、
前端 GM 选择器（经 REST 转发）。清单内容扩展（新增节奏型/鼓键别名）属数据层变更，
不修改 schema（contracts/README.md §4.3）。

import 期自检：INVENTORY 经冻结契约 music-inventory.schema.json 校验，
校验失败或契约文件缺失即 raise ImportError（防漂移）。
"""
from __future__ import annotations

import copy
import json
import os
from typing import Any, Optional

from jsonschema import Draft7Validator

# ---------------------------------------------------------------------------
# 常量数据（实例 = music-inventory.schema.json 的合法实例）
# ---------------------------------------------------------------------------


def _group(group_id: str, name: str, start: int, instruments: list[str]) -> dict:
    """构造一个 GM 音色分组：program 严格 = start + 组内序号"""
    return {
        "group_id": group_id,
        "name": name,
        "program_range": [start, start + 7],
        "instruments": [
            {"program": start + i, "name": instrument_name}
            for i, instrument_name in enumerate(instruments)
        ],
    }


INVENTORY: dict[str, Any] = {
    "instrument_groups": [
        _group("piano", "钢琴", 0, [
            "大钢琴 Acoustic Grand Piano",
            "亮音钢琴 Bright Acoustic Piano",
            "电三角钢琴 Electric Grand Piano",
            "酒吧钢琴 Honky-tonk Piano",
            "电钢琴1 Electric Piano 1",
            "电钢琴2 Electric Piano 2",
            "羽管键琴 Harpsichord",
            "击弦古钢琴 Clavinet",
        ]),
        _group("chromatic_percussion", "色彩打击乐", 8, [
            "钢片琴 Celesta",
            "钟琴 Glockenspiel",
            "八音盒 Music Box",
            "颤音琴 Vibraphone",
            "马林巴 Marimba",
            "木琴 Xylophone",
            "管钟 Tubular Bells",
            "扬琴 Dulcimer",
        ]),
        _group("organ", "风琴", 16, [
            "拉杆风琴 Drawbar Organ",
            "敲击风琴 Percussive Organ",
            "摇滚风琴 Rock Organ",
            "教堂风琴 Church Organ",
            "簧风琴 Reed Organ",
            "手风琴 Accordion",
            "口琴 Harmonica",
            "探戈手风琴 Tango Accordion",
        ]),
        _group("guitar", "吉他", 24, [
            "尼龙弦吉他 Acoustic Guitar (nylon)",
            "钢弦吉他 Acoustic Guitar (steel)",
            "爵士电吉他 Electric Guitar (jazz)",
            "清音电吉他 Electric Guitar (clean)",
            "闷音电吉他 Electric Guitar (muted)",
            "过载吉他 Overdriven Guitar",
            "失真吉他 Distortion Guitar",
            "吉他泛音 Guitar Harmonics",
        ]),
        _group("bass", "贝斯", 32, [
            "原声贝斯 Acoustic Bass",
            "指弹电贝斯 Electric Bass (finger)",
            "拨片电贝斯 Electric Bass (pick)",
            "无品贝斯 Fretless Bass",
            "击勾弦贝斯1 Slap Bass 1",
            "击勾弦贝斯2 Slap Bass 2",
            "合成贝斯1 Synth Bass 1",
            "合成贝斯2 Synth Bass 2",
        ]),
        _group("strings", "弦乐", 40, [
            "小提琴 Violin",
            "中提琴 Viola",
            "大提琴 Cello",
            "低音提琴 Contrabass",
            "震音弦乐 Tremolo Strings",
            "拨奏弦乐 Pizzicato Strings",
            "竖琴 Orchestral Harp",
            "定音鼓 Timpani",
        ]),
        _group("ensemble", "合奏", 48, [
            "弦乐合奏1 String Ensemble 1",
            "弦乐合奏2 String Ensemble 2",
            "合成弦乐1 Synth Strings 1",
            "合成弦乐2 Synth Strings 2",
            "人声啊 Choir Aahs",
            "人声哦 Voice Oohs",
            "合成人声 Synth Voice",
            "管弦乐重音 Orchestra Hit",
        ]),
        _group("brass", "铜管", 56, [
            "小号 Trumpet",
            "长号 Trombone",
            "大号 Tuba",
            "弱音小号 Muted Trumpet",
            "圆号 French Horn",
            "铜管组 Brass Section",
            "合成铜管1 Synth Brass 1",
            "合成铜管2 Synth Brass 2",
        ]),
        _group("reed", "簧片", 64, [
            "高音萨克斯 Soprano Sax",
            "中音萨克斯 Alto Sax",
            "次中音萨克斯 Tenor Sax",
            "上低音萨克斯 Baritone Sax",
            "双簧管 Oboe",
            "英国管 English Horn",
            "巴松管 Bassoon",
            "单簧管 Clarinet",
        ]),
        _group("pipe", "管乐", 72, [
            "短笛 Piccolo",
            "长笛 Flute",
            "竖笛 Recorder",
            "排箫 Pan Flute",
            "吹瓶 Blown Bottle",
            "尺八 Shakuhachi",
            "口哨 Whistle",
            "陶笛 Ocarina",
        ]),
        _group("synth_lead", "合成主音", 80, [
            "主音1（方波） Lead 1 (square)",
            "主音2（锯齿波） Lead 2 (sawtooth)",
            "主音3（汽笛风琴） Lead 3 (calliope)",
            "主音4（吹管） Lead 4 (chiff)",
            "主音5（查兰格） Lead 5 (charang)",
            "主音6（人声） Lead 6 (voice)",
            "主音7（五度） Lead 7 (fifths)",
            "主音8（贝斯+主音） Lead 8 (bass + lead)",
        ]),
        _group("synth_pad", "合成铺底", 88, [
            "铺底1（新世纪） Pad 1 (new age)",
            "铺底2（温暖） Pad 2 (warm)",
            "铺底3（复音合成） Pad 3 (polysynth)",
            "铺底4（合唱） Pad 4 (choir)",
            "铺底5（弓弦） Pad 5 (bowed)",
            "铺底6（金属） Pad 6 (metallic)",
            "铺底7（光环） Pad 7 (halo)",
            "铺底8（扫频） Pad 8 (sweep)",
        ]),
        _group("synth_effects", "合成音效", 96, [
            "音效1（雨） FX 1 (rain)",
            "音效2（音轨） FX 2 (soundtrack)",
            "音效3（水晶） FX 3 (crystal)",
            "音效4（氛围） FX 4 (atmosphere)",
            "音效5（明亮） FX 5 (brightness)",
            "音效6（精灵） FX 6 (goblins)",
            "音效7（回声） FX 7 (echoes)",
            "音效8（科幻） FX 8 (sci-fi)",
        ]),
        _group("ethnic", "民族乐器", 104, [
            "西塔琴 Sitar",
            "班卓琴 Banjo",
            "三味线 Shamisen",
            "古筝 Koto",
            "卡林巴 Kalimba",
            "风笛 Bagpipe",
            "小提琴（民谣） Fiddle",
            "唢呐 Shanai",
        ]),
        _group("percussive", "打击乐器", 112, [
            "叮当铃 Tinkle Bell",
            "阿哥哥铃 Agogo",
            "钢鼓 Steel Drums",
            "木鱼 Woodblock",
            "太鼓 Taiko Drum",
            "旋律桶鼓 Melodic Tom",
            "合成鼓 Synth Drum",
            "反镲 Reverse Cymbal",
        ]),
        _group("sound_effects", "音效", 120, [
            "吉他滑品噪音 Guitar Fret Noise",
            "呼吸噪音 Breath Noise",
            "海浪 Seashore",
            "鸟鸣 Bird Tweet",
            "电话铃 Telephone Ring",
            "直升机 Helicopter",
            "掌声 Applause",
            "枪声 Gunshot",
        ]),
    ],
    "styles": [
        {
            "id": "block_chords",
            "name": "柱式和弦",
            "applies_to": "melodic",
            "description": "每个和弦按持续区间根音+三音+五音同时铺底（柱式），适合钢琴/铺底类音色",
        },
        {
            "id": "arpeggio",
            "name": "八分分解",
            "applies_to": "melodic",
            "description": "和弦音按八分音符分解依次上行循环，适合流动感伴奏",
        },
        {
            "id": "root_eighth",
            "name": "根音八分",
            "applies_to": "melodic",
            "description": "每八分音符重复和弦根音（低八度铺底），适合贝斯轨",
        },
        {
            "id": "rock_4beat",
            "name": "鼓组四拍型",
            "applies_to": "percussion",
            "description": "四拍摇滚鼓型：底鼓 1/3 拍、军鼓 2/4 拍、闭镲八分，仅打击乐轨可用",
        },
    ],
    "drum_keys": [
        {"key": "kick", "midi": 36, "name": "底鼓"},
        {"key": "snare", "midi": 38, "name": "军鼓"},
        {"key": "closed_hihat", "midi": 42, "name": "闭镲"},
        {"key": "open_hihat", "midi": 46, "name": "开镲"},
        {"key": "crash", "midi": 49, "name": "吊镲"},
        {"key": "ride", "midi": 51, "name": "叮叮镲"},
        {"key": "tom_high", "midi": 50, "name": "高音桶鼓"},
        {"key": "tom_mid", "midi": 47, "name": "中音桶鼓"},
        {"key": "tom_low", "midi": 45, "name": "低音桶鼓"},
        {"key": "clap", "midi": 39, "name": "拍手"},
    ],
}

# 鼓键别名（实现层数据，契约 schema 不约束；扩展属数据层变更）。
# 取值 -> drum_keys[].key 规范键名。
_DRUM_KEY_ALIASES: dict[str, str] = {
    "bd": "kick",
    "bass_drum": "kick",
    "sd": "snare",
    "hh": "closed_hihat",
    "hihat": "closed_hihat",
    "oh": "open_hihat",
    "hi_tom": "tom_high",
    "mid_tom": "tom_mid",
    "low_tom": "tom_low",
    "hand_clap": "clap",
}


def _build_drum_key_index() -> dict[str, int]:
    """鼓键解析索引：规范键名 + 别名 + 中文显示名 → MIDI 音号"""
    index: dict[str, int] = {}
    for entry in INVENTORY["drum_keys"]:
        index[entry["key"]] = entry["midi"]
        index[entry["name"]] = entry["midi"]
    for alias, canonical in _DRUM_KEY_ALIASES.items():
        index[alias] = index[canonical]
    return index


_DRUM_KEY_INDEX = _build_drum_key_index()

# ---------------------------------------------------------------------------
# import 期自检：INVENTORY 必须经冻结契约校验（防漂移）
# ---------------------------------------------------------------------------

# 路径解析：禁止相对路径字符串拼接（rules-0 §三），逐层 dirname 定位 CX-O 根
_MUSIC_DIR = os.path.dirname(os.path.abspath(__file__))
_CXO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_MUSIC_DIR)))
_INVENTORY_SCHEMA_PATH = os.path.join(
    _CXO_ROOT, ".trae", "specs", "redesign-composition-staff-editor",
    "contracts", "music-inventory.schema.json",
)


def _self_check() -> None:
    """import 期校验 INVENTORY 形状；失败即 raise ImportError 防漂移"""
    try:
        with open(_INVENTORY_SCHEMA_PATH, "r", encoding="utf-8") as fp:
            schema = json.load(fp)
    except OSError as exc:
        raise ImportError(
            f"music-inventory 契约文件缺失或不可读: {_INVENTORY_SCHEMA_PATH} ({exc})"
        ) from exc
    validator = Draft7Validator(schema)
    errors = sorted(validator.iter_errors(INVENTORY), key=lambda e: list(e.absolute_path))
    if errors:
        detail = "; ".join(
            f"{'/'.join(str(n) for n in err.absolute_path) or '$'}: {err.message}"
            for err in errors[:5]
        )
        raise ImportError(
            f"INVENTORY 未通过 music-inventory.schema.json 实例校验（{len(errors)} 处）: {detail}"
        )


_self_check()

# ---------------------------------------------------------------------------
# 存取函数（签名严格匹配 voicews_music.pyi）
# ---------------------------------------------------------------------------


def get_inventory() -> dict[str, Any]:
    """
    返回音乐枚举清单（GM 16 组 128 音色 / 节奏型枚举 / 鼓键映射）。

    Returns:
        INVENTORY 深拷贝（防调用方原地篡改常量）

    Raises:
        无（常量为模块内静态数据，加载即合法——import 期已自检）
    """
    return copy.deepcopy(INVENTORY)


def get_style(style_id: str) -> Optional[dict[str, Any]]:
    """
    按 id 查节奏型定义（含 applies_to）；未命中返回 None。

    Args:
        style_id: 节奏型 id（如 "block_chords"）

    Returns:
        节奏型定义 dict（拷贝），未命中返回 None
    """
    for style in INVENTORY["styles"]:
        if style["id"] == style_id:
            return copy.deepcopy(style)
    return None


def resolve_drum_key(key: str) -> int:
    """
    GM 鼓键名 → MIDI 音号（如 "kick"→36）。

    接受规范键名（drum_keys[].key）、实现层别名（如 "bd"/"hh"）
    与中文显示名（如 "底鼓"）。

    Args:
        key: 鼓键名 / 别名 / 中文显示名

    Returns:
        GM 鼓键 MIDI 音号（35–81）

    Raises:
        ValueError: 鼓键名未定义时（附可用键名清单）
    """
    if isinstance(key, str):
        midi = _DRUM_KEY_INDEX.get(key.strip())
        if midi is not None:
            return midi
    available = "、".join(entry["key"] for entry in INVENTORY["drum_keys"])
    raise ValueError(f"未定义的鼓键名: {key!r}（可用键名: {available}）")
