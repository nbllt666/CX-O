/**
 * @file virtual-list.tsx — VirtualList 业务组件重组（模块7）
 * ============================================================================
 * 模块: 模块7 业务组件重组层 — A 组数据展示类
 * 落点: C:\CX-O\CX-O-Frontend\src\components\business\virtual-list.tsx
 * 原组件: src/components/VirtualList.tsx
 *
 * 重组策略（MODULE-7 AGENTS.md §2.4）:
 *   - 保留现有业务逻辑（虚拟滚动计算 / scrollTop / visibleItems / wheel 拦截不变）
 *   - 注入 Liquid Glass + data-glass + motion variants
 *   - 通过 className 消费 token，不硬编码颜色
 *
 * 跨模块导入约束（rules-0 §四 + MODULE-7 AGENTS.md §2.3）:
 *   - 仅 import 模块6 ui-v2 公开产出（glass 基础设施）
 *   - 禁止 import 模块8/9 内部实现
 * ============================================================================
 */

import React, { useRef, useState, useEffect, useCallback, memo } from 'react';
import { motion, type Variants } from 'framer-motion';
import {
  buildGlassDataAttributes,
  getComponentMotionVariants,
} from '@/components/ui-v2';

interface VirtualListProps<T> {
  items: T[];
  itemHeight: number;
  containerHeight: number;
  renderItem: (item: T, index: number) => React.ReactNode;
  overscan?: number;
  className?: string;
}

// 入场 motion variants（基于模块6 getComponentMotionVariants 工厂，glass spring）
const listVariants: Variants = getComponentMotionVariants({
  componentName: 'Card',
  springKey: 'glass',
});

function VirtualListComponent<T>({
  items,
  itemHeight,
  containerHeight,
  renderItem,
  overscan = 3,
  className = '',
}: VirtualListProps<T>) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [scrollTop, setScrollTop] = useState(0);

  const totalHeight = items.length * itemHeight;
  const visibleCount = Math.ceil(containerHeight / itemHeight);
  const startIndex = Math.max(0, Math.floor(scrollTop / itemHeight) - overscan);
  const endIndex = Math.min(items.length - 1, startIndex + visibleCount + overscan * 2);

  const visibleItems = items.slice(startIndex, endIndex + 1);

  const handleScroll = useCallback((e: React.UIEvent<HTMLDivElement>) => {
    setScrollTop(e.currentTarget.scrollTop);
  }, []);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const handleWheel = (e: WheelEvent) => {
      e.preventDefault();
      container.scrollTop += e.deltaY;
    };

    container.addEventListener('wheel', handleWheel, { passive: false });
    return () => container.removeEventListener('wheel', handleWheel);
  }, []);

  const glassAttributes = buildGlassDataAttributes(true, 3);

  return (
    <motion.div
      ref={containerRef}
      className={className}
      style={{
        height: containerHeight,
        overflow: 'auto',
        position: 'relative',
      }}
      onScroll={handleScroll}
      variants={listVariants}
      initial="initial"
      animate="animate"
      exit="exit"
      {...glassAttributes}
    >
      <div
        style={{
          height: totalHeight,
          position: 'relative',
        }}
      >
        {visibleItems.map((item, index) => {
          const actualIndex = startIndex + index;
          return (
            <div
              key={actualIndex}
              style={{
                position: 'absolute',
                top: actualIndex * itemHeight,
                height: itemHeight,
                width: '100%',
              }}
            >
              {renderItem(item, actualIndex)}
            </div>
          );
        })}
      </div>
    </motion.div>
  );
}

export const VirtualList = memo(VirtualListComponent) as typeof VirtualListComponent;
