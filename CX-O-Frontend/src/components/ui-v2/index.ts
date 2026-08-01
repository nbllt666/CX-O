/**
 * @file index.ts — 模块6 基础组件层（shadcn ui-v2）统一导出入口
 * ============================================================================
 * 模块: 模块6 基础组件层（shadcn ui-v2）— 波1+波2+波3+波4
 * 落点: C:\CX-O\CX-O-Frontend\src\components\ui-v2\index.ts
 *
 * 契约对齐:
 *   - I5 frontend_components_uiv2.pyi（15 组件 + 8 函数 + 4 异常 + WaveKey + GlassTier）
 *   - C5 frontend_migration_config.schema.json §shadcnMigrationWaves.wave1 + wave2 + wave3 + wave4
 *   - merged.md §4.2 定制策略（fork 后注入 Liquid Glass 样式）
 *
 * 导出范围（波1+波2+波3+波4）:
 *   - 基础设施 3 文件: inject-glass-style / with-glass-data-attribute / motion-variants
 *   - 波1 5 组件: Button / Input / Card / Dialog / Tooltip
 *   - 波2 4 组件: Form / Select / Checkbox / RadioGroup（含 RadioGroupItem 子组件）
 *   - 波3 4 组件: Table / Tabs / Badge / Avatar（含 Table/Tabs/Avatar 子组件）
 *   - 波4 2 组件: ChatPanel / AudioTrack（业务封装，基于 shadcn 基础组件重组；
 *     含 ChatMessage / AudioTrackItem 子组件）
 *   - 统一类型: GlassComponentProps（Liquid Glass 扩展 props 基类）
 *
 * 下游被依赖（MODULE-6 AGENTS.md §4.3）:
 *   - 模块7（业务组件）: `import { Button, Input, Card, Dialog, Tooltip } from '@/components/ui-v2'`
 *   - 模块8（页面应用）: 通过模块7 间接消费，或直接 `import { Button } from '@/components/ui-v2/button'`
 *
 * 跨模块导入约束（rules-0 §四 + MODULE-6 AGENTS.md §4.3）:
 *   - 本文件仅做导出聚合，不包含实现逻辑
 *   - 禁止 import 模块5/7/8/9 内部实现
 * ============================================================================
 */

// =============================================================================
// 基础设施 3 文件导出
// =============================================================================

// inject-glass-style.ts — Liquid Glass 样式注入工具（v2 简化版）
export {
  // v2 新常量（推荐使用）
  glassPanelClass,
  glassPanelInteractiveClass,
  glassPanelLgClass,
  // 运行时辅助函数
  buildGlassDataAttributes,
  // 兼容性导出（波5 清理后删除）
  injectGlassClassName,
  isValidGlassTier,
} from './inject-glass-style';

// with-glass-data-attribute.tsx — data-glass 属性 HOC
export {
  withGlassDataAttribute,
  enableGlassAttribute,
  disableGlassAttribute,
} from './with-glass-data-attribute';

export type {
  WithGlassDataAttributeProps,
} from './with-glass-data-attribute';

// motion-variants.ts — 引用模块3 springs 的 motion variants 工厂
export {
  getComponentMotionVariants,
  getComponentMotionProps,
  getDefaultComponentSpring,
  isSpringKeyForUI,
  getComponentSpringTransition,
  // 常量
  DEFAULT_COMPONENT_SPRINGS,
} from './motion-variants';

export type {
  Wave1ComponentName,
  Wave1_2ComponentName,
  Wave1_2_3ComponentName,
  Wave1_2_3_4ComponentName,
  ComponentMotionProps,
  ComponentMotionVariantsConfig,
} from './motion-variants';

// =============================================================================
// 波1 5 组件导出（对应 I5 §Button/Input/Card/Dialog/Tooltip）
// =============================================================================

// button.tsx — Button 组件（第1波基础组件）
export {
  Button,
} from './button';

export type {
  ButtonProps,
  GlassComponentProps,
} from './button';

// input.tsx — Input 组件（第1波基础组件）
export {
  Input,
  Textarea,
} from './input';

export type {
  InputProps,
  TextareaProps,
} from './input';

// card.tsx — Card 组件（第1波基础组件）
export {
  Card,
  CardHeader,
  CardBody,
  CardFooter,
} from './card';

export type {
  CardProps,
  CardHeaderProps,
  CardBodyProps,
  CardFooterProps,
} from './card';

// dialog.tsx — Dialog 组件（第1波基础组件）
export {
  Dialog,
} from './dialog';

export type {
  DialogProps,
} from './dialog';

// tooltip.tsx — Tooltip 组件（第1波基础组件）
export {
  Tooltip,
} from './tooltip';

export type {
  TooltipProps,
} from './tooltip';

// =============================================================================
// 波2 4 组件导出（对应 I5 §Form/Select/Checkbox/RadioGroup）
// =============================================================================

// form.tsx — Form 组件（第2波表单组件）
export {
  Form,
} from './form';

export type {
  FormProps,
} from './form';

// select.tsx — Select 组件（第2波表单组件）
export {
  Select,
} from './select';

export type {
  SelectProps,
  SelectOption,
} from './select';

// checkbox.tsx — Checkbox 组件（第2波表单组件）
export {
  Checkbox,
} from './checkbox';

export type {
  CheckboxProps,
} from './checkbox';

// radio-group.tsx — RadioGroup 组件（第2波表单组件，含 RadioGroupItem 子组件）
export {
  RadioGroup,
  RadioGroupItem,
} from './radio-group';

export type {
  RadioGroupProps,
  RadioGroupItemProps,
} from './radio-group';

// =============================================================================
// 波3 4 组件导出（对应 I5 §Table/Tabs/Badge/Avatar）
// =============================================================================

// table.tsx — Table 组件（第3波数据展示组件，含 Table 子组件）
export {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from './table';

export type {
  TableProps,
  TableColumn,
  TableHeaderProps,
  TableBodyProps,
  TableRowProps,
  TableHeadProps,
  TableCellProps,
} from './table';

// tabs.tsx — Tabs 组件（第3波数据展示组件，含 TabsList/TabsTrigger/TabsContent 子组件）
export {
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
} from './tabs';

export type {
  TabsProps,
  TabsListProps,
  TabsTriggerProps,
  TabsContentProps,
} from './tabs';

// badge.tsx — Badge 组件（第3波数据展示组件，6 种 variant）
export {
  Badge,
} from './badge';

export type {
  BadgeProps,
  BadgeVariant,
  BadgeSize,
} from './badge';

// avatar.tsx — Avatar 组件（第3波数据展示组件，含 AvatarFallback 子组件）
export {
  Avatar,
  AvatarFallback,
} from './avatar';

export type {
  AvatarProps,
  AvatarFallbackProps,
  AvatarSize,
  AvatarShape,
} from './avatar';

// =============================================================================
// 波4 2 组件导出（对应 I5 §ChatPanel/AudioTrack，业务封装，基于 shadcn 基础组件重组）
// =============================================================================

// chat-panel.tsx — ChatPanel 业务封装组件（第4波业务封装，含 ChatMessage 子组件）
export {
  ChatPanel,
  ChatMessage,
} from './chat-panel';

export type {
  ChatPanelProps,
  ChatMessageProps,
  ChatMessageData,
} from './chat-panel';

// audio-track.tsx — AudioTrack 业务封装组件（第4波业务封装，含 AudioTrackItem 子组件）
export {
  AudioTrack,
  AudioTrackItem,
} from './audio-track';

export type {
  AudioTrackProps,
  AudioTrackItemProps,
  AudioTrackData,
} from './audio-track';
