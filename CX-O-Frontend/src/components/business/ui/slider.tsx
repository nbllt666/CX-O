/**
 * @file slider.tsx — Slider 业务组件重组（模块7 ui 子目录）
 * ============================================================================
 * 模块: 模块7 业务组件重组层 — A 组（ui 子目录）
 * 落点: C:\CX-O\CX-O-Frontend\src\components\business\ui\slider.tsx
 * 原组件: src/components/ui/Slider.tsx
 *
 * 重组策略（MODULE-7 AGENTS.md §2.4）:
 *   - 保留现有业务逻辑（label/value/min/max/step/onChange/format/editing/commitEdit 不变）
 *   - 注入 Liquid Glass + data-glass（slider 容器挂载属性）
 *   - 注入 motion variants（snappy spring，slider 值变化反馈）
 *   - 通过 className 消费 token，不硬编码颜色
 *
 * 跨模块导入约束（rules-0 §四 + MODULE-7 AGENTS.md §2.3）:
 *   - 仅 import 模块3 motion / 模块4 glass / 模块6 ui-v2 公开产出
 *   - 禁止 import 模块8/9 内部实现
 * ============================================================================
 */

import { useState, useRef, useEffect } from 'react';
import { motion, type Variants } from 'framer-motion';
import { cn } from '@/lib/utils';
import {
  buildGlassDataAttributes,
  getComponentMotionVariants,
} from '@/components/ui-v2';

export interface SliderProps {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (value: number) => void;
  format?: (value: number) => string;
}

// 入场 motion variants（基于模块6 getComponentMotionVariants 工厂，snappy spring）
const sliderVariants: Variants = getComponentMotionVariants({
  componentName: 'Button',
  springKey: 'snappy',
});

/**
 * Slider 业务组件（重组版）。
 *
 * 业务逻辑保留: label / value / min / max / step / onChange / format / editing / commitEdit 全部原样保留。
 * UI 层重组: 容器挂载 data-glass，注入 motion variants。
 */
export function Slider({
  label,
  value,
  min,
  max,
  step,
  onChange,
  format = (v) => v.toFixed(2),
}: SliderProps) {
  const [editing, setEditing] = useState(false);
  const [editValue, setEditValue] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  const glassAttributes = buildGlassDataAttributes(true, 4);

  useEffect(() => {
    if (editing && inputRef.current) inputRef.current.select();
  }, [editing]);

  const commitEdit = () => {
    const v = parseFloat(editValue);
    if (!isNaN(v)) {
      const clamped = Math.max(min, Math.min(max, Math.round(v / step) * step));
      onChange(clamped);
    }
    setEditing(false);
  };

  return (
    <motion.div
      className="flex flex-col gap-0.5"
      variants={sliderVariants}
      initial="initial"
      animate="animate"
      exit="exit"
      {...glassAttributes}
    >
      <div className="flex justify-between">
        <span className="text-xs text-[var(--color-text-secondary)]">{label}</span>
        {editing ? (
          <input
            ref={inputRef}
            type="number"
            value={editValue}
            min={min}
            max={max}
            step={step}
            onChange={(e) => setEditValue(e.target.value)}
            onBlur={commitEdit}
            onKeyDown={(e) => {
              if (e.key === 'Enter') commitEdit();
              if (e.key === 'Escape') setEditing(false);
            }}
            className={cn(
              'text-[10px] text-[var(--color-text-primary)] tabular-nums w-16 text-right',
              'bg-[var(--color-bg-secondary)] border border-[var(--color-border)]',
              'rounded px-1 py-0 outline-none focus:border-[var(--color-accent)]',
            )}
          />
        ) : (
          <span
            className={cn(
              'text-[10px] text-[var(--color-text-tertiary)] tabular-nums w-12 text-right',
              'cursor-pointer hover:text-[var(--color-text-primary)] transition-colors',
            )}
            onClick={() => {
              setEditValue(String(value));
              setEditing(true);
            }}
            title="点击输入值"
          >
            {format(value)}
          </span>
        )}
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className={cn(
          'w-full h-1 rounded-full appearance-none cursor-pointer accent-[var(--color-accent)]',
          '[&::-webkit-slider-runnable-track]:rounded-full [&::-webkit-slider-runnable-track]:h-1',
          '[&::-webkit-slider-runnable-track]:bg-[var(--color-bg-secondary)]',
          '[&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3',
          '[&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-[var(--color-accent)]',
          '[&::-webkit-slider-thumb]:mt-[-4px]',
        )}
      />
    </motion.div>
  );
}
