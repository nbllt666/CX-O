 
// ============================================================================
// inventory.ts — 音乐枚举清单数据 + 存取函数（前后端同源）
// 本文件由 scripts/gen_music_types.py 自动生成（s0202 前后端同源），禁止手改。
// 数据源：
//   - CX-O-VoiceWorkStation/workstation/music/inventory.py（INVENTORY 与鼓键别名唯一真源，经 import 取得）
//   - music-inventory.schema.json  x-version: 1.0.0（形状基准）
// 生成时间：2026-07-24T22:45:19+08:00
// ============================================================================


import type { MusicInventory, StyleDef } from '../types';

/** 音乐枚举清单（GM 16 组 128 音色 / 4 节奏型 / 10 鼓键，后端 INVENTORY 原样投影） */
export const INVENTORY: MusicInventory = {
  "instrument_groups": [
    {
      "group_id": "piano",
      "name": "钢琴",
      "program_range": [
        0,
        7
      ],
      "instruments": [
        {
          "program": 0,
          "name": "大钢琴 Acoustic Grand Piano"
        },
        {
          "program": 1,
          "name": "亮音钢琴 Bright Acoustic Piano"
        },
        {
          "program": 2,
          "name": "电三角钢琴 Electric Grand Piano"
        },
        {
          "program": 3,
          "name": "酒吧钢琴 Honky-tonk Piano"
        },
        {
          "program": 4,
          "name": "电钢琴1 Electric Piano 1"
        },
        {
          "program": 5,
          "name": "电钢琴2 Electric Piano 2"
        },
        {
          "program": 6,
          "name": "羽管键琴 Harpsichord"
        },
        {
          "program": 7,
          "name": "击弦古钢琴 Clavinet"
        }
      ]
    },
    {
      "group_id": "chromatic_percussion",
      "name": "色彩打击乐",
      "program_range": [
        8,
        15
      ],
      "instruments": [
        {
          "program": 8,
          "name": "钢片琴 Celesta"
        },
        {
          "program": 9,
          "name": "钟琴 Glockenspiel"
        },
        {
          "program": 10,
          "name": "八音盒 Music Box"
        },
        {
          "program": 11,
          "name": "颤音琴 Vibraphone"
        },
        {
          "program": 12,
          "name": "马林巴 Marimba"
        },
        {
          "program": 13,
          "name": "木琴 Xylophone"
        },
        {
          "program": 14,
          "name": "管钟 Tubular Bells"
        },
        {
          "program": 15,
          "name": "扬琴 Dulcimer"
        }
      ]
    },
    {
      "group_id": "organ",
      "name": "风琴",
      "program_range": [
        16,
        23
      ],
      "instruments": [
        {
          "program": 16,
          "name": "拉杆风琴 Drawbar Organ"
        },
        {
          "program": 17,
          "name": "敲击风琴 Percussive Organ"
        },
        {
          "program": 18,
          "name": "摇滚风琴 Rock Organ"
        },
        {
          "program": 19,
          "name": "教堂风琴 Church Organ"
        },
        {
          "program": 20,
          "name": "簧风琴 Reed Organ"
        },
        {
          "program": 21,
          "name": "手风琴 Accordion"
        },
        {
          "program": 22,
          "name": "口琴 Harmonica"
        },
        {
          "program": 23,
          "name": "探戈手风琴 Tango Accordion"
        }
      ]
    },
    {
      "group_id": "guitar",
      "name": "吉他",
      "program_range": [
        24,
        31
      ],
      "instruments": [
        {
          "program": 24,
          "name": "尼龙弦吉他 Acoustic Guitar (nylon)"
        },
        {
          "program": 25,
          "name": "钢弦吉他 Acoustic Guitar (steel)"
        },
        {
          "program": 26,
          "name": "爵士电吉他 Electric Guitar (jazz)"
        },
        {
          "program": 27,
          "name": "清音电吉他 Electric Guitar (clean)"
        },
        {
          "program": 28,
          "name": "闷音电吉他 Electric Guitar (muted)"
        },
        {
          "program": 29,
          "name": "过载吉他 Overdriven Guitar"
        },
        {
          "program": 30,
          "name": "失真吉他 Distortion Guitar"
        },
        {
          "program": 31,
          "name": "吉他泛音 Guitar Harmonics"
        }
      ]
    },
    {
      "group_id": "bass",
      "name": "贝斯",
      "program_range": [
        32,
        39
      ],
      "instruments": [
        {
          "program": 32,
          "name": "原声贝斯 Acoustic Bass"
        },
        {
          "program": 33,
          "name": "指弹电贝斯 Electric Bass (finger)"
        },
        {
          "program": 34,
          "name": "拨片电贝斯 Electric Bass (pick)"
        },
        {
          "program": 35,
          "name": "无品贝斯 Fretless Bass"
        },
        {
          "program": 36,
          "name": "击勾弦贝斯1 Slap Bass 1"
        },
        {
          "program": 37,
          "name": "击勾弦贝斯2 Slap Bass 2"
        },
        {
          "program": 38,
          "name": "合成贝斯1 Synth Bass 1"
        },
        {
          "program": 39,
          "name": "合成贝斯2 Synth Bass 2"
        }
      ]
    },
    {
      "group_id": "strings",
      "name": "弦乐",
      "program_range": [
        40,
        47
      ],
      "instruments": [
        {
          "program": 40,
          "name": "小提琴 Violin"
        },
        {
          "program": 41,
          "name": "中提琴 Viola"
        },
        {
          "program": 42,
          "name": "大提琴 Cello"
        },
        {
          "program": 43,
          "name": "低音提琴 Contrabass"
        },
        {
          "program": 44,
          "name": "震音弦乐 Tremolo Strings"
        },
        {
          "program": 45,
          "name": "拨奏弦乐 Pizzicato Strings"
        },
        {
          "program": 46,
          "name": "竖琴 Orchestral Harp"
        },
        {
          "program": 47,
          "name": "定音鼓 Timpani"
        }
      ]
    },
    {
      "group_id": "ensemble",
      "name": "合奏",
      "program_range": [
        48,
        55
      ],
      "instruments": [
        {
          "program": 48,
          "name": "弦乐合奏1 String Ensemble 1"
        },
        {
          "program": 49,
          "name": "弦乐合奏2 String Ensemble 2"
        },
        {
          "program": 50,
          "name": "合成弦乐1 Synth Strings 1"
        },
        {
          "program": 51,
          "name": "合成弦乐2 Synth Strings 2"
        },
        {
          "program": 52,
          "name": "人声啊 Choir Aahs"
        },
        {
          "program": 53,
          "name": "人声哦 Voice Oohs"
        },
        {
          "program": 54,
          "name": "合成人声 Synth Voice"
        },
        {
          "program": 55,
          "name": "管弦乐重音 Orchestra Hit"
        }
      ]
    },
    {
      "group_id": "brass",
      "name": "铜管",
      "program_range": [
        56,
        63
      ],
      "instruments": [
        {
          "program": 56,
          "name": "小号 Trumpet"
        },
        {
          "program": 57,
          "name": "长号 Trombone"
        },
        {
          "program": 58,
          "name": "大号 Tuba"
        },
        {
          "program": 59,
          "name": "弱音小号 Muted Trumpet"
        },
        {
          "program": 60,
          "name": "圆号 French Horn"
        },
        {
          "program": 61,
          "name": "铜管组 Brass Section"
        },
        {
          "program": 62,
          "name": "合成铜管1 Synth Brass 1"
        },
        {
          "program": 63,
          "name": "合成铜管2 Synth Brass 2"
        }
      ]
    },
    {
      "group_id": "reed",
      "name": "簧片",
      "program_range": [
        64,
        71
      ],
      "instruments": [
        {
          "program": 64,
          "name": "高音萨克斯 Soprano Sax"
        },
        {
          "program": 65,
          "name": "中音萨克斯 Alto Sax"
        },
        {
          "program": 66,
          "name": "次中音萨克斯 Tenor Sax"
        },
        {
          "program": 67,
          "name": "上低音萨克斯 Baritone Sax"
        },
        {
          "program": 68,
          "name": "双簧管 Oboe"
        },
        {
          "program": 69,
          "name": "英国管 English Horn"
        },
        {
          "program": 70,
          "name": "巴松管 Bassoon"
        },
        {
          "program": 71,
          "name": "单簧管 Clarinet"
        }
      ]
    },
    {
      "group_id": "pipe",
      "name": "管乐",
      "program_range": [
        72,
        79
      ],
      "instruments": [
        {
          "program": 72,
          "name": "短笛 Piccolo"
        },
        {
          "program": 73,
          "name": "长笛 Flute"
        },
        {
          "program": 74,
          "name": "竖笛 Recorder"
        },
        {
          "program": 75,
          "name": "排箫 Pan Flute"
        },
        {
          "program": 76,
          "name": "吹瓶 Blown Bottle"
        },
        {
          "program": 77,
          "name": "尺八 Shakuhachi"
        },
        {
          "program": 78,
          "name": "口哨 Whistle"
        },
        {
          "program": 79,
          "name": "陶笛 Ocarina"
        }
      ]
    },
    {
      "group_id": "synth_lead",
      "name": "合成主音",
      "program_range": [
        80,
        87
      ],
      "instruments": [
        {
          "program": 80,
          "name": "主音1（方波） Lead 1 (square)"
        },
        {
          "program": 81,
          "name": "主音2（锯齿波） Lead 2 (sawtooth)"
        },
        {
          "program": 82,
          "name": "主音3（汽笛风琴） Lead 3 (calliope)"
        },
        {
          "program": 83,
          "name": "主音4（吹管） Lead 4 (chiff)"
        },
        {
          "program": 84,
          "name": "主音5（查兰格） Lead 5 (charang)"
        },
        {
          "program": 85,
          "name": "主音6（人声） Lead 6 (voice)"
        },
        {
          "program": 86,
          "name": "主音7（五度） Lead 7 (fifths)"
        },
        {
          "program": 87,
          "name": "主音8（贝斯+主音） Lead 8 (bass + lead)"
        }
      ]
    },
    {
      "group_id": "synth_pad",
      "name": "合成铺底",
      "program_range": [
        88,
        95
      ],
      "instruments": [
        {
          "program": 88,
          "name": "铺底1（新世纪） Pad 1 (new age)"
        },
        {
          "program": 89,
          "name": "铺底2（温暖） Pad 2 (warm)"
        },
        {
          "program": 90,
          "name": "铺底3（复音合成） Pad 3 (polysynth)"
        },
        {
          "program": 91,
          "name": "铺底4（合唱） Pad 4 (choir)"
        },
        {
          "program": 92,
          "name": "铺底5（弓弦） Pad 5 (bowed)"
        },
        {
          "program": 93,
          "name": "铺底6（金属） Pad 6 (metallic)"
        },
        {
          "program": 94,
          "name": "铺底7（光环） Pad 7 (halo)"
        },
        {
          "program": 95,
          "name": "铺底8（扫频） Pad 8 (sweep)"
        }
      ]
    },
    {
      "group_id": "synth_effects",
      "name": "合成音效",
      "program_range": [
        96,
        103
      ],
      "instruments": [
        {
          "program": 96,
          "name": "音效1（雨） FX 1 (rain)"
        },
        {
          "program": 97,
          "name": "音效2（音轨） FX 2 (soundtrack)"
        },
        {
          "program": 98,
          "name": "音效3（水晶） FX 3 (crystal)"
        },
        {
          "program": 99,
          "name": "音效4（氛围） FX 4 (atmosphere)"
        },
        {
          "program": 100,
          "name": "音效5（明亮） FX 5 (brightness)"
        },
        {
          "program": 101,
          "name": "音效6（精灵） FX 6 (goblins)"
        },
        {
          "program": 102,
          "name": "音效7（回声） FX 7 (echoes)"
        },
        {
          "program": 103,
          "name": "音效8（科幻） FX 8 (sci-fi)"
        }
      ]
    },
    {
      "group_id": "ethnic",
      "name": "民族乐器",
      "program_range": [
        104,
        111
      ],
      "instruments": [
        {
          "program": 104,
          "name": "西塔琴 Sitar"
        },
        {
          "program": 105,
          "name": "班卓琴 Banjo"
        },
        {
          "program": 106,
          "name": "三味线 Shamisen"
        },
        {
          "program": 107,
          "name": "古筝 Koto"
        },
        {
          "program": 108,
          "name": "卡林巴 Kalimba"
        },
        {
          "program": 109,
          "name": "风笛 Bagpipe"
        },
        {
          "program": 110,
          "name": "小提琴（民谣） Fiddle"
        },
        {
          "program": 111,
          "name": "唢呐 Shanai"
        }
      ]
    },
    {
      "group_id": "percussive",
      "name": "打击乐器",
      "program_range": [
        112,
        119
      ],
      "instruments": [
        {
          "program": 112,
          "name": "叮当铃 Tinkle Bell"
        },
        {
          "program": 113,
          "name": "阿哥哥铃 Agogo"
        },
        {
          "program": 114,
          "name": "钢鼓 Steel Drums"
        },
        {
          "program": 115,
          "name": "木鱼 Woodblock"
        },
        {
          "program": 116,
          "name": "太鼓 Taiko Drum"
        },
        {
          "program": 117,
          "name": "旋律桶鼓 Melodic Tom"
        },
        {
          "program": 118,
          "name": "合成鼓 Synth Drum"
        },
        {
          "program": 119,
          "name": "反镲 Reverse Cymbal"
        }
      ]
    },
    {
      "group_id": "sound_effects",
      "name": "音效",
      "program_range": [
        120,
        127
      ],
      "instruments": [
        {
          "program": 120,
          "name": "吉他滑品噪音 Guitar Fret Noise"
        },
        {
          "program": 121,
          "name": "呼吸噪音 Breath Noise"
        },
        {
          "program": 122,
          "name": "海浪 Seashore"
        },
        {
          "program": 123,
          "name": "鸟鸣 Bird Tweet"
        },
        {
          "program": 124,
          "name": "电话铃 Telephone Ring"
        },
        {
          "program": 125,
          "name": "直升机 Helicopter"
        },
        {
          "program": 126,
          "name": "掌声 Applause"
        },
        {
          "program": 127,
          "name": "枪声 Gunshot"
        }
      ]
    }
  ],
  "styles": [
    {
      "id": "block_chords",
      "name": "柱式和弦",
      "applies_to": "melodic",
      "description": "每个和弦按持续区间根音+三音+五音同时铺底（柱式），适合钢琴/铺底类音色"
    },
    {
      "id": "arpeggio",
      "name": "八分分解",
      "applies_to": "melodic",
      "description": "和弦音按八分音符分解依次上行循环，适合流动感伴奏"
    },
    {
      "id": "root_eighth",
      "name": "根音八分",
      "applies_to": "melodic",
      "description": "每八分音符重复和弦根音（低八度铺底），适合贝斯轨"
    },
    {
      "id": "rock_4beat",
      "name": "鼓组四拍型",
      "applies_to": "percussion",
      "description": "四拍摇滚鼓型：底鼓 1/3 拍、军鼓 2/4 拍、闭镲八分，仅打击乐轨可用"
    }
  ],
  "drum_keys": [
    {
      "key": "kick",
      "midi": 36,
      "name": "底鼓"
    },
    {
      "key": "snare",
      "midi": 38,
      "name": "军鼓"
    },
    {
      "key": "closed_hihat",
      "midi": 42,
      "name": "闭镲"
    },
    {
      "key": "open_hihat",
      "midi": 46,
      "name": "开镲"
    },
    {
      "key": "crash",
      "midi": 49,
      "name": "吊镲"
    },
    {
      "key": "ride",
      "midi": 51,
      "name": "叮叮镲"
    },
    {
      "key": "tom_high",
      "midi": 50,
      "name": "高音桶鼓"
    },
    {
      "key": "tom_mid",
      "midi": 47,
      "name": "中音桶鼓"
    },
    {
      "key": "tom_low",
      "midi": 45,
      "name": "低音桶鼓"
    },
    {
      "key": "clap",
      "midi": 39,
      "name": "拍手"
    }
  ]
};

/** 鼓键别名 → 规范键名（实现层数据，扩展属数据层变更） */
export const DRUM_KEY_ALIASES: Record<string, string> = {
  "bd": "kick",
  "bass_drum": "kick",
  "sd": "snare",
  "hh": "closed_hihat",
  "hihat": "closed_hihat",
  "oh": "open_hihat",
  "hi_tom": "tom_high",
  "mid_tom": "tom_mid",
  "low_tom": "tom_low",
  "hand_clap": "clap"
};

/** 鼓键解析索引：规范键名 + 别名 + 中文显示名 → MIDI 音号（模块加载期构建） */
const DRUM_KEY_INDEX: Record<string, number> = (() => {
  const index: Record<string, number> = {};
  for (const entry of INVENTORY.drum_keys) {
    index[entry.key] = entry.midi;
    index[entry.name] = entry.midi;
  }
  for (const [alias, canonical] of Object.entries(DRUM_KEY_ALIASES)) {
    index[alias] = index[canonical];
  }
  return index;
})();

/** 按 id 查节奏型定义（含 applies_to）；未命中返回 undefined */
export function getStyle(styleId: string): StyleDef | undefined {
  const hit = INVENTORY.styles.find((style) => style.id === styleId);
  return hit ? (JSON.parse(JSON.stringify(hit)) as StyleDef) : undefined;
}

/**
 * GM 鼓键名 → MIDI 音号（如 "kick"→36）。
 * 接受规范键名、实现层别名（如 "bd"/"hh"）与中文显示名（如 "底鼓"）。
 */
export function resolveDrumKey(key: string): number {
  if (typeof key === 'string') {
    const midi = DRUM_KEY_INDEX[key.trim()];
    if (midi !== undefined) {
      return midi;
    }
  }
  const available = INVENTORY.drum_keys.map((entry) => entry.key).join('、');
  throw new Error(`未定义的鼓键名: ${JSON.stringify(key)}（可用键名: ${available}）`);
}
