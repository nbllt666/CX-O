import { describe, it, expect } from 'vitest';
import type { Memory } from '@/api/types';
import { filterBySource, getVisionMeta, isVisionMemory } from './memoryFilter';

/**
 * 记忆来源过滤纯函数单测（记忆管理页增强）：
 * 覆盖「选中『视觉』后仅保留 source==='vision' 的记忆」，以及
 * metadata.source==='vision'、tags 含 vision/visual 的兼容后备路径。
 */
const base = (over: Partial<Memory>): Memory => ({
  id: 1,
  content: '记忆',
  type: 'long_term',
  importance: 3,
  tags: [],
  created_at: '2026-08-01 00:00:00',
  is_archived: false,
  ...over,
});

// 视觉：列级 source='vision'（路径 A 唯一权威标记）
const visionByColumn = base({ id: 1, source: 'vision', metadata: { source: 'vision' } });
// 视觉后备：仅 metadata.source='vision'（无顶层 source）
const visionByMeta = base({ id: 2, metadata: { source: 'vision' } });
// 视觉后备：仅 tags 含 'visual'
const visionByTag = base({ id: 3, tags: ['visual', 'narrative'] });
// 普通记忆：source='user'
const ordinary = base({ id: 4, source: 'user', tags: ['日常'] });

const all = [visionByColumn, visionByMeta, visionByTag, ordinary];

describe('filterBySource 记忆来源过滤', () => {
  it("'all' 返回全部记忆（原数组）", () => {
    expect(filterBySource(all, 'all')).toBe(all);
    expect(filterBySource(all, 'all')).toHaveLength(4);
  });

  it("'vision' 仅保留 source==='vision' 的记忆", () => {
    const result = filterBySource(all, 'vision');
    expect(result.map((m) => m.id)).toEqual([1, 2, 3]);
    expect(result).not.toContain(ordinary);
  });

  it('仅仅依赖顶层 source===\'vision\' 即可命中，无需额外 TLS', () => {
    expect(filterBySource([visionByColumn], 'vision')).toHaveLength(1);
  });

  it('空输入返回空数组', () => {
    expect(filterBySource([], 'vision')).toEqual([]);
  });
});

describe('isVisionMemory 视觉记忆判定', () => {
  it('列级 source 或 metadata.source/tags 任一命中即为视觉记忆', () => {
    expect(isVisionMemory(visionByColumn)).toBe(true);
    expect(isVisionMemory(visionByMeta)).toBe(true);
    expect(isVisionMemory(visionByTag)).toBe(true);
    expect(isVisionMemory(ordinary)).toBe(false);
  });

  it('tags 关键词大小写不敏感且只匹配精确标签', () => {
    expect(isVisionMemory(base({ id: 9, tags: ['Visual'] }))).toBe(true);
    expect(isVisionMemory(base({ id: 10, tags: ['visual_memories'] }))).toBe(false);
  });
});

describe('getVisionMeta 可视化元数据提取', () => {
  it('提取 event_type / emotion / source，缺失字段为 undefined', () => {
    const meta = getVisionMeta(visionByColumn);
    expect(meta).toEqual({ event_type: undefined, emotion: undefined, source: 'vision' });

    const rich = getVisionMeta(
      base({ id: 5, metadata: { source: 'vision', event_type: '宠物玩耍', emotion: '快乐' } }),
    );
    expect(rich).toEqual({ event_type: '宠物玩耍', emotion: '快乐', source: 'vision' });
  });

  it('无 metadata 时返回空对象（不抛错）', () => {
    expect(getVisionMeta(base({ id: 6 }))).toEqual({
      event_type: undefined,
      emotion: undefined,
      source: undefined,
    });
  });
});