import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Wrench,
  Plus,
  Trash2,
  Edit3,
  CheckCircle2,
  Loader2,
  Settings,
  Terminal,
  Globe,
  Database,
  FileText,
  Code,
  ToggleLeft,
  ToggleRight,
  Play,
  AlertCircle,
  ChevronDown,
  ChevronUp,
  Copy,
  Check,
} from 'lucide-react';
import { api } from '../api/client';
import { cn } from '../lib/utils';

interface Tool {
  id: string;
  name: string;
  description: string;
  type: 'builtin' | 'mcp' | 'custom';
  status: 'active' | 'inactive' | 'error';
  config: Record<string, unknown>;
  icon?: string;
  created_at: string;
  last_used?: string;
  use_count: number;
  parameters?: Record<string, unknown>;
  examples?: string[];
  tags?: string[];
}

interface ToolStats {
  total_tools: number;
  active_tools: number;
  mcp_tools: number;
  native_tools: number;
  total_calls: number;
}

const toolIcons: Record<string, React.ElementType> = {
  terminal: Terminal,
  globe: Globe,
  database: Database,
  file: FileText,
  code: Code,
  wrench: Wrench,
  settings: Settings,
};

// 预设的工具模板
const toolTemplates = {
  custom: {
    name: '',
    description: '',
    parameters: {
      type: 'object',
      properties: {},
      required: [],
    },
    examples: [],
  },
  mcp: {
    name: '',
    description: 'MCP 服务器工具',
    parameters: {
      type: 'object',
      properties: {
        server_name: {
          type: 'string',
          description: 'MCP 服务器名称',
        },
      },
      required: ['server_name'],
    },
    config: {
      server_name: '',
      tool_name: '',
    },
  },
  calculator: {
    name: 'calculator',
    description: '数学计算工具，支持基本运算、三角函数、对数等',
    parameters: {
      type: 'object',
      properties: {
        expression: {
          type: 'string',
          description: '数学表达式，如 "1 + 2" 或 "sin(30)"',
        },
      },
      required: ['expression'],
    },
    examples: ['1 + 2', 'sin(30)', 'log(100)'],
  },
  datetime: {
    name: 'datetime',
    description: '获取当前日期和时间',
    parameters: {
      type: 'object',
      properties: {
        format: {
          type: 'string',
          description: '日期格式，如 "YYYY-MM-DD HH:mm:ss"',
        },
      },
      required: [],
    },
    examples: ['', 'YYYY-MM-DD'],
  },
};

export function ToolsPage() {
  const queryClient = useQueryClient();
  const [selectedTool, setSelectedTool] = useState<Tool | null>(null);
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [isTestModalOpen, setIsTestModalOpen] = useState(false);
  const [filter, setFilter] = useState<'all' | 'builtin' | 'mcp' | 'custom'>('all');

  // Fetch tools stats
  const { data: stats, isLoading: statsLoading } = useQuery<ToolStats>({
    queryKey: ['tools-stats'],
    queryFn: async () => {
      const response = await api.getToolsStats();
      return response;
    },
    refetchInterval: 10000,
  });

  // Fetch tools list
  const { data: toolsData, isLoading: toolsLoading } = useQuery({
    queryKey: ['tools', filter],
    queryFn: async () => {
      const response = await api.getTools(filter === 'all' ? undefined : filter);
      // 将工具对象转换为数组
      const toolsObj = response.tools || {};
      return Object.values(toolsObj) as Tool[];
    },
  });

  // Create tool mutation
  const createToolMutation = useMutation({
    mutationFn: api.createTool,
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
            stats ? `${Math.round((stats.active_tools / stats.total_tools) * 100)}%` : undefined
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
        {(['all', 'builtin', 'mcp', 'custom'] as const).map((type) => (
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
          filteredTools.map((tool) => {
            const IconComponent = toolIcons[tool.icon || ''] || Wrench;
            return (
              <div
                key={tool.id}
                className="bg-card rounded-lg border border-border p-4 hover:shadow-md transition-shadow"
              >
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
                      <p className="text-sm text-muted-foreground">{tool.type}</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => toggleToolStatus(tool)}
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
                      onClick={() => {
                        setSelectedTool(tool);
                        setIsTestModalOpen(true);
                      }}
                      className="flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 text-sm bg-muted rounded-lg hover:bg-accent transition-colors"
                    >
                      <Play className="w-4 h-4" />
                      测试
                    </button>
                    <button
                      onClick={() => {
                        setSelectedTool(tool);
                        setIsEditModalOpen(true);
                      }}
                      className="flex items-center justify-center gap-1.5 px-3 py-1.5 text-sm bg-muted rounded-lg hover:bg-accent transition-colors"
                    >
                      <Edit3 className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => {
                        if (confirm('确定要删除此工具吗？')) {
                          deleteToolMutation.mutate(tool.id);
                        }
                      }}
                      className="flex items-center justify-center gap-1.5 px-3 py-1.5 text-sm bg-muted rounded-lg hover:bg-red-500/10 hover:text-red-500 transition-colors"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              </div>
            );
          })
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

// Stat Card Component
interface StatCardProps {
  title: string;
  value: number;
  icon: React.ElementType;
  loading?: boolean;
  trend?: string;
}

function StatCard({ title, value, icon: Icon, loading, trend }: StatCardProps) {
  return (
    <div className="bg-card rounded-lg border border-border p-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm text-muted-foreground">{title}</p>
          {loading ? (
            <div className="h-8 w-16 bg-muted rounded animate-pulse mt-1" />
          ) : (
            <div className="flex items-baseline gap-2">
              <p className="text-2xl font-bold">{value}</p>
              {trend && <span className="text-xs text-green-500">{trend}</span>}
            </div>
          )}
        </div>
        <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center">
          <Icon className="w-5 h-5 text-primary" />
        </div>
      </div>
    </div>
  );
}

// Tool Modal Component
interface ToolModalProps {
  title: string;
  tool?: Tool;
  onClose: () => void;
  onSubmit: (data: {
    name: string;
    description?: string;
    type: 'mcp' | 'native' | 'custom';
    icon?: string;
    config?: Record<string, unknown>;
    parameters?: Record<string, unknown>;
    examples?: string[];
    tags?: string[];
  }) => void;
  isLoading: boolean;
}

function ToolModal({ title, tool, onClose, onSubmit, isLoading }: ToolModalProps) {
  const [selectedTemplate, setSelectedTemplate] = useState<string>('custom');
  const [activeTab, setActiveTab] = useState<'basic' | 'params' | 'advanced'>('basic');
  const [copied, setCopied] = useState(false);

  const [formData, setFormData] = useState({
    name: tool?.name || '',
    description: tool?.description || '',
    type: (tool?.type as 'mcp' | 'native' | 'custom') || 'custom',
    icon: tool?.icon || 'wrench',
    parameters: JSON.stringify(
      tool?.parameters || { type: 'object', properties: {}, required: [] },
      null,
      2
    ),
    examples: tool?.examples?.join('\n') || '',
    tags: tool?.tags?.join(', ') || '',
    config: JSON.stringify(tool?.config || {}, null, 2),
  });

  const handleTemplateSelect = (templateKey: string) => {
    setSelectedTemplate(templateKey);
    const template = toolTemplates[templateKey as keyof typeof toolTemplates];
    if (template) {
      const templateExamples = 'examples' in template ? template.examples : [];
      setFormData((prev) => ({
        ...prev,
        name: template.name || prev.name,
        description: template.description || prev.description,
        parameters: JSON.stringify(template.parameters, null, 2),
        examples: templateExamples?.join('\n') || '',
      }));
    }
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const parameters = JSON.parse(formData.parameters);
      const config = JSON.parse(formData.config);
      const examples = formData.examples.split('\n').filter((e) => e.trim());
      const tags = formData.tags
        .split(',')
        .map((t) => t.trim())
        .filter((t) => t);

      onSubmit({
        name: formData.name,
        description: formData.description,
        type: formData.type,
        icon: formData.icon,
        parameters,
        examples,
        tags,
        config,
      });
    } catch {
      alert('JSON 格式错误，请检查参数或配置');
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-card rounded-lg border border-border w-full max-w-2xl p-6 max-h-[90vh] overflow-auto">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-semibold">{title}</h2>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
            ✕
          </button>
        </div>

        {/* Template Selector */}
        {!tool && (
          <div className="mb-6">
            <label className="block text-sm font-medium mb-2">选择模板</label>
            <div className="grid grid-cols-4 gap-2">
              {Object.keys(toolTemplates).map((key) => (
                <button
                  key={key}
                  onClick={() => handleTemplateSelect(key)}
                  className={cn(
                    'px-3 py-2 text-sm rounded-lg border transition-colors',
                    selectedTemplate === key
                      ? 'border-primary bg-primary/10 text-primary'
                      : 'border-border hover:border-primary/50'
                  )}
                >
                  {key === 'custom'
                    ? '自定义'
                    : key === 'mcp'
                      ? 'MCP'
                      : key === 'calculator'
                        ? '计算器'
                        : '时间'}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Tabs */}
        <div className="flex gap-1 mb-4 bg-muted rounded-lg p-1">
          {(['basic', 'params', 'advanced'] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={cn(
                'flex-1 px-3 py-1.5 text-sm font-medium rounded-md transition-colors',
                activeTab === tab
                  ? 'bg-card text-foreground shadow-sm'
                  : 'text-muted-foreground hover:text-foreground'
              )}
            >
              {tab === 'basic' ? '基本信息' : tab === 'params' ? '参数定义' : '高级配置'}
            </button>
          ))}
        </div>

        <form onSubmit={handleSubmit}>
          {/* Basic Tab */}
          {activeTab === 'basic' && (
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium mb-1">
                  名称 <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  className="w-full px-3 py-2 bg-muted rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/50"
                  placeholder="例如：calculator"
                  required
                />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">描述</label>
                <textarea
                  value={formData.description}
                  onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                  className="w-full px-3 py-2 bg-muted rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/50"
                  rows={2}
                  placeholder="描述这个工具的用途..."
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium mb-1">类型</label>
                  <select
                    value={formData.type}
                    onChange={(e) =>
                      setFormData({
                        ...formData,
                        type: e.target.value as 'mcp' | 'native' | 'custom',
                      })
                    }
                    className="w-full px-3 py-2 bg-muted rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/50"
                  >
                    <option value="custom">自定义</option>
                    <option value="mcp">MCP</option>
                    <option value="native">原生</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium mb-1">图标</label>
                  <select
                    value={formData.icon}
                    onChange={(e) => setFormData({ ...formData, icon: e.target.value })}
                    className="w-full px-3 py-2 bg-muted rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/50"
                  >
                    <option value="wrench">工具</option>
                    <option value="terminal">终端</option>
                    <option value="globe">网络</option>
                    <option value="database">数据库</option>
                    <option value="file">文件</option>
                    <option value="code">代码</option>
                    <option value="settings">设置</option>
                  </select>
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">标签（用逗号分隔）</label>
                <input
                  type="text"
                  value={formData.tags}
                  onChange={(e) => setFormData({ ...formData, tags: e.target.value })}
                  className="w-full px-3 py-2 bg-muted rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/50"
                  placeholder="math, calculation, utility"
                />
              </div>
            </div>
          )}

          {/* Params Tab */}
          {activeTab === 'params' && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <label className="block text-sm font-medium">
                  参数定义 (JSON Schema) <span className="text-red-500">*</span>
                </label>
                <button
                  type="button"
                  onClick={() => copyToClipboard(formData.parameters)}
                  className="text-xs flex items-center gap-1 text-muted-foreground hover:text-foreground"
                >
                  {copied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
                  {copied ? '已复制' : '复制'}
                </button>
              </div>
              <textarea
                value={formData.parameters}
                onChange={(e) => setFormData({ ...formData, parameters: e.target.value })}
                className="w-full px-3 py-2 bg-muted rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/50 font-mono text-sm"
                rows={12}
                placeholder={`{
  "type": "object",
  "properties": {
    "expression": {
      "type": "string",
      "description": "数学表达式"
    }
  },
  "required": ["expression"]
}`}
              />
              <div>
                <label className="block text-sm font-medium mb-1">示例（每行一个）</label>
                <textarea
                  value={formData.examples}
                  onChange={(e) => setFormData({ ...formData, examples: e.target.value })}
                  className="w-full px-3 py-2 bg-muted rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/50 font-mono text-sm"
                  rows={4}
                  placeholder="1 + 2&#10;sin(30)&#10;log(100)"
                />
              </div>
            </div>
          )}

          {/* Advanced Tab */}
          {activeTab === 'advanced' && (
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium mb-1">配置 (JSON)</label>
                <textarea
                  value={formData.config}
                  onChange={(e) => setFormData({ ...formData, config: e.target.value })}
                  className="w-full px-3 py-2 bg-muted rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/50 font-mono text-sm"
                  rows={12}
                  placeholder='{"key": "value"}'
                />
              </div>
            </div>
          )}

          <div className="flex justify-end gap-3 pt-6 mt-6 border-t border-border">
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
              {tool ? '保存' : '添加'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// Test Tool Modal
interface TestToolModalProps {
  tool: Tool;
  onClose: () => void;
}

function TestToolModal({ tool, onClose }: TestToolModalProps) {
  const [params, setParams] = useState('{}');
  const [result, setResult] = useState<string | null>(null);
  const [isTesting, setIsTesting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showParamsHelp, setShowParamsHelp] = useState(false);

  const handleTest = async () => {
    setIsTesting(true);
    setError(null);
    setResult(null);

    try {
      const parsedParams = JSON.parse(params);
      const response = await api.testTool(tool.id, parsedParams);
      setResult(JSON.stringify(response, null, 2));
    } catch (e) {
      setError(e instanceof Error ? e.message : '测试失败');
    } finally {
      setIsTesting(false);
    }
  };

  // 生成示例参数
  const generateExampleParams = () => {
    if (!tool.parameters || !tool.parameters.properties) return '{}';

    const example: Record<string, unknown> = {};
    const properties = tool.parameters.properties as Record<
      string,
      { type: string; description?: string; default?: unknown }
    >;

    Object.entries(properties).forEach(([key, prop]) => {
      switch (prop.type) {
        case 'string':
          example[key] = prop.default || tool.examples?.[0] || '';
          break;
        case 'number':
        case 'integer':
          example[key] = prop.default || 0;
          break;
        case 'boolean':
          example[key] = prop.default || false;
          break;
        case 'array':
          example[key] = [];
          break;
        case 'object':
          example[key] = {};
          break;
        default:
          example[key] = null;
      }
    });

    return JSON.stringify(example, null, 2);
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-card rounded-lg border border-border w-full max-w-2xl p-6 max-h-[90vh] overflow-auto">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-semibold">测试工具: {tool.name}</h2>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
            ✕
          </button>
        </div>

        <div className="space-y-4">
          {/* Parameters Help */}
          <div className="bg-muted rounded-lg p-3">
            <button
              onClick={() => setShowParamsHelp(!showParamsHelp)}
              className="flex items-center justify-between w-full text-sm font-medium"
            >
              <span>参数说明</span>
              {showParamsHelp ? (
                <ChevronUp className="w-4 h-4" />
              ) : (
                <ChevronDown className="w-4 h-4" />
              )}
            </button>
            {showParamsHelp && (
              <div className="mt-2 text-sm text-muted-foreground">
                {tool.parameters && tool.parameters.properties ? (
                  <ul className="space-y-1">
                    {Object.entries(
                      tool.parameters.properties as Record<
                        string,
                        { type: string; description?: string }
                      >
                    ).map(([key, prop]) => (
                      <li key={key}>
                        <code className="bg-background px-1 rounded">{key}</code>
                        <span className="text-xs ml-2">({prop.type})</span>
                        {prop.description && <span className="ml-2">- {prop.description}</span>}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p>暂无参数说明</p>
                )}
                {tool.examples && tool.examples.length > 0 && (
                  <div className="mt-2">
                    <span className="font-medium">示例值:</span>
                    <ul className="mt-1 space-y-1">
                      {tool.examples.map((ex, i) => (
                        <li key={i} className="font-mono text-xs bg-background px-2 py-1 rounded">
                          {ex}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
          </div>

          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="block text-sm font-medium">参数 (JSON)</label>
              <button
                onClick={() => setParams(generateExampleParams())}
                className="text-xs text-primary hover:underline"
              >
                填入示例
              </button>
            </div>
            <textarea
              value={params}
              onChange={(e) => setParams(e.target.value)}
              className="w-full px-3 py-2 bg-muted rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/50 font-mono text-sm"
              rows={6}
              placeholder='{"key": "value"}'
            />
          </div>

          <button
            onClick={handleTest}
            disabled={isTesting}
            className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-50"
          >
            {isTesting ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Play className="w-4 h-4" />
            )}
            {isTesting ? '测试中...' : '执行测试'}
          </button>

          {error && (
            <div className="p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-red-500 text-sm flex items-center gap-2">
              <AlertCircle className="w-4 h-4" />
              {error}
            </div>
          )}

          {result && (
            <div>
              <label className="block text-sm font-medium mb-1">执行结果</label>
              <pre className="w-full px-3 py-2 bg-muted rounded-lg font-mono text-sm overflow-auto max-h-60">
                {result}
              </pre>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
