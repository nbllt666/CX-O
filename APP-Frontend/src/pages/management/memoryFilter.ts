/**
 * 视觉记忆筛选纯函数（记忆管理页增强）
 *
 * 过滤依据（以现有后端返回字段为准）：
 * - 后端记忆行 `crud_mixin._row_to_memory` 返回顶层 `source` 字段（见
 *   CX-O-SERVER/server/core/memory/mixins/crud_mixin.py）；vision 叙事记忆落库时
 *   source='vision'（路径 A：列级 source，唯一权威标记，见 narrative_memory.py）。
 * - 兼容后备：metadata.source==='vision'（视觉增强写入的检索冗余字段），或
 *   tags 含 'vision'/'visual'/'narrative'（叙事沉淀器写入的标签）。
 * 本页对 GET /api/memories 返回的列表做前端侧过滤（该端点无 source 查询参数，不改后端）。
 */
import type { Memory } from '@/api/types';

/** 来源过滤取值：全部 / 视觉记忆 */
export type MemorySourceFilter = 'all' | 'vision';

/** 视觉叙事记忆可视化元数据（缺失即 undefined，不强求展示） */
export interface VisionMemoryMeta {
  event_type?: string;
  emotion?: string;
  source?: string;
}

/** 视觉增强写入标签的关键词（冗余承载，仅当列级 source 缺失时兜底） */
const VISION_TAGS = ['vision', 'visual', 'narrative'];

/** 判断是否为视觉叙事记忆 */
export function isVisionMemory(m: Memory): boolean {
  // 首选：列级 source==='vision'（路径 A 唯一权威标记）
  if (m.source === 'vision') return true;
  // 后备：metadata.source==='vision'
  const meta = (m.metadata ?? {}) as Record<string, unknown>;
  if (meta.source === 'vision') return true;
  // 再后备：tags 含 vision/visual/narrative
  return (
    Array.isArray(m.tags) &&
    m.tags.some((tag) => VISION_TAGS.includes(String(tag).toLowerCase()))
  );
}

/** 提取视觉叙事记忆的可视化元数据 */
export function getVisionMeta(m: Memory): VisionMemoryMeta {
  const meta = (m.metadata ?? {}) as Record<string, unknown>;
  return {
    event_type: typeof meta.event_type === 'string' ? meta.event_type : undefined,
    emotion: typeof meta.emotion === 'string' ? meta.emotion : undefined,
    source: typeof meta.source === 'string' ? meta.source : undefined,
  };
}

/** 按来源过滤记忆：'all' 返回原数组；'vision' 仅保留视觉叙事记忆 */
export function filterBySource(memories: Memory[], filter: MemorySourceFilter): Memory[] {
  if (filter !== 'vision') return memories;
  return memories.filter(isVisionMemory);
}