import { useCallback, useMemo } from 'react';
import ForceGraph2D from 'react-force-graph-2d';

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
    [onNodeClick]
  );

  return (
    <div className="border border-[var(--color-border)] rounded-[var(--radius-lg)] overflow-hidden bg-[var(--color-bg-primary)]">
      <div style={{ width, height }} className="bg-[var(--color-bg-primary)]">
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
    </div>
  );
}
