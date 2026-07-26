/**
 * mockDraftBackend.ts — s0202 预生成 Mock：歌谱草稿命令总线（前端并行开发支点）
 *
 * 手写实现（非生成物），消费同目录生成物 types.ts / fixtures.ts / inventory.ts，
 * 模拟后端 draft_registry（模块3）+ validate_score（模块0）+ arranger（模块1）的外部行为，
 * 供模块6（五线谱渲染层）/ 模块7（作曲交互面板）在后端模块3 就绪前并行开发。
 *
 * 行为契约锚点（冻结）：
 * - contracts/command-protocol.schema.json：20 命令分发 / command_result 形状 / 10 错误码 /
 *   version 单调递增（get_draft、validate_draft 不增）/ undo-redo 空栈空操作成功 / 命令原子性
 * - contracts/score-v2.schema.json：v1→v2 迁移（accompaniment_style→首条 auto 钢琴轨）/
 *   轨 id 唯一 / 打击乐轨鼓键名
 * - contracts/README.md §4：note_id 轨内序号寻址 / 空白草稿 C4 全音符占位、首个 add_note 替换
 *
 * Mock 简化声明（与真实后端的差异，README 同步登记）：
 * 1. validateScore 为契约子集的手写校验（后端为 jsonschema 全量 + default 填充）；
 *    错误文本格式对齐后端（字段路径 + 可读消息），但不逐字一致。
 * 2. undo/redo 栈记录整谱快照（后端记录逆操作 before 片段），外部行为等价。
 * 3. arrangeEvents 为 mock 级确定性编排（三和弦简化解析、无视 time_signature）；
 *    真实 arranger（模块1）就绪后以其为准。
 * 4. 纯内存注册表，无落盘 / TTL 清扫 / REST 传输层；draft_id 为 draft_N 自增。
 * 5. changed_paths 恒为 ["$"]（契约允许首版全谱路径标记）。
 */
import type {
  AccompanimentTrack,
  ChordEntry,
  CommandName,
  CommandRequest,
  CommandResult,
  ErrorCode,
  MelodyNote,
  ScoreV2,
  TrackEvent,
} from '../types';
import { COMMAND_NAMES } from '../types';
import { getFixture } from './fixtures';
import { getStyle, INVENTORY, resolveDrumKey } from './inventory';

// ---------------------------------------------------------------------------
// 基础工具
// ---------------------------------------------------------------------------

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function nowIso(): string {
  return new Date().toISOString();
}

function isObj(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function isNum(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function isNonNegativeInt(value: unknown): value is number {
  return Number.isInteger(value) && (value as number) >= 0;
}

// ---------------------------------------------------------------------------
// 音高换算（与后端 score.pitch_to_midi 行为对齐，C4=60）
// ---------------------------------------------------------------------------

const PITCH_BASE: Record<string, number> = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };
const PITCH_PATTERN = /^([A-Ga-g])([#b]?)(-?\d+)$/;
const PITCH_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];

/** 科学音高记谱 → MIDI 音号（C4=60）；非法格式抛 Error */
export function pitchToMidi(pitch: string): number {
  if (typeof pitch !== 'string') {
    throw new Error(`非法音高记谱: ${JSON.stringify(pitch)}（必须是字符串）`);
  }
  const match = PITCH_PATTERN.exec(pitch.trim());
  if (!match) {
    throw new Error(`非法音高记谱: ${JSON.stringify(pitch)}（期望形如 C4 / A#3 / Bb5）`);
  }
  let semitone = PITCH_BASE[match[1].toUpperCase()];
  if (match[2] === '#') semitone += 1;
  else if (match[2] === 'b') semitone -= 1;
  return (parseInt(match[3], 10) + 1) * 12 + semitone;
}

/** MIDI 音号 → 科学音高记谱（升号写法，供编排生成事件音高） */
export function midiToPitch(midi: number): string {
  const octave = Math.floor(midi / 12) - 1;
  return `${PITCH_NAMES[((midi % 12) + 12) % 12]}${octave}`;
}

// ---------------------------------------------------------------------------
// v1 → v2 迁移（幂等纯函数，深拷贝；规则见 score-v2.schema.json x-migration）
// ---------------------------------------------------------------------------

const V1_STYLE_MAP: Record<string, string> = { piano: 'block_chords' };

export function migrateV1ToV2(data: Record<string, unknown>): Record<string, unknown> {
  const result = clone(data);
  if (!isObj(result)) {
    return result;
  }
  if ('accompaniment_style' in result && !('accompaniment_tracks' in result)) {
    const style = String(result.accompaniment_style);
    delete result.accompaniment_style;
    result.accompaniment_tracks = [
      {
        id: 'trk_0',
        name: '钢琴',
        program: 0,
        mode: 'auto',
        style: V1_STYLE_MAP[style] ?? style,
        volume: 100,
        pan: 64,
        events: [],
      },
    ];
  }
  return result;
}

// ---------------------------------------------------------------------------
// validateScore（mock 级：契约子集结构校验 + 后端同款追加校验 + default 填充）
// ---------------------------------------------------------------------------

export interface ValidateOutcome {
  ok: boolean;
  errors: string[];
  /** 规范化后的 v2 歌谱（default 已填充）；不合法时为 undefined */
  normalized?: ScoreV2;
}

const TIME_SIGNATURE_PATTERN = /^\d+\/\d+$/;
const TRACK_ID_PATTERN = /^[a-z0-9_]+$/;
const ROOT_KEYS = ['title', 'bpm', 'time_signature', 'key', 'melody', 'chords', 'accompaniment_tracks'];
const MELODY_KEYS = ['pitch', 'beats', 'lyric'];
const CHORD_KEYS = ['chord', 'beats'];
const TRACK_KEYS = ['id', 'name', 'program', 'mode', 'style', 'volume', 'pan', 'events'];
const EVENT_KEYS = ['pitch', 'beats', 'offset', 'velocity'];

function checkExtraKeys(obj: Record<string, unknown>, allowed: string[], path: string, errors: string[]): void {
  for (const key of Object.keys(obj)) {
    if (!allowed.includes(key)) {
      errors.push(`${path}: 不允许的额外字段: ${JSON.stringify(key)}`);
    }
  }
}

export function validateScore(data: unknown): ValidateOutcome {
  if (!isObj(data)) {
    return { ok: false, errors: ['$: 歌谱必须是 JSON 对象'] };
  }
  const src = migrateV1ToV2(data);
  const errors: string[] = [];
  checkExtraKeys(src, ROOT_KEYS, '$', errors);

  // 根字段
  const title = src.title;
  if (typeof title !== 'string' || title.length < 1) {
    errors.push('title: 必填，必须是非空字符串');
  }
  const bpm = src.bpm;
  if (!isNum(bpm) || bpm <= 0) {
    errors.push('bpm: 必填，必须是大于 0 的数字');
  }
  const timeSignature = src.time_signature ?? '4/4';
  if (typeof timeSignature !== 'string' || !TIME_SIGNATURE_PATTERN.test(timeSignature)) {
    errors.push('time_signature: 必须形如 "4/4"');
  }
  const key = src.key ?? 'C';
  if (typeof key !== 'string' || key.length < 1) {
    errors.push('key: 必须是非空字符串');
  }

  // melody（必填，minItems=1）
  const melody: MelodyNote[] = [];
  if (!Array.isArray(src.melody) || src.melody.length < 1) {
    errors.push('melody: 必填，至少一个音符');
  } else {
    src.melody.forEach((raw: unknown, idx: number) => {
      const path = `melody[${idx}]`;
      if (!isObj(raw)) {
        errors.push(`${path}: 必须是对象`);
        return;
      }
      checkExtraKeys(raw, MELODY_KEYS, path, errors);
      const lyric = raw.lyric ?? '';
      if (typeof raw.pitch !== 'string' || raw.pitch.length < 1) {
        errors.push(`${path}.pitch: 必填，必须是字符串`);
      }
      if (!isNum(raw.beats) || raw.beats <= 0) {
        errors.push(`${path}.beats: 必须大于 0`);
      }
      if (typeof lyric !== 'string') {
        errors.push(`${path}.lyric: 必须是字符串`);
      }
      melody.push({
        pitch: typeof raw.pitch === 'string' ? raw.pitch : '',
        beats: isNum(raw.beats) ? raw.beats : 1,
        lyric: typeof lyric === 'string' ? lyric : '',
      });
    });
  }

  // chords（默认 []）
  const chords: ChordEntry[] = [];
  const rawChords = src.chords ?? [];
  if (!Array.isArray(rawChords)) {
    errors.push('chords: 必须是数组');
  } else {
    rawChords.forEach((raw: unknown, idx: number) => {
      const path = `chords[${idx}]`;
      if (!isObj(raw)) {
        errors.push(`${path}: 必须是对象`);
        return;
      }
      checkExtraKeys(raw, CHORD_KEYS, path, errors);
      if (typeof raw.chord !== 'string' || raw.chord.length < 1) {
        errors.push(`${path}.chord: 必填，必须是非空字符串`);
      }
      if (!isNum(raw.beats) || raw.beats <= 0) {
        errors.push(`${path}.beats: 必须大于 0`);
      }
      chords.push({
        chord: typeof raw.chord === 'string' ? raw.chord : '',
        beats: isNum(raw.beats) ? raw.beats : 1,
      });
    });
  }

  // accompaniment_tracks（默认 []）
  const tracks: AccompanimentTrack[] = [];
  const rawTracks = src.accompaniment_tracks ?? [];
  if (!Array.isArray(rawTracks)) {
    errors.push('accompaniment_tracks: 必须是数组');
  } else {
    rawTracks.forEach((raw: unknown, idx: number) => {
      const path = `accompaniment_tracks[${idx}]`;
      if (!isObj(raw)) {
        errors.push(`${path}: 必须是对象`);
        return;
      }
      checkExtraKeys(raw, TRACK_KEYS, path, errors);
      const id = raw.id;
      const name = raw.name;
      const program = raw.program;
      const mode = raw.mode;
      const style = raw.style ?? '';
      const volume = raw.volume ?? 100;
      const pan = raw.pan ?? 64;
      if (typeof id !== 'string' || !TRACK_ID_PATTERN.test(id)) {
        errors.push(`${path}.id: 必填，必须匹配 ^[a-z0-9_]+$`);
      }
      if (typeof name !== 'string' || name.length < 1) {
        errors.push(`${path}.name: 必填，必须是非空字符串`);
      }
      if (!Number.isInteger(program) || (program as number) < -1 || (program as number) > 127) {
        errors.push(`${path}.program: 必填，必须是 -1..127 的整数`);
      }
      if (mode !== 'auto' && mode !== 'manual') {
        errors.push(`${path}.mode: 必填，枚举 auto|manual`);
      }
      if (typeof style !== 'string') {
        errors.push(`${path}.style: 必须是字符串`);
      }
      if (!Number.isInteger(volume) || (volume as number) < 0 || (volume as number) > 127) {
        errors.push(`${path}.volume: 必须是 0..127 的整数`);
      }
      if (!Number.isInteger(pan) || (pan as number) < 0 || (pan as number) > 127) {
        errors.push(`${path}.pan: 必须是 0..127 的整数`);
      }
      const events: TrackEvent[] = [];
      const rawEvents = raw.events ?? [];
      if (!Array.isArray(rawEvents)) {
        errors.push(`${path}.events: 必须是数组`);
      } else {
        rawEvents.forEach((rawEvent: unknown, eventIdx: number) => {
          const eventPath = `${path}.events[${eventIdx}]`;
          if (!isObj(rawEvent)) {
            errors.push(`${eventPath}: 必须是对象`);
            return;
          }
          checkExtraKeys(rawEvent, EVENT_KEYS, eventPath, errors);
          const velocity = rawEvent.velocity ?? 64;
          if (typeof rawEvent.pitch !== 'string' || rawEvent.pitch.length < 1) {
            errors.push(`${eventPath}.pitch: 必填，必须是字符串`);
          }
          if (!isNum(rawEvent.beats) || rawEvent.beats <= 0) {
            errors.push(`${eventPath}.beats: 必须大于 0`);
          }
          if (!isNum(rawEvent.offset) || rawEvent.offset < 0) {
            errors.push(`${eventPath}.offset: 必须大于等于 0`);
          }
          if (!Number.isInteger(velocity) || (velocity as number) < 1 || (velocity as number) > 127) {
            errors.push(`${eventPath}.velocity: 必须是 1..127 的整数`);
          }
          events.push({
            pitch: typeof rawEvent.pitch === 'string' ? rawEvent.pitch : '',
            beats: isNum(rawEvent.beats) ? rawEvent.beats : 1,
            offset: isNum(rawEvent.offset) ? rawEvent.offset : 0,
            velocity: Number.isInteger(velocity) ? (velocity as number) : 64,
          });
        });
      }
      tracks.push({
        id: typeof id === 'string' ? id : '',
        name: typeof name === 'string' ? name : '',
        program: Number.isInteger(program) ? (program as number) : 0,
        mode: mode === 'auto' ? 'auto' : 'manual',
        style: typeof style === 'string' ? style : '',
        volume: Number.isInteger(volume) ? (volume as number) : 100,
        pan: Number.isInteger(pan) ? (pan as number) : 64,
        events,
      });
    });
  }

  if (errors.length > 0) {
    return { ok: false, errors };
  }

  // 追加校验①：melody 逐音符音高
  melody.forEach((note, idx) => {
    try {
      pitchToMidi(note.pitch);
    } catch (exc) {
      errors.push(`melody[${idx}].pitch: ${(exc as Error).message}`);
    }
  });

  // 追加校验②③：轨 id 唯一性 + 轨 events 音高/鼓键名合法性
  const seenTrackIds = new Set<string>();
  tracks.forEach((track, trackIdx) => {
    if (seenTrackIds.has(track.id)) {
      errors.push(
        `accompaniment_tracks[${trackIdx}].id: 轨道 id 重复: ${JSON.stringify(track.id)}（同一歌谱内各轨 id 必须唯一）`,
      );
    }
    seenTrackIds.add(track.id);
    const isDrumTrack = track.program === -1;
    track.events.forEach((event, eventIdx) => {
      try {
        if (isDrumTrack) {
          resolveDrumKey(event.pitch);
        } else {
          pitchToMidi(event.pitch);
        }
      } catch (exc) {
        errors.push(`accompaniment_tracks[${trackIdx}].events[${eventIdx}].pitch: ${(exc as Error).message}`);
      }
    });
  });

  if (errors.length > 0) {
    return { ok: false, errors };
  }
  return {
    ok: true,
    errors: [],
    normalized: {
      title: title as string,
      bpm: bpm as number,
      time_signature: timeSignature as string,
      key: key as string,
      melody,
      chords,
      accompaniment_tracks: tracks,
    },
  };
}

// ---------------------------------------------------------------------------
// arrangeEvents（mock 级确定性编排：同输入同输出；真实实现为后端模块1）
// ---------------------------------------------------------------------------

class MockCommandError extends Error {
  constructor(
    readonly code: ErrorCode,
    message: string,
    readonly details?: Record<string, unknown>,
  ) {
    super(message);
    this.name = 'MockCommandError';
  }
}

const CHORD_ROOT_PATTERN = /^([A-Ga-g])([#b]?)(.*)$/;
const ALL_STYLE_IDS = INVENTORY.styles.map((style) => style.id).join('、');

/** 空 style 回退默认：program=-1 → rock_4beat；其余 → block_chords */
export function resolveStyleId(style: string, program: number): string {
  return style || (program === -1 ? 'rock_4beat' : 'block_chords');
}

function chordRoot(chord: string): { semitone: number; minor: boolean } {
  const match = CHORD_ROOT_PATTERN.exec(chord.trim());
  if (!match) {
    return { semitone: 0, minor: false }; // 无法解析回退 C 大三（mock 级简化）
  }
  let semitone = PITCH_BASE[match[1].toUpperCase()];
  if (match[2] === '#') semitone += 1;
  else if (match[2] === 'b') semitone -= 1;
  const rest = match[3] ?? '';
  return { semitone, minor: rest.startsWith('m') && !rest.startsWith('maj') };
}

function assertStyleUsable(styleId: string, program: number): void {
  const def = getStyle(styleId);
  if (!def) {
    throw new MockCommandError(
      'STYLE_UNKNOWN',
      `未定义的节奏型: ${JSON.stringify(styleId)}（可用: ${ALL_STYLE_IDS}）`,
      { style: styleId, available: INVENTORY.styles.map((style) => style.id) },
    );
  }
  const trackKind = program === -1 ? 'percussion' : 'melodic';
  if (def.applies_to !== trackKind) {
    throw new MockCommandError(
      'STYLE_UNKNOWN',
      `节奏型 ${JSON.stringify(styleId)} 仅适用于 ${def.applies_to} 轨，当前轨 program=${program}（${trackKind}）`,
      { style: styleId, applies_to: def.applies_to, program },
    );
  }
}

/**
 * 按和弦骨架 + 节奏型生成轨事件（mock 级确定性纯函数）。
 * 空和弦骨架 → 空事件列表（静音轨，不报错）。
 */
export function arrangeEvents(
  chords: ChordEntry[],
  style: string,
  program: number,
  _timeSignature: string = '4/4',
): TrackEvent[] {
  const styleId = resolveStyleId(style, program);
  assertStyleUsable(styleId, program);

  const events: TrackEvent[] = [];
  let offset = 0;
  for (const entry of chords) {
    const { semitone, minor } = chordRoot(entry.chord);
    const third = minor ? 3 : 4;
    if (styleId === 'block_chords') {
      for (const interval of [0, third, 7]) {
        events.push({ pitch: midiToPitch(48 + semitone + interval), beats: entry.beats, offset, velocity: 64 });
      }
    } else if (styleId === 'arpeggio') {
      const pattern = [0, third, 7, 12];
      const steps = Math.max(1, Math.round(entry.beats / 0.5));
      for (let i = 0; i < steps; i += 1) {
        events.push({
          pitch: midiToPitch(48 + semitone + pattern[i % pattern.length]),
          beats: 0.5,
          offset: offset + i * 0.5,
          velocity: 64,
        });
      }
    } else if (styleId === 'root_eighth') {
      const steps = Math.max(1, Math.round(entry.beats / 0.5));
      for (let i = 0; i < steps; i += 1) {
        events.push({ pitch: midiToPitch(36 + semitone), beats: 0.5, offset: offset + i * 0.5, velocity: 64 });
      }
    } else {
      // rock_4beat：底鼓 1/3 拍、军鼓 2/4 拍、闭镲八分
      const steps = Math.max(1, Math.round(entry.beats / 0.5));
      for (let i = 0; i < steps; i += 1) {
        const position = offset + i * 0.5;
        const phase = i % 8; // 4 拍 = 8 个八分
        events.push({ pitch: 'closed_hihat', beats: 0.5, offset: position, velocity: 64 });
        if (phase === 0 || phase === 4) {
          events.push({ pitch: 'kick', beats: 0.5, offset: position, velocity: 96 });
        }
        if (phase === 2 || phase === 6) {
          events.push({ pitch: 'snare', beats: 0.5, offset: position, velocity: 80 });
        }
      }
    }
    offset += entry.beats;
  }
  return events.sort((a, b) => a.offset - b.offset);
}

// ---------------------------------------------------------------------------
// 草稿注册表（命令执行器，20 命令唯一入口）
// ---------------------------------------------------------------------------

/** 内存注册表条目（undo/redo 栈为整谱快照，不落盘） */
export interface DraftEntry {
  draft_id: string;
  score: ScoreV2;
  version: number;
  undoStack: ScoreV2[];
  redoStack: ScoreV2[];
  updatedAt: string;
  /** 空白草稿占位标记：首个 melody add_note 替换占位符后清除 */
  placeholder: boolean;
}

export interface MockDraftBackendOptions {
  /** undo 栈深上限（配置契约 undo_stack_limit，默认 100） */
  undoStackLimit?: number;
}

function ok(draft: DraftEntry, result?: Record<string, unknown>): CommandResult {
  return {
    success: true,
    draft_id: draft.draft_id,
    version: draft.version,
    snapshot: clone(draft.score),
    changed_paths: ['$'], // mock 恒为全谱路径标记（契约允许首版返回 ["$"]）
    ...(result !== undefined ? { result } : {}),
  };
}

function err(code: ErrorCode, message: string, details?: Record<string, unknown>): CommandResult {
  return { success: false, error: { code, message, ...(details !== undefined ? { details } : {}) } };
}

function argsInvalid(message: string): CommandResult {
  return err('COMMAND_ARGS_INVALID', message);
}

function findTrack(score: ScoreV2, trackId: string): AccompanimentTrack {
  const hit = score.accompaniment_tracks.find((track) => track.id === trackId);
  if (!hit) {
    throw new MockCommandError(
      'TRACK_NOT_FOUND',
      `track 寻址失败: ${JSON.stringify(trackId)}（非 "melody" 且不在伴奏轨 id 集合内）`,
      { track: trackId },
    );
  }
  return hit;
}

function trackEnd(track: AccompanimentTrack): number {
  return track.events.reduce((end, event) => Math.max(end, event.offset + event.beats), 0);
}

export class MockDraftBackend {
  private readonly drafts = new Map<string, DraftEntry>();
  private counter = 0;
  private readonly undoLimit: number;

  constructor(options: MockDraftBackendOptions = {}) {
    this.undoLimit = options.undoStackLimit ?? 100;
  }

  /** 清空全部草稿（测试隔离用） */
  reset(): void {
    this.drafts.clear();
    this.counter = 0;
  }

  /** 草稿摘要列表（按 updated_at 倒序），对应 .pyi list_drafts / REST GET /drafts */
  listDrafts(): Array<{ draft_id: string; title: string; version: number; updated_at: string }> {
    return [...this.drafts.values()]
      .map((draft) => ({
        draft_id: draft.draft_id,
        title: draft.score.title,
        version: draft.version,
        updated_at: draft.updatedAt,
      }))
      .sort((a, b) => (a.updated_at < b.updated_at ? 1 : a.updated_at > b.updated_at ? -1 : 0));
  }

  /** 删除草稿（幂等，不存在返回 false），对应 .pyi delete_draft / REST DELETE /drafts/{id} */
  deleteDraft(draftId: string): boolean {
    return this.drafts.delete(draftId);
  }

  /** 以夹具为种子创建草稿（测试/开发便捷入口） */
  seedFromFixture(name: string): CommandResult {
    return this.execute({ command: 'create_draft', args: { score: getFixture(name) } });
  }

  /**
   * 命令执行器唯一入口（对应后端 draft_registry.execute_command）。
   * 原子性：args 校验 → 应用 → 整谱 validateScore → 入 undo 栈 → version+1；
   * 任一步失败整体回滚，草稿状态不变。
   */
  execute(request: CommandRequest): CommandResult {
    const command = String((request as { command?: unknown }).command ?? '');
    const args = ((request as { args?: unknown }).args ?? {}) as Record<string, unknown>;
    if (!(COMMAND_NAMES as readonly string[]).includes(command)) {
      return err('COMMAND_UNKNOWN', `command 不在枚举内: ${JSON.stringify(command)}`, {
        available: [...COMMAND_NAMES],
      });
    }
    if (command === 'create_draft') {
      return this.cmdCreateDraft(args);
    }
    const draftId = args.draft_id;
    if (typeof draftId !== 'string' || draftId.length < 1) {
      return argsInvalid('args.draft_id 必填（非空字符串）');
    }
    const draft = this.drafts.get(draftId);
    if (!draft) {
      return err('DRAFT_NOT_FOUND', `草稿不存在: ${draftId}`, { draft_id: draftId });
    }
    switch (command as Exclude<CommandName, 'create_draft'>) {
      case 'get_draft':
        return ok(draft);
      case 'add_note':
        return this.cmdAddNote(draft, args);
      case 'update_note':
        return this.cmdUpdateNote(draft, args);
      case 'move_note':
        return this.cmdMoveNote(draft, args);
      case 'delete_note':
        return this.cmdDeleteNote(draft, args);
      case 'set_lyric':
        return this.cmdSetLyric(draft, args);
      case 'add_chord':
        return this.cmdAddChord(draft, args);
      case 'update_chord':
        return this.cmdUpdateChord(draft, args);
      case 'delete_chord':
        return this.cmdDeleteChord(draft, args);
      case 'add_track':
        return this.cmdAddTrack(draft, args);
      case 'remove_track':
        return this.cmdRemoveTrack(draft, args);
      case 'set_track_instrument':
        return this.cmdSetTrackInstrument(draft, args);
      case 'set_track_mode':
        return this.cmdSetTrackMode(draft, args);
      case 'arrange_track':
        return this.cmdArrangeTrack(draft, args);
      case 'set_track_mix':
        return this.cmdSetTrackMix(draft, args);
      case 'undo':
        return this.cmdUndo(draft);
      case 'redo':
        return this.cmdRedo(draft);
      case 'validate_draft':
        return this.cmdValidateDraft(draft);
      case 'submit_draft':
        return this.cmdSubmitDraft(draft);
    }
  }

  // ------------------------------------------------------------------
  // 命令实现（私有）
  // ------------------------------------------------------------------

  private cmdCreateDraft(args: Record<string, unknown>): CommandResult {
    let scoreInput: Record<string, unknown>;
    let placeholder = false;
    if (args.score === undefined) {
      // 空白草稿：C4 全音符占位（首个 melody add_note 替换）
      placeholder = true;
      scoreInput = { title: '未命名', bpm: 120, melody: [{ pitch: 'C4', beats: 4, lyric: '' }] };
    } else {
      if (!isObj(args.score)) {
        return argsInvalid('args.score 必须是歌谱 JSON 对象');
      }
      scoreInput = args.score;
    }
    const outcome = validateScore(scoreInput);
    if (!outcome.ok || !outcome.normalized) {
      return err('SCORE_VALIDATION_FAILED', `歌谱校验失败: ${outcome.errors.join('；')}`, {
        errors: outcome.errors,
      });
    }
    this.counter += 1;
    const entry: DraftEntry = {
      draft_id: `draft_${this.counter}`,
      score: outcome.normalized,
      version: 0,
      undoStack: [],
      redoStack: [],
      updatedAt: nowIso(),
      placeholder,
    };
    this.drafts.set(entry.draft_id, entry);
    return ok(entry);
  }

  /**
   * 编辑命令公共流：克隆 → 变更 → 整谱校验 → 入 undo 栈 / 清 redo → version+1。
   * mutate 抛 MockCommandError 即业务失败（原子回滚）。
   */
  private applyEdit(
    draft: DraftEntry,
    mutate: (score: ScoreV2, draft: DraftEntry) => Record<string, unknown> | void,
  ): CommandResult {
    const before = clone(draft.score);
    const working = clone(draft.score);
    let resultExtra: Record<string, unknown> | void;
    try {
      resultExtra = mutate(working, draft);
    } catch (exc) {
      if (exc instanceof MockCommandError) {
        return err(exc.code, exc.message, exc.details);
      }
      throw exc;
    }
    const outcome = validateScore(working);
    if (!outcome.ok || !outcome.normalized) {
      return err('SCORE_VALIDATION_FAILED', `命令应用后整谱校验失败: ${outcome.errors.join('；')}`, {
        errors: outcome.errors,
      });
    }
    draft.undoStack.push(before);
    if (draft.undoStack.length > this.undoLimit) {
      draft.undoStack.shift();
    }
    draft.redoStack = [];
    draft.score = outcome.normalized;
    draft.version += 1;
    draft.updatedAt = nowIso();
    draft.placeholder = false;
    return ok(draft, resultExtra === undefined ? undefined : resultExtra);
  }

  private cmdAddNote(draft: DraftEntry, args: Record<string, unknown>): CommandResult {
    const trackRef = args.track;
    if (typeof trackRef !== 'string' || trackRef.length < 1) {
      return argsInvalid('args.track 必填（"melody" 或伴奏轨 id）');
    }
    if (typeof args.pitch !== 'string' || args.pitch.length < 1) {
      return argsInvalid('args.pitch 必填（科学音高记谱或 GM 鼓键名）');
    }
    if (!isNum(args.beats) || args.beats <= 0) {
      return argsInvalid('args.beats 必须是大于 0 的数字');
    }
    const pitch = args.pitch;
    const beats = args.beats;
    const lyric = typeof args.lyric === 'string' ? args.lyric : '';
    const offset = isNum(args.offset) && args.offset >= 0 ? args.offset : undefined;
    return this.applyEdit(draft, (score, current) => {
      if (trackRef === 'melody') {
        const note: MelodyNote = { pitch, beats, lyric };
        if (current.placeholder) {
          score.melody = [note]; // 空白草稿首个 add_note 替换占位符
        } else {
          score.melody.push(note);
        }
        return;
      }
      const track = findTrack(score, trackRef);
      const event: TrackEvent = { pitch, beats, offset: offset ?? trackEnd(track), velocity: 64 };
      track.events.push(event);
      track.events.sort((a, b) => a.offset - b.offset);
    });
  }

  private cmdUpdateNote(draft: DraftEntry, args: Record<string, unknown>): CommandResult {
    const trackRef = args.track;
    if (typeof trackRef !== 'string' || trackRef.length < 1) {
      return argsInvalid('args.track 必填');
    }
    if (!isNonNegativeInt(args.note_id)) {
      return argsInvalid('args.note_id 必须是 ≥0 的整数');
    }
    if (!isObj(args.patch) || Object.keys(args.patch).length < 1) {
      return argsInvalid('args.patch 至少包含一个字段');
    }
    const noteId = args.note_id;
    const patch = args.patch;
    return this.applyEdit(draft, (score) => {
      if (trackRef === 'melody') {
        if (noteId >= score.melody.length) {
          throw new MockCommandError('NOTE_NOT_FOUND', `melody 轨 note_id 越界: ${noteId}`, {
            track: trackRef,
            note_id: noteId,
          });
        }
        const note = score.melody[noteId];
        if (patch.pitch !== undefined) note.pitch = String(patch.pitch);
        if (patch.beats !== undefined) note.beats = Number(patch.beats);
        if (patch.lyric !== undefined) note.lyric = String(patch.lyric);
        return;
      }
      const track = findTrack(score, trackRef);
      if (noteId >= track.events.length) {
        throw new MockCommandError('NOTE_NOT_FOUND', `轨 ${trackRef} note_id 越界: ${noteId}`, {
          track: trackRef,
          note_id: noteId,
        });
      }
      const event = track.events[noteId];
      if (patch.pitch !== undefined) event.pitch = String(patch.pitch);
      if (patch.beats !== undefined) event.beats = Number(patch.beats);
      if (patch.offset !== undefined) event.offset = Number(patch.offset);
      if (patch.velocity !== undefined) event.velocity = Number(patch.velocity);
      track.events.sort((a, b) => a.offset - b.offset);
    });
  }

  private cmdMoveNote(draft: DraftEntry, args: Record<string, unknown>): CommandResult {
    const trackRef = args.track;
    if (typeof trackRef !== 'string' || trackRef.length < 1) {
      return argsInvalid('args.track 必填');
    }
    if (!isNonNegativeInt(args.note_id)) {
      return argsInvalid('args.note_id 必须是 ≥0 的整数');
    }
    if (!isNum(args.new_offset) || args.new_offset < 0) {
      return argsInvalid('args.new_offset 必须是 ≥0 的数字');
    }
    const noteId = args.note_id;
    const newOffset = args.new_offset;
    const newPitch = typeof args.new_pitch === 'string' ? args.new_pitch : undefined;
    return this.applyEdit(draft, (score) => {
      if (trackRef === 'melody') {
        if (noteId >= score.melody.length) {
          throw new MockCommandError('NOTE_NOT_FOUND', `melody 轨 note_id 越界: ${noteId}`, {
            track: trackRef,
            note_id: noteId,
          });
        }
        // melody 语义：移动到序号位置（重排，落点钳制在合法区间）
        const [moved] = score.melody.splice(noteId, 1);
        if (newPitch !== undefined) moved.pitch = newPitch;
        const target = Math.min(Math.floor(newOffset), score.melody.length);
        score.melody.splice(target, 0, moved);
        return;
      }
      const track = findTrack(score, trackRef);
      if (noteId >= track.events.length) {
        throw new MockCommandError('NOTE_NOT_FOUND', `轨 ${trackRef} note_id 越界: ${noteId}`, {
          track: trackRef,
          note_id: noteId,
        });
      }
      const event = track.events[noteId];
      event.offset = newOffset;
      if (newPitch !== undefined) event.pitch = newPitch;
      track.events.sort((a, b) => a.offset - b.offset);
    });
  }

  private cmdDeleteNote(draft: DraftEntry, args: Record<string, unknown>): CommandResult {
    const trackRef = args.track;
    if (typeof trackRef !== 'string' || trackRef.length < 1) {
      return argsInvalid('args.track 必填');
    }
    if (!isNonNegativeInt(args.note_id)) {
      return argsInvalid('args.note_id 必须是 ≥0 的整数');
    }
    const noteId = args.note_id;
    return this.applyEdit(draft, (score) => {
      // delete_note 幂等设计：note_id 越界为空操作成功（不报 NOTE_NOT_FOUND）
      if (trackRef === 'melody') {
        if (noteId < score.melody.length) {
          score.melody.splice(noteId, 1);
        }
        return;
      }
      const track = findTrack(score, trackRef);
      if (noteId < track.events.length) {
        track.events.splice(noteId, 1);
      }
    });
  }

  private cmdSetLyric(draft: DraftEntry, args: Record<string, unknown>): CommandResult {
    if (!isNonNegativeInt(args.note_id)) {
      return argsInvalid('args.note_id 必须是 ≥0 的整数（melody 轨内序号）');
    }
    if (typeof args.lyric !== 'string') {
      return argsInvalid('args.lyric 必须是字符串（允许空串=延音）');
    }
    const noteId = args.note_id;
    const lyric = args.lyric;
    return this.applyEdit(draft, (score) => {
      if (noteId >= score.melody.length) {
        throw new MockCommandError('NOTE_NOT_FOUND', `melody 轨 note_id 越界: ${noteId}`, {
          track: 'melody',
          note_id: noteId,
        });
      }
      score.melody[noteId].lyric = lyric;
    });
  }

  private cmdAddChord(draft: DraftEntry, args: Record<string, unknown>): CommandResult {
    if (typeof args.chord !== 'string' || args.chord.length < 1) {
      return argsInvalid('args.chord 必填（非空字符串）');
    }
    if (!isNum(args.beats) || args.beats <= 0) {
      return argsInvalid('args.beats 必须是大于 0 的数字');
    }
    const entry: ChordEntry = { chord: args.chord, beats: args.beats };
    const index = isNonNegativeInt(args.index) ? args.index : undefined;
    return this.applyEdit(draft, (score) => {
      const target = index === undefined ? score.chords.length : Math.min(index, score.chords.length);
      score.chords.splice(target, 0, entry);
    });
  }

  private cmdUpdateChord(draft: DraftEntry, args: Record<string, unknown>): CommandResult {
    if (!isNonNegativeInt(args.index)) {
      return argsInvalid('args.index 必须是 ≥0 的整数');
    }
    if (!isObj(args.patch) || Object.keys(args.patch).length < 1) {
      return argsInvalid('args.patch 至少包含一个字段（chord/beats）');
    }
    const index = args.index;
    const patch = args.patch;
    return this.applyEdit(draft, (score) => {
      if (index >= score.chords.length) {
        throw new MockCommandError('CHORD_NOT_FOUND', `和弦序号越界: ${index}`, { index });
      }
      const entry = score.chords[index];
      if (patch.chord !== undefined) entry.chord = String(patch.chord);
      if (patch.beats !== undefined) entry.beats = Number(patch.beats);
    });
  }

  private cmdDeleteChord(draft: DraftEntry, args: Record<string, unknown>): CommandResult {
    if (!isNonNegativeInt(args.index)) {
      return argsInvalid('args.index 必须是 ≥0 的整数');
    }
    const index = args.index;
    return this.applyEdit(draft, (score) => {
      if (index >= score.chords.length) {
        throw new MockCommandError('CHORD_NOT_FOUND', `和弦序号越界: ${index}`, { index });
      }
      score.chords.splice(index, 1);
    });
  }

  private cmdAddTrack(draft: DraftEntry, args: Record<string, unknown>): CommandResult {
    if (typeof args.name !== 'string' || args.name.length < 1) {
      return argsInvalid('args.name 必填（非空字符串）');
    }
    if (!Number.isInteger(args.program) || (args.program as number) < -1 || (args.program as number) > 127) {
      return argsInvalid('args.program 必须是 -1..127 的整数（-1=打击乐轨）');
    }
    if (args.mode !== 'auto' && args.mode !== 'manual') {
      return argsInvalid('args.mode 枚举 auto|manual');
    }
    const style = typeof args.style === 'string' ? args.style : '';
    const program = args.program as number;
    return this.applyEdit(draft, (score) => {
      if (style) {
        assertStyleUsable(style, program);
      }
      const used = new Set(score.accompaniment_tracks.map((track) => track.id));
      let serial = 0;
      while (used.has(`trk_${serial}`)) {
        serial += 1;
      }
      const trackId = `trk_${serial}`;
      score.accompaniment_tracks.push({
        id: trackId,
        name: args.name as string,
        program,
        mode: args.mode as 'auto' | 'manual',
        style,
        volume: 100,
        pan: 64,
        events: [],
      });
      return { track_id: trackId };
    });
  }

  private cmdRemoveTrack(draft: DraftEntry, args: Record<string, unknown>): CommandResult {
    if (typeof args.track_id !== 'string' || args.track_id.length < 1) {
      return argsInvalid('args.track_id 必填');
    }
    const trackId = args.track_id;
    return this.applyEdit(draft, (score) => {
      const index = score.accompaniment_tracks.findIndex((track) => track.id === trackId);
      if (index < 0) {
        throw new MockCommandError('TRACK_NOT_FOUND', `轨不存在: ${trackId}`, { track: trackId });
      }
      score.accompaniment_tracks.splice(index, 1);
    });
  }

  private cmdSetTrackInstrument(draft: DraftEntry, args: Record<string, unknown>): CommandResult {
    if (typeof args.track_id !== 'string' || args.track_id.length < 1) {
      return argsInvalid('args.track_id 必填');
    }
    if (!Number.isInteger(args.program) || (args.program as number) < -1 || (args.program as number) > 127) {
      return argsInvalid('args.program 必须是 -1..127 的整数');
    }
    const trackId = args.track_id;
    const program = args.program as number;
    return this.applyEdit(draft, (score) => {
      findTrack(score, trackId).program = program;
    });
  }

  private cmdSetTrackMode(draft: DraftEntry, args: Record<string, unknown>): CommandResult {
    if (typeof args.track_id !== 'string' || args.track_id.length < 1) {
      return argsInvalid('args.track_id 必填');
    }
    if (args.mode !== 'auto' && args.mode !== 'manual') {
      return argsInvalid('args.mode 枚举 auto|manual');
    }
    const trackId = args.track_id;
    const mode = args.mode;
    return this.applyEdit(draft, (score) => {
      const track = findTrack(score, trackId);
      if (mode === 'manual' && track.mode === 'auto' && track.events.length === 0) {
        // 切 manual 前物化：按 chords+style 生成可编辑音符（保留微调基线）
        track.events = arrangeEvents(score.chords, track.style, track.program, score.time_signature);
      }
      track.mode = mode;
    });
  }

  private cmdArrangeTrack(draft: DraftEntry, args: Record<string, unknown>): CommandResult {
    if (typeof args.track_id !== 'string' || args.track_id.length < 1) {
      return argsInvalid('args.track_id 必填');
    }
    const styleOverride = typeof args.style === 'string' && args.style ? args.style : undefined;
    const trackId = args.track_id;
    return this.applyEdit(draft, (score) => {
      const track = findTrack(score, trackId);
      if (track.mode !== 'auto') {
        throw new MockCommandError(
          'TRACK_MODE_INVALID',
          `arrange_track 仅 auto 轨可用（轨 ${trackId} 当前为 ${track.mode}）`,
          { track_id: trackId, mode: track.mode },
        );
      }
      if (styleOverride !== undefined) {
        assertStyleUsable(styleOverride, track.program);
        track.style = styleOverride;
      }
      const events = arrangeEvents(score.chords, track.style, track.program, score.time_signature);
      track.events = events; // 物化写入（预览=渲染，可再逐音符微调）
      return { events: clone(events) };
    });
  }

  private cmdSetTrackMix(draft: DraftEntry, args: Record<string, unknown>): CommandResult {
    if (typeof args.track_id !== 'string' || args.track_id.length < 1) {
      return argsInvalid('args.track_id 必填');
    }
    const hasVolume = args.volume !== undefined;
    const hasPan = args.pan !== undefined;
    if (!hasVolume && !hasPan) {
      return argsInvalid('args.volume / args.pan 至少提供一个');
    }
    if (hasVolume && (!Number.isInteger(args.volume) || (args.volume as number) < 0 || (args.volume as number) > 127)) {
      return argsInvalid('args.volume 必须是 0..127 的整数');
    }
    if (hasPan && (!Number.isInteger(args.pan) || (args.pan as number) < 0 || (args.pan as number) > 127)) {
      return argsInvalid('args.pan 必须是 0..127 的整数');
    }
    const trackId = args.track_id;
    return this.applyEdit(draft, (score) => {
      const track = findTrack(score, trackId);
      if (hasVolume) track.volume = args.volume as number;
      if (hasPan) track.pan = args.pan as number;
    });
  }

  private cmdUndo(draft: DraftEntry): CommandResult {
    const previous = draft.undoStack.pop();
    if (!previous) {
      return ok(draft); // 空栈：空操作成功，快照与 version 不变
    }
    draft.redoStack.push(clone(draft.score));
    draft.score = previous;
    draft.version += 1;
    draft.updatedAt = nowIso();
    return ok(draft);
  }

  private cmdRedo(draft: DraftEntry): CommandResult {
    const next = draft.redoStack.pop();
    if (!next) {
      return ok(draft); // 空栈：空操作成功，快照与 version 不变
    }
    draft.undoStack.push(clone(draft.score));
    draft.score = next;
    draft.version += 1;
    draft.updatedAt = nowIso();
    return ok(draft);
  }

  private cmdValidateDraft(draft: DraftEntry): CommandResult {
    const outcome = validateScore(draft.score);
    return ok(draft, { valid: outcome.ok, errors: outcome.errors });
  }

  private cmdSubmitDraft(draft: DraftEntry): CommandResult {
    const outcome = validateScore(draft.score);
    if (!outcome.ok || !outcome.normalized) {
      return err('SCORE_VALIDATION_FAILED', `提交前歌谱校验失败: ${outcome.errors.join('；')}`, {
        errors: outcome.errors,
      });
    }
    try {
      // 物化检查：auto 空 events 轨按 chords+style 可生成（不写回草稿）
      for (const track of outcome.normalized.accompaniment_tracks) {
        if (track.mode === 'auto' && track.events.length === 0) {
          arrangeEvents(outcome.normalized.chords, track.style, track.program, outcome.normalized.time_signature);
        }
      }
    } catch (exc) {
      if (exc instanceof MockCommandError) {
        return err('SUBMIT_FAILED', `提交合成流水线失败: ${exc.message}`, { reason: exc.message });
      }
      throw exc;
    }
    return ok(draft, {
      task_id: `mock_task_${draft.draft_id}_v${draft.version}`,
      song_id: `mock_song_${draft.draft_id}`,
      status: 'pending',
    });
  }
}

/** 工厂入口（与后端 get_song_pipeline 单例风格对齐的显式实例化） */
export function createMockDraftBackend(options: MockDraftBackendOptions = {}): MockDraftBackend {
  return new MockDraftBackend(options);
}
