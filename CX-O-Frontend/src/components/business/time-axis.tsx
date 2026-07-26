/**
 * @file time-axis.tsx — TimeAxis 业务组件重组（模块7）
 * ============================================================================
 * 模块: 模块7 业务组件重组层 — A 组数据展示类
 * 落点: C:\CX-O\CX-O-Frontend\src\components\business\time-axis.tsx
 * 原组件: src/components/TimeAxis.tsx
 *
 * 重组策略（MODULE-7 AGENTS.md §2.4）:
 *   - 保留现有业务逻辑（d3-scale / d3-zoom / d3-selection 全部逻辑不变）
 *   - UI 层换用模块6 ui-v2 基础组件（Card）
 *   - 注入 Liquid Glass + data-glass + motion variants
 *   - 通过 className 消费 token，不硬编码颜色
 *   - d3 数据可视化调色板（colorScale.range）保留为业务逻辑（数据可视化专属配色）
 *
 * 跨模块导入约束（rules-0 §四 + MODULE-7 AGENTS.md §2.3）:
 *   - 仅 import 模块6 ui-v2 公开产出
 *   - 仅 import 第三方库 d3-scale / d3-zoom / d3-selection / framer-motion
 *   - 禁止 import 模块8/9 内部实现
 * ============================================================================
 */

import { useRef, useState, useCallback, useMemo, useEffect } from 'react';
import { scaleTime, scaleLinear } from 'd3-scale';
import { zoom, zoomIdentity, type ZoomTransform, type D3ZoomEvent } from 'd3-zoom';
import { select } from 'd3-selection';
import { motion, type Variants } from 'framer-motion';
import { cn } from '@/lib/utils';
import { Card } from '@/components/ui-v2';
import {
  buildGlassDataAttributes,
  getComponentMotionVariants,
} from '@/components/ui-v2';

export interface TimeAxisDataPoint {
  timestamp: string;
  count: number;
}

export interface TimeAxisProps {
  data: TimeAxisDataPoint[];
  width?: number;
  height?: number;
  onTimeRangeChange?: (start: Date, end: Date) => void;
  onTimeRangeSelected?: (start: Date, end: Date) => void;
}

// 入场 motion variants（基于模块6 getComponentMotionVariants 工厂，glass spring）
const axisVariants: Variants = getComponentMotionVariants({
  componentName: 'Card',
  springKey: 'glass',
});

// 数据可视化调色板（d3 colorScale 专属配色，属业务逻辑，非 UI chrome 颜色）
const VIZ_COLOR_LOW = '#3b82f6';
const VIZ_COLOR_MID1 = '#10b981';
const VIZ_COLOR_MID2 = '#f59e0b';
const VIZ_COLOR_HIGH = '#ef4444';

export function TimeAxis({
  data,
  width = 800,
  height = 120,
  onTimeRangeChange,
  onTimeRangeSelected,
}: TimeAxisProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const [transform, setTransform] = useState<ZoomTransform>(zoomIdentity);
  const [selectedRange, setSelectedRange] = useState<{ start: Date; end: Date } | null>(null);
  const [isSelecting, setIsSelecting] = useState(false);
  const [selectionStart, setSelectionStart] = useState<number>(0);
  const [selectionEnd, setSelectionEnd] = useState<number>(0);

  const parsedData = useMemo(() => {
    return data
      .map((d) => ({
        ...d,
        date: new Date(d.timestamp),
      }))
      .sort((a, b) => a.date.getTime() - b.date.getTime());
  }, [data]);

  const extent = useMemo((): [Date, Date] => {
    if (parsedData.length === 0) return [new Date(), new Date()];
    const dates = parsedData.map((d) => d.date.getTime());
    return [new Date(Math.min(...dates)), new Date(Math.max(...dates))];
  }, [parsedData]);

  const maxCount = useMemo(() => {
    return Math.max(...parsedData.map((d) => d.count), 1);
  }, [parsedData]);

  const timeScale = useMemo(() => {
    return scaleTime()
      .domain(extent)
      .range([0, width]);
  }, [extent, width]);

  const countScale = useMemo(() => {
    return scaleLinear()
      .domain([0, maxCount])
      .range([height - 40, 10]);
  }, [maxCount, height]);

  const colorScale = useMemo(() => {
    return scaleLinear<string>()
      .domain([0, maxCount * 0.3, maxCount * 0.6, maxCount])
      .range([VIZ_COLOR_LOW, VIZ_COLOR_MID1, VIZ_COLOR_MID2, VIZ_COLOR_HIGH]);
  }, [maxCount]);

  const handleZoom = useCallback(
    (event: D3ZoomEvent<SVGSVGElement, unknown>) => {
      const newTransform = event.transform;
      setTransform(newTransform);

      const newTimeScale = newTransform.rescaleX(timeScale);
      const domain = newTimeScale.domain();
      onTimeRangeChange?.(domain[0], domain[1]);
    },
    [timeScale, onTimeRangeChange],
  );

  useEffect(() => {
    if (!containerRef.current || !svgRef.current) return;

    const svg = select(svgRef.current as SVGSVGElement);

    const zoomBehavior = zoom<SVGSVGElement, unknown>()
      .scaleExtent([1, 50])
      .extent([
        [0, 0],
        [width, height],
      ])
      .translateExtent([
        [0, 0],
        [width, height],
      ])
      .on('zoom', handleZoom);

    svg.call(zoomBehavior);

    return () => {
      svg.on('.zoom', null);
    };
  }, [width, height, handleZoom]);

  const handleMouseDown = useCallback((e: React.MouseEvent<SVGSVGElement>) => {
    setIsSelecting(true);
    const rect = svgRef.current?.getBoundingClientRect();
    if (rect) {
      const x = e.clientX - rect.left;
      setSelectionStart(x);
      setSelectionEnd(x);
    }
  }, []);

  const handleMouseMove = useCallback((e: React.MouseEvent<SVGSVGElement>) => {
    if (!isSelecting) return;
    const rect = svgRef.current?.getBoundingClientRect();
    if (rect) {
      const x = e.clientX - rect.left;
      setSelectionEnd(x);
    }
  }, [isSelecting]);

  const handleMouseUp = useCallback(() => {
    if (!isSelecting) return;
    setIsSelecting(false);

    const startX = Math.min(selectionStart, selectionEnd);
    const endX = Math.max(selectionStart, selectionEnd);

    if (Math.abs(endX - startX) > 5) {
      const newTimeScale = transform.rescaleX(timeScale);
      const domain = newTimeScale.domain();
      const range = domain[1].getTime() - domain[0].getTime();

      const startTime = domain[0].getTime() + range * (startX / width);
      const endTime = domain[0].getTime() + range * (endX / width);

      const newRange = { start: new Date(startTime), end: new Date(endTime) };
      setSelectedRange(newRange);
      onTimeRangeSelected?.(newRange.start, newRange.end);
    }

    setSelectionStart(0);
    setSelectionEnd(0);
  }, [isSelecting, selectionStart, selectionEnd, transform, timeScale, width, onTimeRangeSelected]);

  const ticks = useMemo(() => {
    const count = Math.floor(width / 100);
    return timeScale.ticks(count);
  }, [timeScale, width]);

  const visibleData = useMemo(() => {
    const newTimeScale = transform.rescaleX(timeScale);
    const domain = newTimeScale.domain();
    return parsedData.filter((d) => d.date >= domain[0] && d.date <= domain[1]);
  }, [parsedData, transform, timeScale]);

  const glassAttributes = buildGlassDataAttributes(true, 3);

  return (
    <motion.div
      variants={axisVariants}
      initial="initial"
      animate="animate"
      exit="exit"
    >
      <Card
        className={cn('p-4')}
        dataGlass={true}
        glassTier={3}
      >
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-semibold text-[var(--color-text-primary)]">向量时间分布</h3>
          <div className="flex items-center gap-2">
            {selectedRange && (
              <span className="text-xs text-[var(--color-text-tertiary)]">
                已选：{selectedRange.start.toLocaleString()} - {selectedRange.end.toLocaleString()}
              </span>
            )}
          </div>
        </div>

        <div ref={containerRef} style={{ width, height }} {...glassAttributes}>
          <svg
            ref={svgRef}
            width={width}
            height={height}
            className="cursor-crosshair"
            onMouseDown={handleMouseDown}
            onMouseMove={handleMouseMove}
            onMouseUp={handleMouseUp}
            onMouseLeave={handleMouseUp}
          >
            <g transform={transform.toString()}>
              {visibleData.map((d, i) => {
                const x = timeScale(d.date);
                const barWidth = Math.max(1, (width / Math.max(visibleData.length, 1)) * 0.8);
                const barHeight = countScale(d.count);
                const color = colorScale(d.count);

                return (
                  <rect
                    key={i}
                    x={x - barWidth / 2}
                    y={barHeight}
                    width={barWidth}
                    height={height - 40 - barHeight}
                    fill={color}
                    opacity={0.7}
                    rx={1}
                  >
                    <title>{`${d.date.toLocaleString()}: ${d.count} 个向量`}</title>
                  </rect>
                );
              })}

              {ticks.map((tick, i) => (
                <g key={i}>
                  <line
                    x1={timeScale(tick)}
                    y1={10}
                    x2={timeScale(tick)}
                    y2={height - 40}
                    stroke="var(--color-border)"
                    strokeWidth={1}
                    strokeDasharray="2,2"
                    opacity={0.3}
                  />
                  <text
                    x={timeScale(tick)}
                    y={height - 25}
                    textAnchor="middle"
                    className="text-[10px] fill-[var(--color-text-tertiary)]"
                  >
                    {tick.toLocaleDateString()}
                  </text>
                </g>
              ))}

              {selectedRange && (
                <rect
                  x={timeScale(selectedRange.start)}
                  y={10}
                  width={timeScale(selectedRange.end) - timeScale(selectedRange.start)}
                  height={height - 40}
                  fill="none"
                  stroke={VIZ_COLOR_LOW}
                  strokeWidth={2}
                  strokeDasharray="4,2"
                  opacity={0.5}
                />
              )}

              {isSelecting && (
                <rect
                  x={Math.min(selectionStart, selectionEnd)}
                  y={10}
                  width={Math.abs(selectionEnd - selectionStart)}
                  height={height - 40}
                  fill={VIZ_COLOR_LOW}
                  opacity={0.2}
                  stroke={VIZ_COLOR_LOW}
                  strokeWidth={1}
                  strokeDasharray="2,2"
                />
              )}
            </g>

            <line
              x1={0}
              y1={height - 40}
              x2={width}
              y2={height - 40}
              stroke="var(--color-border)"
              strokeWidth={2}
            />
          </svg>
        </div>

        <div className="mt-2 flex items-center justify-between text-xs text-[var(--color-text-tertiary)]">
          <span>提示：滚动鼠标缩放，拖拽平移，点击拖拽选择时间段</span>
          <div className="flex items-center gap-2">
            <span>密度:</span>
            <div className="flex items-center gap-1">
              <span className="w-4 h-2 rounded" style={{ backgroundColor: VIZ_COLOR_LOW }} />
              <span>低</span>
            </div>
            <div className="flex items-center gap-1">
              <span className="w-4 h-2 rounded" style={{ backgroundColor: VIZ_COLOR_HIGH }} />
              <span>高</span>
            </div>
          </div>
        </div>
      </Card>
    </motion.div>
  );
}
