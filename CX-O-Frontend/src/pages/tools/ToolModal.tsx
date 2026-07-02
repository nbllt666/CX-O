import { useState } from 'react';
import { Loader2, Copy, Check } from 'lucide-react';
import { cn } from '../../lib/utils';
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
