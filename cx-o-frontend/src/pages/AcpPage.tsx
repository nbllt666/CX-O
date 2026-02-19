import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Bot,
  Users,
  MessageSquare,
  Activity,
  RefreshCw,
  Plus,
  Trash2,
  Edit3,
  CheckCircle2,
  XCircle,
  Loader2,
  Network,
} from 'lucide-react';
import { api } from '../api/client';
import { cn } from '../lib/utils';

interface Agent {
  id: string;
  name: string;
  description: string;
  status: 'active' | 'inactive' | 'error';
  capabilities: string[];
  created_at: string;
  last_active?: string;
}

interface AcpStats {
  total_agents: number;
  active_agents: number;
  total_conversations: number;
  avg_response_time: number;
}

export function AcpPage() {
  const queryClient = useQueryClient();
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null);
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);

  // Fetch ACP stats
  const { data: stats, isLoading: statsLoading } = useQuery<AcpStats>({
    queryKey: ['acp-stats'],
    queryFn: async () => {
      const response = await api.getAcpStats();
      return response;
    },
    refetchInterval: 10000,
  });

  // Fetch agents list
  const { data: agents, isLoading: agentsLoading } = useQuery<Agent[]>({
    queryKey: ['acp-agents'],
    queryFn: async () => {
      const response = await api.getAgents();
      return response.agents || [];
    },
    refetchInterval: 5000,
  });

  // Create agent mutation
  const createAgentMutation = useMutation({
    mutationFn: api.createAgent,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['acp-agents'] });
      queryClient.invalidateQueries({ queryKey: ['acp-stats'] });
      setIsCreateModalOpen(false);
    },
  });

  // Update agent mutation
  const updateAgentMutation = useMutation({
    mutationFn: ({
      id,
      data,
    }: {
      id: string;
      data: {
        name?: string;
        description?: string;
        capabilities?: string[];
        status?: 'active' | 'inactive';
      };
    }) => api.updateAgent(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['acp-agents'] });
      setIsEditModalOpen(false);
      setSelectedAgent(null);
    },
  });

  // Delete agent mutation
  const deleteAgentMutation = useMutation({
    mutationFn: api.deleteAgent,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['acp-agents'] });
      queryClient.invalidateQueries({ queryKey: ['acp-stats'] });
      setSelectedAgent(null);
    },
  });

  // Toggle agent status
  const toggleAgentStatus = (agent: Agent) => {
    updateAgentMutation.mutate({
      id: agent.id,
      data: { status: agent.status === 'active' ? 'inactive' : 'active' },
    });
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Network className="w-6 h-6 text-primary" />
            ACP 管理
          </h1>
          <p className="text-muted-foreground mt-1">管理 AI 代理和协调协议</p>
        </div>
        <button
          onClick={() => setIsCreateModalOpen(true)}
          className="flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
        >
          <Plus className="w-4 h-4" />
          创建代理
        </button>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <StatCard
          title="总代理数"
          value={stats?.total_agents || 0}
          icon={Bot}
          loading={statsLoading}
        />
        <StatCard
          title="活跃代理"
          value={stats?.active_agents || 0}
          icon={Activity}
          loading={statsLoading}
          trend={
            stats ? `${Math.round((stats.active_agents / stats.total_agents) * 100)}%` : undefined
          }
        />
        <StatCard
          title="总会话数"
          value={stats?.total_conversations || 0}
          icon={MessageSquare}
          loading={statsLoading}
        />
        <StatCard
          title="平均响应时间"
          value={`${stats?.avg_response_time?.toFixed(2) || 0}ms`}
          icon={RefreshCw}
          loading={statsLoading}
        />
      </div>

      {/* Agents List */}
      <div className="bg-card rounded-lg border border-border">
        <div className="p-4 border-b border-border flex items-center justify-between">
          <h2 className="font-semibold flex items-center gap-2">
            <Users className="w-5 h-5" />
            代理列表
          </h2>
          <button
            onClick={() => queryClient.invalidateQueries({ queryKey: ['acp-agents'] })}
            className="p-2 hover:bg-accent rounded-lg transition-colors"
            title="刷新"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>

        {agentsLoading ? (
          <div className="p-8 flex justify-center">
            <Loader2 className="w-8 h-8 animate-spin text-primary" />
          </div>
        ) : agents && agents.length > 0 ? (
          <div className="divide-y divide-border">
            {agents.map((agent) => (
              <div
                key={agent.id}
                className={cn(
                  'p-4 hover:bg-accent/50 transition-colors cursor-pointer',
                  selectedAgent?.id === agent.id && 'bg-accent'
                )}
                onClick={() => setSelectedAgent(agent)}
              >
                <div className="flex items-start justify-between">
                  <div className="flex items-start gap-3">
                    <div
                      className={cn(
                        'w-10 h-10 rounded-lg flex items-center justify-center',
                        agent.status === 'active'
                          ? 'bg-green-500/10'
                          : agent.status === 'error'
                            ? 'bg-red-500/10'
                            : 'bg-[var(--color-bg-tertiary)]'
                      )}
                    >
                      <Bot
                        className={cn(
                          'w-5 h-5',
                          agent.status === 'active'
                            ? 'text-green-500'
                            : agent.status === 'error'
                              ? 'text-red-500'
                              : 'text-[var(--color-text-tertiary)]'
                        )}
                      />
                    </div>
                    <div>
                      <h3 className="font-medium">{agent.name}</h3>
                      <p className="text-sm text-muted-foreground">{agent.description}</p>
                      <div className="flex items-center gap-2 mt-2">
                        <span
                          className={cn(
                            'text-xs px-2 py-0.5 rounded-full',
                            agent.status === 'active'
                              ? 'bg-green-500/10 text-green-600'
                              : agent.status === 'error'
                                ? 'bg-red-500/10 text-red-600'
                                : 'bg-[var(--color-bg-tertiary)] text-[var(--color-text-tertiary)]'
                          )}
                        >
                          {agent.status === 'active'
                            ? '活跃'
                            : agent.status === 'error'
                              ? '错误'
                              : '停用'}
                        </span>
                        {agent.capabilities.map((cap) => (
                          <span
                            key={cap}
                            className="text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary"
                          >
                            {cap}
                          </span>
                        ))}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        toggleAgentStatus(agent);
                      }}
                      className={cn(
                        'p-2 rounded-lg transition-colors',
                        agent.status === 'active'
                          ? 'hover:bg-red-500/10 hover:text-red-500'
                          : 'hover:bg-green-500/10 hover:text-green-500'
                      )}
                      title={agent.status === 'active' ? '停用' : '启用'}
                    >
                      {agent.status === 'active' ? (
                        <XCircle className="w-4 h-4" />
                      ) : (
                        <CheckCircle2 className="w-4 h-4" />
                      )}
                    </button>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setSelectedAgent(agent);
                        setIsEditModalOpen(true);
                      }}
                      className="p-2 hover:bg-accent rounded-lg transition-colors"
                      title="编辑"
                    >
                      <Edit3 className="w-4 h-4" />
                    </button>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        if (confirm('确定要删除此代理吗？')) {
                          deleteAgentMutation.mutate(agent.id);
                        }
                      }}
                      className="p-2 hover:bg-red-500/10 hover:text-red-500 rounded-lg transition-colors"
                      title="删除"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="p-8 text-center text-muted-foreground">
            <Bot className="w-12 h-12 mx-auto mb-3 opacity-50" />
            <p>暂无代理</p>
            <button
              onClick={() => setIsCreateModalOpen(true)}
              className="mt-4 text-primary hover:underline"
            >
              创建第一个代理
            </button>
          </div>
        )}
      </div>

      {/* Create Modal */}
      {isCreateModalOpen && (
        <AgentModal
          title="创建代理"
          onClose={() => setIsCreateModalOpen(false)}
          onSubmit={(data) => createAgentMutation.mutate(data)}
          isLoading={createAgentMutation.isPending}
        />
      )}

      {/* Edit Modal */}
      {isEditModalOpen && selectedAgent && (
        <AgentModal
          title="编辑代理"
          agent={selectedAgent}
          onClose={() => {
            setIsEditModalOpen(false);
            setSelectedAgent(null);
          }}
          onSubmit={(data) => updateAgentMutation.mutate({ id: selectedAgent.id, data })}
          isLoading={updateAgentMutation.isPending}
        />
      )}
    </div>
  );
}

// Stat Card Component
function StatCard({
  title,
  value,
  icon: Icon,
  loading,
  trend,
}: {
  title: string;
  value: string | number;
  icon: React.ElementType;
  loading?: boolean;
  trend?: string;
}) {
  return (
    <div className="bg-card p-4 rounded-lg border border-border">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm text-muted-foreground">{title}</p>
          {loading ? (
            <Loader2 className="w-6 h-6 animate-spin mt-2" />
          ) : (
            <div className="flex items-baseline gap-2">
              <p className="text-2xl font-bold mt-1">{value}</p>
              {trend && <span className="text-xs text-green-500">{trend}</span>}
            </div>
          )}
        </div>
        <div className="p-2 bg-primary/10 rounded-lg">
          <Icon className="w-5 h-5 text-primary" />
        </div>
      </div>
    </div>
  );
}

// Agent Modal Component
interface AgentModalProps {
  title: string;
  agent?: Agent;
  onClose: () => void;
  onSubmit: (data: {
    name: string;
    description?: string;
    capabilities?: string[];
    status?: 'active' | 'inactive';
  }) => void;
  isLoading: boolean;
}

function AgentModal({ title, agent, onClose, onSubmit, isLoading }: AgentModalProps) {
  const [formData, setFormData] = useState({
    name: agent?.name || '',
    description: agent?.description || '',
    capabilities: agent?.capabilities?.join(', ') || '',
    status: (agent?.status as 'active' | 'inactive') || 'inactive',
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSubmit({
      name: formData.name,
      description: formData.description,
      capabilities: formData.capabilities
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean),
      status: formData.status,
    });
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-card rounded-lg border border-border w-full max-w-md p-6">
        <h2 className="text-xl font-semibold mb-4">{title}</h2>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium mb-1">名称</label>
            <input
              type="text"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              className="w-full px-3 py-2 bg-muted rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/50"
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">描述</label>
            <textarea
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              className="w-full px-3 py-2 bg-muted rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/50"
              rows={3}
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">能力（逗号分隔）</label>
            <input
              type="text"
              value={formData.capabilities}
              onChange={(e) => setFormData({ ...formData, capabilities: e.target.value })}
              className="w-full px-3 py-2 bg-muted rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/50"
              placeholder="chat, memory, tool"
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">状态</label>
            <select
              value={formData.status}
              onChange={(e) =>
                setFormData({ ...formData, status: e.target.value as 'active' | 'inactive' })
              }
              className="w-full px-3 py-2 bg-muted rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/50"
            >
              <option value="active">活跃</option>
              <option value="inactive">停用</option>
            </select>
          </div>
          <div className="flex justify-end gap-3 pt-4">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-muted-foreground hover:text-foreground transition-colors"
            >
              取消
            </button>
            <button
              type="submit"
              disabled={isLoading}
              className="px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50 flex items-center gap-2"
            >
              {isLoading && <Loader2 className="w-4 h-4 animate-spin" />}
              {agent ? '保存' : '创建'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
