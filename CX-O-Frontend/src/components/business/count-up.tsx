/**
 * @file count-up.tsx — CountUp 业务组件重组（模块7）
 * ============================================================================
 * 模块: 模块7 业务组件重组层 — A 组数据展示类
 * 落点: C:\CX-O\CX-O-Frontend\src\components\business\count-up.tsx
 * 原组件: src/components/CountUp.tsx
 *
 * 重组策略（MODULE-7 AGENTS.md §2.4）:
 *   - 保留现有业务逻辑（useMotionValue / useTransform / animate / displayValue 不变）
 *   - 注入 Liquid Glass + data-glass + motion variants
 *   - 通过 className 消费 token，不硬编码颜色
 *
 * 跨模块导入约束（rules-0 §四 + MODULE-7 AGENTS.md §2.3）:
 *   - 仅 import 模块6 ui-v2 公开产出（glass 基础设施）
 *   - 禁止 import 模块8/9 内部实现
 * ============================================================================
 */

import React, { useEffect, useState } from 'react';
import { useMotionValue, useTransform, animate, motion, type Variants } from 'framer-motion';
import { buildGlassDataAttributes, getComponentMotionVariants } from '@/components/ui-v2';

interface CountUpProps {
  end: number;
  duration?: number;
  prefix?: string;
  suffix?: string;
  className?: string;
}

// 入场 motion variants（基于模块6 getComponentMotionVariants 工厂，glass spring）
const countUpVariants: Variants = getComponentMotionVariants({
  componentName: 'Card',
  springKey: 'glass',
});

export const CountUp: React.FC<CountUpProps> = ({
  end,
  duration = 1000,
  prefix = '',
  suffix = '',
  className,
}) => {
  const count = useMotionValue(0);
  const rounded = useTransform(count, (latest) => Math.round(latest));
  const [displayValue, setDisplayValue] = useState(rounded.get());

  useEffect(() => {
    const controls = animate(count, end, {
      duration: duration / 1000,
      ease: 'easeOut',
    });

    const unsubscribe = rounded.on('change', (latest) => {
      setDisplayValue(latest);
    });

    return () => {
      controls.stop();
      unsubscribe();
    };
  }, [count, end, duration, rounded]);

  const glassAttributes = buildGlassDataAttributes(true, 3);

  return (
    <motion.span
      className={className}
      variants={countUpVariants}
      initial="initial"
      animate="animate"
      exit="exit"
      {...glassAttributes}
    >
      {prefix}
      {displayValue}
      {suffix}
    </motion.span>
  );
};
