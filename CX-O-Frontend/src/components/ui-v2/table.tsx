/**
 * @file table.tsx — Table 组件（第3波数据展示组件，Liquid Glass 定制）
 * ============================================================================
 * 模块: 模块6 基础组件层（shadcn ui-v2）— 波3 数据展示组件
 * 落点: C:\CX-O\CX-O-Frontend\src\components\ui-v2\table.tsx
 *
 * 契约对齐:
 *   - I5 frontend_components_uiv2.pyi §Table + §TableProps + §GlassComponentProps
 *   - D1 frontend_design_tokens.schema.json §component.table（token 消费，不硬编码颜色）
 *   - D2 glass_tier_config.schema.json §tiers（data-glass-tier 属性值）
 *   - D3 theme.schema.json（双主题通过 CSS 变量自动切换，无需 JS 介入）
 *   - D5 motion_springs.schema.json §springs.snappy（Table 默认 spring，行 hover/选中快速响应）
 *   - merged.md §4.2 定制策略 + §4.3 第3波（数据展示，第7-9周）+ §7.7 虚拟列表（react-window）
 *
 * Liquid Glass 定制（I5 §Table docstring + merged.md §4.2）:
 *   - 挂载 data-glass 属性，由 WebGL 层（I1 GlassRenderer）接管玻璃渲染
 *   - 受控表格组件，基于 data + columns 配置驱动渲染
 *   - 提供 Table 子组件组合 API（Table/TableHeader/TableBody/TableRow/TableHead/TableCell）
 *   - 行 hover/选中使用 Framer Motion variants（snappy spring，scale 微动 + 背景色过渡）
 *   - 行选中状态支持（selectedRowKeys + onRowSelect）
 *   - 长列表虚拟化作为可选优化（virtualized prop，默认 false，本次先实现基础表格）
 *   - Framer Motion variants 替换 shadcn 默认 Tailwind transition
 *   - 通过 className + Tailwind utility 消费 token，不硬编码颜色
 *   - 双主题通过 CSS 变量自动切换，无需 JS 介入
 *
 * 跨模块导入约束（rules-0 §四 + MODULE-6 AGENTS.md §4.3）:
 *   - 仅 import 模块1 token（通过 className 消费 CSS 变量）
 *   - 仅 import 模块3 springs/variants（通过 motion-variants.ts 工厂）
 *   - 仅 import 模块4 GlassTier 类型（data-glass-tier 属性值）
 *   - 仅 import 本模块基础设施（inject-glass-style / motion-variants / button 的 GlassComponentProps）
 *   - 仅 import 第三方库 react / framer-motion
 *   - 禁止 import 模块5/7/8/9 内部实现
 *
 * 默认 spring: snappy（D5 §springs.snappy.useCase=button-press，行 hover/选中快速响应）
 * apple-design 对齐: damping=22 / stiffness=420 / mass=0.8（快速响应，低过冲）
 * ============================================================================
 */

import React from 'react';
import { motion, type Variants } from 'framer-motion';
import { cn } from '@/lib/utils';
import {
  injectGlassClassName,
  buildGlassDataAttributes,
  isValidGlassTier,
} from './inject-glass-style';
import {
  getComponentMotionVariants,
  getComponentSpringTransition,
  getDefaultComponentSpring,
} from './motion-variants';
import type { GlassComponentProps } from './button';

// =============================================================================
// TableColumn + TableProps（对应 I5 §TableProps）
// =============================================================================

/**
 * Table 列定义（对应 I5 §TableProps.columns 数组元素）。
 *
 * key 为行数据字段名，header 为表头展示内容，render 为自定义单元格渲染函数。
 */
export interface TableColumn {
  /** 行数据字段名（用于读取行数据 `row[key]`） */
  readonly key: string;
  /** 表头展示内容 */
  readonly header: React.ReactNode;
  /** 自定义单元格渲染函数（默认直接展示 `row[key]`） */
  readonly render?: (
    value: unknown,
    row: Record<string, unknown>,
    index: number,
  ) => React.ReactNode;
  /** 列宽（CSS 宽度值，如 '120px' / '20%' / 120） */
  readonly width?: string | number;
  /** 列对齐方式（默认 left） */
  readonly align?: 'left' | 'center' | 'right';
}

/**
 * Table 组件 props（对应 I5 §TableProps）。
 *
 * 继承 GlassComponentProps（Liquid Glass 扩展）。
 * 受控表格，基于 data + columns 配置驱动渲染。
 */
export interface TableProps extends GlassComponentProps {
  /** 表格数据（每行为一个键值对对象） */
  readonly data: ReadonlyArray<Record<string, unknown>>;
  /** 列定义（控制列渲染顺序与渲染方式） */
  readonly columns: ReadonlyArray<TableColumn>;
  /** 自定义 className（应用到 Table 容器） */
  readonly className?: string;
  /** 选中行的 key 集合（受控模式，配合 onRowSelect 使用） */
  readonly selectedRowKeys?: ReadonlyArray<string>;
  /** 行选中变化回调（受控模式） */
  readonly onRowSelect?: (selectedKeys: string[]) => void;
  /** 行唯一标识字段名或函数（默认 'id'，用于选中状态追踪） */
  readonly rowKey?: string | ((row: Record<string, unknown>) => string);
  /** 是否启用虚拟列表（默认 false，本次先实现基础表格；true 时未来接入 react-window） */
  readonly virtualized?: boolean;
  /** 空数据时展示的占位内容 */
  readonly emptyText?: React.ReactNode;
  /** 无障碍标签 */
  readonly 'aria-label'?: string;
  /** 无障碍关联标签 id */
  readonly 'aria-labelledby'?: string;
}

// =============================================================================
// 子组件 Props 类型
// =============================================================================

/**
 * 表格公共 HTML 属性剔除（移除 framer-motion 冲突事件）。
 */
type TableHTMLElementOmit =
  | 'onDrag'
  | 'onDragEnd'
  | 'onAnimationStart'
  | 'onDragStart'
  | 'onDragOver'
  | 'onDragEnter'
  | 'onDragLeave'
  | 'onDrop';

/**
 * TableHeader 组件 props（thead 容器）。
 */
export interface TableHeaderProps
  extends Omit<React.HTMLAttributes<HTMLTableSectionElement>, TableHTMLElementOmit> {}

/**
 * TableBody 组件 props（tbody 容器）。
 */
export interface TableBodyProps
  extends Omit<React.HTMLAttributes<HTMLTableSectionElement>, TableHTMLElementOmit> {}

/**
 * TableRow 组件 props（tr 行，支持 hover/selected 交互态）。
 */
export interface TableRowProps
  extends Omit<React.HTMLAttributes<HTMLTableRowElement>, TableHTMLElementOmit> {
  /** 该行是否选中（高亮 + ring） */
  readonly selected?: boolean;
  /** 该行是否可交互（启用 hover 反馈，默认 false） */
  readonly interactive?: boolean;
  /** 行 key（用于 data-row-key 属性，便于测试与追踪） */
  readonly rowKey?: string;
}

/**
 * TableHead 组件 props（th 表头单元格）。
 */
export interface TableHeadProps
  extends Omit<React.ThHTMLAttributes<HTMLTableCellElement>, TableHTMLElementOmit> {
  /** 列对齐方式（控制文本对齐） */
  readonly align?: 'left' | 'center' | 'right';
}

/**
 * TableCell 组件 props（td 数据单元格）。
 */
export interface TableCellProps
  extends Omit<React.TdHTMLAttributes<HTMLTableCellElement>, TableHTMLElementOmit> {
  /** 列对齐方式（控制文本对齐） */
  readonly align?: 'left' | 'center' | 'right';
}

// =============================================================================
// 辅助: 行 key 解析
// =============================================================================

/**
 * 解析行 key（根据 rowKey 配置从行数据中提取唯一标识）。
 *
 * @param row 行数据
 * @param rowKey rowKey 配置（字段名字符串或函数）
 * @param index 行索引（fallback）
 * @returns 行唯一标识字符串
 */
function resolveRowKey(
  row: Record<string, unknown>,
  rowKey: string | ((row: Record<string, unknown>) => string),
  index: number,
): string {
  if (typeof rowKey === 'function') {
    return rowKey(row);
  }
  const value = row[rowKey];
  return value !== undefined && value !== null ? String(value) : `__row_${index}`;
}

/**
 * 对齐方式到 className 的映射。
 */
const alignClassMap: Record<'left' | 'center' | 'right', string> = {
  left: 'text-left',
  center: 'text-center',
  right: 'text-right',
};

// =============================================================================
// Table 组件实现（数据驱动模式）
// =============================================================================

/**
 * Table 组件（第3波数据展示组件，Liquid Glass 定制）。
 *
 * 对应 I5 §Table: ``Table(props: TableProps): JSX.Element``。
 *
 * Liquid Glass 定制（merged.md §4.2）:
 *   - 挂载 data-glass 属性，由 WebGL 层接管玻璃渲染
 *   - 基于 data + columns 配置驱动渲染
 *   - 行 hover/选中使用 snappy spring（scale 微动 + 背景色过渡）
 *   - Framer Motion variants 替换 shadcn 默认 Tailwind transition
 *   - 通过 className + Tailwind utility 消费 token，不硬编码颜色
 *   - 双主题通过 CSS 变量自动切换，无需 JS 介入
 *
 * 默认 spring: snappy（D5 §springs.snappy.useCase=button-press）
 *
 * @param props Table 组件配置（含 data/columns + Liquid Glass 扩展字段）
 * @returns 渲染后的 Table
 */
export const Table = React.forwardRef<HTMLTableElement, TableProps>(
  function Table(
    {
      className,
      data,
      columns,
      selectedRowKeys,
      onRowSelect,
      rowKey = 'id',
      virtualized = false,
      emptyText = '暂无数据',
      'aria-label': ariaLabel,
      'aria-labelledby': ariaLabelledBy,
      dataGlass = true,
      glassTier,
      glassVariant,
      motionVariants,
      ...props
    },
    ref,
  ) {
    // 构建 data-glass + data-glass-tier 属性（由 WebGL 层接管渲染）
    const validTier = isValidGlassTier(glassTier) ? glassTier : undefined;
    const glassAttributes = buildGlassDataAttributes(dataGlass, validTier);

    // 获取 Framer Motion variants（替换 shadcn 默认 Tailwind transition）
    // Table 使用 snappy spring；容器入场使用默认 variants（可选注入）
    const resolvedVariants: Variants | undefined =
      motionVariants ??
      (glassVariant
        ? getComponentMotionVariants({
            componentName: 'Table',
            springKey: glassVariant,
          })
        : undefined);

    // 行选中集合（用于快速查找）
    const selectedSet = React.useMemo(
      () => new Set(selectedRowKeys ?? []),
      [selectedRowKeys],
    );

    // 行点击：切换选中状态（仅在 onRowSelect 提供时启用选择语义）
    const handleRowClick = (key: string) => {
      if (!onRowSelect) return;
      const next = new Set(selectedSet);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      onRowSelect(Array.from(next));
    };

    // 构建 Table 容器 className（通过 className 消费 token，不硬编码颜色）
    const tableBaseClassName = cn(
      'w-full caption-bottom border-collapse',
      'text-[var(--table-text)] text-sm',
      'bg-[var(--table-bg)]',
      'rounded-[var(--table-radius)]',
      'border border-[var(--table-border)]',
      'transition-none', // 移除 shadcn 默认 Tailwind transition，由 Framer Motion 接管
      className,
    );

    // 注入 glass 样式类（仅当调用方提供 glassTier 时注入 CSS 降级样式）
    const composedClassName = validTier
      ? injectGlassClassName(tableBaseClassName, validTier)
      : tableBaseClassName;

    // virtualized prop 本次仅做语义接收（未来接入 react-window）
    // 当 virtualized=true 且数据量大时由后续优化承接，当前走基础渲染路径
    void virtualized;

    return (
      <motion.table
        ref={ref}
        className={composedClassName}
        // data-glass 属性（由 WebGL 层 GlassRenderer 扫描接管渲染）
        data-glass={glassAttributes['data-glass'] ?? undefined}
        data-glass-tier={glassAttributes['data-glass-tier'] ?? undefined}
        // Framer Motion variants（替换 shadcn 默认 Tailwind transition）
        {...(resolvedVariants ? { variants: resolvedVariants } : {})}
        aria-label={ariaLabel}
        aria-labelledby={ariaLabelledBy}
        {...props}
      >
        {/* 表头 */}
        <TableHeader>
          <TableRow>
            {columns.map((column) => (
              <TableHead
                key={column.key}
                align={column.align}
                style={
                  column.width !== undefined
                    ? { width: column.width }
                    : undefined
                }
              >
                {column.header}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        {/* 表体 */}
        <TableBody>
          {data.length === 0 ? (
            <TableRow>
              <TableCell
                colSpan={columns.length}
                align="center"
                className="py-8 text-[var(--table-empty-text)]"
              >
                {emptyText}
              </TableCell>
            </TableRow>
          ) : (
            data.map((row, index) => {
              const key = resolveRowKey(row, rowKey, index);
              const isSelected = selectedSet.has(key);
              const interactive = !!onRowSelect;
              return (
                <TableRow
                  key={key}
                  rowKey={key}
                  selected={isSelected}
                  interactive={interactive}
                  onClick={interactive ? () => handleRowClick(key) : undefined}
                >
                  {columns.map((column) => {
                    const cellValue = row[column.key];
                    const cellContent = column.render
                      ? column.render(cellValue, row, index)
                      : (cellValue as React.ReactNode);
                    return (
                      <TableCell key={column.key} align={column.align}>
                        {cellContent ?? null}
                      </TableCell>
                    );
                  })}
                </TableRow>
              );
            })
          )}
        </TableBody>
      </motion.table>
    );
  },
);

Table.displayName = 'Table';

// =============================================================================
// Table 子组件（TableHeader / TableBody / TableRow / TableHead / TableCell）
// =============================================================================

/**
 * TableHeader 组件（thead 容器，表头区域）。
 *
 * 通过 className 消费 token，不硬编码颜色。
 */
export const TableHeader = React.forwardRef<HTMLTableSectionElement, TableHeaderProps>(
  function TableHeader({ className, ...props }, ref) {
    return (
      <thead
        ref={ref}
        className={cn(
          'bg-[var(--table-header-bg)]',
          'border-b border-[var(--table-border)]',
          'transition-none',
          className,
        )}
        {...props}
      />
    );
  },
);

TableHeader.displayName = 'TableHeader';

/**
 * TableBody 组件（tbody 容器，表体区域）。
 *
 * 通过 className 消费 token，不硬编码颜色。
 */
export const TableBody = React.forwardRef<HTMLTableSectionElement, TableBodyProps>(
  function TableBody({ className, ...props }, ref) {
    return (
      <tbody
        ref={ref}
        className={cn('transition-none', className)}
        {...props}
      />
    );
  },
);

TableBody.displayName = 'TableBody';

/**
 * TableRow 组件（tr 行，支持 hover/selected 交互态）。
 *
 * 通过 className 消费 token，不硬编码颜色。
 * 交互态使用 Framer Motion variants（snappy spring，scale 微动 + 背景色过渡）。
 *
 * 默认 spring: snappy（D5 §springs.snappy.useCase=button-press，行 hover/选中快速响应）
 */
export const TableRow = React.forwardRef<HTMLTableRowElement, TableRowProps>(
  function TableRow(
    { className, selected = false, interactive = false, rowKey, ...props },
    ref,
  ) {
    // 行 hover/选中交互态的 snappy spring transition（Table 默认 spring）
    const rowSpring = getComponentSpringTransition(getDefaultComponentSpring('Table'));

    // 行交互态 variants（scale 微动 + 背景色由 className 控制）
    const rowVariants: Variants = {
      default: { scale: 1, transition: rowSpring },
      hover: { scale: 1.003, transition: rowSpring },
      selected: { scale: 1, transition: rowSpring },
    } as Variants;

    return (
      <motion.tr
        ref={ref}
        className={cn(
          'border-b border-[var(--table-border)]',
          'transition-none',
          interactive && 'cursor-pointer',
          selected && 'bg-[var(--table-row-selected-bg)]',
          !selected && interactive && 'hover:bg-[var(--table-row-hover-bg)]',
          className,
        )}
        // 行 hover/选中动画（snappy spring，scale 微动）
        variants={rowVariants}
        initial={false}
        animate={selected ? 'selected' : 'default'}
        whileHover={interactive ? 'hover' : undefined}
        {...(rowKey ? { 'data-row-key': rowKey } : {})}
        {...props}
      />
    );
  },
);

TableRow.displayName = 'TableRow';

/**
 * TableHead 组件（th 表头单元格）。
 *
 * 通过 className 消费 token，不硬编码颜色。
 */
export const TableHead = React.forwardRef<HTMLTableCellElement, TableHeadProps>(
  function TableHead({ className, align = 'left', ...props }, ref) {
    return (
      <th
        ref={ref}
        className={cn(
          'h-11 px-4 align-middle font-medium whitespace-nowrap',
          'text-[var(--table-header-text)]',
          alignClassMap[align],
          'transition-none',
          className,
        )}
        {...props}
      />
    );
  },
);

TableHead.displayName = 'TableHead';

/**
 * TableCell 组件（td 数据单元格）。
 *
 * 通过 className 消费 token，不硬编码颜色。
 */
export const TableCell = React.forwardRef<HTMLTableCellElement, TableCellProps>(
  function TableCell({ className, align = 'left', ...props }, ref) {
    return (
      <td
        ref={ref}
        className={cn(
          'p-4 align-middle',
          'text-[var(--table-text)]',
          alignClassMap[align],
          'transition-none',
          className,
        )}
        {...props}
      />
    );
  },
);

TableCell.displayName = 'TableCell';
