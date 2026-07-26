/**
 * @file page-header.tsx — PageHeader 业务组件重组（模块7）
 * ============================================================================
 * 模块: 模块7 业务组件重组层 — A 组布局类（layout 子目录）
 * 落点: C:\CX-O\CX-O-Frontend\src\components\business\layout\page-header.tsx
 * 原组件: src/components/layout/PageHeader.tsx
 *
 * 重组策略（MODULE-7 AGENTS.md §2.4）:
 *   - 保留现有业务逻辑（title / description / actions / breadcrumbs 渲染不变）
 *   - UI 层注入 Liquid Glass + data-glass（容器挂载 data-glass 属性）
 *   - motion variants 处理页面标题进场动画
 *   - 通过 className 消费 token，不硬编码颜色
 *
 * 跨模块导入约束（rules-0 §四 + MODULE-7 AGENTS.md §2.3）:
 *   - 仅 import 模块3 motion / 模块4 glass / 模块6 ui-v2 公开产出
 *   - 仅 import 本模块内部实现
 *   - 禁止 import 模块8/9 内部实现
 * ============================================================================
 */

import { motion, type Variants } from 'framer-motion';
import { cn } from '@/lib/utils';
import {
  buildGlassDataAttributes,
  getComponentMotionVariants,
} from '@/components/ui-v2';

interface PageHeaderProps {
  title: string;
  description?: string;
  actions?: React.ReactNode;
  breadcrumbs?: { label: string; path?: string }[];
  className?: string;
}

// 入场 motion variants（基于模块6 getComponentMotionVariants 工厂，gentle spring）
const headerVariants: Variants = getComponentMotionVariants({
  componentName: 'Card',
  springKey: 'gentle',
});

/**
 * PageHeader 业务组件（重组版）。
 *
 * 业务逻辑保留: title / description / breadcrumbs / actions 渲染逻辑原样保留。
 * UI 层重组: 容器挂载 data-glass 属性，注入 motion variants 进场动画。
 */
export function PageHeader({
  title,
  description,
  actions,
  breadcrumbs,
  className,
}: PageHeaderProps) {
  const glassAttributes = buildGlassDataAttributes(true, 3);

  return (
    <motion.div
      className={cn('mb-6', className)}
      variants={headerVariants}
      initial="initial"
      animate="animate"
      exit="exit"
      {...glassAttributes}
    >
      {breadcrumbs && breadcrumbs.length > 0 && (
        <nav className="mb-2 text-sm text-[var(--color-text-tertiary)]">
          <ol className="flex items-center gap-2">
            {breadcrumbs.map((crumb, index) => (
              <li key={index} className="flex items-center gap-2">
                {index > 0 && <span>/</span>}
                {crumb.path ? (
                  <a
                    href={crumb.path}
                    className="hover:text-[var(--color-text-primary)] transition-colors"
                  >
                    {crumb.label}
                  </a>
                ) : (
                  <span>{crumb.label}</span>
                )}
              </li>
            ))}
          </ol>
        </nav>
      )}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">
            {title}
          </h1>
          {description && (
            <p className="mt-1 text-sm text-[var(--color-text-secondary)]">
              {description}
            </p>
          )}
        </div>
        {actions && <div className="flex items-center gap-2">{actions}</div>}
      </div>
    </motion.div>
  );
}
