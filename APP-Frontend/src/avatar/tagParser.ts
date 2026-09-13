/**
 * 头像标签解析器：从 LLM 输出文本中提取驱动标签。
 *
 * 行为口径对齐 CX-O-Frontend src/lib/avatarTagParser.ts（纯逻辑移植，零依赖）。
 * 支持标签：[emotion:x] [blend:name:w] [bone:name:x:y:z[:speed[:hold]]] [pose[:ms]]
 *           [release] [wind:dir:str[:gust:freq[:dur]]] [sleep:ms] [action:name]
 * 容错分级：类型可识别（VALID_TYPES 内）但参数非法/情感名未知的标签 → 剥离不显示
 * （不进 segments/cleanText/tags）；完全未知类型的方括号文本 → 按原文保留为文本。
 */

export type TagType =
  | 'emotion'
  | 'blend'
  | 'bone'
  | 'pose'
  | 'release'
  | 'wind'
  | 'sleep'
  | 'action';

export type EmotionTag = { type: 'emotion'; emotion: string };
export type BlendTag = { type: 'blend'; name: string; weight: number };
export type BoneTag = {
  type: 'bone';
  boneName: string;
  rotation: { x: number; y: number; z: number };
  speed: number;
  /** 保持时长（ms），省略时由引擎使用默认值并自动归中 */
  holdMs?: number;
};
export type PoseTag = { type: 'pose'; durationMs: number };
export type ReleaseTag = { type: 'release' };
export type WindTag = {
  type: 'wind';
  direction: number;
  strength: number;
  gustStrength: number;
  gustFrequency: number;
  gustDuration: number | string;
};
export type SleepTag = { type: 'sleep'; duration_ms: number };
export type ActionTag = { type: 'action'; action: string };

export type AvatarTag =
  | EmotionTag
  | BlendTag
  | BoneTag
  | PoseTag
  | ReleaseTag
  | WindTag
  | SleepTag
  | ActionTag;

export type TextSegment = { type: 'text'; content: string };
export type TagSegment = { type: 'tag'; tag: AvatarTag; raw: string };
export type Segment = TextSegment | TagSegment;

export type ParseResult = {
  segments: Segment[];
  cleanText: string;
  tags: AvatarTag[];
};

/** 单个标签解析结果三态：
 *  - valid：合法标签（进 segments/tags，从 cleanText 剥离）；
 *  - dropped：类型可识别但参数非法/情感名未知 → 剥离不显示（不进任何产出）；
 *  - unknown：完全未知类型（非标签意图的方括号文本）→ 按原文保留为 text。 */
export type TagParseOutcome =
  | { kind: 'valid'; tag: AvatarTag }
  | { kind: 'dropped' }
  | { kind: 'unknown' };

/** dropped 复用对象，避免高频解析时的无谓分配 */
const DROPPED: TagParseOutcome = { kind: 'dropped' };

// 参数段允许为空（[^\]]*）：使 [action:] 等空参数畸形标签也能命中并走剥离分级
const TAG_REGEX = /\[(\w+)(?::([^\]]*))?\]/g;

const VALID_TYPES = new Set<TagType>([
  'emotion',
  'blend',
  'bone',
  'pose',
  'release',
  'wind',
  'sleep',
  'action',
]);

const SUPPORTED_EMOTIONS = new Set<string>([
  'happy', 'sad', 'angry', 'surprised', 'fear',
  'disgust', 'neutral', 'excited', 'calm', 'whisper',
  'shout', 'laugh', 'cry', 'sigh', 'giggle',
  'normal', 'fearful', 'disgusted', 'tender',
]);

export function getSupportedEmotions(): string[] {
  return Array.from(SUPPORTED_EMOTIONS).sort();
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function parseNumber(raw: string): number | null {
  const n = Number(raw);
  return Number.isNaN(n) ? null : n;
}

function parseParams(paramsStr: string | undefined): string[] {
  if (!paramsStr) return [];
  return paramsStr.split(':');
}

function parseTag(type: string, paramsStr: string | undefined, _raw: string): TagParseOutcome {
  if (!VALID_TYPES.has(type as TagType)) return { kind: 'unknown' };
  // 参数段为空（如 [action:] [pose:]）→ 类型可识别但参数畸形 → 剥离；
  // 仅无参标签（[pose] [release]，无冒号）保留缺省值语义
  if (paramsStr === '') return DROPPED;

  const params = parseParams(paramsStr);

  switch (type as TagType) {
    case 'emotion': {
      if (params.length < 1) return DROPPED;
      const emotion = params[0].toLowerCase();
      if (!SUPPORTED_EMOTIONS.has(emotion)) return DROPPED;
      return { kind: 'valid', tag: { type: 'emotion', emotion } };
    }
    case 'blend': {
      if (params.length < 1) return DROPPED;
      const weight = params.length >= 2 ? parseNumber(params[1]) : 1.0;
      if (weight === null) return DROPPED;
      return { kind: 'valid', tag: { type: 'blend', name: params[0], weight: clamp(weight, 0, 1) } };
    }
    case 'bone': {
      if (params.length < 4) return DROPPED;
      const rx = parseNumber(params[1]);
      const ry = parseNumber(params[2]);
      const rz = parseNumber(params[3]);
      if (rx === null || ry === null || rz === null) return DROPPED;
      const speed = params.length >= 5 ? parseNumber(params[4]) : 1.0;
      if (speed === null) return DROPPED;
      const holdMs = params.length >= 6 ? parseNumber(params[5]) : undefined;
      if (holdMs === null) return DROPPED;
      return {
        kind: 'valid',
        tag: {
          type: 'bone',
          boneName: params[0],
          rotation: {
            x: clamp(rx, -Math.PI, Math.PI),
            y: clamp(ry, -Math.PI, Math.PI),
            z: clamp(rz, -Math.PI, Math.PI),
          },
          speed: clamp(speed, 0.1, 5.0),
          ...(holdMs !== undefined
            ? { holdMs: clamp(holdMs, 200, 300000) }
            : {}),
        },
      };
    }
    case 'pose': {
      const durationMs = params.length >= 1 ? parseNumber(params[0]) : 3000;
      if (durationMs === null) return DROPPED;
      return { kind: 'valid', tag: { type: 'pose', durationMs: clamp(durationMs, 0, 30000) } };
    }
    case 'release': {
      return { kind: 'valid', tag: { type: 'release' } };
    }
    case 'wind': {
      if (params.length < 2) return DROPPED;
      const direction = parseNumber(params[0]);
      const strength = parseNumber(params[1]);
      if (direction === null || strength === null) return DROPPED;
      const gustStrength = params.length >= 3 ? parseNumber(params[2]) : 0;
      if (gustStrength === null) return DROPPED;
      const gustFrequency = params.length >= 4 ? parseNumber(params[3]) : 0;
      if (gustFrequency === null) return DROPPED;
      let gustDuration: number | string = 0;
      if (params.length >= 5) {
        const parsed = parseNumber(params[4]);
        if (parsed !== null) {
          gustDuration = parsed;
        } else if (/^\d+(\.\d+)?-\d+(\.\d+)?$/.test(params[4])) {
          gustDuration = params[4];
        } else {
          return DROPPED;
        }
      }
      return {
        kind: 'valid',
        tag: {
          type: 'wind',
          direction: clamp(direction, 0, 360),
          strength: clamp(strength, 0, 1),
          gustStrength: clamp(gustStrength, 0, 1),
          gustFrequency: clamp(gustFrequency, 0.1, 5.0),
          gustDuration:
            typeof gustDuration === 'number' ? clamp(gustDuration, 0, Infinity) : gustDuration,
        },
      };
    }
    case 'sleep': {
      if (params.length < 1) return DROPPED;
      const ms = parseNumber(params[0]);
      if (ms === null) return DROPPED;
      return { kind: 'valid', tag: { type: 'sleep', duration_ms: clamp(ms, 100, 5000) } };
    }
    case 'action': {
      if (params.length < 1) return DROPPED;
      return { kind: 'valid', tag: { type: 'action', action: params[0].toLowerCase() } };
    }
    default:
      return DROPPED;
  }
}

/** 一次标签扫描结果：原文偏移 + 原文 + 解析产出 */
export interface TagMatch {
  /** 标签起点在原文中的字符偏移 */
  start: number;
  /** 标签原文（含方括号） */
  raw: string;
  /** 合法标签；null 表示不可用（dropped 或 unknown） */
  tag: AvatarTag | null;
  /** 类型是否可识别（VALID_TYPES 内）——tag 为 null 时区分 dropped(true)/unknown(false) */
  knownType: boolean;
}

/**
 * 扫描文本中的全部方括号标签匹配，保留原文偏移。
 *
 * 供标签时间线按 rawText 真实字符位置组织触发点：已剥离（dropped）的标签
 * 不产生命中，也不会使后续标签的偏移发生位移。
 */
export function scanAvatarTagMatches(text: string): TagMatch[] {
  const matches: TagMatch[] = [];
  const regex = new RegExp(TAG_REGEX.source, 'g');
  let match: RegExpExecArray | null;

  while ((match = regex.exec(text)) !== null) {
    const raw = match[0];
    const outcome = parseTag(match[1], match[2], raw);
    matches.push({
      start: match.index,
      raw,
      tag: outcome.kind === 'valid' ? outcome.tag : null,
      knownType: outcome.kind !== 'unknown',
    });
  }

  return matches;
}

export function parseAvatarTags(text: string): ParseResult {
  const segments: Segment[] = [];
  const tags: AvatarTag[] = [];
  let lastIndex = 0;

  for (const m of scanAvatarTagMatches(text)) {
    if (m.start > lastIndex) {
      segments.push({ type: 'text', content: text.slice(lastIndex, m.start) });
    }

    if (m.tag) {
      segments.push({ type: 'tag', tag: m.tag, raw: m.raw });
      tags.push(m.tag);
    } else if (!m.knownType) {
      // 完全未知类型（非标签意图的方括号文本）→ 按原文保留为 text
      segments.push({ type: 'text', content: m.raw });
    } else {
      // 类型可识别但参数非法/情感名未知 → 剥离：不进 segments/cleanText/tags，仅 debug 留痕
      console.debug('[tagParser] 剥离非法标签:', m.raw);
    }

    lastIndex = m.start + m.raw.length;
  }

  if (lastIndex < text.length) {
    segments.push({ type: 'text', content: text.slice(lastIndex) });
  }

  const cleanText = segments
    .filter((s) => s.type === 'text')
    .map((s) => s.content)
    .join('');

  return { segments, cleanText, tags };
}

export function stripAvatarTags(text: string): string {
  return parseAvatarTags(text).cleanText;
}
