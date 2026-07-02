import { useState } from 'react';
import { Loader2, Play, AlertCircle, ChevronDown, ChevronUp } from 'lucide-react';
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
