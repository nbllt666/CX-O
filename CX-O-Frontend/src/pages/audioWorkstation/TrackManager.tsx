/**
 * TrackManager.tsx — 轨道管理面板（模块7，merged.md §6 轨道管理面板）
 *
 * 职责：
 *  - 轨道列表：主旋律（只读）+ 各伴奏轨（id/name/program/mode）
 *  - 增删轨：dispatch add_track / remove_track
 *  - GM 128 分组选乐器：16 组 × 8 音色 optgroup + 打击乐 program=-1
 *  - 自动手动模式切换：dispatch set_track_mode
 *  - 节奏型选择（auto 轨）：dispatch arrange_track（物化生成）+ set_track_mix
 *  - 音量/声像滑块（0–127）：经防抖 dispatch set_track_mix（300ms 合并）
 *
 * 全部经命令分发层，无旁路状态（AGENTS.md §3.2 binding_rules）。
 * inventory 数据源：staff/__mocks__/inventory.ts（前后端同源生成副本，AccompanimentStaff 同款 import）。
 */
import { useState, useMemo } from 'react';
import { Button, Card, CardBody, Input, Badge } from '@/components/ui-v2';
import type {
  ScoreV2,
  AccompanimentTrack,
  CommandName,
  CommandResult,
} from './staff/types';
import { INVENTORY } from './staff/__mocks__/inventory';
import { createDebouncedDispatch, type Dispatch } from './dispatch';

export interface TrackManagerProps {
  score: ScoreV2;
  /** 命令分发入口（由 CompositionPanel 传入 handleDispatch） */
  onDispatch: (
    command: CommandName,
    args: Record<string, unknown>,
  ) => Promise<CommandResult | null>;
  /** set_track_mix 防抖延迟（默认 300ms；测试可缩短） */
  mixDebounceMs?: number;
}

const selectClassName =
  'w-full px-2 py-1.5 text-sm rounded-[var(--radius-lg)] bg-[var(--glass-surface)] text-[var(--color-text-primary)] border border-[var(--glass-border)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)] focus:border-transparent transition-all';

export function TrackManager({ score, onDispatch, mixDebounceMs = 300 }: TrackManagerProps) {
  // 防抖 dispatch（set_track_mix 滑杆连续微调合并为一次）
  const debouncedDispatch = useMemo<Dispatch>(
    () => createDebouncedDispatch(onDispatch, mixDebounceMs),
    [onDispatch, mixDebounceMs],
  );

  // ── 添加轨表单 ──
  const [newName, setNewName] = useState('钢琴');
  const [newProgram, setNewProgram] = useState(0);
  const [newMode, setNewMode] = useState<'auto' | 'manual'>('auto');
  const [newStyle, setNewStyle] = useState('');

  // 新轨可选节奏型（按 mode+program 类型过滤，与 arranger applies_to 对齐）
  const newTrackStyles = useMemo(() => {
    if (newMode === 'manual') return [];
    const kind = newProgram === -1 ? 'percussion' : 'melodic';
    return INVENTORY.styles.filter((s) => s.applies_to === kind);
  }, [newMode, newProgram]);

  // ── 命令 handler ──
  const handleAddTrack = async () => {
    const args: Record<string, unknown> = {
      name: newName.trim() || '新轨',
      program: newProgram,
      mode: newMode,
    };
    if (newStyle && newMode === 'auto') args.style = newStyle;
    await onDispatch('add_track', args);
  };

  const handleRemoveTrack = async (trackId: string) => {
    await onDispatch('remove_track', { track_id: trackId });
  };

  const handleSetInstrument = async (trackId: string, program: number) => {
    await onDispatch('set_track_instrument', { track_id: trackId, program });
  };

  const handleSetMode = async (trackId: string, mode: 'auto' | 'manual') => {
    await onDispatch('set_track_mode', { track_id: trackId, mode });
  };

  const handleArrange = async (trackId: string, style?: string) => {
    const args: Record<string, unknown> = { track_id: trackId };
    if (style) args.style = style;
    await onDispatch('arrange_track', args);
  };

  // 音量/声像：防抖合并（连续微调 300ms 内只发最后一次）
  const handleSetMix = async (trackId: string, volume?: number, pan?: number) => {
    const args: Record<string, unknown> = { track_id: trackId };
    if (volume !== undefined) args.volume = Math.round(volume);
    if (pan !== undefined) args.pan = Math.round(pan);
    await debouncedDispatch('set_track_mix', args);
  };

  // 轨可用节奏型（按 program 类型过滤）
  const stylesForTrack = (track: AccompanimentTrack) => {
    const kind = track.program === -1 ? 'percussion' : 'melodic';
    return INVENTORY.styles.filter((s) => s.applies_to === kind);
  };

  // GM 音色选择器选项（16 组 optgroup + 打击乐）
  const instrumentOptions = (
    <>
      <option value={-1}>打击乐（鼓组）</option>
      {INVENTORY.instrument_groups.map((g) => (
        <optgroup key={g.group_id} label={g.name}>
          {g.instruments.map((inst) => (
            <option key={inst.program} value={inst.program}>
              {inst.name}
            </option>
          ))}
        </optgroup>
      ))}
    </>
  );

  return (
    <Card>
      <CardBody className="space-y-4" data-testid="track-manager">
        <h3 className="text-sm font-medium text-[var(--color-text-primary)]">轨道管理</h3>

        {/* 主旋律（只读展示） */}
        <div
          className="px-3 py-2 rounded-[var(--radius-lg)] bg-[var(--glass-surface)] border border-[var(--glass-border)]"
          data-testid="track-melody"
        >
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium">主旋律</span>
            <Badge variant="default">旋律轨</Badge>
          </div>
          <p className="text-xs text-[var(--color-text-tertiary)] mt-1">
            {score.melody.length} 个音符（逐字歌词）
          </p>
        </div>

        {/* 伴奏轨列表 */}
        {score.accompaniment_tracks.map((track) => (
          <div
            key={track.id}
            className="px-3 py-2 rounded-[var(--radius-lg)] bg-[var(--glass-surface)] border border-[var(--glass-border)] space-y-2"
            data-testid={`track-${track.id}`}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm font-medium truncate">{track.name}</span>
              <div className="flex items-center gap-1">
                <Badge variant={track.mode === 'auto' ? 'warning' : 'default'}>{track.mode}</Badge>
                <Button
                  variant="danger"
                  size="sm"
                  onClick={() => handleRemoveTrack(track.id)}
                  data-testid={`remove-track-${track.id}`}
                >
                  删除
                </Button>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="block text-xs text-[var(--color-text-tertiary)] mb-1">音色</label>
                <select
                  className={selectClassName}
                  value={track.program}
                  onChange={(e) => handleSetInstrument(track.id, Number(e.target.value))}
                  data-testid={`instrument-${track.id}`}
                >
                  {instrumentOptions}
                </select>
              </div>
              <div>
                <label className="block text-xs text-[var(--color-text-tertiary)] mb-1">模式</label>
                <select
                  className={selectClassName}
                  value={track.mode}
                  onChange={(e) =>
                    handleSetMode(track.id, e.target.value as 'auto' | 'manual')
                  }
                  data-testid={`mode-${track.id}`}
                >
                  <option value="auto">auto（自动编排）</option>
                  <option value="manual">manual（逐音符）</option>
                </select>
              </div>
            </div>

            {track.mode === 'auto' && (
              <div className="flex items-end gap-2">
                <div className="flex-1">
                  <label className="block text-xs text-[var(--color-text-tertiary)] mb-1">
                    节奏型
                  </label>
                  <select
                    className={selectClassName}
                    value={track.style}
                    onChange={(e) => handleArrange(track.id, e.target.value || undefined)}
                    data-testid={`style-${track.id}`}
                  >
                    <option value="">（默认）</option>
                    {stylesForTrack(track).map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.name}
                      </option>
                    ))}
                  </select>
                </div>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => handleArrange(track.id)}
                  data-testid={`arrange-${track.id}`}
                >
                  编排
                </Button>
              </div>
            )}

            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="block text-xs text-[var(--color-text-tertiary)] mb-1">
                  音量 {track.volume}
                </label>
                <input
                  type="range"
                  min={0}
                  max={127}
                  value={track.volume}
                  onChange={(e) =>
                    handleSetMix(track.id, Number(e.target.value), undefined)
                  }
                  data-testid={`volume-${track.id}`}
                  className="w-full"
                />
              </div>
              <div>
                <label className="block text-xs text-[var(--color-text-tertiary)] mb-1">
                  声像 {track.pan}
                </label>
                <input
                  type="range"
                  min={0}
                  max={127}
                  value={track.pan}
                  onChange={(e) =>
                    handleSetMix(track.id, undefined, Number(e.target.value))
                  }
                  data-testid={`pan-${track.id}`}
                  className="w-full"
                />
              </div>
            </div>

            <p className="text-xs text-[var(--color-text-tertiary)]">
              {track.events.length} 个事件 · id: {track.id}
            </p>
          </div>
        ))}

        {/* 添加伴奏轨 */}
        <div
          className="space-y-2 p-3 rounded border border-[var(--color-border)]"
          data-testid="add-track-panel"
        >
          <h4 className="text-sm font-medium text-[var(--color-text-secondary)]">添加伴奏轨</h4>
          <div className="grid grid-cols-2 gap-2">
            <Input
              label="名称"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              data-testid="new-track-name"
            />
            <div>
              <label className="block text-xs text-[var(--color-text-tertiary)] mb-1">音色</label>
              <select
                className={selectClassName}
                value={newProgram}
                onChange={(e) => setNewProgram(Number(e.target.value))}
                data-testid="new-track-program"
              >
                {instrumentOptions}
              </select>
            </div>
            <div>
              <label className="block text-xs text-[var(--color-text-tertiary)] mb-1">模式</label>
              <select
                className={selectClassName}
                value={newMode}
                onChange={(e) => setNewMode(e.target.value as 'auto' | 'manual')}
                data-testid="new-track-mode"
              >
                <option value="auto">auto</option>
                <option value="manual">manual</option>
              </select>
            </div>
            <div>
              <label className="block text-xs text-[var(--color-text-tertiary)] mb-1">
                节奏型（auto）
              </label>
              <select
                className={selectClassName}
                value={newStyle}
                onChange={(e) => setNewStyle(e.target.value)}
                data-testid="new-track-style"
                disabled={newMode === 'manual'}
              >
                <option value="">（默认）</option>
                {newTrackStyles.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <Button size="sm" onClick={handleAddTrack} data-testid="add-track-btn">
            添加轨道
          </Button>
        </div>
      </CardBody>
    </Card>
  );
}

export default TrackManager;
