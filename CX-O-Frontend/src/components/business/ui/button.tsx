/**
 * @file button.tsx — Button 业务组件重组（模块7 ui 子目录）
 * ============================================================================
 * 模块: 模块7 业务组件重组层 — A 组（ui 子目录）
 * 落点: C:\CX-O\CX-O-Frontend\src\components\business\ui\button.tsx
 * 原组件: src/components/ui/Button.tsx
 *
 * 重组策略（MODULE-7 AGENTS.md §2.4）:
 *   - 旧 Button API（variant/size/loading/icon）与 ui-v2 Button 完全兼容
 *   - 直接委托 ui-v2 Button（已内置 data-glass + motion variants + Liquid Glass）
 *   - 旧版 ripple 效果由 Liquid Glass 玻璃渲染替代（UI 层升级，非业务逻辑）
 *
 * 跨模块导入约束（rules-0 §四 + MODULE-7 AGENTS.md §2.3）:
 *   - 仅 import 模块6 ui-v2 公开产出
 *   - 禁止 import 模块8/9 内部实现
 * ============================================================================
 */

export { Button } from '@/components/ui-v2';
export type { ButtonProps } from '@/components/ui-v2';
