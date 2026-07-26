/**
 * @file index.ts — live 子目录统一导出（模块7）
 * ============================================================================
 * 模块: 模块7 业务组件重组层 — B 组直播类（live 子目录）
 * 落点: C:\CX-O\CX-O-Frontend\src\components\business\live\index.ts
 * 原组件: src/components/Live/（DanmakuOverlay/LiveStage/SubtitleDisplay）
 *
 * 重组策略（MODULE-7 AGENTS.md §2.4）:
 *   - 保持原有导出结构（LiveStage / DanmakuOverlay / SubtitleDisplay + DanmakuItem 类型）
 *   - 供模块8 页面通过 '@/components/business/live' 消费
 *
 * 跨模块导入约束（rules-0 §四 + MODULE-7 AGENTS.md §2.3）:
 *   - 仅做导出聚合，不包含实现逻辑
 *   - 禁止 import 模块8/9 内部实现
 *
 * 主线程补建说明（current-note.md 接续入口第 1 项）:
 *   - P5-B 组 subagent 创建了 live/live-stage.tsx + live/danmaku-overlay.tsx + live/subtitle-display.tsx
 *   - 但 B 组未创建 live/index.ts，主线程统一补建以匹配其他子目录的导出聚合模式
 * ============================================================================
 */

export { LiveStage } from './live-stage';
export { DanmakuOverlay } from './danmaku-overlay';
export type { DanmakuItem } from './danmaku-overlay';
export { SubtitleDisplay } from './subtitle-display';
