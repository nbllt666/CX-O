/**
 * dispatch.ts — 模块7 命令分发层（merged.md §6 冻结）
 *
 * 职责（spec 行为规范 §3-5）：
 *  1. 统一编辑入口：所有编辑动作经 dispatch(command, args) → backend.execute → 服务端真源
 *  2. version 防乱序：记录本地 lastVersion，响应 version ≤ lastVersion 时丢弃（返回 null）
 *  3. draft_id 自动注入：调用方无需手传 draft_id（create_draft/get_draft 除外，走 backend 直调）
 *  4. 错误处理：success=false 时返回 CommandResult（含 error），调用方据 describeError 显示可读提示
 *  5. 防抖：连续微调（如音量/声像滑杆）经 createDebouncedDispatch 合并为最终一次提交
 *
 * 后端真源（merged.md §0.3 裁决 B）：
 *  - REST 端点（模块4 已完成）：POST /api/music/drafts、GET /api/music/drafts/{id}、
 *    DELETE /api/music/drafts/{id}、POST /api/music/drafts/{id}/commands
 *  - 前端为受控渲染 + 命令产生器，绝不直接改 score（AGENTS.md §3.2 binding_rules）
 *
 * 测试支点：createSyncBackendAdapter 包装 s0202 MockDraftBackend，使组件测试不经 HTTP
 * 即可验证交互→命令映射与 version 防乱序（jsdom 下 fetch mock 仅用于 REST 路径冒烟）。
 */
import { getVoiceWorkstationUrl } from '@/api/client';
import type {
  CommandError,
  CommandName,
  CommandRequest,
  CommandResult,
  ErrorCode,
  ScoreV2,
} from './staff/types';

// ---------------------------------------------------------------------------
// 草稿后端接口（统一 REST / Mock）
// ---------------------------------------------------------------------------

/** 草稿摘要（REST GET /drafts 与 Mock listDrafts 同构） */
export interface DraftSummary {
  draft_id: string;
  title: string;
  version: number;
  updated_at: string;
}

/**
 * 草稿后端接口：CompositionPanel 经此与服务端交互。
 * - 生产实现：createRestBackend（fetch → /api/music/drafts…）
 * - 测试实现：createSyncBackendAdapter(MockDraftBackend)
 *
 * execute 对应 POST /drafts/{id}/commands（命令执行器唯一入口）；
 * createDraft / getDraft / deleteDraft / listDrafts 对应 /drafts CRUD。
 */
export interface DraftBackend {
  execute(request: CommandRequest): Promise<CommandResult>;
  createDraft(score?: Record<string, unknown>): Promise<CommandResult>;
  getDraft(draftId: string): Promise<CommandResult>;
  deleteDraft(draftId: string): Promise<{ success: boolean }>;
  listDrafts(): Promise<DraftSummary[]>;
}

// ---------------------------------------------------------------------------
// VersionGuard：防乱序纯类（可独立单测）
// ---------------------------------------------------------------------------

/**
 * version 防乱序守卫。
 *
 * 语义（command-protocol.schema.json x-notes §version）：
 *  - 每草稿单调递增整数，每次成功编辑命令 +1（get_draft/validate_draft 不增）
 *  - 前端据此丢弃过期响应；服务端不拒绝旧 version 请求（单时钟天然免疫覆盖）
 *
 * 接受规则：version > lastVersion 才接受；version === undefined 视为无 version 字段
 * （如 get_draft 响应），不丢弃。
 */
export class VersionGuard {
  private lastVersion = -1;

  reset(version = -1): void {
    this.lastVersion = version;
  }

  shouldAccept(version: number | undefined): boolean {
    if (version === undefined) return true;
    return version > this.lastVersion;
  }

  update(version: number): void {
    if (version > this.lastVersion) this.lastVersion = version;
  }

  get current(): number {
    return this.lastVersion;
  }
}

// ---------------------------------------------------------------------------
// 错误码 → 可读文案（command-protocol x-error-codes 10 枚举）
// ---------------------------------------------------------------------------

export const ERROR_MESSAGES: Record<ErrorCode, string> = {
  SCORE_VALIDATION_FAILED: '歌谱校验失败，请检查字段是否合规',
  DRAFT_NOT_FOUND: '草稿不存在，可能已被清理或删除',
  COMMAND_UNKNOWN: '未知命令，请刷新页面后重试',
  COMMAND_ARGS_INVALID: '命令参数无效，请检查输入',
  TRACK_NOT_FOUND: '轨道不存在，可能已被删除',
  NOTE_NOT_FOUND: '音符不存在，可能已被删除',
  CHORD_NOT_FOUND: '和弦不存在，可能已被删除',
  STYLE_UNKNOWN: '未知的节奏型，或节奏型与轨类型不匹配',
  TRACK_MODE_INVALID: '轨道模式不匹配（如对 manual 轨调用编排）',
  SUBMIT_FAILED: '提交合成失败，请稍后重试',
};

/**
 * 把 CommandError 转为用户可读文案。
 * - 命中 10 错误码枚举 → 对应中文文案
 * - 未命中（如本地 NETWORK_ERROR）→ 通用兜底
 * - 附 details 摘要（如 NOTE_NOT_FOUND 的 track+note_id）
 */
export function describeError(error: CommandError): string {
  const code = error.code as ErrorCode;
  const base = ERROR_MESSAGES[code] ?? `操作失败（${error.code}）`;
  if (error.details && Object.keys(error.details).length > 0) {
    const det = Object.entries(error.details)
      .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
      .join('；');
    return `${base}（${det}）`;
  }
  return base;
}

// ---------------------------------------------------------------------------
// dispatch 工厂
// ---------------------------------------------------------------------------

/**
 * 编辑命令分发函数。
 *
 * @returns
 *  - CommandResult：命令执行结果（success=true 或 false）；调用方据此更新 score/version 或显示错误
 *  - null：响应被 version 守卫丢弃（过期响应，调用方应忽略）
 *
 * draft_id 自动注入：args 内未传 draft_id 时，从 getDraftId() 取当前草稿 id 补入。
 * 网络错误：合成 {success:false, error:{code:'NETWORK_ERROR', message}} 返回（不抛）。
 *
 * 类型安全：调用方构造 args 时建议用 `Omit<CommandArgsMap[command], 'draft_id'>`
 * 保证字段齐全（如 `const args: Omit<AddNoteArgs,'draft_id'> = {track,pitch,beats}`）。
 */
export type Dispatch = (
  command: CommandName,
  args: Record<string, unknown>,
) => Promise<CommandResult | null>;

export interface DispatchHandle {
  dispatch: Dispatch;
  /** 初始化或重置 version 基线（createDraft/getDraft 载入后调用，避免后续编辑被误丢弃） */
  setVersion(version: number): void;
  /** 当前 version 基线（受控渲染时可读取展示） */
  getVersion(): number;
}

export interface DispatchOptions {
  backend: DraftBackend;
  getDraftId: () => string;
}

export function createDispatch(opts: DispatchOptions): DispatchHandle {
  const guard = new VersionGuard();

  const dispatch: Dispatch = async (command, args) => {
    // draft_id 自动注入（create_draft/get_draft 不经 dispatch，此处 args 必有 draft_id 字段需求）
    const rawArgs = args;
    const fullArgs: Record<string, unknown> =
      rawArgs.draft_id === undefined ? { ...rawArgs, draft_id: opts.getDraftId() } : { ...rawArgs };
    const request = { command, args: fullArgs } as CommandRequest;

    let result: CommandResult;
    try {
      result = await opts.backend.execute(request);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      return {
        success: false,
        error: { code: 'NETWORK_ERROR', message: `网络错误：${msg}` },
      };
    }

    if (result.success) {
      // version 防乱序：过期响应丢弃
      if (result.version !== undefined && !guard.shouldAccept(result.version)) {
        return null;
      }
      if (result.version !== undefined) guard.update(result.version);
    }
    return result;
  };

  return {
    dispatch,
    setVersion: (version: number) => guard.reset(version),
    getVersion: () => guard.current,
  };
}

// ---------------------------------------------------------------------------
// 防抖 dispatch（连续微调合并：set_track_mix 滑杆 300ms）
// ---------------------------------------------------------------------------

/**
 * 按命令+track_id 维度防抖的 dispatch 包装。
 *
 * 行为：同一 key（`${command}:${track_id}`）的连续调用，仅最后一次真正下发，
 * 前面的 Promise resolve(null)（表示被合并丢弃，调用方忽略即可）。
 * 不同 key 互不干扰。用于音量/声像滑杆连续微调，合并为一次 set_track_mix。
 */
export function createDebouncedDispatch(dispatch: Dispatch, delay = 300): Dispatch {
  const timers = new Map<string, ReturnType<typeof setTimeout>>();
  const pending = new Map<
    string,
    { args: Record<string, unknown>; resolve: (r: CommandResult | null) => void; reject: (e: unknown) => void }
  >();

  return ((command: CommandName, args: Record<string, unknown>) => {
    const key = `${command}:${(args.track_id as string | undefined) ?? ''}`;
    return new Promise<CommandResult | null>((resolve, reject) => {
      // 清旧 timer：重新计时，确保防抖延迟从末次调用算起（而非首次）
      const prevTimer = timers.get(key);
      if (prevTimer) clearTimeout(prevTimer);
      // 旧 pending resolve(null)（被合并丢弃，调用方忽略）
      const prev = pending.get(key);
      if (prev) prev.resolve(null);
      pending.set(key, { args, resolve, reject });

      const timer = setTimeout(async () => {
        const cur = pending.get(key);
        pending.delete(key);
        timers.delete(key);
        if (!cur) return;
        try {
          const r = await dispatch(command, cur.args);
          cur.resolve(r);
        } catch (e) {
          cur.reject(e);
        }
      }, delay);
      timers.set(key, timer);
    });
  }) as Dispatch;
}

// ---------------------------------------------------------------------------
// REST backend（生产用，fetch → /api/music/drafts…）
// ---------------------------------------------------------------------------

/**
 * 创建 REST 草稿后端。
 *
 * @param getBaseUrl 返回 VoiceWorkStation base URL（dev=/voice-station proxy，prod=http://127.0.0.1:8200）
 *
 * 端点映射（模块4 已完成）：
 *  - createDraft → POST   /api/music/drafts               body {score?}
 *  - getDraft    → GET    /api/music/drafts/{id}
 *  - deleteDraft → DELETE /api/music/drafts/{id}
 *  - listDrafts  → GET    /api/music/drafts
 *  - execute     → POST   /api/music/drafts/{id}/commands body {command, args}
 */
export function createRestBackend(
  getBaseUrl: () => string = getVoiceWorkstationUrl,
): DraftBackend {
  const base = () => `${getBaseUrl().replace(/\/$/, '')}/api/music`;

  async function postJson(path: string, body: unknown): Promise<CommandResult> {
    const res = await fetch(`${base()}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    return (await res.json()) as CommandResult;
  }

  async function getJson<T>(path: string): Promise<T> {
    const res = await fetch(`${base()}${path}`, { method: 'GET' });
    return (await res.json()) as T;
  }

  async function deleteJson<T>(path: string): Promise<T> {
    const res = await fetch(`${base()}${path}`, { method: 'DELETE' });
    return (await res.json()) as T;
  }

  return {
    execute: (req) => {
      const draftId = (req.args as { draft_id?: string }).draft_id;
      if (!draftId) {
        return Promise.reject(
          new Error('dispatch.execute: args.draft_id 缺失（REST 路径需要 draft_id 寻址）'),
        );
      }
      return postJson(
        `/drafts/${encodeURIComponent(draftId)}/commands`,
        { command: req.command, args: req.args },
      );
    },
    createDraft: (score) => postJson('/drafts', score ? { score } : {}),
    getDraft: (id) => getJson<CommandResult>(`/drafts/${encodeURIComponent(id)}`),
    deleteDraft: async (id) => ({
      success: (await deleteJson<{ success: boolean }>(`/drafts/${encodeURIComponent(id)}`)).success,
    }),
    listDrafts: () => getJson<DraftSummary[]>('/drafts'),
  };
}

// ---------------------------------------------------------------------------
// Mock backend 适配器（测试用，包装 s0202 MockDraftBackend）
// ---------------------------------------------------------------------------

/**
 * 把同步命令执行器（如 s0202 MockDraftBackend）适配为异步 DraftBackend。
 * 测试中注入此适配器，组件不经 HTTP 即可验证交互→命令映射。
 *
 * createDraft 经 execute({command:'create_draft'})，与 MockDraftBackend.seedFromFixture 等价；
 * getDraft 经 execute({command:'get_draft'})；deleteDraft/listDrafts 直调 sync 方法。
 */
export function createSyncBackendAdapter(
  sync: {
    execute(request: CommandRequest): CommandResult;
    listDrafts(): DraftSummary[];
    deleteDraft(id: string): boolean;
  },
): DraftBackend {
  return {
    execute: (req) => Promise.resolve(sync.execute(req)),
    createDraft: (score) =>
      Promise.resolve(
        sync.execute({ command: 'create_draft', args: score ? { score } : {} }),
      ),
    getDraft: (id) =>
      Promise.resolve(sync.execute({ command: 'get_draft', args: { draft_id: id } })),
    deleteDraft: (id) => Promise.resolve({ success: sync.deleteDraft(id) }),
    listDrafts: () => Promise.resolve(sync.listDrafts()),
  };
}

// ---------------------------------------------------------------------------
// 快照提取辅助
// ---------------------------------------------------------------------------

/** 从 CommandResult 提取服务端最新快照（success=true 时存在） */
export function extractSnapshot(result: CommandResult): ScoreV2 | null {
  return result.snapshot ?? null;
}
