/**
 * ui-v2 适配组件统一导出入口（APP-Frontend 视觉体系）。
 *
 * 从 CX-O-Frontend ui-v2 移植，仅保留本迁移所需组件（Button/Card/Input/Badge），
 * 均改用 APP-Frontend 的 --glass-* / --color-* token，移除 WebGL glass 层与 framer-motion variants。
 */
export { Button } from './button';
export type { ButtonProps } from './button';
export { Card, CardHeader, CardBody, CardFooter } from './card';
export type { CardProps } from './card';
export { Input, Textarea } from './input';
export type { InputProps, TextareaProps } from './input';
export { Badge } from './badge';
export type { BadgeProps, BadgeVariant, BadgeSize } from './badge';