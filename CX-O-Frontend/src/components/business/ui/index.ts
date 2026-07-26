/**
 * @file index.ts — ui 子目录统一导出（模块7）
 * ============================================================================
 * 模块: 模块7 业务组件重组层 — A 组（ui 子目录）
 * 落点: C:\CX-O\CX-O-Frontend\src\components\business\ui\index.ts
 * 原组件: src/components/ui/index.ts
 *
 * 重组策略（MODULE-7 AGENTS.md §2.4）:
 *   - 保持与旧 ui/index.ts 相同的导出结构（13 组件 + 子组件 + 类型）
 *   - 供模块8 页面通过 '@/components/business/ui' 消费
 *
 * 跨模块导入约束（rules-0 §四 + MODULE-7 AGENTS.md §2.3）:
 *   - 仅做导出聚合，不包含实现逻辑
 *   - 禁止 import 模块8/9 内部实现
 * ============================================================================
 */

export { Button } from './button';
export type { ButtonProps } from './button';

export { Input, Textarea } from './input';
export type { InputProps, TextareaProps } from './input';

export { Card, CardHeader, CardBody, CardFooter } from './card';
export type {
  CardProps,
  CardHeaderProps,
  CardBodyProps,
  CardFooterProps,
} from './card';

export { Modal } from './modal';
export type { ModalProps } from './modal';

export { Drawer } from './drawer';
export type { DrawerProps } from './drawer';

export { ToastProvider, useToast } from './toast';

export { Dropdown, DropdownItem, DropdownDivider } from './dropdown';
export type { DropdownProps } from './dropdown';

export { Tooltip } from './tooltip';
export type { TooltipProps } from './tooltip';

export { Skeleton, SkeletonText, SkeletonCard } from './skeleton';

export { EmptyState, EmptyStateIcon } from './empty-state';

export { Badge, Tag } from './badge';
export type { BadgeVariant } from './badge';

export { Slider } from './slider';
export type { SliderProps } from './slider';

export { Toggle } from './toggle';
export type { ToggleProps } from './toggle';
