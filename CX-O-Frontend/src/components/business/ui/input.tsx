/**
 * @file input.tsx — Input / Textarea 业务组件重组（模块7 ui 子目录）
 * ============================================================================
 * 模块: 模块7 业务组件重组层 — A 组（ui 子目录）
 * 落点: C:\CX-O\CX-O-Frontend\src\components\business\ui\input.tsx
 * 原组件: src/components/ui/Input.tsx
 *
 * 重组策略（MODULE-7 AGENTS.md §2.4）:
 *   - 旧 Input API（label/error/icon/suffix）与 ui-v2 Input 完全兼容
 *   - 旧 Textarea API（label/error）与 ui-v2 Textarea 完全兼容
 *   - 直接委托 ui-v2 Input / Textarea（已内置 data-glass + motion variants）
 *
 * 跨模块导入约束（rules-0 §四 + MODULE-7 AGENTS.md §2.3）:
 *   - 仅 import 模块6 ui-v2 公开产出
 *   - 禁止 import 模块8/9 内部实现
 * ============================================================================
 */

export { Input, Textarea } from '@/components/ui-v2';
export type { InputProps, TextareaProps } from '@/components/ui-v2';
