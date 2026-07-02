import {
  ToggleLeft,
  ToggleRight,
  Play,
  Edit3,
  Trash2,
} from 'lucide-react';
import type { Tool } from './types';
import { toolIcons, toolFallbackIcon } from './types';
import { cn } from '../../lib/utils';

interface ToolCardProps {
  tool: Tool;
  onToggle: (tool: Tool) => void;
  onTest: (tool: Tool) => void;
  onEdit: (tool: Tool) => void;
  onDelete: (tool: Tool) => void;
}

export function ToolCard({ tool, onToggle, onTest, onEdit, onDelete }: ToolCardProps) {
  const IconComponent = toolIcons[tool.icon || ''] || toolFallbackIcon;
  return (
    <div className="bg-card rounded-lg border border-border p-4 hover:shadow-md transition-shadow">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <div
            className={cn(
              'w-10 h-10 rounded-lg flex items-center justify-center',
              tool.status === 'active' ? 'bg-primary/10' : 'bg-muted'
            )}
          >
            <IconComponent
              className={cn(
                'w-5 h-5',
                tool.status === 'active' ? 'text-primary' : 'text-muted-foreground'
              )}
            />
          </div>
          <div>
            <h3 className="font-medium">{tool.name}</h3>
            <p className="text-sm text-muted-foreground">
              {tool.type === 'cxfc' ? 'CXFC' : tool.type}
              {tool.type === 'cxfc' && tool.source_plugin_id && ` · ${tool.source_plugin_id}`}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={() => onToggle(tool)}
            className="p-1.5 hover:bg-accent rounded-lg transition-colors"
            title={tool.status === 'active' ? '停用' : '启用'}
          >
            {tool.status === 'active' ? (
              <ToggleRight className="w-5 h-5 text-green-500" />
            ) : (
              <ToggleLeft className="w-5 h-5 text-[var(--color-text-muted)]" />
            )}
          </button>
        </div>
      </div>

      <p className="text-sm text-muted-foreground mt-3 line-clamp-2">
        {tool.description || '暂无描述'}
      </p>

      <div className="mt-4 pt-4 border-t border-border">
        <div className="flex items-center justify-between text-sm text-muted-foreground">
          <span>调用次数: {tool.use_count}</span>
          {tool.last_used && (
            <span>最后使用: {new Date(tool.last_used).toLocaleDateString()}</span>
          )}
        </div>
        <div className="flex gap-2 mt-3">
          <button
            onClick={() => onTest(tool)}
            className="flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 text-sm bg-muted rounded-lg hover:bg-accent transition-colors"
          >
            <Play className="w-4 h-4" />
            测试
          </button>
          <button
            onClick={() => onEdit(tool)}
            className="flex items-center justify-center gap-1.5 px-3 py-1.5 text-sm bg-muted rounded-lg hover:bg-accent transition-colors"
          >
            <Edit3 className="w-4 h-4" />
          </button>
          <button
            onClick={() => onDelete(tool)}
            className="flex items-center justify-center gap-1.5 px-3 py-1.5 text-sm bg-muted rounded-lg hover:bg-red-500/10 hover:text-red-500 transition-colors"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
