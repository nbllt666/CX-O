/**
 * StaffScore.test.tsx — 模块6 五线谱渲染层 vitest 冒烟测试
 *
 * spec: redesign-composition-staff-editor，AGENTS.md §3.3 要求：
 * "VexFlow 渲染层快照 fixture 冒烟（jsdom SVG 存在性）"。
 * 自 CX-O-Frontend 迁移（Task 3.3），相对路径依赖原样保留。
 */
import { describe, it, expect, vi, beforeEach, beforeAll } from 'vitest';
import { render } from '@testing-library/react';
import { Element as VexElement } from 'vexflow';
import { StaffScore } from '../StaffScore';
import { clefForTrack } from '../useVexflow';
import { getFixture } from '../__mocks__/fixtures';
import type { ScoreV2 } from '../types';

// jsdom 不实现 HTMLCanvasElement.prototype.getContext，VexFlow 的 Clef/TimeSignature/Barline/
// Stave 宽度计算经 Element.measureText → canvas.getContext('2d') 会抛 not-implemented。
// 用 VexFlow 官方 Element.setTextMeasurementCanvas 注入桩 canvas，measureText 返回固定宽度。
beforeAll(() => {
  const mockCtx = {
    measureText: (text: string) => ({ width: text.length * 6 + 4 }),
    font: '10px sans-serif',
  } as unknown as CanvasRenderingContext2D;
  const mockCanvas = { getContext: () => mockCtx } as unknown as HTMLCanvasElement;
  VexElement.setTextMeasurementCanvas(mockCanvas);
});

/** 把夹具（可能缺省 default 字段）规范化为完整 ScoreV2（模拟 validate_score 后的快照形状） */
function normalizeScore(raw: Record<string, unknown>): ScoreV2 {
  return {
    title: (raw.title as string) ?? '未命名',
    bpm: (raw.bpm as number) ?? 120,
    time_signature: (raw.time_signature as string) ?? '4/4',
    key: (raw.key as string) ?? 'C',
    melody: (raw.melody as ScoreV2['melody']) ?? [],
    chords: (raw.chords as ScoreV2['chords']) ?? [],
    accompaniment_tracks: (raw.accompaniment_tracks as ScoreV2['accompaniment_tracks']) ?? [],
  };
}

/** 统计容器内命中的音符元素数量（VexFlow 渲染的 SVG notehead） */
function countNoteheads(container: HTMLElement): number {
  const byClass = container.querySelectorAll('.vf-notehead').length;
  const byData = container.querySelectorAll('[data-noteid]').length;
  return Math.max(byClass, byData);
}

describe('StaffScore — 模块6 五线谱渲染层冒烟', () => {
  beforeEach(() => {
    vi.spyOn(console, 'warn').mockImplementation(() => {});
  });

  it('场景1：渲染空歌谱（仅 melody 占位）不报错', () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const score = normalizeScore(getFixture('minimal_v2'));
    const { container } = render(<StaffScore score={score} />);
    expect(container.querySelector('[data-testid="staff-score"]')).toBeTruthy();
    expect(container.querySelector('[data-testid="melody-staff-svg"]')).toBeTruthy();
    const svg = container.querySelector('svg');
    expect(svg).toBeTruthy();
    expect(errorSpy).not.toHaveBeenCalled();
    errorSpy.mockRestore();
  });

  it('场景2：渲染 1 旋律 + 1 伴奏轨，SVG 输出含正确数量的音符', () => {
    const score = normalizeScore(getFixture('full_multitrack_v2'));
    const { container } = render(<StaffScore score={score} />);

    expect(container.querySelector('[data-testid="melody-staff-svg"]')).toBeTruthy();
    expect(container.querySelector('[data-testid="accompaniment-staff-trk_piano"]')).toBeTruthy();
    expect(container.querySelector('[data-testid="accompaniment-staff-trk_bass"]')).toBeTruthy();
    expect(container.querySelector('[data-testid="accompaniment-staff-trk_drum"]')).toBeTruthy();

    const melodyStaff = container.querySelector('[data-testid="melody-staff-svg"]') as HTMLElement;
    const bassStaff = container.querySelector('[data-testid="accompaniment-staff-trk_bass"]') as HTMLElement;
    expect(countNoteheads(melodyStaff)).toBeGreaterThanOrEqual(3);
    expect(countNoteheads(bassStaff)).toBeGreaterThanOrEqual(4);

    const pianoStaff = container.querySelector('[data-testid="accompaniment-staff-trk_piano"]') as HTMLElement;
    const drumStaff = container.querySelector('[data-testid="accompaniment-staff-trk_drum"]') as HTMLElement;
    expect(countNoteheads(pianoStaff)).toBe(0);
    expect(countNoteheads(drumStaff)).toBe(0);
  });

  it('场景3：打击乐轨用 percussion clef', () => {
    expect(clefForTrack(-1)).toBe('percussion');
    expect(clefForTrack(0)).toBe('treble');
    expect(clefForTrack(33)).toBe('bass');

    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const score = normalizeScore(getFixture('full_multitrack_v2'));
    const { container } = render(<StaffScore score={score} />);

    const drumStaff = container.querySelector('[data-testid="accompaniment-staff-trk_drum"]') as HTMLElement;
    expect(drumStaff).toBeTruthy();
    const svg = drumStaff.querySelector('svg');
    expect(svg).toBeTruthy();
    expect(drumStaff.parentElement?.textContent).toContain('鼓组');
    expect(drumStaff.parentElement?.textContent).toContain('打击乐');
    expect(errorSpy).not.toHaveBeenCalled();
    errorSpy.mockRestore();
  });

  it('场景4：选中态高亮（selectedNote 命中的音符红色 setStyle）', () => {
    const score = normalizeScore(getFixture('melody_only_v2'));
    const { container } = render(
      <StaffScore score={score} selectedNote={{ track: 'melody', noteId: 0 }} />,
    );

    const redElements = container.querySelectorAll('[fill="#dc2626"], [stroke="#dc2626"]');
    expect(redElements.length).toBeGreaterThan(0);
  });

  it('场景5：props 变化重渲（score 变化 → SVG 音符数量变化）', () => {
    const one = normalizeScore(getFixture('minimal_v2'));
    const three = normalizeScore(getFixture('melody_only_v2'));

    const { container, rerender } = render(<StaffScore score={one} />);
    const melodyStaff = () => container.querySelector('[data-testid="melody-staff-svg"]') as HTMLElement;
    const count1 = countNoteheads(melodyStaff());
    expect(count1).toBeGreaterThanOrEqual(1);

    rerender(<StaffScore score={three} />);
    const count2 = countNoteheads(melodyStaff());
    expect(count2).toBeGreaterThanOrEqual(3);
    expect(count2).toBeGreaterThan(count1);
  });
});