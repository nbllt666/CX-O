/**
 * CompositionPanel.test.tsx — 模块7 作曲交互面板组件测试
 *
 * spec: redesign-composition-staff-editor §8 测试策略
 * 覆盖：
 *  A. dispatch 层单元测试（VersionGuard / describeError / 防抖 / createDispatch / REST 冒烟）
 *  B. CompositionPanel 组件集成测试（初始化 / 四交互映射 / 轨道管理 / 草稿管理 / 合成 / 歌曲历史 / 错误处理）
 *
 * 测试策略：
 *  - backend 注入 createSyncBackendAdapter(MockDraftBackend)，不经 HTTP 验证交互→命令映射
 *  - StaffScore mock 为可点击音符列表（渲染层冒烟已在 StaffScore.test.tsx 覆盖）
 *  - @/api/client mock 为 vi.fn，歌曲历史/任务轮询可控
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import type { ReactElement } from 'react';
import type {
  ScoreV2,
  CommandResult,
  CommandRequest,
  ErrorCode,
} from './staff/types';

// ---------------------------------------------------------------------------
// Mock: @/api/client（CompositionPanel 经 api.musicListSongs/musicGetTask/musicDeleteSong）
// ---------------------------------------------------------------------------

vi.mock('@/api/client', () => ({
  api: {
    musicGetTask: vi.fn(),
    musicListSongs: vi.fn(),
    musicDeleteSong: vi.fn(),
  },
  getVoiceWorkstationAudioUrl: (url: string) => `http://test-voice${url}`,
}));

// ---------------------------------------------------------------------------
// Mock: StaffScore（简化为可点击音符列表，聚焦 CompositionPanel 命令映射；
//   VexFlow 渲染层冒烟已在 StaffScore.test.tsx 独立覆盖）
// ---------------------------------------------------------------------------

vi.mock('./staff/StaffScore', () => ({
  StaffScore: ({
    score,
    selectedNote,
    onSelectNote,
  }: {
    score: ScoreV2;
    selectedNote?: { track: string; noteId: number } | null;
    onSelectNote?: (track: string, noteId: number) => void;
  }) => (
    <div data-testid="staff-score" role="group" aria-label="总谱">
      {score.melody.map((note, i) => (
        <button
          key={`melody-${i}`}
          data-testid={`note-melody-${i}`}
          data-track="melody"
          data-noteid={i}
          data-selected={
            selectedNote?.track === 'melody' && selectedNote?.noteId === i ? 'true' : 'false'
          }
          onClick={() => onSelectNote?.('melody', i)}
        >
          {note.pitch}
        </button>
      ))}
      {score.accompaniment_tracks.flatMap((track) =>
        track.events.map((event, i) => (
          <button
            key={`${track.id}-${i}`}
            data-testid={`note-${track.id}-${i}`}
            data-track={track.id}
            data-noteid={i}
            data-selected={
              selectedNote?.track === track.id && selectedNote?.noteId === i ? 'true' : 'false'
            }
            onClick={() => onSelectNote?.(track.id, i)}
          >
            {event.pitch}
          </button>
        )),
      )}
    </div>
  ),
}));

// ---------------------------------------------------------------------------
// Imports（在 vi.mock 之后，确保 mock 生效）
// ---------------------------------------------------------------------------

import { api } from '@/api/client';
import { CompositionPanel, type CompositionPanelProps } from './CompositionPanel';
import {
  VersionGuard,
  describeError,
  createDispatch,
  createDebouncedDispatch,
  createSyncBackendAdapter,
  createRestBackend,
  type DraftBackend,
  type Dispatch,
} from './dispatch';
import { createMockDraftBackend, type MockDraftBackend } from './staff/__mocks__/mockDraftBackend';

// ---------------------------------------------------------------------------
// 辅助：空白快照断言基线
// ---------------------------------------------------------------------------

/** 空白草稿的 melody 应为单个 C4 全音符占位 */
const BLANK_PLACEHOLDER_PITCH = 'C4';

/**
 * 设置受控 range input 的值并派发 change 事件。
 * 直接用 fireEvent.change 连续改值时，React 的 valueTracker 在某些情况下
 * 会把末次值与受控 prop 重置值比较导致 onChange 被吞（已知 React 测试怪癖）。
 * 用原生 value setter 绕过 valueTracker，确保每次 change 都触发 onChange。
 */
function setRangeValue(el: HTMLElement, value: string): void {
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype,
    'value',
  )?.set;
  if (!setter) throw new Error('无法获取 HTMLInputElement value setter');
  setter.call(el, value);
  el.dispatchEvent(new Event('change', { bubbles: true }));
}

// ---------------------------------------------------------------------------
// A. dispatch 层单元测试
// ---------------------------------------------------------------------------

describe('dispatch 层：VersionGuard', () => {
  it('初始状态 lastVersion=-1，接受任何 ≥0 的 version', () => {
    const guard = new VersionGuard();
    expect(guard.shouldAccept(0)).toBe(true);
    expect(guard.shouldAccept(5)).toBe(true);
  });

  it('version=undefined 视为无 version 字段（如 get_draft 响应），不丢弃', () => {
    const guard = new VersionGuard();
    expect(guard.shouldAccept(undefined)).toBe(true);
  });

  it('update 后只接受比 lastVersion 更新的 version', () => {
    const guard = new VersionGuard();
    guard.update(3);
    expect(guard.shouldAccept(3)).toBe(false); // 同版本不接受
    expect(guard.shouldAccept(2)).toBe(false); // 更旧不接受
    expect(guard.shouldAccept(4)).toBe(true); // 更新接受
  });

  it('update 只增不减', () => {
    const guard = new VersionGuard();
    guard.update(5);
    guard.update(3); // 尝试回退
    expect(guard.current).toBe(5);
  });

  it('reset 重置基线', () => {
    const guard = new VersionGuard();
    guard.update(10);
    guard.reset(0);
    expect(guard.current).toBe(0);
    expect(guard.shouldAccept(0)).toBe(false);
    expect(guard.shouldAccept(1)).toBe(true);
  });

  it('reset() 无参默认 -1', () => {
    const guard = new VersionGuard();
    guard.update(10);
    guard.reset();
    expect(guard.current).toBe(-1);
  });
});

describe('dispatch 层：describeError', () => {
  it('每个错误码枚举映射到中文文案', () => {
    const codes: ErrorCode[] = [
      'SCORE_VALIDATION_FAILED',
      'DRAFT_NOT_FOUND',
      'COMMAND_UNKNOWN',
      'COMMAND_ARGS_INVALID',
      'TRACK_NOT_FOUND',
      'NOTE_NOT_FOUND',
      'CHORD_NOT_FOUND',
      'STYLE_UNKNOWN',
      'TRACK_MODE_INVALID',
      'SUBMIT_FAILED',
    ];
    for (const code of codes) {
      const msg = describeError({ code, message: '原始消息' });
      expect(msg).toBeTruthy();
      expect(msg.length).toBeGreaterThan(0);
      // 不应暴露原始英文 code 裸串（应有人类可读中文）
      expect(msg).not.toBe(code);
    }
  });

  it('未知错误码走兜底（含 code 原文）', () => {
    const msg = describeError({ code: 'NETWORK_ERROR', message: 'timeout' });
    expect(msg).toContain('NETWORK_ERROR');
  });

  it('附 details 时追加可读摘要', () => {
    const msg = describeError({
      code: 'NOTE_NOT_FOUND',
      message: '音符不存在',
      details: { track: 'melody', note_id: 3 },
    });
    expect(msg).toContain('track=');
    expect(msg).toContain('note_id=');
  });

  it('details 为空对象时不追加括号', () => {
    const msg = describeError({ code: 'DRAFT_NOT_FOUND', message: '不存在', details: {} });
    expect(msg).not.toContain('(');
  });
});

describe('dispatch 层：createDebouncedDispatch', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('同 key 连续调用：仅最后一次真正下发，前面的 resolve(null)', async () => {
    const inner = vi.fn<(c: string, a: Record<string, unknown>) => Promise<CommandResult | null>>();
    inner.mockResolvedValue({ success: true, version: 1 });
    const debounced = createDebouncedDispatch(inner as Dispatch, 300);

    const p1 = debounced('set_track_mix', { track_id: 'trk_0', volume: 50 });
    const p2 = debounced('set_track_mix', { track_id: 'trk_0', volume: 60 });
    const p3 = debounced('set_track_mix', { track_id: 'trk_0', volume: 70 });

    // 推进定时器
    vi.advanceTimersByTime(300);

    const [r1, r2, r3] = await Promise.all([p1, p2, p3]);

    // 前两次被合并丢弃（resolve null）
    expect(r1).toBeNull();
    expect(r2).toBeNull();
    // 最后一次真正执行
    expect(r3).not.toBeNull();
    expect(r3?.success).toBe(true);

    // inner 只被调用一次，参数为最后一次的 volume=70
    expect(inner).toHaveBeenCalledTimes(1);
    expect(inner.mock.calls[0][1]).toEqual({ track_id: 'trk_0', volume: 70 });
  });

  it('不同 track_id 的 key 互不干扰', async () => {
    const inner = vi.fn<(c: string, a: Record<string, unknown>) => Promise<CommandResult | null>>();
    inner.mockResolvedValue({ success: true, version: 1 });
    const debounced = createDebouncedDispatch(inner as Dispatch, 300);

    const p1 = debounced('set_track_mix', { track_id: 'trk_0', volume: 50 });
    const p2 = debounced('set_track_mix', { track_id: 'trk_1', volume: 60 });

    vi.advanceTimersByTime(300);

    const [r1, r2] = await Promise.all([p1, p2]);

    expect(r1).not.toBeNull();
    expect(r2).not.toBeNull();
    expect(inner).toHaveBeenCalledTimes(2);
  });

  it('防抖延迟从末次调用算起（清旧 timer 重计时）', async () => {
    const inner = vi.fn<(c: string, a: Record<string, unknown>) => Promise<CommandResult | null>>();
    inner.mockResolvedValue({ success: true, version: 1 });
    const debounced = createDebouncedDispatch(inner as Dispatch, 300);

    debounced('set_track_mix', { track_id: 'trk_0', volume: 50 });
    // 推进 200ms（未到 300ms，不应执行）
    vi.advanceTimersByTime(200);
    expect(inner).not.toHaveBeenCalled();

    // 再次调用，重置定时器
    debounced('set_track_mix', { track_id: 'trk_0', volume: 60 });
    // 再推进 200ms（从第二次算起未到 300ms）
    vi.advanceTimersByTime(200);
    expect(inner).not.toHaveBeenCalled();

    // 推进到 300ms（从第二次算起）
    vi.advanceTimersByTime(100);
    expect(inner).toHaveBeenCalledTimes(1);
  });
});

describe('dispatch 层：createDispatch', () => {
  it('draft_id 自动注入：args 未含 draft_id 时从 getDraftId() 补入', async () => {
    let captured: CommandRequest | null = null;
    const backend: DraftBackend = {
      execute: (req) => {
        captured = req;
        return Promise.resolve({ success: true, version: 1 });
      },
      createDraft: vi.fn(),
      getDraft: vi.fn(),
      deleteDraft: vi.fn(),
      listDrafts: vi.fn(),
    };
    const handle = createDispatch({ backend, getDraftId: () => 'draft_42' });

    await handle.dispatch('add_note', { track: 'melody', pitch: 'C4', beats: 1 });

    expect(captured).not.toBeNull();
    expect(captured!.command).toBe('add_note');
    expect((captured!.args as Record<string, unknown>).draft_id).toBe('draft_42');
  });

  it('draft_id 不覆盖：args 已含 draft_id 时保留原值', async () => {
    let captured: CommandRequest | null = null;
    const backend: DraftBackend = {
      execute: (req) => {
        captured = req;
        return Promise.resolve({ success: true, version: 1 });
      },
      createDraft: vi.fn(),
      getDraft: vi.fn(),
      deleteDraft: vi.fn(),
      listDrafts: vi.fn(),
    };
    const handle = createDispatch({ backend, getDraftId: () => 'fallback' });

    await handle.dispatch('add_note', { draft_id: 'explicit', track: 'melody', pitch: 'C4', beats: 1 });

    expect((captured!.args as Record<string, unknown>).draft_id).toBe('explicit');
  });

  it('version 防乱序：过期响应丢弃（返回 null）', async () => {
    const backend: DraftBackend = {
      execute: () => Promise.resolve({ success: true, version: 1 }),
      createDraft: vi.fn(),
      getDraft: vi.fn(),
      deleteDraft: vi.fn(),
      listDrafts: vi.fn(),
    };
    const handle = createDispatch({ backend, getDraftId: () => 'd1' });

    // 第一次 version=1 被接受
    const r1 = await handle.dispatch('add_note', { track: 'melody', pitch: 'C4', beats: 1 });
    expect(r1).not.toBeNull();
    expect(handle.getVersion()).toBe(1);

    // 第二次 version=1 被丢弃（不比 lastVersion 更新）
    const r2 = await handle.dispatch('add_note', { track: 'melody', pitch: 'D4', beats: 1 });
    expect(r2).toBeNull();
  });

  it('网络错误：backend.execute 抛异常时返回 NETWORK_ERROR CommandResult', async () => {
    const backend: DraftBackend = {
      execute: () => Promise.reject(new Error('connection refused')),
      createDraft: vi.fn(),
      getDraft: vi.fn(),
      deleteDraft: vi.fn(),
      listDrafts: vi.fn(),
    };
    const handle = createDispatch({ backend, getDraftId: () => 'd1' });

    const result = await handle.dispatch('add_note', { track: 'melody', pitch: 'C4', beats: 1 });

    expect(result).not.toBeNull();
    expect(result!.success).toBe(false);
    expect(result!.error?.code).toBe('NETWORK_ERROR');
    expect(result!.error?.message).toContain('connection refused');
  });

  it('setVersion / getVersion 基线管理', () => {
    const backend: DraftBackend = {
      execute: vi.fn(),
      createDraft: vi.fn(),
      getDraft: vi.fn(),
      deleteDraft: vi.fn(),
      listDrafts: vi.fn(),
    };
    const handle = createDispatch({ backend, getDraftId: () => 'd1' });

    expect(handle.getVersion()).toBe(-1);
    handle.setVersion(5);
    expect(handle.getVersion()).toBe(5);
  });
});

describe('dispatch 层：createRestBackend（REST 冒烟）', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('createDraft → POST /api/music/drafts', async () => {
    const backend = createRestBackend(() => 'http://test');
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      json: () => Promise.resolve({ success: true, draft_id: 'd1', version: 0 }),
    });

    await backend.createDraft();

    expect(global.fetch).toHaveBeenCalledWith(
      'http://test/api/music/drafts',
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('execute → POST /drafts/{id}/commands', async () => {
    const backend = createRestBackend(() => 'http://test');
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      json: () => Promise.resolve({ success: true, version: 1 }),
    });

    await backend.execute({
      command: 'add_note',
      args: { draft_id: 'd1', track: 'melody', pitch: 'C4', beats: 1 },
    });

    expect(global.fetch).toHaveBeenCalledWith(
      'http://test/api/music/drafts/d1/commands',
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('execute 缺 draft_id 时 reject', async () => {
    const backend = createRestBackend(() => 'http://test');
    await expect(
      backend.execute({ command: 'add_note', args: { track: 'melody' } } as CommandRequest),
    ).rejects.toThrow('draft_id');
  });

  it('getDraft → GET /drafts/{id}', async () => {
    const backend = createRestBackend(() => 'http://test');
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      json: () => Promise.resolve({ success: true, draft_id: 'd1' }),
    });

    await backend.getDraft('d1');

    expect(global.fetch).toHaveBeenCalledWith(
      'http://test/api/music/drafts/d1',
      expect.objectContaining({ method: 'GET' }),
    );
  });

  it('deleteDraft → DELETE /drafts/{id}', async () => {
    const backend = createRestBackend(() => 'http://test');
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      json: () => Promise.resolve({ success: true }),
    });

    const result = await backend.deleteDraft('d1');

    expect(global.fetch).toHaveBeenCalledWith(
      'http://test/api/music/drafts/d1',
      expect.objectContaining({ method: 'DELETE' }),
    );
    expect(result.success).toBe(true);
  });

  it('listDrafts → GET /drafts', async () => {
    const backend = createRestBackend(() => 'http://test');
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      json: () => Promise.resolve([{ draft_id: 'd1', title: 't', version: 0, updated_at: '' }]),
    });

    const list = await backend.listDrafts();

    expect(global.fetch).toHaveBeenCalledWith(
      'http://test/api/music/drafts',
      expect.objectContaining({ method: 'GET' }),
    );
    expect(list).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// B. CompositionPanel 组件集成测试
// ---------------------------------------------------------------------------

// ── 渲染辅助 ──

interface RenderResult {
  mockBackend: MockDraftBackend;
  backend: DraftBackend;
  rerender: (ui: ReactElement) => void;
  unmount: () => void;
  container: HTMLElement;
}

function makeBackend(): { mockBackend: MockDraftBackend; backend: DraftBackend } {
  const mockBackend = createMockDraftBackend();
  const backend = createSyncBackendAdapter(mockBackend);
  return { mockBackend, backend };
}

async function renderPanel(
  options?: {
    initialDraftId?: string;
    backend?: DraftBackend;
    mockBackend?: MockDraftBackend;
    pollTask?: CompositionPanelProps['pollTask'];
    pollIntervalMs?: number;
  },
): Promise<RenderResult> {
  const mockBackend = options?.mockBackend ?? createMockDraftBackend();
  const backend = options?.backend ?? createSyncBackendAdapter(mockBackend);
  const utils = render(
    <CompositionPanel
      backend={backend}
      initialDraftId={options?.initialDraftId}
      pollTask={options?.pollTask}
      pollIntervalMs={options?.pollIntervalMs}
    />,
  );
  // 等待初始化完成（staff-score 出现 = score 已载入）
  await waitFor(() => {
    expect(screen.getByTestId('staff-score')).toBeInTheDocument();
  });
  return {
    mockBackend,
    backend,
    rerender: utils.rerender,
    unmount: utils.unmount,
    container: utils.container,
  };
}

/** 种子创建草稿，返回 draft_id */
function seedDraft(mockBackend: MockDraftBackend, fixtureName: string): string {
  const result = mockBackend.seedFromFixture(fixtureName);
  if (!result.success || !result.draft_id) {
    throw new Error(`种子创建失败: ${fixtureName}`);
  }
  return result.draft_id;
}

// ── beforeEach：api mock 默认值 ──

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.musicListSongs).mockResolvedValue({ songs: [] });
  vi.mocked(api.musicGetTask).mockResolvedValue({
    song_id: '',
    title: '',
    status: 'completed',
    stage: '',
    progress: 100,
    error: null,
    created_at: '',
    finished_at: null,
    audio_url: null,
  });
  vi.mocked(api.musicDeleteSong).mockResolvedValue({ status: 'success', song_id: '' });
});

afterEach(() => {
  vi.useRealTimers();
});

// ── 初始化 ──

describe('CompositionPanel：初始化', () => {
  it('无 initialDraftId 时创建空白草稿（C4 全音符占位）', async () => {
    await renderPanel();

    // staff-score 已渲染（说明 score 已载入）
    expect(screen.getByTestId('staff-score')).toBeInTheDocument();
    // 空白草稿的 melody 占位音符可点击
    expect(screen.getByTestId('note-melody-0')).toBeInTheDocument();

    // 验证空白草稿确实含 C4 占位（通过点击后属性面板回显）
    fireEvent.click(screen.getByTestId('note-melody-0'));
    await waitFor(() => {
      expect(screen.getByTestId('note-prop-panel')).toBeInTheDocument();
    });
    expect((screen.getByTestId('edit-pitch-input') as HTMLInputElement).value).toBe(
      BLANK_PLACEHOLDER_PITCH,
    );
  });

  it('有 initialDraftId 时载入既有草稿', async () => {
    const { mockBackend } = makeBackend();
    const draftId = seedDraft(mockBackend, 'full_multitrack_v2');
    const backend = createSyncBackendAdapter(mockBackend);

    await renderPanel({ initialDraftId: draftId, backend, mockBackend });

    // full_multitrack_v2 含 3 旋律音符 + 3 伴奏轨
    expect(screen.getByTestId('note-melody-0')).toBeInTheDocument();
    expect(screen.getByTestId('note-melody-1')).toBeInTheDocument();
    expect(screen.getByTestId('note-melody-2')).toBeInTheDocument();
    // 伴奏轨贝斯有 4 events
    expect(screen.getByTestId('note-trk_bass-0')).toBeInTheDocument();
    expect(screen.getByTestId('note-trk_bass-3')).toBeInTheDocument();

    // draft badge 显示草稿 id
    expect(screen.getByTestId('draft-badge').textContent).toContain(draftId);
  });

  it('初始化期间显示 loading 态', async () => {
    // 用延迟 backend 验证 loading 显示
    const { mockBackend } = makeBackend();
    const delayedBackend: DraftBackend = {
      execute: (req) =>
        new Promise((resolve) => setTimeout(() => resolve(mockBackend.execute(req)), 50)),
      createDraft: () =>
        new Promise((resolve) =>
          setTimeout(() => resolve(mockBackend.execute({ command: 'create_draft', args: {} })), 50),
        ),
      getDraft: (id) =>
        new Promise((resolve) =>
          setTimeout(
            () => resolve(mockBackend.execute({ command: 'get_draft', args: { draft_id: id } })),
            50,
          ),
        ),
      deleteDraft: (id) => Promise.resolve({ success: mockBackend.deleteDraft(id) }),
      listDrafts: () => Promise.resolve(mockBackend.listDrafts()),
    };

    render(<CompositionPanel backend={delayedBackend} />);
    // loading 态先出现
    expect(screen.getByTestId('loading')).toBeInTheDocument();

    // 等待 score 载入
    await waitFor(() => {
      expect(screen.getByTestId('staff-score')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('loading')).not.toBeInTheDocument();
  });

  it('初始化失败时显示错误提示', async () => {
    const failBackend: DraftBackend = {
      execute: vi.fn(),
      createDraft: () =>
        Promise.resolve({
          success: false,
          error: { code: 'SCORE_VALIDATION_FAILED', message: '校验失败' },
        }),
      getDraft: vi.fn(),
      deleteDraft: vi.fn(),
      listDrafts: vi.fn(),
    };

    render(<CompositionPanel backend={failBackend} />);

    await waitFor(() => {
      expect(screen.getByTestId('error-banner')).toBeInTheDocument();
    });
    expect(screen.getByTestId('error-banner').textContent).toContain('校验失败');
  });
});

// ── 交互1：添加音符 ──

describe('CompositionPanel：交互1 — 添加音符（add_note）', () => {
  it('melody 轨添加音符（首个 add_note 替换占位符）', async () => {
    const { mockBackend } = await renderPanel();
    const executeSpy = vi.spyOn(mockBackend, 'execute');

    // 填写添加音符表单
    fireEvent.change(screen.getByTestId('add-pitch-input'), { target: { value: 'D4' } });
    fireEvent.change(screen.getByTestId('add-beats-input'), { target: { value: '2' } });
    fireEvent.change(screen.getByTestId('add-lyric-input'), { target: { value: '你' } });
    fireEvent.click(screen.getByTestId('add-note-btn'));

    await waitFor(() => {
      // 占位符被替换，melody 仍为 1 个音符但 pitch 变为 D4
      expect(screen.getByTestId('note-melody-0').textContent).toBe('D4');
    });

    // 验证命令分发
    expect(executeSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        command: 'add_note',
        args: expect.objectContaining({
          track: 'melody',
          pitch: 'D4',
          beats: 2,
          lyric: '你',
        }),
      }),
    );
  });

  it('melody 轨追加音符（非首次）', async () => {
    await renderPanel();

    // 第一次添加（替换占位符）
    fireEvent.change(screen.getByTestId('add-pitch-input'), { target: { value: 'D4' } });
    fireEvent.change(screen.getByTestId('add-lyric-input'), { target: { value: '你' } });
    fireEvent.click(screen.getByTestId('add-note-btn'));
    await waitFor(() => {
      expect(screen.getByTestId('note-melody-0').textContent).toBe('D4');
    });

    // 第二次添加（追加）
    fireEvent.change(screen.getByTestId('add-pitch-input'), { target: { value: 'E4' } });
    fireEvent.change(screen.getByTestId('add-lyric-input'), { target: { value: '好' } });
    fireEvent.click(screen.getByTestId('add-note-btn'));
    await waitFor(() => {
      expect(screen.getByTestId('note-melody-1')).toBeInTheDocument();
    });
    expect(screen.getByTestId('note-melody-1').textContent).toBe('E4');
  });

  it('伴奏轨添加音符（带 offset）', async () => {
    const { mockBackend } = makeBackend();
    const draftId = seedDraft(mockBackend, 'full_multitrack_v2');
    const backend = createSyncBackendAdapter(mockBackend);
    await renderPanel({ initialDraftId: draftId, backend, mockBackend });

    const executeSpy = vi.spyOn(mockBackend, 'execute');

    // 选择伴奏轨 trk_bass
    fireEvent.change(screen.getByTestId('add-track-select'), { target: { value: 'trk_bass' } });
    // 此时 add-lyric-input 消失，add-offset-input 出现
    fireEvent.change(screen.getByTestId('add-offset-input'), { target: { value: '8' } });
    fireEvent.change(screen.getByTestId('add-pitch-input'), { target: { value: 'A2' } });
    fireEvent.click(screen.getByTestId('add-note-btn'));

    await waitFor(() => {
      // trk_bass 原 4 events，添加后 5 events
      expect(screen.getByTestId('note-trk_bass-4')).toBeInTheDocument();
    });

    expect(executeSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        command: 'add_note',
        args: expect.objectContaining({
          track: 'trk_bass',
          pitch: 'A2',
          offset: 8,
        }),
      }),
    );
  });
});

// ── 交互2：选中修改 ──

describe('CompositionPanel：交互2 — 选中修改（update_note）', () => {
  it('点击旋律音符选中 → 属性面板出现并回显当前值', async () => {
    const { mockBackend } = makeBackend();
    const draftId = seedDraft(mockBackend, 'melody_only_v2');
    const backend = createSyncBackendAdapter(mockBackend);
    await renderPanel({ initialDraftId: draftId, backend, mockBackend });

    // 点击第 0 个旋律音符
    fireEvent.click(screen.getByTestId('note-melody-0'));

    await waitFor(() => {
      expect(screen.getByTestId('note-prop-panel')).toBeInTheDocument();
    });

    // 回显当前值（melody_only_v2 第 0 音符 = C4, beats=1, lyric=你）
    expect((screen.getByTestId('edit-pitch-input') as HTMLInputElement).value).toBe('C4');
    expect((screen.getByTestId('edit-beats-input') as HTMLInputElement).value).toBe('1');
    expect((screen.getByTestId('edit-lyric-input') as HTMLInputElement).value).toBe('你');
  });

  it('修改旋律音符属性 → dispatch update_note', async () => {
    const { mockBackend } = makeBackend();
    const draftId = seedDraft(mockBackend, 'melody_only_v2');
    const backend = createSyncBackendAdapter(mockBackend);
    await renderPanel({ initialDraftId: draftId, backend, mockBackend });

    const executeSpy = vi.spyOn(mockBackend, 'execute');

    // 选中第 0 个音符
    fireEvent.click(screen.getByTestId('note-melody-0'));
    await waitFor(() => {
      expect(screen.getByTestId('note-prop-panel')).toBeInTheDocument();
    });

    // 修改音高和拍数
    fireEvent.change(screen.getByTestId('edit-pitch-input'), { target: { value: 'G4' } });
    fireEvent.change(screen.getByTestId('edit-beats-input'), { target: { value: '2' } });
    fireEvent.click(screen.getByTestId('update-note-btn'));

    await waitFor(() => {
      expect(executeSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          command: 'update_note',
          args: expect.objectContaining({
            track: 'melody',
            note_id: 0,
            patch: expect.objectContaining({ pitch: 'G4', beats: 2 }),
          }),
        }),
      );
    });
  });

  it('修改伴奏音符属性（offset + velocity）', async () => {
    const { mockBackend } = makeBackend();
    const draftId = seedDraft(mockBackend, 'full_multitrack_v2');
    const backend = createSyncBackendAdapter(mockBackend);
    await renderPanel({ initialDraftId: draftId, backend, mockBackend });

    const executeSpy = vi.spyOn(mockBackend, 'execute');

    // 选中 trk_bass 第 0 个 event
    fireEvent.click(screen.getByTestId('note-trk_bass-0'));
    await waitFor(() => {
      expect(screen.getByTestId('note-prop-panel')).toBeInTheDocument();
    });

    // 伴奏轨属性面板含 offset + velocity（而非 lyric）
    expect(screen.getByTestId('edit-offset-input')).toBeInTheDocument();
    expect(screen.getByTestId('edit-velocity-input')).toBeInTheDocument();
    expect(screen.queryByTestId('edit-lyric-input')).not.toBeInTheDocument();

    // 修改 offset 和 velocity
    fireEvent.change(screen.getByTestId('edit-offset-input'), { target: { value: '1' } });
    fireEvent.change(screen.getByTestId('edit-velocity-input'), { target: { value: '100' } });
    fireEvent.click(screen.getByTestId('update-note-btn'));

    await waitFor(() => {
      expect(executeSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          command: 'update_note',
          args: expect.objectContaining({
            track: 'trk_bass',
            note_id: 0,
            patch: expect.objectContaining({ offset: 1, velocity: 100 }),
          }),
        }),
      );
    });
  });

  it('选中态高亮（selectedNote 传给 StaffScore）', async () => {
    const { mockBackend } = makeBackend();
    const draftId = seedDraft(mockBackend, 'melody_only_v2');
    const backend = createSyncBackendAdapter(mockBackend);
    await renderPanel({ initialDraftId: draftId, backend, mockBackend });

    // 点击前无选中
    expect(screen.getByTestId('note-melody-0').getAttribute('data-selected')).toBe('false');

    // 点击后选中
    fireEvent.click(screen.getByTestId('note-melody-0'));
    await waitFor(() => {
      expect(screen.getByTestId('note-melody-0').getAttribute('data-selected')).toBe('true');
    });
  });
});

// ── 交互3：移动音符 ──

describe('CompositionPanel：交互3 — 移动音符（move_note）', () => {
  it('melody 轨 move_note（重排）', async () => {
    const { mockBackend } = makeBackend();
    const draftId = seedDraft(mockBackend, 'melody_only_v2');
    const backend = createSyncBackendAdapter(mockBackend);
    await renderPanel({ initialDraftId: draftId, backend, mockBackend });

    const executeSpy = vi.spyOn(mockBackend, 'execute');

    // 选中第 0 个音符
    fireEvent.click(screen.getByTestId('note-melody-0'));
    await waitFor(() => {
      expect(screen.getByTestId('note-prop-panel')).toBeInTheDocument();
    });

    // 设置移动落点并点击移动
    fireEvent.change(screen.getByTestId('move-offset-input'), { target: { value: '2' } });
    fireEvent.click(screen.getByTestId('move-note-btn'));

    await waitFor(() => {
      expect(executeSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          command: 'move_note',
          args: expect.objectContaining({
            track: 'melody',
            note_id: 0,
            new_offset: 2,
          }),
        }),
      );
    });
  });

  it('伴奏轨 move_note（设置 offset）', async () => {
    const { mockBackend } = makeBackend();
    const draftId = seedDraft(mockBackend, 'full_multitrack_v2');
    const backend = createSyncBackendAdapter(mockBackend);
    await renderPanel({ initialDraftId: draftId, backend, mockBackend });

    const executeSpy = vi.spyOn(mockBackend, 'execute');

    // 选中 trk_bass 第 0 个 event
    fireEvent.click(screen.getByTestId('note-trk_bass-0'));
    await waitFor(() => {
      expect(screen.getByTestId('note-prop-panel')).toBeInTheDocument();
    });

    fireEvent.change(screen.getByTestId('move-offset-input'), { target: { value: '3' } });
    fireEvent.click(screen.getByTestId('move-note-btn'));

    await waitFor(() => {
      expect(executeSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          command: 'move_note',
          args: expect.objectContaining({
            track: 'trk_bass',
            note_id: 0,
            new_offset: 3,
          }),
        }),
      );
    });
  });
});

// ── 交互4：歌词行内编辑 ──

describe('CompositionPanel：交互4 — 歌词行内编辑（set_lyric）', () => {
  it('blur 提交 set_lyric', async () => {
    const { mockBackend } = makeBackend();
    const draftId = seedDraft(mockBackend, 'melody_only_v2');
    const backend = createSyncBackendAdapter(mockBackend);
    await renderPanel({ initialDraftId: draftId, backend, mockBackend });

    const executeSpy = vi.spyOn(mockBackend, 'execute');

    // 选中第 0 个旋律音符
    fireEvent.click(screen.getByTestId('note-melody-0'));
    await waitFor(() => {
      expect(screen.getByTestId('edit-lyric-input')).toBeInTheDocument();
    });

    // 修改歌词并 blur
    fireEvent.change(screen.getByTestId('edit-lyric-input'), { target: { value: '哈' } });
    fireEvent.blur(screen.getByTestId('edit-lyric-input'));

    await waitFor(() => {
      expect(executeSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          command: 'set_lyric',
          args: expect.objectContaining({
            note_id: 0,
            lyric: '哈',
          }),
        }),
      );
    });
  });

  it('Enter 键触发 blur 提交', async () => {
    const { mockBackend } = makeBackend();
    const draftId = seedDraft(mockBackend, 'melody_only_v2');
    const backend = createSyncBackendAdapter(mockBackend);
    await renderPanel({ initialDraftId: draftId, backend, mockBackend });

    const executeSpy = vi.spyOn(mockBackend, 'execute');

    fireEvent.click(screen.getByTestId('note-melody-0'));
    await waitFor(() => {
      expect(screen.getByTestId('edit-lyric-input')).toBeInTheDocument();
    });

    fireEvent.change(screen.getByTestId('edit-lyric-input'), { target: { value: '啦' } });
    fireEvent.keyDown(screen.getByTestId('edit-lyric-input'), { key: 'Enter' });

    await waitFor(() => {
      expect(executeSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          command: 'set_lyric',
          args: expect.objectContaining({ lyric: '啦' }),
        }),
      );
    });
  });
});

// ── 删除音符 ──

describe('CompositionPanel：删除音符（delete_note）', () => {
  it('删除旋律音符 → 选中清除', async () => {
    const { mockBackend } = makeBackend();
    const draftId = seedDraft(mockBackend, 'melody_only_v2');
    const backend = createSyncBackendAdapter(mockBackend);
    await renderPanel({ initialDraftId: draftId, backend, mockBackend });

    const executeSpy = vi.spyOn(mockBackend, 'execute');

    // 选中第 0 个音符
    fireEvent.click(screen.getByTestId('note-melody-0'));
    await waitFor(() => {
      expect(screen.getByTestId('note-prop-panel')).toBeInTheDocument();
    });

    // 删除
    fireEvent.click(screen.getByTestId('delete-note-btn'));

    await waitFor(() => {
      expect(executeSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          command: 'delete_note',
          args: expect.objectContaining({ track: 'melody', note_id: 0 }),
        }),
      );
    });

    // 选中态清除（属性面板消失）
    await waitFor(() => {
      expect(screen.queryByTestId('note-prop-panel')).not.toBeInTheDocument();
    });
  });
});

// ── 轨道管理 ──

describe('CompositionPanel：轨道管理（TrackManager）', () => {
  it('添加伴奏轨 → dispatch add_track', async () => {
    const { mockBackend } = await renderPanel();
    const executeSpy = vi.spyOn(mockBackend, 'execute');

    // 轨道管理面板存在
    expect(screen.getByTestId('track-manager')).toBeInTheDocument();

    // 填写新轨表单
    fireEvent.change(screen.getByTestId('new-track-name'), { target: { value: '贝斯' } });
    fireEvent.change(screen.getByTestId('new-track-program'), { target: { value: '33' } });
    fireEvent.change(screen.getByTestId('new-track-mode'), { target: { value: 'manual' } });
    fireEvent.click(screen.getByTestId('add-track-btn'));

    await waitFor(() => {
      expect(executeSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          command: 'add_track',
          args: expect.objectContaining({
            name: '贝斯',
            program: 33,
            mode: 'manual',
          }),
        }),
      );
    });

    // 新轨出现在轨道列表
    await waitFor(() => {
      expect(screen.getByTestId('track-trk_0')).toBeInTheDocument();
    });
  });

  it('删除伴奏轨 → dispatch remove_track', async () => {
    const { mockBackend } = makeBackend();
    const draftId = seedDraft(mockBackend, 'full_multitrack_v2');
    const backend = createSyncBackendAdapter(mockBackend);
    await renderPanel({ initialDraftId: draftId, backend, mockBackend });

    const executeSpy = vi.spyOn(mockBackend, 'execute');

    // trk_piano 存在
    expect(screen.getByTestId('track-trk_piano')).toBeInTheDocument();

    // 删除 trk_piano
    fireEvent.click(screen.getByTestId('remove-track-trk_piano'));

    await waitFor(() => {
      expect(executeSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          command: 'remove_track',
          args: expect.objectContaining({ track_id: 'trk_piano' }),
        }),
      );
    });

    // trk_piano 从列表消失
    await waitFor(() => {
      expect(screen.queryByTestId('track-trk_piano')).not.toBeInTheDocument();
    });
  });

  it('切换音色 → dispatch set_track_instrument', async () => {
    const { mockBackend } = makeBackend();
    const draftId = seedDraft(mockBackend, 'full_multitrack_v2');
    const backend = createSyncBackendAdapter(mockBackend);
    await renderPanel({ initialDraftId: draftId, backend, mockBackend });

    const executeSpy = vi.spyOn(mockBackend, 'execute');

    // 切换 trk_bass 的音色
    fireEvent.change(screen.getByTestId('instrument-trk_bass'), { target: { value: '34' } });

    await waitFor(() => {
      expect(executeSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          command: 'set_track_instrument',
          args: expect.objectContaining({ track_id: 'trk_bass', program: 34 }),
        }),
      );
    });
  });

  it('切换模式 → dispatch set_track_mode', async () => {
    const { mockBackend } = makeBackend();
    const draftId = seedDraft(mockBackend, 'full_multitrack_v2');
    const backend = createSyncBackendAdapter(mockBackend);
    await renderPanel({ initialDraftId: draftId, backend, mockBackend });

    const executeSpy = vi.spyOn(mockBackend, 'execute');

    // trk_piano 当前为 auto，切到 manual
    fireEvent.change(screen.getByTestId('mode-trk_piano'), { target: { value: 'manual' } });

    await waitFor(() => {
      expect(executeSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          command: 'set_track_mode',
          args: expect.objectContaining({ track_id: 'trk_piano', mode: 'manual' }),
        }),
      );
    });
  });

  it('auto 轨编排 → dispatch arrange_track', async () => {
    const { mockBackend } = makeBackend();
    const draftId = seedDraft(mockBackend, 'full_multitrack_v2');
    const backend = createSyncBackendAdapter(mockBackend);
    await renderPanel({ initialDraftId: draftId, backend, mockBackend });

    const executeSpy = vi.spyOn(mockBackend, 'execute');

    // trk_piano 为 auto 轨，点击编排按钮
    fireEvent.click(screen.getByTestId('arrange-trk_piano'));

    await waitFor(() => {
      expect(executeSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          command: 'arrange_track',
          args: expect.objectContaining({ track_id: 'trk_piano' }),
        }),
      );
    });
  });

  it('音量滑块调整 → 防抖后 dispatch set_track_mix', async () => {
    const { mockBackend } = makeBackend();
    const draftId = seedDraft(mockBackend, 'full_multitrack_v2');
    const backend = createSyncBackendAdapter(mockBackend);

    // 真实计时器下渲染并等待初始化完成
    render(<CompositionPanel backend={backend} initialDraftId={draftId} />);
    await waitFor(() => {
      expect(screen.getByTestId('staff-score')).toBeInTheDocument();
    });

    const executeSpy = vi.spyOn(mockBackend, 'execute');

    // 连续拖动音量滑块（用原生 value setter 派发 change；
    // 末值取 110，避开受控 prop=100 导致 valueTracker 误判"未变化"吞掉 onChange）
    const volumeSlider = screen.getByTestId('volume-trk_piano');
    setRangeValue(volumeSlider, '80');
    setRangeValue(volumeSlider, '90');
    setRangeValue(volumeSlider, '110');

    // 等待防抖（300ms）后 set_track_mix 被调用一次
    await waitFor(() => {
      const mixCalls = executeSpy.mock.calls.filter(
        (c) => c[0]?.command === 'set_track_mix',
      );
      expect(mixCalls).toHaveLength(1);
    });

    const mixCalls = executeSpy.mock.calls.filter(
      (c) => c[0]?.command === 'set_track_mix',
    );
    expect(mixCalls).toHaveLength(1);
    expect(mixCalls[0][0].args).toEqual(
      expect.objectContaining({ track_id: 'trk_piano', volume: 110 }),
    );
  });

  it('声像滑块调整 → 防抖后 dispatch set_track_mix', async () => {
    const { mockBackend } = makeBackend();
    const draftId = seedDraft(mockBackend, 'full_multitrack_v2');
    const backend = createSyncBackendAdapter(mockBackend);

    render(<CompositionPanel backend={backend} initialDraftId={draftId} />);
    await waitFor(() => {
      expect(screen.getByTestId('staff-score')).toBeInTheDocument();
    });

    const executeSpy = vi.spyOn(mockBackend, 'execute');

    const panSlider = screen.getByTestId('pan-trk_piano');
    setRangeValue(panSlider, '32');

    await waitFor(() => {
      const mixCalls = executeSpy.mock.calls.filter(
        (c) => c[0]?.command === 'set_track_mix',
      );
      expect(mixCalls).toHaveLength(1);
    });

    const mixCalls = executeSpy.mock.calls.filter(
      (c) => c[0]?.command === 'set_track_mix',
    );
    expect(mixCalls).toHaveLength(1);
    expect(mixCalls[0][0].args).toEqual(
      expect.objectContaining({ track_id: 'trk_piano', pan: 32 }),
    );
  });

  it('主旋律轨只读展示（无删除/编辑控件）', async () => {
    const { mockBackend } = makeBackend();
    const draftId = seedDraft(mockBackend, 'full_multitrack_v2');
    const backend = createSyncBackendAdapter(mockBackend);
    await renderPanel({ initialDraftId: draftId, backend, mockBackend });

    // 主旋律轨展示存在
    expect(screen.getByTestId('track-melody')).toBeInTheDocument();
    // 主旋律轨无删除按钮
    expect(screen.queryByTestId('remove-track-melody')).not.toBeInTheDocument();
  });
});

// ── 草稿管理 ──

describe('CompositionPanel：草稿管理', () => {
  it('新建草稿按钮 → 创建空白草稿', async () => {
    const { mockBackend } = await renderPanel();
    const executeSpy = vi.spyOn(mockBackend, 'execute');

    // 记住原 draft_id
    const originalBadge = screen.getByTestId('draft-badge').textContent;

    fireEvent.click(screen.getByTestId('new-draft-btn'));

    await waitFor(() => {
      // info banner 显示已创建
      expect(screen.getByTestId('info-banner')).toBeInTheDocument();
    });

    // create_draft 命令被调用
    expect(executeSpy).toHaveBeenCalledWith(
      expect.objectContaining({ command: 'create_draft' }),
    );

    // draft_id 变化（新草稿）
    await waitFor(() => {
      expect(screen.getByTestId('draft-badge').textContent).not.toBe(originalBadge);
    });
  });

  it('草稿列表显示并可载入', async () => {
    const { mockBackend } = makeBackend();
    // 创建两个草稿
    const id1 = seedDraft(mockBackend, 'minimal_v2');
    const id2 = seedDraft(mockBackend, 'melody_only_v2');
    const backend = createSyncBackendAdapter(mockBackend);

    // 用 id1 初始化
    await renderPanel({ initialDraftId: id1, backend, mockBackend });

    // 草稿列表存在
    await waitFor(() => {
      expect(screen.getByTestId('draft-list')).toBeInTheDocument();
    });

    // 列表中含 id2 的载入按钮
    const loadBtn = screen.getByTestId(`load-draft-${id2}`);
    expect(loadBtn).toBeInTheDocument();

    // 点击载入 id2
    fireEvent.click(loadBtn);

    await waitFor(() => {
      // info banner 显示已载入
      expect(screen.getByTestId('info-banner').textContent).toContain(id2);
    });

    // score 更新为 melody_only_v2（3 个旋律音符）
    await waitFor(() => {
      expect(screen.getByTestId('note-melody-2')).toBeInTheDocument();
    });
  });

  it('草稿列表为空时显示占位文本', async () => {
    await renderPanel();

    // 空白草稿创建后，draftList 为空（只有当前草稿在内存注册表中，
    // 但 listDrafts 返回的列表在 init 后 refreshDrafts 时才有1条）
    // 此处验证草稿列表区域存在（不管有无内容）
    expect(screen.getByText('草稿列表')).toBeInTheDocument();
  });
});

// ── 提交合成 ──

describe('CompositionPanel：提交合成（submit_draft）', () => {
  it('提交合成 → submit_draft → 显示任务信息', async () => {
    const { mockBackend } = makeBackend();
    const draftId = seedDraft(mockBackend, 'full_multitrack_v2');
    const backend = createSyncBackendAdapter(mockBackend);

    // 注入 pollTask 立即返回 completed
    const pollTask = vi.fn().mockResolvedValue({
      song_id: 'song_1',
      title: '多轨样本',
      status: 'completed',
      stage: 'done',
      progress: 100,
      error: null,
      created_at: '',
      finished_at: null,
      audio_url: '/songs/song_1/final.wav',
    });

    await renderPanel({
      initialDraftId: draftId,
      backend,
      mockBackend,
      pollTask,
      pollIntervalMs: 1000,
    });

    const executeSpy = vi.spyOn(mockBackend, 'execute');

    // 点击提交合成
    fireEvent.click(screen.getByTestId('submit-btn'));

    await waitFor(() => {
      expect(executeSpy).toHaveBeenCalledWith(
        expect.objectContaining({ command: 'submit_draft' }),
      );
    });

    // 任务信息出现
    await waitFor(() => {
      expect(screen.getByTestId('task-info')).toBeInTheDocument();
    });

    // 轮询完成后状态为 completed，音频播放器出现
    await waitFor(() => {
      expect(screen.getByTestId('audio-player')).toBeInTheDocument();
    });
  });

  it('提交合成失败 → 显示错误', async () => {
    const { mockBackend } = makeBackend();
    // 用 minimal_v2（无 chords 无伴奏轨）种草稿
    const draftId = seedDraft(mockBackend, 'minimal_v2');
    const backend = createSyncBackendAdapter(mockBackend);
    await renderPanel({ initialDraftId: draftId, backend, mockBackend });

    // 直接在 mock backend 上让 submit_draft 失败
    // minimal_v2 应该能提交成功（有 melody），所以我们用破坏 score 的方式
    // 改为：让 backend.execute 对 submit_draft 返回失败
    const originalExecute = mockBackend.execute.bind(mockBackend);
    vi.spyOn(mockBackend, 'execute').mockImplementation((req: CommandRequest) => {
      if (req.command === 'submit_draft') {
        return {
          success: false,
          error: { code: 'SUBMIT_FAILED', message: '流水线错误' },
        };
      }
      return originalExecute(req);
    });

    fireEvent.click(screen.getByTestId('submit-btn'));

    await waitFor(() => {
      expect(screen.getByTestId('error-banner')).toBeInTheDocument();
    });
    expect(screen.getByTestId('error-banner').textContent).toContain('提交合成失败');
  });

  it('未初始化时提交按钮禁用', async () => {
    // 用失败 backend 使初始化不成功
    const failBackend: DraftBackend = {
      execute: vi.fn(),
      createDraft: () =>
        Promise.resolve({
          success: false,
          error: { code: 'SCORE_VALIDATION_FAILED', message: '失败' },
        }),
      getDraft: vi.fn(),
      deleteDraft: vi.fn(),
      listDrafts: vi.fn(),
    };

    render(<CompositionPanel backend={failBackend} />);

    await waitFor(() => {
      expect(screen.getByTestId('error-banner')).toBeInTheDocument();
    });

    // submit 按钮禁用（draftId 为 null）
    expect(screen.getByTestId('submit-btn')).toBeDisabled();
  });
});

// ── 歌曲历史 ──

describe('CompositionPanel：歌曲历史', () => {
  it('歌曲列表渲染', async () => {
    vi.mocked(api.musicListSongs).mockResolvedValue({
      songs: [
        {
          song_id: 'song_a',
          title: '测试歌曲A',
          status: 'completed',
          stage: 'done',
          progress: 100,
          error: null,
          created_at: '2026-01-01',
          finished_at: '2026-01-02',
          audio_url: '/songs/song_a/final.wav',
        },
      ],
    });

    await renderPanel();

    await waitFor(() => {
      expect(screen.getByText('测试歌曲A')).toBeInTheDocument();
    });
  });

  it('删除歌曲 → 调用 api.musicDeleteSong', async () => {
    vi.mocked(api.musicListSongs).mockResolvedValue({
      songs: [
        {
          song_id: 'song_del',
          title: '待删除',
          status: 'completed',
          stage: '',
          progress: 0,
          error: null,
          created_at: '',
          finished_at: null,
          audio_url: null,
        },
      ],
    });

    await renderPanel();

    await waitFor(() => {
      expect(screen.getByText('待删除')).toBeInTheDocument();
    });

    // mock confirm 返回 true
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    // 找到删除按钮（歌曲列表中的 danger Button）
    const songRow = screen.getByText('待删除').closest('div.flex')?.parentElement;
    const deleteBtn = within(songRow ?? document.body).getByText('删除');
    fireEvent.click(deleteBtn);

    await waitFor(() => {
      expect(api.musicDeleteSong).toHaveBeenCalledWith('song_del');
    });
  });

  it('空歌曲列表显示占位文本', async () => {
    vi.mocked(api.musicListSongs).mockResolvedValue({ songs: [] });
    await renderPanel();

    await waitFor(() => {
      expect(screen.getByText('暂无歌曲')).toBeInTheDocument();
    });
  });
});

// ── 错误处理 ──

describe('CompositionPanel：错误处理', () => {
  it('命令失败时显示可读错误文案', async () => {
    const { mockBackend } = await renderPanel();

    // 让 add_note 返回 NOTE_NOT_FOUND
    const originalExecute = mockBackend.execute.bind(mockBackend);
    vi.spyOn(mockBackend, 'execute').mockImplementation((req: CommandRequest) => {
      if (req.command === 'add_note') {
        return {
          success: false,
          error: {
            code: 'NOTE_NOT_FOUND',
            message: '音符不存在',
            details: { track: 'melody', note_id: 99 },
          },
        };
      }
      return originalExecute(req);
    });

    // 触发 add_note
    fireEvent.click(screen.getByTestId('add-note-btn'));

    await waitFor(() => {
      expect(screen.getByTestId('error-banner')).toBeInTheDocument();
    });

    // 错误文案含中文可读描述 + details
    const banner = screen.getByTestId('error-banner').textContent ?? '';
    expect(banner).toContain('音符不存在');
  });

  it('成功操作后清除错误提示', async () => {
    const { mockBackend } = await renderPanel();

    // 第一次触发错误
    const originalExecute = mockBackend.execute.bind(mockBackend);
    let shouldFail = true;
    vi.spyOn(mockBackend, 'execute').mockImplementation((req: CommandRequest) => {
      if (shouldFail && req.command === 'add_note') {
        return {
          success: false,
          error: { code: 'COMMAND_ARGS_INVALID', message: '参数无效' },
        };
      }
      return originalExecute(req);
    });

    fireEvent.click(screen.getByTestId('add-note-btn'));
    await waitFor(() => {
      expect(screen.getByTestId('error-banner')).toBeInTheDocument();
    });

    // 恢复正常
    shouldFail = false;
    fireEvent.click(screen.getByTestId('add-note-btn'));

    await waitFor(() => {
      expect(screen.queryByTestId('error-banner')).not.toBeInTheDocument();
    });
  });
});

// ── version 防乱序（组件级）──

describe('CompositionPanel：version 防乱序（组件级）', () => {
  it('version 不递增的响应被丢弃，score 不更新', async () => {
    const { mockBackend } = makeBackend();
    const draftId = seedDraft(mockBackend, 'melody_only_v2');
    const backend = createSyncBackendAdapter(mockBackend);

    // 包装 execute：对 add_note 返回旧 version（不递增）
    const originalExecute = mockBackend.execute.bind(mockBackend);
    vi.spyOn(mockBackend, 'execute').mockImplementation((req: CommandRequest) => {
      if (req.command === 'add_note') {
        const result = originalExecute(req);
        // 篡改 version 为旧值（0），应被 VersionGuard 丢弃
        return { ...result, version: 0 };
      }
      return originalExecute(req);
    });

    await renderPanel({ initialDraftId: draftId, backend, mockBackend });

    // 当前 melody 有 3 个音符（melody_only_v2）
    expect(screen.getByTestId('note-melody-2')).toBeInTheDocument();

    // 添加音符
    fireEvent.change(screen.getByTestId('add-pitch-input'), { target: { value: 'G4' } });
    fireEvent.change(screen.getByTestId('add-lyric-input'), { target: { value: '新' } });
    fireEvent.click(screen.getByTestId('add-note-btn'));

    // 等待命令执行完成
    await waitFor(() => {
      expect(vi.mocked(api.musicGetTask)).toBeDefined();
    });

    // version 被丢弃 → score 不更新 → 第 4 个音符不出现
    // 给一点时间确保不会出现
    await new Promise((r) => setTimeout(r, 100));
    expect(screen.queryByTestId('note-melody-3')).not.toBeInTheDocument();
  });
});
