/**
 * CompositionPanel.tsx — 作曲交互面板（模块7 重构）
 *
 * spec: redesign-composition-staff-editor，merged.md §6 前端架构冻结。
 * 重构自原表单式 UI（refactor-audiostation-engine-consolidation Task 9.2），
 * 为五线谱总谱编辑器：命令分发层 + StaffScore 受控渲染 + 四交互映射 + 轨道管理面板。
 *
 * 受控语义（AGENTS.md §3.2）：
 *  - 持有 draft 状态 {draftId, version, score, selectedNote}，下传 score+selectedNote 给 StaffScore
 *  - 所有编辑经 dispatch（命令分发层）→ REST /drafts/{id}/commands → 服务端真源；前端不直接改 score
 *  - dispatch 层职责：version 防乱序（丢弃过期响应）+ draft_id 自动注入 + 错误码可读提示
 *
 * 四交互映射（merged.md §6）：
 *  1. 添加音符：属性表单选 track+pitch+beats+lyric+offset → dispatch add_note
 *  2. 选中修改：点击音符选中 → 属性面板改 pitch/beats/offset/velocity → dispatch update_note
 *  3. 拖拽调整（首版简化）：属性面板改 offset+pitch → dispatch move_note（实时虚影二期）
 *  4. 歌词行内编辑：属性面板 lyric input blur/Enter → dispatch set_lyric
 *
 * 偏离契约说明（首版简化，二期增强，见最终报告）：
 *  - 点击谱面空白坐标反解 add_note：首版用显式"添加音符"表单，坐标反解二期
 *  - 拖拽实时虚影：首版用属性面板改 offset 一次性 move_note，虚影二期
 *  - 歌词双击 contenteditable：首版用属性面板 lyric input（blur 提交），双击行内二期
 *  - i18n：首版中文硬编码，i18n key 待补
 *  - 合成参数（svc_model/transpose/gain）：首版用默认，合成面板二期补全
 */
import { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { api, getVoiceWorkstationAudioUrl } from '@/api/client';
import type { SongTask, SongSummary } from '@/api/client';
import { Button, Card, CardBody, Input, Badge } from '@/components/ui-v2';
import { StaffScore } from './staff/StaffScore';
import type {
  ScoreV2,
  MelodyNote,
  TrackEvent,
  AccompanimentTrack,
  CommandName,
  CommandResult,
} from './staff/types';
import {
  createDispatch,
  describeError,
  createRestBackend,
  type DraftBackend,
  type DraftSummary,
  type DispatchHandle,
} from './dispatch';
import { TrackManager } from './TrackManager';

const DEFAULT_PITCH = 'C4';
const DEFAULT_BEATS = 1;
const POLL_INTERVAL_MS = 3000;

export interface CompositionPanelProps {
  /** 初始草稿 id；提供则载入既有草稿，缺省则创建空白草稿（C4 占位） */
  initialDraftId?: string;
  /** 草稿后端（默认 REST；测试可注入 createSyncBackendAdapter(MockDraftBackend)） */
  backend?: DraftBackend;
  /** 任务轮询函数（默认 api.musicGetTask；测试可注入 mock） */
  pollTask?: (songId: string) => Promise<SongTask>;
  /** 轮询间隔（测试可缩短；默认 3000ms） */
  pollIntervalMs?: number;
}

// select 元素统一样式（保留原 CompositionPanel 风格）
const selectClassName =
  'w-full px-3 py-2 text-sm rounded-[var(--radius-md)] bg-[var(--color-bg-primary)] text-[var(--color-text-primary)] border border-[var(--color-border)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)] focus:border-transparent';

export function CompositionPanel({
  initialDraftId,
  backend,
  pollTask,
  pollIntervalMs = POLL_INTERVAL_MS,
}: CompositionPanelProps) {
  const resolvedBackend = useMemo(() => backend ?? createRestBackend(), [backend]);
  const resolvedPollTask = useMemo(
    () => pollTask ?? ((id: string) => api.musicGetTask(id)),
    [pollTask],
  );

  // ── 草稿受控状态 ──
  const [draftId, setDraftId] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const [score, setScore] = useState<ScoreV2 | null>(null);
  const [selectedNote, setSelectedNote] = useState<{ track: string; noteId: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [draftList, setDraftList] = useState<DraftSummary[]>([]);

  // ── 合成状态 ──
  const [submitting, setSubmitting] = useState(false);
  const [taskInfo, setTaskInfo] = useState<{
    songId: string;
    status: string;
    audioUrl?: string;
    error?: string;
  } | null>(null);

  // ── 歌曲历史 ──
  const [songs, setSongs] = useState<SongSummary[]>([]);

  // ── dispatch handle（version 防乱序 + draft_id 注入）──
  const draftIdRef = useRef<string>('');
  draftIdRef.current = draftId ?? ''; // render 期同步 ref，避免 getDraftId 闭包 stale
  const handle = useMemo<DispatchHandle>(
    () => createDispatch({ backend: resolvedBackend, getDraftId: () => draftIdRef.current }),
    [resolvedBackend],
  );

  // ── 添加音符表单 ──
  const [addTrack, setAddTrack] = useState('melody');
  const [addPitch, setAddPitch] = useState(DEFAULT_PITCH);
  const [addBeats, setAddBeats] = useState(DEFAULT_BEATS);
  const [addLyric, setAddLyric] = useState('');
  const [addOffset, setAddOffset] = useState('');

  // ── 属性面板编辑值 ──
  const [editPitch, setEditPitch] = useState('');
  const [editBeats, setEditBeats] = useState('');
  const [editLyric, setEditLyric] = useState('');
  const [editOffset, setEditOffset] = useState('');
  const [editVelocity, setEditVelocity] = useState('');
  const [editMoveOffset, setEditMoveOffset] = useState('');

  // ── 初始化：创建空白草稿 或 载入既有草稿 ──
  useEffect(() => {
    let cancelled = false;
    async function init() {
      try {
        const result = initialDraftId
          ? await resolvedBackend.getDraft(initialDraftId)
          : await resolvedBackend.createDraft();
        if (cancelled) return;
        if (result.success && result.snapshot) {
          setDraftId(result.draft_id ?? initialDraftId ?? null);
          setScore(result.snapshot);
          setVersion(result.version ?? 0);
          handle.setVersion(result.version ?? 0);
        } else {
          setError(result.error ? describeError(result.error) : '初始化草稿失败');
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    }
    init();
    return () => {
      cancelled = true;
    };
  }, [initialDraftId, resolvedBackend, handle]);

  // ── 草稿列表 / 歌曲历史刷新 ──
  const refreshDrafts = useCallback(async () => {
    try {
      const list = await resolvedBackend.listDrafts();
      setDraftList(list ?? []);
    } catch {
      // 静默（草稿列表加载失败不阻断编辑）
    }
  }, [resolvedBackend]);

  const refreshSongs = useCallback(() => {
    api
      .musicListSongs()
      .then((r) => setSongs(r.songs ?? []))
      .catch(() => {});
  }, []);

  useEffect(() => {
    refreshDrafts();
    refreshSongs();
  }, [refreshDrafts, refreshSongs]);

  // ── 任务轮询 ──
  useEffect(() => {
    if (!taskInfo?.songId) return;
    let stopped = false;
    let timer: ReturnType<typeof setInterval>;
    const poll = async () => {
      try {
        const task = await resolvedPollTask(taskInfo.songId);
        if (stopped) return;
        setTaskInfo({
          songId: taskInfo.songId,
          status: task.status,
          audioUrl: task.audio_url ?? undefined,
          error: task.error ?? undefined,
        });
        if (task.status === 'completed' || task.status === 'failed') {
          stopped = true;
          clearInterval(timer);
          if (task.status === 'completed') refreshSongs();
        }
      } catch {
        // 任务查询失败时静默，下一轮继续
      }
    };
    poll();
    timer = setInterval(poll, pollIntervalMs);
    return () => {
      stopped = true;
      clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskInfo?.songId, resolvedPollTask, refreshSongs, pollIntervalMs]);

  // ── 统一编辑入口 ──
  const handleDispatch = useCallback(
    async (command: CommandName, args: Record<string, unknown>): Promise<CommandResult | null> => {
      if (!draftIdRef.current) {
        setError('草稿未初始化，无法编辑');
        return null;
      }
      const result = await handle.dispatch(command, args);
      if (result === null) {
        // version 过期响应被丢弃（防乱序）
        return null;
      }
      if (result.success) {
        if (result.snapshot) setScore(result.snapshot);
        if (result.version !== undefined) setVersion(result.version);
        setError(null);
      } else {
        setError(result.error ? describeError(result.error) : '操作失败');
      }
      return result;
    },
    [handle],
  );

  // ── 四交互 handler ──

  // 1. 添加音符
  const handleAddNote = async () => {
    const args: Record<string, unknown> = {
      track: addTrack,
      pitch: addPitch.trim() || DEFAULT_PITCH,
      beats: Number(addBeats) || DEFAULT_BEATS,
    };
    if (addTrack === 'melody') {
      args.lyric = addLyric;
    } else if (addOffset.trim() !== '') {
      const off = Number(addOffset);
      if (Number.isFinite(off) && off >= 0) args.offset = off;
    }
    await handleDispatch('add_note', args);
  };

  // 2. 选中音符（StaffScore onSelectNote 回调）
  const handleSelectNote = (track: string, noteId: number) => {
    setSelectedNote({ track, noteId });
    setError(null);
  };

  // 当前选中音符数据（属性面板回显）
  const selectedNoteData = useMemo<{
    kind: 'melody' | 'accompaniment';
    note: MelodyNote | TrackEvent;
    track: AccompanimentTrack | null;
  } | null>(() => {
    if (!selectedNote || !score) return null;
    if (selectedNote.track === 'melody') {
      const note = score.melody[selectedNote.noteId];
      return note ? { kind: 'melody', note, track: null } : null;
    }
    const track = score.accompaniment_tracks.find((t) => t.id === selectedNote.track);
    if (!track) return null;
    const event = track.events[selectedNote.noteId];
    return event ? { kind: 'accompaniment', note: event, track } : null;
  }, [selectedNote, score]);

  // 选中音符变化时同步属性面板编辑值
  useEffect(() => {
    if (!selectedNoteData) return;
    const n = selectedNoteData.note;
    setEditPitch(n.pitch);
    setEditBeats(String(n.beats));
    if (selectedNoteData.kind === 'melody') {
      setEditLyric((n as MelodyNote).lyric ?? '');
      setEditOffset('');
      setEditVelocity('');
      setEditMoveOffset(String(selectedNote?.noteId ?? 0));
    } else {
      const ev = n as TrackEvent;
      setEditOffset(String(ev.offset));
      setEditVelocity(String(ev.velocity ?? 64));
      setEditMoveOffset(String(ev.offset));
      setEditLyric('');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedNoteData]);

  // 2. 选中修改：update_note（pitch/beats/offset/velocity）
  const handleUpdateNote = async () => {
    if (!selectedNote) return;
    const patch: Record<string, unknown> = {};
    if (editPitch.trim()) patch.pitch = editPitch.trim();
    const beats = Number(editBeats);
    if (Number.isFinite(beats) && beats > 0) patch.beats = beats;
    if (selectedNote.track !== 'melody') {
      const off = Number(editOffset);
      if (Number.isFinite(off) && off >= 0) patch.offset = off;
      const vel = Number(editVelocity);
      if (Number.isInteger(vel) && vel >= 1 && vel <= 127) patch.velocity = vel;
    }
    if (Object.keys(patch).length === 0) return;
    await handleDispatch('update_note', {
      track: selectedNote.track,
      note_id: selectedNote.noteId,
      patch,
    });
  };

  // 4. 歌词行内编辑：set_lyric（blur/Enter 提交）
  const handleCommitLyric = async () => {
    if (!selectedNote || selectedNote.track !== 'melody') return;
    await handleDispatch('set_lyric', {
      note_id: selectedNote.noteId,
      lyric: editLyric,
    });
  };

  // 3. 拖拽调整（首版简化）：move_note（new_offset + 可选 new_pitch）
  const handleMoveNote = async () => {
    if (!selectedNote) return;
    const newOffset = Number(editMoveOffset);
    if (!Number.isFinite(newOffset) || newOffset < 0) return;
    const args: Record<string, unknown> = {
      track: selectedNote.track,
      note_id: selectedNote.noteId,
      new_offset: newOffset,
    };
    if (editPitch.trim()) args.new_pitch = editPitch.trim();
    await handleDispatch('move_note', args);
  };

  // 删除音符
  const handleDeleteNote = async () => {
    if (!selectedNote) return;
    await handleDispatch('delete_note', {
      track: selectedNote.track,
      note_id: selectedNote.noteId,
    });
    setSelectedNote(null);
  };

  // ── 草稿管理 ──
  const handleLoadDraft = async (id: string) => {
    try {
      const result = await resolvedBackend.getDraft(id);
      if (result.success && result.snapshot) {
        setDraftId(id);
        setScore(result.snapshot);
        setVersion(result.version ?? 0);
        handle.setVersion(result.version ?? 0);
        setSelectedNote(null);
        setError(null);
        setInfo(`已载入草稿 ${id}`);
      } else {
        setError(result.error ? describeError(result.error) : '载入失败');
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleNewDraft = async () => {
    try {
      const result = await resolvedBackend.createDraft();
      if (result.success && result.snapshot) {
        setDraftId(result.draft_id ?? null);
        setScore(result.snapshot);
        setVersion(result.version ?? 0);
        handle.setVersion(result.version ?? 0);
        setSelectedNote(null);
        setError(null);
        setInfo('已创建空白草稿');
        refreshDrafts();
      } else {
        setError(result.error ? describeError(result.error) : '创建失败');
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  // ── 提交合成 ──
  // submit_draft 非谱面编辑命令（不递增 version），走 backend.execute 直调：
  // 一则提交结果（task_id/song_id）不应被 VersionGuard 当作过期响应丢弃，
  // 二则 submit 语义本就不属于"编辑总线"受控范畴（merged.md §6 编辑命令限定）。
  const handleSubmit = async () => {
    if (!draftId) return;
    setSubmitting(true);
    setError(null);
    setTaskInfo(null);
    try {
      const result = await resolvedBackend.execute({
        command: 'submit_draft',
        args: { draft_id: draftId },
      });
      setSubmitting(false);
      if (result.success && result.result) {
        const r = result.result as { task_id?: string; song_id?: string; status?: string };
        if (r.song_id) {
          setTaskInfo({ songId: r.song_id, status: r.status ?? 'pending' });
          setInfo(`已提交合成，任务 ${r.task_id ?? r.song_id}`);
        } else {
          setInfo('提交合成已受理（未返回 song_id）');
        }
      } else {
        setError(result.error ? describeError(result.error) : '提交合成失败');
      }
    } catch (e) {
      setSubmitting(false);
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  // ── 歌曲历史操作 ──
  const handleDeleteSong = async (songId: string) => {
    if (!window.confirm('确认删除该歌曲？')) return;
    try {
      await api.musicDeleteSong(songId);
      if (taskInfo?.songId === songId) setTaskInfo(null);
      refreshSongs();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const taskBadgeVariant = (status: string) =>
    status === 'completed'
      ? 'success'
      : status === 'failed'
        ? 'error'
        : status === 'running'
          ? 'warning'
          : 'default';

  const trackOptions = useMemo(() => {
    const opts: Array<{ value: string; label: string }> = [{ value: 'melody', label: '主旋律' }];
    if (score) {
      for (const t of score.accompaniment_tracks) {
        opts.push({ value: t.id, label: t.name });
      }
    }
    return opts;
  }, [score]);

  return (
    <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
      {/* ── 左栏：五线谱 + 音符交互 ── */}
      <div className="xl:col-span-2 space-y-6">
        <Card>
          <CardBody className="space-y-4">
            <div className="flex items-center justify-between flex-wrap gap-2">
              <div className="flex items-center gap-2">
                <h3 className="text-sm font-medium text-[var(--color-text-primary)]">五线谱总谱</h3>
                {draftId && (
                  <Badge variant="default" data-testid="draft-badge">
                    {draftId} · v{version}
                  </Badge>
                )}
              </div>
              <div className="flex gap-2">
                <Button variant="secondary" size="sm" onClick={refreshDrafts}>
                  刷新草稿
                </Button>
                <Button variant="secondary" size="sm" onClick={handleNewDraft} data-testid="new-draft-btn">
                  新建草稿
                </Button>
              </div>
            </div>

            {error && (
              <div
                className="p-3 rounded-lg bg-red-50 border border-red-200 text-sm text-red-700"
                role="alert"
                data-testid="error-banner"
              >
                {error}
              </div>
            )}
            {info && (
              <div
                className="p-3 rounded-lg bg-green-50 border border-green-200 text-sm text-green-700"
                data-testid="info-banner"
              >
                {info}
              </div>
            )}

            {score ? (
              <StaffScore
                score={score}
                selectedNote={selectedNote}
                onSelectNote={handleSelectNote}
                width={760}
              />
            ) : (
              <div
                className="py-12 text-center text-sm text-[var(--color-text-tertiary)]"
                data-testid="loading"
              >
                正在初始化草稿…
              </div>
            )}
          </CardBody>
        </Card>

        {score && (
          <Card>
            <CardBody className="space-y-5">
              {/* 1. 添加音符 */}
              <div className="space-y-3" data-testid="add-note-panel">
                <h4 className="text-sm font-medium text-[var(--color-text-secondary)]">添加音符</h4>
                <div className="grid grid-cols-2 md:grid-cols-5 gap-2 items-end">
                  <div>
                    <label className="block text-xs text-[var(--color-text-tertiary)] mb-1">轨</label>
                    <select
                      className={selectClassName}
                      value={addTrack}
                      onChange={(e) => setAddTrack(e.target.value)}
                      data-testid="add-track-select"
                    >
                      {trackOptions.map((o) => (
                        <option key={o.value} value={o.value}>
                          {o.label}
                        </option>
                      ))}
                    </select>
                  </div>
                  <Input
                    label="音高"
                    value={addPitch}
                    onChange={(e) => setAddPitch(e.target.value)}
                    placeholder="C4"
                    data-testid="add-pitch-input"
                  />
                  <Input
                    label="拍数"
                    type="number"
                    step="0.25"
                    value={addBeats}
                    onChange={(e) => setAddBeats(Number(e.target.value))}
                    data-testid="add-beats-input"
                  />
                  {addTrack === 'melody' ? (
                    <Input
                      label="歌词"
                      value={addLyric}
                      onChange={(e) => setAddLyric(e.target.value)}
                      placeholder="你"
                      data-testid="add-lyric-input"
                    />
                  ) : (
                    <Input
                      label="offset"
                      type="number"
                      step="0.5"
                      value={addOffset}
                      onChange={(e) => setAddOffset(e.target.value)}
                      placeholder="追加"
                      data-testid="add-offset-input"
                    />
                  )}
                  <Button onClick={handleAddNote} data-testid="add-note-btn">
                    添加
                  </Button>
                </div>
              </div>

              {/* 2/3/4. 选中音符属性面板 */}
              {selectedNoteData && (
                <div
                  className="space-y-3 p-3 rounded-lg bg-[var(--color-bg-tertiary)]"
                  data-testid="note-prop-panel"
                >
                  <div className="flex items-center justify-between">
                    <h4 className="text-sm font-medium text-[var(--color-text-secondary)]">
                      选中：
                      {selectedNote?.track === 'melody'
                        ? '主旋律'
                        : selectedNoteData.track?.name}{' '}
                      #{selectedNote?.noteId}
                    </h4>
                    <Button
                      variant="danger"
                      size="sm"
                      onClick={handleDeleteNote}
                      data-testid="delete-note-btn"
                    >
                      删除
                    </Button>
                  </div>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                    <Input
                      label="音高"
                      value={editPitch}
                      onChange={(e) => setEditPitch(e.target.value)}
                      data-testid="edit-pitch-input"
                    />
                    <Input
                      label="拍数"
                      type="number"
                      step="0.25"
                      value={editBeats}
                      onChange={(e) => setEditBeats(e.target.value)}
                      data-testid="edit-beats-input"
                    />
                    {selectedNoteData.kind === 'melody' ? (
                      <Input
                        label="歌词（blur 提交 set_lyric）"
                        value={editLyric}
                        onChange={(e) => setEditLyric(e.target.value)}
                        onBlur={handleCommitLyric}
                        onKeyDown={(e) => {
                          // Enter 直接提交（jsdom 下 e.target.blur() 不能可靠触发
                          // React 合成 onBlur，故直接调 handler；真实浏览器亦保留 blur 提交路径）
                          if (e.key === 'Enter') handleCommitLyric();
                        }}
                        data-testid="edit-lyric-input"
                      />
                    ) : (
                      <>
                        <Input
                          label="offset"
                          type="number"
                          step="0.5"
                          value={editOffset}
                          onChange={(e) => setEditOffset(e.target.value)}
                          data-testid="edit-offset-input"
                        />
                        <Input
                          label="力度"
                          type="number"
                          min={1}
                          max={127}
                          value={editVelocity}
                          onChange={(e) => setEditVelocity(e.target.value)}
                          data-testid="edit-velocity-input"
                        />
                      </>
                    )}
                  </div>
                  <div className="flex flex-wrap items-end gap-2">
                    <Button size="sm" onClick={handleUpdateNote} data-testid="update-note-btn">
                      应用修改（update_note）
                    </Button>
                    <div className="w-44">
                      <Input
                        label="移动落点"
                        type="number"
                        step="0.5"
                        value={editMoveOffset}
                        onChange={(e) => setEditMoveOffset(e.target.value)}
                        data-testid="move-offset-input"
                      />
                    </div>
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={handleMoveNote}
                      data-testid="move-note-btn"
                    >
                      移动（move_note）
                    </Button>
                  </div>
                </div>
              )}
            </CardBody>
          </Card>
        )}
      </div>

      {/* ── 右栏：轨道管理 + 合成 + 草稿列表 + 歌曲历史 ── */}
      <div className="space-y-6">
        {score && <TrackManager score={score} onDispatch={handleDispatch} />}

        <Card>
          <CardBody className="space-y-3">
            <h3 className="text-sm font-medium text-[var(--color-text-primary)]">合成</h3>
            <Button
              onClick={handleSubmit}
              loading={submitting}
              disabled={submitting || !draftId}
              data-testid="submit-btn"
            >
              提交合成（submit_draft）
            </Button>
            {taskInfo && (
              <div className="space-y-2" data-testid="task-info">
                <div className="flex items-center gap-2">
                  <span className="text-xs text-[var(--color-text-tertiary)]">任务状态</span>
                  <Badge variant={taskBadgeVariant(taskInfo.status)}>{taskInfo.status}</Badge>
                </div>
                {taskInfo.error && <p className="text-xs text-red-500">{taskInfo.error}</p>}
                {taskInfo.audioUrl && (
                  <audio
                    controls
                    className="w-full"
                    src={getVoiceWorkstationAudioUrl(taskInfo.audioUrl)}
                    data-testid="audio-player"
                  />
                )}
              </div>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardBody className="space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-medium text-[var(--color-text-primary)]">草稿列表</h3>
              <Button variant="secondary" size="sm" onClick={refreshDrafts}>
                刷新
              </Button>
            </div>
            {draftList.length === 0 ? (
              <p className="text-sm text-[var(--color-text-tertiary)]">暂无草稿</p>
            ) : (
              <div className="space-y-1.5" data-testid="draft-list">
                {draftList.map((d) => (
                  <div
                    key={d.draft_id}
                    className="flex items-center justify-between px-2 py-1.5 rounded bg-[var(--color-bg-tertiary)]"
                  >
                    <button
                      className="text-sm text-left truncate flex-1"
                      onClick={() => handleLoadDraft(d.draft_id)}
                      data-testid={`load-draft-${d.draft_id}`}
                    >
                      <span className="font-medium">{d.title}</span>
                      <span className="ml-2 text-xs text-[var(--color-text-tertiary)]">
                        v{d.version}
                      </span>
                    </button>
                    <span className="text-xs text-[var(--color-text-tertiary)]">{d.draft_id}</span>
                  </div>
                ))}
              </div>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardBody className="space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-medium text-[var(--color-text-primary)]">歌曲历史</h3>
              <Button variant="secondary" size="sm" onClick={refreshSongs}>
                刷新
              </Button>
            </div>
            {songs.length === 0 ? (
              <p className="text-sm text-[var(--color-text-tertiary)]">暂无歌曲</p>
            ) : (
              <div className="space-y-2">
                {songs.map((song) => (
                  <div
                    key={song.song_id}
                    className="px-2 py-1.5 rounded bg-[var(--color-bg-tertiary)] flex items-center justify-between gap-2"
                  >
                    <div className="flex-1 min-w-0">
                      <div className="text-sm truncate">{song.title}</div>
                      <div className="flex items-center gap-1.5">
                        <Badge variant={taskBadgeVariant(song.status)}>{song.status}</Badge>
                        {song.audio_url && (
                          <a
                            className="text-xs text-[var(--color-accent)] underline"
                            href={getVoiceWorkstationAudioUrl(song.audio_url as string)}
                            target="_blank"
                            rel="noreferrer"
                          >
                            播放
                          </a>
                        )}
                      </div>
                    </div>
                    <Button
                      variant="danger"
                      size="sm"
                      onClick={() => handleDeleteSong(song.song_id)}
                    >
                      删除
                    </Button>
                  </div>
                ))}
              </div>
            )}
          </CardBody>
        </Card>
      </div>
    </div>
  );
}

export default CompositionPanel;
