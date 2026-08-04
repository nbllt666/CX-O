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
import { api, type AcpStats, type AcpAgentRow } from '../api/client';
import { cn } from '../lib/utils';
import { Button, Card, CardBody, Badge, Dialog, Input, Textarea, Select } from '@/components/ui-v2';

export function AcpPage() {
  const queryClient = useQueryClient();
  const [selectedAgent, setSelectedAgent] = useState<AcpAgentRow | null>(null);
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
  const { data: agents, isLoading: agentsLoading } = useQuery<AcpAgentRow[]>({
    queryKey: ['acp-agents'],
    queryFn: () => api.getAcpAgents(),
    refetchInterval: 5000,
  });

  // Create agent mutation
  const createAgentMutation = useMutation({
    mutationFn: (data: { name: string; description?: string; capabilities?: string[]; status?: 'active' | 'inactive' }) =>
      api.createAcpAgent({
        name: data.name,
        description: data.description,
        capabilities: data.capabilities,
      }),
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
    }) =>
      api.updateAcpAgent(id, {
        name: data.name,
        description: data.description,
        capabilities: data.capabilities,
        status: data.status,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['acp-agents'] });
      setIsEditModalOpen(false);
      setSelectedAgent(null);
    },
  });

  // Delete agent mutation
  const deleteAgentMutation = useMutation({
    mutationFn: api.deleteAcpAgent,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['acp-agents'] });
      queryClient.invalidateQueries({ queryKey: ['acp-stats'] });
      setSelectedAgent(null);
    },
  });

  // Toggle agent status
  const toggleAgentStatus = (agent: AcpAgentRow) => {
    updateAgentMutation.mutate({
      id: agent.id,
      data: { status: agent.status === 'active' ? 'inactive' : 'active' },
    });
  };

  return (
    <div className="max-w-6xl mx-auto px-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Network className="w-6 h-6 text-[var(--color-accent)]" />
            ACP 管理
          </h1>
          <p className="text-[var(--color-text-secondary)] mt-1">管理 AI 代理和协调协议</p>
        </div>
        <Button onClick={() => setIsCreateModalOpen(true)}>
          <Plus className="w-4 h-4 mr-2" />
          创建代理
        </Button>
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
      <Card>
        <div className="p-4 border-b border-[var(--color-border)] flex items-center justify-between">
          <h2 className="font-semibold flex items-center gap-2">
            <Users className="w-5 h-5" />
            代理列表
          </h2>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => queryClient.invalidateQueries({ queryKey: ['acp-agents'] })}
            title="刷新"
          >
            <RefreshCw className="w-4 h-4" />
          </Button>
        </div>

        {agentsLoading ? (
          <div className="p-8 flex justify-center">
            <Loader2 className="w-8 h-8 animate-spin text-[var(--color-accent)]" />
          </div>
        ) : agents && agents.length > 0 ? (
          <div className="divide-y divide-[var(--color-border)]">
            {agents.map((agent) => (
              <div
                key={agent.id}
                className={cn(
                  'p-4 hover:bg-[var(--color-bg-hover)] transition-colors cursor-pointer',
                  selectedAgent?.id === agent.id && 'bg-[var(--color-bg-tertiary)]'
                )}
                onClick={() => setSelectedAgent(agent)}
              >
                <div className="flex items-start justify-between">
                  <div className="flex items-start gap-3">
                    <div
                      className={cn(
                        'w-10 h-10 rounded-lg flex items-center justify-center',
                        agent.status === 'active'
                          ? 'bg-[var(--color-success-light)]'
                          : agent.status === 'error'
                            ? 'bg-[var(--color-error-light)]'
                            : 'bg-[var(--color-bg-tertiary)]'
                      )}
                    >
                      <Bot
                        className={cn(
                          'w-5 h-5',
                          agent.status === 'active'
                            ? 'text-[var(--color-success)]'
                            : agent.status === 'error'
                              ? 'text-[var(--color-error)]'
                              : 'text-[var(--color-text-tertiary)]'
                        )}
                      />
                    </div>
                    <div>
                      <h3 className="font-medium">{agent.name}</h3>
                      <p className="text-sm text-[var(--color-text-secondary)]">{agent.description}</p>
                      <div className="flex items-center gap-2 mt-2">
                        <Badge
                          variant={
                            agent.status === 'active'
                              ? 'success'
                              : agent.status === 'error'
                                ? 'error'
                                : 'secondary'
                          }
                          size="sm"
                        >
                          {agent.status === 'active'
                            ? '活跃'
                            : agent.status === 'error'
                              ? '错误'
                              : '停用'}
                        </Badge>
                        {agent.capabilities?.map((cap) => (
                          <Badge key={cap} variant="anime" size="sm">
                            {cap}
                          </Badge>
                        ))}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={(e) => {
                        e.stopPropagation();
                        toggleAgentStatus(agent);
                      }}
                      className={cn(
                        agent.status === 'active'
                          ? 'hover:bg-[var(--color-error-light)] hover:text-[var(--color-error)]'
                          : 'hover:bg-[var(--color-success-light)] hover:text-[var(--color-success)]'
                      )}
                      title={agent.status === 'active' ? '停用' : '启用'}
                    >
                      {agent.status === 'active' ? (
                        <XCircle className="w-4 h-4" />
                      ) : (
                        <CheckCircle2 className="w-4 h-4" />
                      )}
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={(e) => {
                        e.stopPropagation();
                        setSelectedAgent(agent);
                        setIsEditModalOpen(true);
                      }}
                      title="编辑"
                    >
                      <Edit3 className="w-4 h-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={(e) => {
                        e.stopPropagation();
                        if (confirm('确定要删除此代理吗？')) {
                          deleteAgentMutation.mutate(agent.id);
                        }
                      }}
                      className="hover:bg-[var(--color-error-light)] hover:text-[var(--color-error)]"
                      title="删除"
                    >
                      <Trash2 className="w-4 h-4" />
                    </Button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="p-8 text-center text-[var(--color-text-secondary)]">
            <Bot className="w-12 h-12 mx-auto mb-3 opacity-50" />
            <p>暂无代理</p>
            <button
              onClick={() => setIsCreateModalOpen(true)}
              className="mt-4 text-[var(--color-accent)] hover:underline"
            >
              创建第一个代理
            </button>
          </div>
        )}
      </Card>

      {/* Create Modal */}
      <AgentModal
        open={isCreateModalOpen}
        title="创建代理"
        onClose={() => setIsCreateModalOpen(false)}
        onSubmit={(data) => createAgentMutation.mutate(data)}
        isLoading={createAgentMutation.isPending}
      />

      {/* Edit Modal */}
      <AgentModal
        open={isEditModalOpen && !!selectedAgent}
        title="编辑代理"
        agent={selectedAgent ?? undefined}
        onClose={() => {
          setIsEditModalOpen(false);
          setSelectedAgent(null);
        }}
        onSubmit={(data) => updateAgentMutation.mutate({ id: selectedAgent!.id, data })}
        isLoading={updateAgentMutation.isPending}
      />
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
    <Card>
      <CardBody className="p-4">
        <div className="flex items-start justify-between">
          <div>
            <p className="text-sm text-[var(--color-text-secondary)]">{title}</p>
            {loading ? (
              <Loader2 className="w-6 h-6 animate-spin mt-2" />
            ) : (
              <div className="flex items-baseline gap-2">
                <p className="text-2xl font-bold mt-1">{value}</p>
                {trend && <span className="text-xs text-[var(--color-success)]">{trend}</span>}
              </div>
            )}
          </div>
          <div className="p-2 bg-[var(--color-accent-light)] rounded-lg">
            <Icon className="w-5 h-5 text-[var(--color-accent)]" />
          </div>
        </div>
      </CardBody>
    </Card>
  );
}

// Agent Modal Component
interface AgentModalProps {
  open: boolean;
  title: string;
  agent?: AcpAgentRow;
  onClose: () => void;
  onSubmit: (data: {
    name: string;
    description?: string;
    capabilities?: string[];
    status?: 'active' | 'inactive';
  }) => void;
  isLoading: boolean;
}

function AgentModal({ open, title, agent, onClose, onSubmit, isLoading }: AgentModalProps) {
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
    <Dialog
      open={open}
      onOpenChange={(o) => { if (!o) onClose(); }}
      title={title}
      size="md"
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="block text-sm font-medium mb-1">名称</label>
          <Input
            type="text"
            value={formData.name}
            onChange={(e) => setFormData({ ...formData, name: e.target.value })}
            required
          />
        </div>
        <div>
          <label className="block text-sm font-medium mb-1">描述</label>
          <Textarea
            value={formData.description}
            onChange={(e) => setFormData({ ...formData, description: e.target.value })}
            rows={3}
          />
        </div>
        <div>
          <label className="block text-sm font-medium mb-1">能力（逗号分隔）</label>
          <Input
            type="text"
            value={formData.capabilities}
            onChange={(e) => setFormData({ ...formData, capabilities: e.target.value })}
            placeholder="chat, memory, tool"
          />
        </div>
        <div>
          <label className="block text-sm font-medium mb-1">状态</label>
          <Select
            value={formData.status}
            onValueChange={(val) =>
              setFormData({ ...formData, status: val as 'active' | 'inactive' })
            }
            options={[
              { label: '活跃', value: 'active' },
              { label: '停用', value: 'inactive' },
            ]}
          />
        </div>
        <div className="flex justify-end gap-3 pt-4">
          <Button type="button" variant="secondary" onClick={onClose}>
            取消
          </Button>
          <Button type="submit" disabled={isLoading} loading={isLoading}>
            {agent ? '保存' : '创建'}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
