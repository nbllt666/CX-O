import { useState } from 'react';
import { Loader2, Play, AlertCircle, ChevronDown, ChevronUp } from 'lucide-react';
import { Button, Textarea } from '@/components/ui-v2';
import { Modal } from '@/components/business/ui';
import { api } from '../../api/client';
import type { Tool } from './types';

interface TestToolModalProps {
  tool: Tool;
  onClose: () => void;
}

export function TestToolModal({ tool, onClose }: TestToolModalProps) {
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
    <Modal isOpen onClose={onClose} title={`测试工具: ${tool.name}`} size="xl">

        <div className="space-y-4">
          {/* Parameters Help */}
          <div className="bg-muted rounded-lg p-3">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setShowParamsHelp(!showParamsHelp)}
              className="flex items-center justify-between w-full text-sm font-medium"
            >
              <span>参数说明</span>
              {showParamsHelp ? (
                <ChevronUp className="w-4 h-4" />
              ) : (
                <ChevronDown className="w-4 h-4" />
              )}
            </Button>
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
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setParams(generateExampleParams())}
              >
                填入示例
              </Button>
            </div>
            <Textarea
              value={params}
              onChange={(e) => setParams(e.target.value)}
              className="w-full font-mono text-sm"
              rows={6}
              placeholder='{"key": "value"}'
            />
          </div>

          <Button
            variant="primary"
            onClick={handleTest}
            loading={isTesting}
            className="w-full"
          >
            {isTesting ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Play className="w-4 h-4" />
            )}
            {isTesting ? '测试中...' : '执行测试'}
          </Button>

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
    </Modal>
  );
}
