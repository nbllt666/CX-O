/**
 * @file index.ts — layout 子目录统一导出（模块7）
 * ============================================================================
 * 模块: 模块7 业务组件重组层 — A 组布局类（layout 子目录）
 * 落点: C:\CX-O\CX-O-Frontend\src\components\business\layout\index.ts
 * 原组件: src/components/layout/index.ts
 *
 * 重组策略（MODULE-7 AGENTS.md §2.4）:
 *   - 保持原有导出结构（Layout / Sidebar / Header / PageHeader）
 *   - 供 business/app-layout.tsx 及模块8 页面通过 './layout' 或 '@/components/business/layout' 消费
 *
 * 跨模块导入约束（rules-0 §四 + MODULE-7 AGENTS.md §2.3）:
 *   - 仅做导出聚合，不包含实现逻辑
 *   - 禁止 import 模块8/9 内部实现
 * ============================================================================
 */

export { Layout } from './layout';
export { Sidebar } from './sidebar';
export { Header } from './header';
export { PageHeader } from './page-header';
