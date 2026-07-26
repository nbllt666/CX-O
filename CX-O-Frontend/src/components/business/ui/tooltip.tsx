/**
 * @file tooltip.tsx — Tooltip 业务组件重组（模块7 ui 子目录）
 * ============================================================================
 * 模块: 模块7 业务组件重组层 — A 组（ui 子目录）
 * 落点: C:\CX-O\CX-O-Frontend\src\components\business\ui\tooltip.tsx
 * 原组件: src/components/ui/Tooltip.tsx
 *
 * 重组策略（MODULE-7 AGENTS.md §2.4）:
 *   - 保留旧 Tooltip API（content/children/position/delay）
 *   - 委托 ui-v2 Tooltip（已内置 data-glass + motion variants + Liquid Glass）
 *   - prop 适配: position → side（语义相同，仅字段名变更）
 *
 * 跨模块导入约束（rules-0 §四 + MODULE-7 AGENTS.md §2.3）:
 *   - 仅 import 模块6 ui-v2 公开产出
 *   - 禁止 import 模块8/9 内部实现
 * ============================================================================
 */

import React from 'react';
import { Tooltip as TooltipV2 } from '@/components/ui-v2';

export interface TooltipProps {
  content: React.ReactNode;
  children: React.ReactNode;
  /** 显示位置（top/right/bottom/left，默认 top）—— 映射到 ui-v2 side prop */
  position?: 'top' | 'bottom' | 'left' | 'right';
  delay?: number;
}

/**
 * Tooltip 业务组件（重组版）。
 *
 * 业务逻辑保留: content / children / position / delay 语义全部保留。
 * UI 层重组: 委托 ui-v2 Tooltip（position→side prop 适配），已内置 data-glass + motion variants。
 */
export function Tooltip({
  content,
  children,
  position = 'top',
  delay,
}: TooltipProps) {
  return (
    <TooltipV2 content={content} side={position} delay={delay}>
      {children}
    </TooltipV2>
  );
}
