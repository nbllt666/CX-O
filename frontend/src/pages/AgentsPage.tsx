import { useState, useEffect } from 'react';
import { api } from '../api/client';
import { formatRelativeTime } from '../lib/utils';
import { PageHeader } from '../components/layout';
import { Button, Card, CardBody, Modal, Input, Textarea, Badge } from '../components/ui';
import { useHotkey } from '../hooks';

interface Agent {
  id: string;
  name: string;
  description: string;
  system_prompt: string;
  model: string;
  temperature: number;
  max_tokens: number;
  use_memory: boolean;
  use_tools: boolean;
  vision_enabled?: boolean;
  memory_scene: string;
  decay_model: string;
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

interface AgentTemplate {
  id: string;
  name: string;
  description: string;
  icon: string;
  system_prompt: string;
  temperature: number;
  memory_scene: string;
}

const AGENT_TEMPLATES: AgentTemplate[] = [
  {
    id: 'general',
    name: '通用助手',
    description: '适合日常对话和一般问题解答',
    icon: '🤖',
    system_prompt: '你是一个有帮助的AI助手。请用中文回答用户的问题，保持友好和专业。',
    temperature: 0.7,
    memory_scene: 'chat',
  },
  {
    id: 'coder',
    name: '编程助手',
    description: '专注于代码编写、调试和技术问题',
    icon: '💻',
    system_prompt:
      '你是一个专业的编程助手。帮助用户编写、调试和优化代码。提供清晰的代码示例和解释，遵循最佳实践。',
    temperature: 0.3,
    memory_scene: 'task',
  },
  {
    id: 'writer',
    name: '写作助手',
    description: '帮助撰写文章、文案和创意内容',
    icon: '✍️',
    system_prompt:
      '你是一个专业的写作助手。帮助用户撰写各类文章、文案、故事等。注重文字的流畅性、逻辑性和创意表达。',
    temperature: 0.8,
    memory_scene: 'chat',
  },
  {
    id: 'analyst',
    name: '数据分析师',
    description: '数据分析和可视化专家',
    icon: '📊',
    system_prompt:
      '你是一个数据分析专家。帮助用户分析数据、生成报告、提供洞察。使用工具进行数据处理和可视化。',
    temperature: 0.4,
    memory_scene: 'task',
  },
  {
    id: 'translator',
    name: '翻译助手',
    description: '多语言翻译和本地化专家',
    icon: '🌐',
    system_prompt:
      '你是一个专业的翻译助手。准确翻译各种语言，保持原文的风格和语境。支持中文、英文、日文等多种语言。',
    temperature: 0.5,
    memory_scene: 'chat',
  },
  {
    id: 'vision',
    name: '视觉助手',
    description: '支持图像理解和多模态交互',
    icon: '👁️',
    system_prompt:
      '你是一个支持视觉理解的AI助手。可以分析图像内容，回答关于图片的问题，并提供视觉相关的建议。',
    temperature: 0.7,
    memory_scene: 'chat',
  },
];

export function AgentsPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showTemplateModal, setShowTemplateModal] = useState(false);
  const [editingAgent, setEditingAgent] = useState<Agent | null>(null);
  const [availableModels, setAvailableModels] = useState<{ name: string }[]>([]);
  const [providers, setProviders] = useState<{ id: string; name: string; provider: string }[]>([]);

  const [formData, setFormData] = useState({
    name: '',
    description: '',
    system_prompt: '你是一个有帮助的AI助手。请用中文回答用户的问题。',
    model: '',
    temperature: 0.7,
    max_tokens: 0,
    memory_scene: 'chat',
    decay_model: 'exponential',
  });

  useHotkey('Escape', () => {
    if (showCreateModal) setShowCreateModal(false);
    if (showTemplateModal) setShowTemplateModal(false);
    if (editingAgent) {
      setEditingAgent(null);
      resetForm();
    }
  });

  useEffect(() => {
    loadAgents();
    loadModels();
  }, []);

  const loadModels = async () => {
    try {
      const data = await api.getAvailableModels();
      if (data.providers) {
        setProviders(data.providers);
      }
      if (data.ollama_models) {
        setAvailableModels(data.ollama_models);
      }
    } catch (error) {
      console.error('加载模型列表失败:', error);
    }
  };

  const loadAgents = async () => {
    try {
      setLoading(true);
      const data = await api.getAgents();
      const agentList = Array.isArray(data) ? data : data.agents || [];
      const filteredAgents = agentList.filter((agent: Agent) => agent.id !== 'memory-agent');
      setAgents(filteredAgents);
    } catch (error) {
      console.error('加载 Agent 失败:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleCreate = async () => {
    try {
      await api.createAgent({
        ...formData,
        model: 'main',
        use_memory: true,
        use_tools: true,
        vision_enabled: true,
      });
      setShowCreateModal(false);
      resetForm();
      loadAgents();
    } catch (error) {
      console.error('创建 Agent 失败:', error);
      alert('创建失败，请检查名称是否重复');
    }
  };

  const handleUpdate = async () => {
    if (!editingAgent) return;
    try {
      await api.updateAgent(editingAgent.id, {
        ...formData,
        model: 'main',
        use_memory: true,
        use_tools: true,
        vision_enabled: true,
      });
      setEditingAgent(null);
      resetForm();
      loadAgents();
    } catch (error) {
      console.error('更新 Agent 失败:', error);
      alert('更新失败');
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm('确定要删除这个 Agent 吗？')) return;
    try {
      await api.deleteAgent(id);
      loadAgents();
    } catch (error) {
      console.error('删除 Agent 失败:', error);
      alert('删除失败');
    }
  };

  const handleClone = async (agent: Agent) => {
    try {
      await api.cloneAgent(agent.id);
      loadAgents();
    } catch (error) {
      console.error('克隆 Agent 失败:', error);
      alert('克隆失败');
    }
  };

  const handleSelectTemplate = (template: AgentTemplate) => {
    setFormData({
      name: template.name,
      description: template.description,
      system_prompt: template.system_prompt,
      model: availableModels.length > 0 ? availableModels[0].name : '',
      temperature: template.temperature,
      max_tokens: 0,
      memory_scene: template.memory_scene,
      decay_model: 'exponential',
    });
    setShowTemplateModal(false);
    setShowCreateModal(true);
  };

  const startEdit = (agent: Agent) => {
    setEditingAgent(agent);
    setFormData({
      name: agent.name,
      description: agent.description,
      system_prompt: agent.system_prompt,
      model: agent.model || '',
      temperature: agent.temperature,
      max_tokens: agent.max_tokens,
      memory_scene: agent.memory_scene,
      decay_model: agent.decay_model || 'exponential',
    });
  };

  const resetForm = () => {
    setFormData({
      name: '',
      description: '',
      system_prompt: '你是一个有帮助的AI助手。请用中文回答用户的问题。',
      model: availableModels.length > 0 ? availableModels[0].name : '',
      temperature: 0.7,
      max_tokens: 0,
      memory_scene: 'chat',
      decay_model: 'exponential',
    });
  };

  const closeModal = () => {
    setShowCreateModal(false);
    setEditingAgent(null);
    resetForm();
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="animate-spin rounded-full h-8 w-8 border-2 border-[var(--color-accent)] border-t-transparent" />
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto">
      <PageHeader
        title="AI 助手管理"
        description="创建和管理不同的 AI 助手，每个助手可以有独立的系统提示词和配置"
        actions={
          <div className="flex gap-2">
            <Button variant="secondary" onClick={() => setShowTemplateModal(true)}>
              <svg className="w-4 h-4 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM4 13a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6zM16 13a1 1 0 011-1h2a1 1 0 011 1v6a1 1 0 01-1 1h-2a1 1 0 01-1-1v-6z"
                />
              </svg>
              从模板创建
            </Button>
            <Button onClick={() => setShowCreateModal(true)}>
              <svg className="w-4 h-4 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M12 4v16m8-8H4"
                />
              </svg>
              新建助手
            </Button>
          </div>
        }
      />

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {agents.map((agent) => (
          <Card
            key={agent.id}
            className={`${agent.is_default ? 'ring-2 ring-[var(--color-accent)]' : ''}`}
          >
            <CardBody>
              <div className="flex items-start justify-between mb-3">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-lg bg-[var(--color-accent-light)] flex items-center justify-center">
                    <svg
                      className="w-5 h-5 text-[var(--color-accent)]"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"
                      />
                    </svg>
                  </div>
                  <div>
                    <h3 className="font-semibold text-[var(--color-text-primary)]">{agent.name}</h3>
                    {agent.is_default && (
                      <Badge variant="primary" size="sm">
                        默认
                      </Badge>
                    )}
                  </div>
                </div>
                <div className="flex gap-1">
                  {!agent.is_default && (
                    <>
                      <button
                        onClick={() => startEdit(agent)}
                        className="p-1.5 hover:bg-[var(--color-bg-hover)] rounded-[var(--radius-sm)] transition-colors"
                        title="编辑"
                      >
                        <svg
                          className="w-4 h-4 text-[var(--color-text-secondary)]"
                          fill="none"
                          viewBox="0 0 24 24"
                          stroke="currentColor"
                        >
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={2}
                            d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"
                          />
                        </svg>
                      </button>
                      <button
                        onClick={() => handleClone(agent)}
                        className="p-1.5 hover:bg-[var(--color-bg-hover)] rounded-[var(--radius-sm)] transition-colors"
                        title="克隆"
                      >
                        <svg
                          className="w-4 h-4 text-[var(--color-text-secondary)]"
                          fill="none"
                          viewBox="0 0 24 24"
                          stroke="currentColor"
                        >
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={2}
                            d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"
                          />
                        </svg>
                      </button>
                      <button
                        onClick={() => handleDelete(agent.id)}
                        className="p-1.5 hover:bg-[var(--color-error-light)] rounded-[var(--radius-sm)] transition-colors"
                        title="删除"
                      >
                        <svg
                          className="w-4 h-4 text-[var(--color-error)]"
                          fill="none"
                          viewBox="0 0 24 24"
                          stroke="currentColor"
                        >
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={2}
                            d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
                          />
                        </svg>
                      </button>
                    </>
                  )}
                  {agent.is_default && (
                    <button
                      onClick={() => startEdit(agent)}
                      className="p-1.5 hover:bg-[var(--color-bg-hover)] rounded-[var(--radius-sm)] transition-colors"
                      title="编辑"
                    >
                      <svg
                        className="w-4 h-4 text-[var(--color-text-secondary)]"
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke="currentColor"
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          strokeWidth={2}
                          d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"
                        />
                      </svg>
                    </button>
                  )}
                </div>
              </div>

              <p className="text-sm text-[var(--color-text-secondary)] mb-4 line-clamp-2">
                {agent.description || '暂无描述'}
              </p>

              <div className="space-y-2 text-xs text-[var(--color-text-tertiary)]">
                <div className="flex items-center gap-2">
                  <svg
                    className="w-3.5 h-3.5"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"
                    />
                  </svg>
                  <span>模型: {agent.model || '默认'}</span>
                </div>
                <div className="flex items-center gap-2">
                  <svg
                    className="w-3.5 h-3.5"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"
                    />
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"
                    />
                  </svg>
                  <span>
                    温度: {agent.temperature} · 场景:{' '}
                    {agent.memory_scene === 'chat'
                      ? '闲聊'
                      : agent.memory_scene === 'task'
                        ? '任务'
                        : '首次交互'}
                  </span>
                </div>
              </div>

              <div className="mt-4 pt-3 border-t border-[var(--color-border)] text-xs text-[var(--color-text-tertiary)]">
                更新于 {formatRelativeTime(agent.updated_at)}
              </div>
            </CardBody>
          </Card>
        ))}
      </div>

      <Modal
        isOpen={showTemplateModal}
        onClose={() => setShowTemplateModal(false)}
        title="选择模板"
      >
        <div className="grid grid-cols-2 gap-3">
          {AGENT_TEMPLATES.map((template) => (
            <button
              key={template.id}
              onClick={() => handleSelectTemplate(template)}
              className="p-4 text-left border border-[var(--color-border)] rounded-[var(--radius-lg)] hover:border-[var(--color-accent)] hover:bg-[var(--color-bg-hover)] transition-all"
            >
              <div className="flex items-center gap-3 mb-2">
                <span className="text-2xl">{template.icon}</span>
                <h3 className="font-medium text-[var(--color-text-primary)]">{template.name}</h3>
              </div>
              <p className="text-sm text-[var(--color-text-secondary)]">{template.description}</p>
            </button>
          ))}
        </div>
      </Modal>

      <Modal
        isOpen={showCreateModal || !!editingAgent}
        onClose={closeModal}
        title={editingAgent ? '编辑助手' : '新建助手'}
      >
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium mb-1.5">名称 *</label>
              <Input
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                placeholder="助手名称"
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1.5">模型</label>
              <select
                value={formData.model}
                onChange={(e) => setFormData({ ...formData, model: e.target.value })}
                className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
              >
                <optgroup label="配置的提供商">
                  {providers.map((p) => (
                    <option key={p.id} value={p.name}>
                      {p.name} ({p.provider})
                    </option>
                  ))}
                </optgroup>
                {availableModels.length > 0 && (
                  <optgroup label="Ollama 可用模型">
                    {availableModels.map((m) => (
                      <option key={m.name} value={m.name}>
                        {m.name}
                      </option>
                    ))}
                  </optgroup>
                )}
              </select>
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium mb-1.5">描述</label>
            <Input
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              placeholder="助手的简短描述"
            />
          </div>

          <div>
            <label className="block text-sm font-medium mb-1.5">系统提示词</label>
            <Textarea
              value={formData.system_prompt}
              onChange={(e) => setFormData({ ...formData, system_prompt: e.target.value })}
              placeholder="定义助手的行为和角色..."
              className="min-h-[100px]"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium mb-1.5">
                温度: {formData.temperature}
              </label>
              <input
                type="range"
                min="0"
                max="2"
                step="0.1"
                value={formData.temperature}
                onChange={(e) =>
                  setFormData({ ...formData, temperature: parseFloat(e.target.value) })
                }
                className="w-full"
              />
              <div className="flex justify-between text-xs text-[var(--color-text-tertiary)]">
                <span>精确</span>
                <span>平衡</span>
                <span>创意</span>
              </div>
            </div>
            <div>
              <label className="block text-sm font-medium mb-1.5">最大 Tokens</label>
              <Input
                type="number"
                value={formData.max_tokens}
                onChange={(e) =>
                  setFormData({ ...formData, max_tokens: parseInt(e.target.value) || 0 })
                }
                min="0"
                placeholder="0 表示使用模型默认"
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium mb-1.5">记忆场景</label>
            <select
              value={formData.memory_scene}
              onChange={(e) => setFormData({ ...formData, memory_scene: e.target.value })}
              className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
            >
              <option value="chat">闲聊 (Chat)</option>
              <option value="task">任务 (Task)</option>
              <option value="first_interaction">首次交互 (First Interaction)</option>
            </select>
          </div>

          <div className="flex justify-end gap-3 pt-4">
            <Button variant="secondary" onClick={closeModal}>
              取消
            </Button>
            <Button
              onClick={editingAgent ? handleUpdate : handleCreate}
              disabled={!formData.name.trim()}
            >
              {editingAgent ? '保存' : '创建'}
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
