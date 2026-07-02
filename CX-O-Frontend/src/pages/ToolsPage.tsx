import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Wrench, Plus, CheckCircle2, Loader2, Code, Terminal } from 'lucide-react';
import { api, type ToolStats } from '../api/client';
import { cn } from '../lib/utils';
import type { Tool } from './tools/types';
import { StatCard } from './tools/StatCard';
import { ToolCard } from './tools/ToolCard';
import { ToolModal } from './tools/ToolModal';
import { TestToolModal } from './tools/TestToolModal';

export function ToolsPage() {
  const queryClient = useQueryClient();
  const [selectedTool, setSelectedTool] = useState<Tool | null>(null);
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [isTestModalOpen, setIsTestModalOpen] = useState(false);
  const [filter, setFilter] = useState<'all' | 'builtin' | 'mcp' | 'custom' | 'cxfc'>('all');

  // Fetch tools stats
  const { data: stats, isLoading: statsLoading } = useQuery<ToolStats>({
    queryKey: ['tools-stats'],
    queryFn: () => api.getToolsStats(),
    refetchInterval: 10000,
  });

  // Fetch tools list
  const { data: toolsData, isLoading: toolsLoading } = useQuery({
    queryKey: ['tools', filter],
    queryFn: async () => {
      const response = await api.getTools(filter === 'all' ? undefined : filter);
      const toolsObj = response.tools || {};
      return Object.entries(toolsObj).map(([key, tool]) => {
        const name = tool.name ?? key;
        return {
          id: tool.id ?? name,
          name,
          description: tool.description ?? '',
          type: (tool.type || 'custom') as Tool['type'],
          status: tool.status || 'inactive',
          config: tool.config ?? {},
          icon: tool.icon,
          created_at: tool.created_at ?? new Date().toISOString(),
          last_used: tool.last_used,
          use_count: tool.use_count ?? 0,
          parameters: tool.parameters,
          examples: tool.examples,
          tags: tool.tags,
          source_plugin_id: tool.source_plugin_id,
        } satisfies Tool;
      });
    },
  });

  // Create tool mutation
  const createToolMutation = useMutation({
    mutationFn: (payload: {
      name: string;
      description?: string;
      type: 'mcp' | 'native' | 'custom';
      icon?: string;
      config?: Record<string, unknown>;
      parameters?: Record<string, unknown>;
      examples?: string[];
      tags?: string[];
    }) => api.createTool({ ...payload, enabled: true }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tools'] });
      queryClient.invalidateQueries({ queryKey: ['tools-stats'] });
      setIsCreateModalOpen(false);
    },
  });

  // Update tool mutation
  const updateToolMutation = useMutation({
    mutationFn: ({
      id,
      data,
    }: {
      id: string;
      data: {
        name?: string;
        description?: string;
        type?: 'mcp' | 'native' | 'custom';
        icon?: string;
        config?: Record<string, unknown>;
        status?: 'active' | 'inactive';
      };
    }) => api.updateTool(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tools'] });
      setIsEditModalOpen(false);
      setSelectedTool(null);
    },
  });

  // Delete tool mutation
  const deleteToolMutation = useMutation({
    mutationFn: api.deleteTool,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tools'] });
      queryClient.invalidateQueries({ queryKey: ['tools-stats'] });
      setSelectedTool(null);
    },
  });

  // Toggle tool status
  const toggleToolStatus = (tool: Tool) => {
    updateToolMutation.mutate({
      id: tool.id,
      data: { status: tool.status === 'active' ? 'inactive' : 'active' },
    });
  };

  // Open test modal
  const handleOpenTest = (tool: Tool) => {
    setSelectedTool(tool);
    setIsTestModalOpen(true);
  };

  // Open edit modal
  const handleOpenEdit = (tool: Tool) => {
    setSelectedTool(tool);
    setIsEditModalOpen(true);
  };

  // Delete tool with confirm
  const handleDeleteTool = (tool: Tool) => {
    if (confirm('确定要删除此工具吗？')) {
      deleteToolMutation.mutate(tool.id);
    }
  };

  // Filter tools
  const filteredTools = toolsData?.filter((tool) => filter === 'all' || tool.type === filter);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Wrench className="w-6 h-6 text-primary" />
            工具管理
          </h1>
          <p className="text-muted-foreground mt-1">管理 MCP 工具、原生工具和自定义工具</p>
        </div>
        <button
          onClick={() => setIsCreateModalOpen(true)}
          className="flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
        >
          <Plus className="w-4 h-4" />
          添加工具
        </button>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <StatCard
          title="总工具数"
          value={stats?.total_tools || 0}
          icon={Wrench}
          loading={statsLoading}
        />
        <StatCard
          title="活跃工具"
          value={stats?.active_tools || 0}
          icon={CheckCircle2}
          loading={statsLoading}
          trend={
            stats && stats.active_tools !== undefined ? `${Math.round((stats.active_tools / stats.total_tools) * 100)}%` : undefined
          }
        />
        <StatCard
          title="MCP 工具"
          value={stats?.mcp_tools || 0}
          icon={Code}
          loading={statsLoading}
        />
        <StatCard
          title="总调用次数"
          value={stats?.total_calls || 0}
          icon={Terminal}
          loading={statsLoading}
        />
      </div>

      {/* Filter Tabs */}
      <div className="flex gap-2">
        {(['all', 'builtin', 'mcp', 'custom', 'cxfc'] as const).map((type) => (
          <button
            key={type}
            onClick={() => setFilter(type)}
            className={cn(
              'px-4 py-2 rounded-lg text-sm font-medium transition-colors',
              filter === type
                ? 'bg-primary text-primary-foreground'
                : 'bg-muted text-muted-foreground hover:bg-accent'
            )}
          >
            {type === 'all'
              ? '全部'
              : type === 'builtin'
                ? '内置'
                : type === 'mcp'
                  ? 'MCP'
                  : type === 'cxfc'
                    ? 'CXFC'
                    : '自定义'}
          </button>
        ))}
      </div>

      {/* Tools Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {toolsLoading ? (
          <div className="col-span-full flex justify-center py-12">
            <Loader2 className="w-8 h-8 animate-spin text-primary" />
          </div>
        ) : filteredTools && filteredTools.length > 0 ? (
          filteredTools.map((tool) => (
            <ToolCard
              key={tool.id}
              tool={tool}
              onToggle={toggleToolStatus}
              onTest={handleOpenTest}
              onEdit={handleOpenEdit}
              onDelete={handleDeleteTool}
            />
          ))
        ) : (
          <div className="col-span-full text-center py-12 text-muted-foreground">
            <Wrench className="w-12 h-12 mx-auto mb-3 opacity-50" />
            <p>暂无工具</p>
            <button
              onClick={() => setIsCreateModalOpen(true)}
              className="mt-4 text-primary hover:underline"
            >
              添加第一个工具
            </button>
          </div>
        )}
      </div>

      {/* Create Modal */}
      {isCreateModalOpen && (
        <ToolModal
          title="添加工具"
          onClose={() => setIsCreateModalOpen(false)}
          onSubmit={(data) => createToolMutation.mutate(data)}
          isLoading={createToolMutation.isPending}
        />
      )}

      {/* Edit Modal */}
      {isEditModalOpen && selectedTool && (
        <ToolModal
          title="编辑工具"
          tool={selectedTool}
          onClose={() => {
            setIsEditModalOpen(false);
            setSelectedTool(null);
          }}
          onSubmit={(data) => updateToolMutation.mutate({ id: selectedTool.id, data })}
          isLoading={updateToolMutation.isPending}
        />
      )}

      {/* Test Modal */}
      {isTestModalOpen && selectedTool && (
        <TestToolModal
          tool={selectedTool}
          onClose={() => {
            setIsTestModalOpen(false);
            setSelectedTool(null);
          }}
        />
      )}
    </div>
  );
}
