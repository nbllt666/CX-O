/**
 * @file card.tsx — Card / CardHeader / CardBody / CardFooter 业务组件重组（模块7 ui 子目录）
 * ============================================================================
 * 模块: 模块7 业务组件重组层 — A 组（ui 子目录）
 * 落点: C:\CX-O\CX-O-Frontend\src\components\business\ui\card.tsx
 * 原组件: src/components/ui/Card.tsx
 *
 * 重组策略（MODULE-7 AGENTS.md §2.4）:
 *   - 旧 Card API（hoverable/selected）与 ui-v2 Card 完全兼容
 *   - 旧 CardHeader / CardBody / CardFooter 与 ui-v2 子组件完全兼容
 *   - 直接委托 ui-v2 Card 系列（已内置 data-glass + motion variants + Liquid Glass）
 *
 * 跨模块导入约束（rules-0 §四 + MODULE-7 AGENTS.md §2.3）:
 *   - 仅 import 模块6 ui-v2 公开产出
 *   - 禁止 import 模块8/9 内部实现
 * ============================================================================
 */

export { Card, CardHeader, CardBody, CardFooter } from '@/components/ui-v2';
export type {
  CardProps,
  CardHeaderProps,
  CardBodyProps,
  CardFooterProps,
} from '@/components/ui-v2';
