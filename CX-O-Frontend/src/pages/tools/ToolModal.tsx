import { useState } from 'react';
import { Copy, Check } from 'lucide-react';
import { Button, Input, Textarea, Select } from '@/components/ui-v2';
import { Modal } from '@/components/business/ui';
import { type Tool, toolTemplates } from './types';

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

export function ToolModal({ title, tool, onClose, onSubmit, isLoading }: ToolModalProps) {
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
    <Modal isOpen onClose={onClose} title={title} size="xl">

        {/* Template Selector */}
        {!tool && (
          <div className="mb-6">
            <label className="block text-sm font-medium mb-2">选择模板</label>
            <div className="grid grid-cols-4 gap-2">
              {Object.keys(toolTemplates).map((key) => (
                <Button
                  key={key}
                  variant={selectedTemplate === key ? 'primary' : 'secondary'}
                  size="sm"
                  onClick={() => handleTemplateSelect(key)}
                >
                  {key === 'custom'
                    ? '自定义'
                    : key === 'mcp'
                      ? 'MCP'
                      : key === 'calculator'
                        ? '计算器'
                        : '时间'}
                </Button>
              ))}
            </div>
          </div>
        )}

        {/* Tabs */}
        <div className="flex gap-1 mb-4 bg-muted rounded-lg p-1">
          {(['basic', 'params', 'advanced'] as const).map((tab) => (
            <Button
              key={tab}
              variant={activeTab === tab ? 'primary' : 'ghost'}
              size="sm"
              onClick={() => setActiveTab(tab)}
              className="flex-1"
            >
              {tab === 'basic' ? '基本信息' : tab === 'params' ? '参数定义' : '高级配置'}
            </Button>
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
                <Input
                  type="text"
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  className="w-full"
                  placeholder="例如：calculator"
                  required
                />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">描述</label>
                <Textarea
                  value={formData.description}
                  onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                  className="w-full"
                  rows={2}
                  placeholder="描述这个工具的用途..."
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium mb-1">类型</label>
                  <Select
                    value={formData.type}
                    onValueChange={(value) =>
                      setFormData({
                        ...formData,
                        type: value as 'mcp' | 'native' | 'custom',
                      })
                    }
                    options={[
                      { label: '自定义', value: 'custom' },
                      { label: 'MCP', value: 'mcp' },
                      { label: '原生', value: 'native' },
                    ]}
                    className="w-full"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium mb-1">图标</label>
                  <Select
                    value={formData.icon}
                    onValueChange={(value) => setFormData({ ...formData, icon: value })}
                    options={[
                      { label: '工具', value: 'wrench' },
                      { label: '终端', value: 'terminal' },
                      { label: '网络', value: 'globe' },
                      { label: '数据库', value: 'database' },
                      { label: '文件', value: 'file' },
                      { label: '代码', value: 'code' },
                      { label: '设置', value: 'settings' },
                    ]}
                    className="w-full"
                  />
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">标签（用逗号分隔）</label>
                <Input
                  type="text"
                  value={formData.tags}
                  onChange={(e) => setFormData({ ...formData, tags: e.target.value })}
                  className="w-full"
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
                <Button
                  variant="ghost"
                  size="sm"
                  type="button"
                  onClick={() => copyToClipboard(formData.parameters)}
                >
                  {copied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
                  {copied ? '已复制' : '复制'}
                </Button>
              </div>
              <Textarea
                value={formData.parameters}
                onChange={(e) => setFormData({ ...formData, parameters: e.target.value })}
                className="w-full font-mono text-sm"
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
                <Textarea
                  value={formData.examples}
                  onChange={(e) => setFormData({ ...formData, examples: e.target.value })}
                  className="w-full font-mono text-sm"
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
                <Textarea
                  value={formData.config}
                  onChange={(e) => setFormData({ ...formData, config: e.target.value })}
                  className="w-full font-mono text-sm"
                  rows={12}
                  placeholder='{"key": "value"}'
                />
              </div>
            </div>
          )}

          <div className="flex justify-end gap-3 pt-6 mt-6 border-t border-border">
            <Button
              variant="ghost"
              type="button"
              onClick={onClose}
            >
              取消
            </Button>
            <Button
              variant="primary"
              type="submit"
              loading={isLoading}
            >
              {tool ? '保存' : '添加'}
            </Button>
          </div>
        </form>
    </Modal>
  );
}
