// ============================================================================
// types.ts — 作曲区契约 TS 类型（歌谱 v2 / 命令协议 / 音乐枚举清单）
// 本文件由 scripts/gen_music_types.py 自动生成（s0202 前后端同源），禁止手改。
// 数据源：
//   - score-v2.schema.json        x-version: 2.0.0
//   - command-protocol.schema.json x-version: 1.0.0
//   - music-inventory.schema.json  x-version: 1.0.0
// 生成时间：2026-07-24T22:45:19+08:00
// ============================================================================


// ---------------------------------------------------------------------------
// 歌谱 v2（ScoreV2 = 经 validate_score 规范化后的快照形状：带 default 字段必然存在）
// ---------------------------------------------------------------------------

export interface MelodyNote {
  /** 科学音高记谱，如 C4、A#3、Bb5（C4=60） */
  pitch: string;
  /** 节拍数（四分音符=1 拍），必须大于 0 */
  beats: number;
  /** 逐字歌词，空串表示延音 */
  lyric: string;
}
export interface ChordEntry {
  /** 和弦标记，如 C、G7、Am */
  chord: string;
  /** 持续节拍数，必须大于 0 */
  beats: number;
}
export interface TrackEvent {
  /** 音高。program≥0 时为科学音高记谱（如 C2、G2）；program=-1（打击乐轨）时为 GM 鼓键名（如 kick、snare，枚举别名见 music-inventory.schema.json，底层映射 MIDI 音号） */
  pitch: string;
  /** 持续节拍数（四分音符=1 拍），必须大于 0 */
  beats: number;
  /** 相对轨道起点的拍数位置（显式定位，允许休止与对位空隙） */
  offset: number;
  /** 力度（MIDI velocity 1–127） */
  velocity: number;
}
export interface AccompanimentTrack {
  /** 轨道稳定标识，草稿内唯一，小写字母/数字/下划线；编辑命令按 id 寻址 */
  id: string;
  /** 轨道显示名（谱表左侧标签） */
  name: string;
  /** General MIDI 音色号 0–127；特殊值 -1 表示打击乐轨（渲染时全部事件强制走通道 9，不写 program change，events.pitch 使用 GM 鼓键名，鼓键名枚举见 music-inventory.schema.json） */
  program: number;
  /** auto=按和弦骨架+节奏型自动生成音符（生成结果可物化后逐音符微调）；manual=逐音符编辑 */
  mode: "auto" | "manual";
  /** 编排节奏型 id，仅 auto 模式有效（manual 模式忽略）。当前枚举：block_chords（柱式和弦）/arpeggio（八分分解）/root_eighth（根音八分）/rock_4beat（鼓组四拍型），枚举真源见 music-inventory.schema.json，可扩展（扩展属数据层变更，不改本 schema）。auto 模式下 style 为空串时回退默认：program=-1 → rock_4beat，其余 → block_chords */
  style: string;
  /** 轨道音量，GM 原生量纲 0–127，渲染时直写 MIDI CC7 */
  volume: number;
  /** 轨道声像，GM 原生量纲 0–127（64=中央），渲染时直写 MIDI CC10 */
  pan: number;
  /** 轨道音符事件列表，按 offset 升序排列，重叠事件即同度和音。auto 模式下为空数组（合成/编排时由 arranger 按 chords+style 生成；arrange_track 命令可将生成结果物化写入本字段以便逐音符微调） */
  events: TrackEvent[];
}
export interface ScoreV2 {
  /** 歌名 */
  title: string;
  /** 每分钟拍数，必须大于 0 */
  bpm: number;
  /** 拍号，如 4/4、3/4、6/8 */
  time_signature: string;
  /** 调号，如 C、G、Am */
  key: string;
  /** 主旋律音符序列（至少一个音符）。旋律轨为逐字歌词轨，事件按顺序累加定位（无 offset 字段），与伴奏轨事件的显式 offset 定位不同 */
  melody: MelodyNote[];
  /** 和弦骨架（和声进行），允许为空数组。用途：①auto 模式伴奏轨的生成源；②谱面上排的和弦标记 */
  chords: ChordEntry[];
  /** 多乐器伴奏轨列表，允许为空数组（纯主旋律）。同一歌谱内各轨 id 必须唯一（JSON Schema 无法表达数组内字段唯一性，由 validate_score 在结构校验后追加唯一性检查） */
  accompaniment_tracks: AccompanimentTrack[];
}

// ---------------------------------------------------------------------------
// 音乐枚举清单（GM 128 音色 / 节奏型 / 鼓键映射）
// ---------------------------------------------------------------------------

export interface Instrument {
  /** GM 音色号 */
  program: number;
  /** 音色显示名（可含英文原名，如 大钢琴 Acoustic Grand Piano） */
  name: string;
}
export interface InstrumentGroup {
  /** 分组标识（如 piano、bass） */
  group_id: string;
  /** 分组显示名（如 钢琴、贝斯） */
  name: string;
  /** 本组 program 区间 [起, 止]（含端点），跨度恒为 8 */
  program_range: [number, number];
  /** 组内 8 个音色，数组顺序与 program 号严格对应（instruments[i].program = program_range[0] + i） */
  instruments: Instrument[];
}
export interface StyleDef {
  /** 节奏型 id（score v2 accompaniment_tracks[].style 的合法取值） */
  id: string;
  /** 节奏型显示名（如 柱式和弦、八分分解） */
  name: string;
  /** 适用轨类型：melodic=旋律类乐器轨（program 0–127）；percussion=打击乐轨（program=-1）。arranger 按此匹配：program=-1 的 auto 轨仅可使用 percussion 型，反之仅可使用 melodic 型 */
  applies_to: "melodic" | "percussion";
  /** 节奏型行为说明（供 agent/用户选择时参考） */
  description?: string;
}
export interface DrumKey {
  /** 鼓键名（打击乐轨 events.pitch 的合法取值） */
  key: string;
  /** GM 鼓键 MIDI 音号（标准打击乐范围 35–81） */
  midi: number;
  /** 鼓件显示名（如 底鼓、军鼓） */
  name: string;
}
/** 本 schema 约束「枚举清单数据」的形状（前后端同源真源：music_list_instruments 工具的返回形状、前端 GM 选择器数据源、arranger 节奏型输入校验、打击乐轨鼓键名解析均以此为准）。清单内容扩展（新增节奏型/鼓键别名）属数据层变更，不修改本 schema。 */
export interface MusicInventory {
  /** GM 128 音色按标准 16 组分组（每组 8 个音色，组序与 program 区间固定对应）：piano(0–7)/chromatic_percussion(8–15)/organ(16–23)/guitar(24–31)/bass(32–39)/strings(40–47)/ensemble(48–55)/brass(56–63)/reed(64–71)/pipe(72–79)/synth_lead(80–87)/synth_pad(88–95)/synth_effects(96–103)/ethnic(104–111)/percussive(112–119)/sound_effects(120–127)。打击乐轨不属本清单（由 score v2 的 program=-1 特殊值表达） */
  instrument_groups: InstrumentGroup[];
  /** 编排节奏型枚举（arranger 输入校验与 auto 轨 style 字段的取值真源）。初始枚举：block_chords/arpeggio/root_eighth（applies_to=melodic）、rock_4beat（applies_to=percussion）；新增节奏型向本数组追加即可 */
  styles: StyleDef[];
  /** GM 鼓键名 → MIDI 音号映射（打击乐轨 events.pitch 的合法取值别名）。初始最小集：kick=36/snare=38/closed_hihat=42/open_hihat=46/crash=49/ride=51/tom_high=50/tom_mid=47/tom_low=45/clap=39；可扩展 */
  drum_keys: DrumKey[];
}

// ---------------------------------------------------------------------------
// 歌谱编辑命令协议（20 命令人机同构）
// ---------------------------------------------------------------------------

/** 命令名枚举（20 命令，schema properties.command.enum 原样） */
export const COMMAND_NAMES = [
  "create_draft",
  "get_draft",
  "add_note",
  "update_note",
  "move_note",
  "delete_note",
  "set_lyric",
  "add_chord",
  "update_chord",
  "delete_chord",
  "add_track",
  "remove_track",
  "set_track_instrument",
  "set_track_mode",
  "arrange_track",
  "set_track_mix",
  "undo",
  "redo",
  "validate_draft",
  "submit_draft"
] as const;

export type CommandName = (typeof COMMAND_NAMES)[number];

/** 错误码枚举（schema x-error-codes 原样） */
export const ERROR_CODES = [
  "SCORE_VALIDATION_FAILED",
  "DRAFT_NOT_FOUND",
  "COMMAND_UNKNOWN",
  "COMMAND_ARGS_INVALID",
  "TRACK_NOT_FOUND",
  "NOTE_NOT_FOUND",
  "CHORD_NOT_FOUND",
  "STYLE_UNKNOWN",
  "TRACK_MODE_INVALID",
  "SUBMIT_FAILED"
] as const;

export type ErrorCode = (typeof ERROR_CODES)[number];

export interface CreateDraftArgs {
  /** 初始歌谱（v1 或 v2，v1 自动迁移）；缺省创建空白草稿（title 默认「未命名」、bpm 默认 120、melody 缺省一个 C4 全音符占位——空白草稿在首个 add_note 时替换占位） */
  score?: Record<string, unknown>;
}
export interface GetDraftArgs {
  draft_id: string;
}
export interface AddNoteArgs {
  draft_id: string;
  track: string;
  pitch: string;
  beats: number;
  /** 仅伴奏轨有效：插入位置（缺省=追加到轨尾，取当前最大 offset+beats 处）。melody 轨忽略本字段（顺序累加定位，追加到末尾） */
  offset?: number;
  /** 仅 melody 轨有效：逐字歌词 */
  lyric?: string;
}
export interface UpdateNotePatch {
  pitch?: string;
  beats?: number;
  /** 仅伴奏轨有效 */
  offset?: number;
  /** 仅 melody 轨有效 */
  lyric?: string;
  /** 仅伴奏轨有效 */
  velocity?: number;
}
export interface UpdateNoteArgs {
  draft_id: string;
  track: string;
  note_id: number;
  patch: UpdateNotePatch;
}
export interface MoveNoteArgs {
  draft_id: string;
  track: string;
  note_id: number;
  /** 拖拽落点位置。melody 轨语义：移动到序号位置（重排）；伴奏轨语义：设置 offset */
  new_offset: number;
  /** 可选：同时改变音高（垂直拖拽） */
  new_pitch?: string;
}
export interface DeleteNoteArgs {
  draft_id: string;
  track: string;
  note_id: number;
}
export interface SetLyricArgs {
  draft_id: string;
  /** melody 轨内序号 */
  note_id: number;
  /** 行内歌词编辑结果（允许空串=延音） */
  lyric: string;
}
export interface AddChordArgs {
  draft_id: string;
  chord: string;
  beats: number;
  /** 插入位置（缺省=追加到和弦骨架末尾） */
  index?: number;
}
export interface UpdateChordPatch {
  chord?: string;
  beats?: number;
}
export interface UpdateChordArgs {
  draft_id: string;
  /** 和弦数组序号 */
  index: number;
  patch: UpdateChordPatch;
}
export interface DeleteChordArgs {
  draft_id: string;
  index: number;
}
export interface AddTrackArgs {
  draft_id: string;
  name: string;
  /** -1=打击乐轨 */
  program: number;
  mode: "auto" | "manual";
  /** auto 模式节奏型（空串回退默认，规则同 score v2） */
  style?: string;
}
export interface RemoveTrackArgs {
  draft_id: string;
  track_id: string;
}
export interface SetTrackInstrumentArgs {
  draft_id: string;
  track_id: string;
  program: number;
}
export interface SetTrackModeArgs {
  draft_id: string;
  track_id: string;
  /** 切 manual 时：若轨为 auto 且 events 为空，先按 chords+style 物化生成结果再切换（保留可编辑音符）；切 auto 时：保留 events 作为微调基线，style 不变 */
  mode: "auto" | "manual";
}
export interface ArrangeTrackArgs {
  draft_id: string;
  track_id: string;
  /** 可选：本次编排使用的节奏型（同时更新轨 style 字段）；缺省用轨当前 style（含空串回退规则）。同输入同输出（确定性生成，幂等） */
  style?: string;
}
export interface SetTrackMixArgs {
  draft_id: string;
  track_id: string;
  volume?: number;
  pan?: number;
}
export interface UndoArgs {
  draft_id: string;
}
export interface RedoArgs {
  draft_id: string;
}
export interface ValidateDraftArgs {
  draft_id: string;
}
export interface SubmitDraftArgs {
  draft_id: string;
  /** SVC 模型路径；空串=不变声 */
  svc_model?: string;
  speaker_id?: number;
  /** SVC 变调（半音数，可为负） */
  transpose?: number;
  /** 缺省=配置契约默认值 */
  vocal_gain?: number;
  /** 缺省=配置契约默认值 */
  accompaniment_gain?: number;
}
/** 失败时返回（success=false），草稿状态不变（命令原子性） */
export interface CommandError {
  /** x-error-codes 枚举值 */
  code: string;
  /** 可读错误说明 */
  message: string;
  /** 错误码对应 payload */
  details?: Record<string, unknown>;
}
export interface CommandResult {
  success: boolean;
  /** 成功时返回 */
  draft_id?: string;
  /** 成功时返回：草稿当前版本号 */
  version?: number;
  /** 成功时返回：当前歌谱 v2 完整快照（形状见 score-v2.schema.json） */
  snapshot?: ScoreV2;
  /** 成功时返回：本次命令变更的 JSON 路径列表（如 ["accompaniment_tracks[1].events[3]"]），供前端增量重渲染；首版实现允许返回全谱路径标记 ["$"] */
  changed_paths?: string[];
  /** 特定命令的附加返回：add_track→{track_id}；arrange_track→{events}；validate_draft→{valid, errors}；submit_draft→{task_id, song_id, status} */
  result?: Record<string, unknown>;
  /** 失败时返回（success=false），草稿状态不变（命令原子性） */
  error?: CommandError;
}
/** 草稿落盘文件形状（workspace/music/drafts/{draft_id}/draft.json，原子写：临时文件+rename）。undo/redo 栈不落盘 */
export interface DraftFile {
  draft_id: string;
  /** 歌谱 v2 完整快照（形状见 score-v2.schema.json） */
  score: ScoreV2;
  version: number;
  /** ISO 8601 时间戳 */
  updated_at: string;
}

/** 命令名 → args 类型映射 */
export interface CommandArgsMap {
  create_draft: CreateDraftArgs;
  get_draft: GetDraftArgs;
  add_note: AddNoteArgs;
  update_note: UpdateNoteArgs;
  move_note: MoveNoteArgs;
  delete_note: DeleteNoteArgs;
  set_lyric: SetLyricArgs;
  add_chord: AddChordArgs;
  update_chord: UpdateChordArgs;
  delete_chord: DeleteChordArgs;
  add_track: AddTrackArgs;
  remove_track: RemoveTrackArgs;
  set_track_instrument: SetTrackInstrumentArgs;
  set_track_mode: SetTrackModeArgs;
  arrange_track: ArrangeTrackArgs;
  set_track_mix: SetTrackMixArgs;
  undo: UndoArgs;
  redo: RedoArgs;
  validate_draft: ValidateDraftArgs;
  submit_draft: SubmitDraftArgs;
}

/** 命令请求（可判别联合：command 与 args 形状一一对应） */
export type CommandRequest = {
  [K in CommandName]: { command: K; args: CommandArgsMap[K] };
}[CommandName];