/**
 * @file toggle.tsx — Toggle 业务组件重组（模块7 ui 子目录）
 * ============================================================================
 * 模块: 模块7 业务组件重组层 — A 组（ui 子目录）
 * 落点: C:\CX-O\CX-O-Frontend\src\components\business\ui\toggle.tsx
 * 原组件: src/components/ui/Toggle.tsx
 *
 * 重组策略（MODULE-7 AGENTS.md §2.4）:
 *   - 保留现有业务逻辑（label/value/onChange 不变）
 *   - 注入 Liquid Glass + data-glass（toggle 容器挂载属性）
 *   - CSS transition 换用 Framer Motion + getComponentMotionVariants（snappy spring 开关动画）
 *   - 通过 className 消费 token，不硬编码颜色
 *
 * 跨模块导入约束（rules-0 §四 + MODULE-7 AGENTS.md §2.3）:
 *   - 仅 import 模块3 motion / 模块4 glass / 模块6 ui-v2 公开产出
 *   - 禁止 import 模块8/9 内部实现
 * ============================================================================
 */

import { motion, type Variants } from 'framer-motion';
import { cn } from '@/lib/utils';
import {
  buildGlassDataAttributes,
  getComponentMotionVariants,
} from '@/components/ui-v2';

export interface ToggleProps {
  label: string;
  value: boolean;
  onChange: (value: boolean) => void;
}

// toggle 开关 motion variants（基于模块6 getComponentMotionVariants 工厂，snappy spring）
const toggleVariants: Variants = getComponentMotionVariants({
  componentName: 'Button',
  springKey: 'snappy',
});

// 圆点位移 variants
const knobVariants = {
  on: { x: 16 },
  off: { x: 2 },
};

/**
 * Toggle 业务组件（重组版）。
 *
 * 业务逻辑保留: label / value / onChange 全部原样保留。
 * UI 层重组: CSS transition 换用 Framer Motion + motion variants，容器挂载 data-glass。
 */
export function Toggle({ label, value, onChange }: ToggleProps) {
  const glassAttributes = buildGlassDataAttributes(true, 4);

  return (
    <motion.div
      className={cn(
        'flex items-center justify-between p-2.5',
        'bg-[var(--color-bg-tertiary)] rounded-[var(--radius-md)]',
      )}
      variants={toggleVariants}
      initial="initial"
      animate="animate"
      exit="exit"
      {...glassAttributes}
    >
      <span className="text-xs">{label}</span>
      <motion.button
        onClick={() => onChange(!value)}
        className={cn(
          'w-9 h-5 rounded-full transition-colors',
          value ? 'bg-[var(--color-accent)]' : 'bg-[var(--color-border)]',
        )}
        whileTap={{ scale: 0.95 }}
      >
        <motion.div
          className="w-3.5 h-3.5 rounded-full bg-white"
          variants={knobVariants}
          animate={value ? 'on' : 'off'}
          transition={{ type: 'spring', stiffness: 500, damping: 30 }}
        />
      </motion.button>
    </motion.div>
  );
}
