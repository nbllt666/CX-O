// ============================================================================
// fixtures.ts — 歌谱夹具（v1/v2 输入原样，前后端唯一真相源的 TS 投影）
// 本文件由 scripts/gen_music_types.py 自动生成（s0202 前后端同源），禁止手改。
// 数据源：
//   - CX-O-VoiceWorkStation/tests/fixtures/score_fixtures.json（唯一真相源，变更只改该 JSON）
//   - score-v2.schema.json        x-version: 2.0.0（v2 夹具校验基准）
// 生成时间：2026-07-24T22:45:19+08:00
// ============================================================================


/** 夹具元信息（description 原样） */
export const SCORE_FIXTURE_META: Record<string, string> = {
  "minimal_v2": "最小样本：仅必填字段 + 占位单音符 melody",
  "melody_only_v2": "纯旋律样本：无 chords 无伴奏轨",
  "full_multitrack_v2": "多轨完整样本：melody + chords + auto 钢琴轨 + manual 贝斯轨（含 events）+ auto 鼓组轨（program=-1）",
  "v1_piano": "v1 输入样本（accompaniment_style=piano）：迁移后应得 style=block_chords 的首条 auto 钢琴轨",
  "v1_guitar": "v1 输入样本（accompaniment_style=guitar）：迁移后 style 原样保留为 guitar"
};

/**
 * 歌谱夹具输入原样（v1 夹具含已移除字段 accompaniment_style，属迁移测试输入；
 * v2 夹具为冻结契约输入形状）。消费方：mockDraftBackend.createDraft 种子、
 * validateScore 冒烟、渲染层快照冒烟。
 */
export const SCORE_FIXTURES: Record<string, Record<string, unknown>> = {
  "minimal_v2": {
    "title": "最小样本",
    "bpm": 120,
    "melody": [
      {
        "pitch": "C4",
        "beats": 4.0,
        "lyric": ""
      }
    ]
  },
  "melody_only_v2": {
    "title": "纯旋律样本",
    "bpm": 96,
    "time_signature": "4/4",
    "key": "C",
    "melody": [
      {
        "pitch": "C4",
        "beats": 1.0,
        "lyric": "你"
      },
      {
        "pitch": "D4",
        "beats": 1.0,
        "lyric": "好"
      },
      {
        "pitch": "E4",
        "beats": 2.0,
        "lyric": "呀"
      }
    ],
    "chords": [],
    "accompaniment_tracks": []
  },
  "full_multitrack_v2": {
    "title": "多轨样本",
    "bpm": 96,
    "time_signature": "4/4",
    "key": "C",
    "melody": [
      {
        "pitch": "C4",
        "beats": 1.0,
        "lyric": "你"
      },
      {
        "pitch": "E4",
        "beats": 1.0,
        "lyric": "好"
      },
      {
        "pitch": "G4",
        "beats": 2.0,
        "lyric": "呀"
      }
    ],
    "chords": [
      {
        "chord": "C",
        "beats": 4
      },
      {
        "chord": "G",
        "beats": 4
      }
    ],
    "accompaniment_tracks": [
      {
        "id": "trk_piano",
        "name": "钢琴",
        "program": 0,
        "mode": "auto",
        "style": "block_chords",
        "volume": 100,
        "pan": 64,
        "events": []
      },
      {
        "id": "trk_bass",
        "name": "贝斯",
        "program": 33,
        "mode": "manual",
        "style": "",
        "volume": 110,
        "pan": 56,
        "events": [
          {
            "pitch": "C2",
            "beats": 2.0,
            "offset": 0.0
          },
          {
            "pitch": "G2",
            "beats": 2.0,
            "offset": 2.0,
            "velocity": 80
          },
          {
            "pitch": "C2",
            "beats": 2.0,
            "offset": 4.0,
            "velocity": 96
          },
          {
            "pitch": "G2",
            "beats": 2.0,
            "offset": 6.0
          }
        ]
      },
      {
        "id": "trk_drum",
        "name": "鼓组",
        "program": -1,
        "mode": "auto",
        "style": "rock_4beat",
        "volume": 120,
        "pan": 64,
        "events": []
      }
    ]
  },
  "v1_piano": {
    "title": "v1钢琴样本",
    "bpm": 100,
    "time_signature": "4/4",
    "key": "C",
    "melody": [
      {
        "pitch": "C4",
        "beats": 1.0,
        "lyric": "一"
      },
      {
        "pitch": "G4",
        "beats": 1.0,
        "lyric": "闪"
      }
    ],
    "chords": [
      {
        "chord": "C",
        "beats": 4
      }
    ],
    "accompaniment_style": "piano"
  },
  "v1_guitar": {
    "title": "v1吉他样本",
    "bpm": 88,
    "melody": [
      {
        "pitch": "A3",
        "beats": 2.0,
        "lyric": "听"
      }
    ],
    "chords": [
      {
        "chord": "Am",
        "beats": 4
      }
    ],
    "accompaniment_style": "guitar"
  }
};

export const V2_FIXTURE_NAMES = ["minimal_v2", "melody_only_v2", "full_multitrack_v2"] as const;
export const V1_FIXTURE_NAMES = ["v1_piano", "v1_guitar"] as const;

/** 按名取夹具（深拷贝，防调用方原地篡改常量） */
export function getFixture(name: string): Record<string, unknown> {
  const score = SCORE_FIXTURES[name];
  if (!score) {
    throw new Error(`未知歌谱夹具: ${name}（可用: ${Object.keys(SCORE_FIXTURES).join('、')}）`);
  }
  return JSON.parse(JSON.stringify(score)) as Record<string, unknown>;
}