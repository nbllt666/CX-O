/**
 * 头像标签解析器：从 LLM 输出文本中提取驱动标签。
 *
 * 行为口径对齐 CX-O-Frontend src/lib/avatarTagParser.ts（纯逻辑移植，零依赖）。
 * 支持标签：[emotion:x] [blend:name:w] [bone:name:x:y:z[:speed]] [pose[:ms]]
 *           [release] [wind:dir:str[:gust:freq[:dur]]] [sleep:ms]
 * 非法标签按原文保留为文本，不产生异常。
 */

export type TagType = 'emotion' | 'blend' | 'bone' | 'pose' | 'release' | 'wind' | 'sleep';

export type EmotionTag = { type: 'emotion'; emotion: string };
export type BlendTag = { type: 'blend'; name: string; weight: number };
export type BoneTag = {
  type: 'bone';
  boneName: string;
  rotation: { x: number; y: number; z: number };
  speed: number;
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

export type AvatarTag =
  | EmotionTag
  | BlendTag
  | BoneTag
  | PoseTag
  | ReleaseTag
  | WindTag
  | SleepTag;

export type TextSegment = { type: 'text'; content: string };
export type TagSegment = { type: 'tag'; tag: AvatarTag; raw: string };
export type Segment = TextSegment | TagSegment;

export type ParseResult = {
  segments: Segment[];
  cleanText: string;
  tags: AvatarTag[];
};

const TAG_REGEX = /\[(\w+)(?::([^\]]+))?\]/g;

const VALID_TYPES = new Set<TagType>([
  'emotion',
  'blend',
  'bone',
  'pose',
  'release',
  'wind',
  'sleep',
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

function parseTag(type: string, paramsStr: string | undefined, _raw: string): AvatarTag | null {
  if (!VALID_TYPES.has(type as TagType)) return null;

  const params = parseParams(paramsStr);

  switch (type as TagType) {
    case 'emotion': {
      if (params.length < 1) return null;
      const emotion = params[0].toLowerCase();
      if (!SUPPORTED_EMOTIONS.has(emotion)) return null;
      return { type: 'emotion', emotion };
    }
    case 'blend': {
      if (params.length < 1) return null;
      const weight = params.length >= 2 ? parseNumber(params[1]) : 1.0;
      if (weight === null) return null;
      return { type: 'blend', name: params[0], weight: clamp(weight, 0, 1) };
    }
    case 'bone': {
      if (params.length < 4) return null;
      const rx = parseNumber(params[1]);
      const ry = parseNumber(params[2]);
      const rz = parseNumber(params[3]);
      if (rx === null || ry === null || rz === null) return null;
      const speed = params.length >= 5 ? parseNumber(params[4]) : 1.0;
      if (speed === null) return null;
      return {
        type: 'bone',
        boneName: params[0],
        rotation: {
          x: clamp(rx, -Math.PI, Math.PI),
          y: clamp(ry, -Math.PI, Math.PI),
          z: clamp(rz, -Math.PI, Math.PI),
        },
        speed: clamp(speed, 0.1, 5.0),
      };
    }
    case 'pose': {
      const durationMs = params.length >= 1 ? parseNumber(params[0]) : 3000;
      if (durationMs === null) return null;
      return { type: 'pose', durationMs: clamp(durationMs, 0, 30000) };
    }
    case 'release': {
      return { type: 'release' };
    }
    case 'wind': {
      if (params.length < 2) return null;
      const direction = parseNumber(params[0]);
      const strength = parseNumber(params[1]);
      if (direction === null || strength === null) return null;
      const gustStrength = params.length >= 3 ? parseNumber(params[2]) : 0;
      if (gustStrength === null) return null;
      const gustFrequency = params.length >= 4 ? parseNumber(params[3]) : 0;
      if (gustFrequency === null) return null;
      let gustDuration: number | string = 0;
      if (params.length >= 5) {
        const parsed = parseNumber(params[4]);
        if (parsed !== null) {
          gustDuration = parsed;
        } else if (/^\d+(\.\d+)?-\d+(\.\d+)?$/.test(params[4])) {
          gustDuration = params[4];
        } else {
          return null;
        }
      }
      return {
        type: 'wind',
        direction: clamp(direction, 0, 360),
        strength: clamp(strength, 0, 1),
        gustStrength: clamp(gustStrength, 0, 1),
        gustFrequency: clamp(gustFrequency, 0.1, 5.0),
        gustDuration:
          typeof gustDuration === 'number' ? clamp(gustDuration, 0, Infinity) : gustDuration,
      };
    }
    case 'sleep': {
      if (params.length < 1) return null;
      const ms = parseNumber(params[0]);
      if (ms === null) return null;
      return { type: 'sleep', duration_ms: clamp(ms, 100, 5000) };
    }
    default:
      return null;
  }
}

export function parseAvatarTags(text: string): ParseResult {
  const segments: Segment[] = [];
  const tags: AvatarTag[] = [];
  let lastIndex = 0;
  const regex = new RegExp(TAG_REGEX.source, 'g');
  let match: RegExpExecArray | null;

  while ((match = regex.exec(text)) !== null) {
    const raw = match[0];
    const tagType = match[1];
    const paramsStr = match[2];
    const matchStart = match.index;
    const matchEnd = matchStart + raw.length;

    if (matchStart > lastIndex) {
      segments.push({ type: 'text', content: text.slice(lastIndex, matchStart) });
    }

    const tag = parseTag(tagType, paramsStr, raw);

    if (tag) {
      segments.push({ type: 'tag', tag, raw });
      tags.push(tag);
    } else {
      segments.push({ type: 'text', content: raw });
    }

    lastIndex = matchEnd;
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
