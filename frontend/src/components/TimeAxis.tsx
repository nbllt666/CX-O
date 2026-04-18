import { useRef, useState, useCallback, useMemo, useEffect } from 'react';
import { scaleTime, scaleLinear } from 'd3-scale';
import { zoom, zoomIdentity, ZoomTransform, D3ZoomEvent } from 'd3-zoom';
import { select } from 'd3-selection';

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
      .range(['#3b82f6', '#10b981', '#f59e0b', '#ef4444']);
  }, [maxCount]);

  const handleZoom = useCallback(
    (event: D3ZoomEvent<SVGSVGElement, unknown>) => {
      const newTransform = event.transform;
      setTransform(newTransform);

      const newTimeScale = newTransform.rescaleX(timeScale);
      const domain = newTimeScale.domain();
      onTimeRangeChange?.(domain[0], domain[1]);
    },
    [timeScale, onTimeRangeChange]
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

      const startTime = domain[0].getTime() + (range * (startX / width));
      const endTime = domain[0].getTime() + (range * (endX / width));

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
    return parsedData.filter(
      (d) => d.date >= domain[0] && d.date <= domain[1]
    );
  }, [parsedData, transform, timeScale]);

  return (
    <div className="border border-[var(--color-border)] rounded-[var(--radius-lg)] p-4 bg-[var(--color-bg-primary)]">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-semibold">向量时间分布</h3>
        <div className="flex items-center gap-2">
          {selectedRange && (
            <span className="text-xs text-[var(--color-text-tertiary)]">
              已选：{selectedRange.start.toLocaleString()} - {selectedRange.end.toLocaleString()}
            </span>
          )}
        </div>
      </div>

      <div ref={containerRef} style={{ width, height }}>
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
                stroke="#3b82f6"
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
                fill="#3b82f6"
                opacity={0.2}
                stroke="#3b82f6"
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
            <span className="w-4 h-2 rounded" style={{ backgroundColor: '#3b82f6' }} />
            <span>低</span>
          </div>
          <div className="flex items-center gap-1">
            <span className="w-4 h-2 rounded" style={{ backgroundColor: '#ef4444' }} />
            <span>高</span>
          </div>
        </div>
      </div>
    </div>
  );
}
