/**
 * @file graph-visualization.tsx — GraphVisualization 业务组件重组（模块7）
 * ============================================================================
 * 模块: 模块7 业务组件重组层 — A 组数据展示类
 * 落点: C:\CX-O\CX-O-Frontend\src\components\business\graph-visualization.tsx
 * 原组件: src/components/GraphVisualization.tsx
 *
 * 重组策略（MODULE-7 AGENTS.md §2.4）:
 *   - 保留现有业务逻辑（ForceGraph2D 渲染 / graphData memo / handleNodeClick 不变）
 *   - UI 层换用模块6 ui-v2 基础组件（Card）
 *   - 注入 Liquid Glass + data-glass + motion variants
 *   - 通过 className 消费 token，不硬编码颜色
 *   - 节点/关系调色板（nodeColorMap / linkColorMap）保留为业务逻辑（数据可视化专属配色）
 *
 * 跨模块导入约束（rules-0 §四 + MODULE-7 AGENTS.md §2.3）:
 *   - 仅 import 模块6 ui-v2 公开产出
 *   - 仅 import 第三方库 react-force-graph-2d / framer-motion
 *   - 禁止 import 模块8/9 内部实现
 * ============================================================================
 */

import { useCallback, useMemo } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import { motion, type Variants } from 'framer-motion';
import { cn } from '@/lib/utils';
import { Card } from '@/components/ui-v2';
import {
  buildGlassDataAttributes,
  getComponentMotionVariants,
} from '@/components/ui-v2';

export interface GraphNode {
  id: string;
  name: string;
  type: string;
  val?: number;
  data?: Record<string, unknown>;
}

export interface GraphLink {
  source: string;
  target: string;
  type: string;
  strength?: number;
}

export interface GraphVisualizationProps {
  nodes: GraphNode[];
  links: GraphLink[];
  width?: number;
  height?: number;
  onNodeClick?: (node: GraphNode) => void;
}

// 数据可视化调色板（节点/关系颜色映射，属业务逻辑，非 UI chrome 颜色）
const nodeColorMap: Record<string, string> = {
  Person: '#3b82f6',
  Organization: '#10b981',
  Location: '#f59e0b',
  Concept: '#8b5cf6',
  Event: '#ef4444',
  Thing: '#06b6d4',
  default: '#6b7280',
};

const linkColorMap: Record<string, string> = {
  KNOWS: '#3b82f6',
  WORKS_FOR: '#10b981',
  LOCATED_AT: '#f59e0b',
  RELATED_TO: '#8b5cf6',
  PARTICIPATED_IN: '#ef4444',
  default: '#9ca3af',
};

interface ForceGraphNode {
  id: string;
  name?: string;
  type?: string;
  [key: string]: unknown;
}

interface ForceGraphLink {
  source: string;
  target: string;
  type?: string;
  [key: string]: unknown;
}

// 入场 motion variants（基于模块6 getComponentMotionVariants 工厂，glass spring）
const graphVariants: Variants = getComponentMotionVariants({
  componentName: 'Card',
  springKey: 'glass',
});

export function GraphVisualization({
  nodes,
  links,
  width = 800,
  height = 600,
  onNodeClick,
}: GraphVisualizationProps) {
  const graphData = useMemo(() => {
    const forceNodes: ForceGraphNode[] = nodes.map((n) => ({
      id: n.id,
      name: n.name,
      type: n.type,
      ...n.data,
    }));
    const forceLinks: ForceGraphLink[] = links.map((l) => ({
      source: l.source,
      target: l.target,
      type: l.type,
    }));
    return { nodes: forceNodes, links: forceLinks };
  }, [nodes, links]);

  const handleNodeClick = useCallback(
    (node: ForceGraphNode) => {
      const graphNode: GraphNode = {
        id: node.id,
        name: node.name || '',
        type: node.type || '',
        data: node,
      };
      onNodeClick?.(graphNode);
    },
    [onNodeClick],
  );

  const glassAttributes = buildGlassDataAttributes(true, 3);

  return (
    <motion.div
      variants={graphVariants}
      initial="initial"
      animate="animate"
      exit="exit"
    >
      <Card
        className={cn('overflow-hidden')}
        dataGlass={true}
        glassTier={3}
      >
        <div style={{ width, height }} className="bg-[var(--color-bg-primary)]" {...glassAttributes}>
          <ForceGraph2D
            graphData={graphData}
            width={width}
            height={height}
            nodeColor={(node: Record<string, unknown>) =>
              nodeColorMap[node.type as string] || nodeColorMap.default
            }
            nodeRelSize={3}
            linkColor={(link: Record<string, unknown>) =>
              linkColorMap[link.type as string] || linkColorMap.default
            }
            linkDirectionalArrowLength={3}
            onNodeClick={handleNodeClick as unknown as (node: ForceGraphNode, event: MouseEvent) => void}
            cooldownTicks={100}
            d3AlphaMin={0.01}
            d3VelocityDecay={0.3}
            warmupTicks={50}
          />
        </div>
        <div className="p-4 border-t border-[var(--color-border)]">
          <div className="flex items-center gap-4 text-xs text-[var(--color-text-tertiary)]">
            <div className="flex items-center gap-2">
              <span>节点:</span>
              {Object.entries(nodeColorMap).slice(0, 5).map(([type, color]) => (
                <div key={type} className="flex items-center gap-1">
                  <span className="w-3 h-3 rounded-full" style={{ backgroundColor: color }} />
                  <span>{type}</span>
                </div>
              ))}
            </div>
            <div className="flex items-center gap-2">
              <span>关系:</span>
              {Object.entries(linkColorMap).slice(0, 3).map(([type, color]) => (
                <div key={type} className="flex items-center gap-1">
                  <span className="w-3 h-1 rounded" style={{ backgroundColor: color }} />
                  <span>{type}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </Card>
    </motion.div>
  );
}
