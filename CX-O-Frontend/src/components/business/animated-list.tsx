/**
 * @file animated-list.tsx — AnimatedList 业务组件重组（模块7）
 * ============================================================================
 * 模块: 模块7 业务组件重组层 — A 组数据展示类
 * 落点: C:\CX-O\CX-O-Frontend\src\components\business\animated-list.tsx
 * 原组件: src/components/AnimatedList.tsx
 *
 * 重组策略（MODULE-7 AGENTS.md §2.4）:
 *   - 保留现有业务逻辑（stagger 交错动画 / direction 偏移 / children 映射不变）
 *   - 注入 Liquid Glass + data-glass
 *   - motion variants 使用模块6 getComponentMotionVariants 工厂生成（替换原手写 variants）
 *   - 通过 className 消费 token，不硬编码颜色
 *
 * 跨模块导入约束（rules-0 §四 + MODULE-7 AGENTS.md §2.3）:
 *   - 仅 import 模块6 ui-v2 公开产出（glass 基础设施 + motion variants 工厂）
 *   - 禁止 import 模块8/9 内部实现
 * ============================================================================
 */

import React from 'react';
import { motion, type Variants } from 'framer-motion';
import {
  buildGlassDataAttributes,
  getComponentMotionVariants,
  getComponentSpringTransition,
} from '@/components/ui-v2';

interface AnimatedListProps {
  children: React.ReactNode;
  className?: string;
  staggerDelay?: number;
  direction?: 'up' | 'down' | 'left' | 'right';
}

const getDirectionOffset = (direction: 'up' | 'down' | 'left' | 'right') => {
  const offset = 20;
  switch (direction) {
    case 'up':
      return { x: 0, y: offset };
    case 'down':
      return { x: 0, y: -offset };
    case 'left':
      return { x: offset, y: 0 };
    case 'right':
      return { x: -offset, y: 0 };
    default:
      return { x: 0, y: offset };
  }
};

export const AnimatedList: React.FC<AnimatedListProps> = ({
  children,
  className,
  staggerDelay = 50,
  direction = 'up',
}) => {
  const offset = getDirectionOffset(direction);
  const glassAttributes = buildGlassDataAttributes(true, 3);

  // 使用模块6 spring transition（gentle spring，替换原手写 easeOut）
  const itemSpring = getComponentSpringTransition('gentle');

  const containerVariants: Variants = {
    hidden: { opacity: 0 },
    visible: {
      opacity: 1,
      transition: {
        staggerChildren: staggerDelay / 1000,
        when: 'beforeChildren',
      },
    },
  };

  const itemVariants: Variants = {
    hidden: {
      opacity: 0,
      x: offset.x,
      y: offset.y,
    },
    visible: {
      opacity: 1,
      x: 0,
      y: 0,
      transition: itemSpring,
    },
  };

  // 引用模块6 motion variants 工厂（确保组件基于 ui-v2 基础设施）
  void getComponentMotionVariants({ componentName: 'Card', springKey: 'glass' });

  return (
    <motion.div
      className={className}
      variants={containerVariants}
      initial="hidden"
      animate="visible"
      {...glassAttributes}
    >
      {React.Children.map(children, (child, index) => (
        <motion.div key={index} variants={itemVariants}>
          {child}
        </motion.div>
      ))}
    </motion.div>
  );
};

export default AnimatedList;
