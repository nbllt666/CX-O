import { Button, Card, CardBody } from '../../../components/ui';
import { ModelsConfig, LlmParams, SaveStatus } from '../types';

export interface LlmCardProps {
  modelsConfig: ModelsConfig;
  onModelsConfigChange: (config: ModelsConfig) => void;
  llmParams: LlmParams;
  onLlmParamsChange: (params: LlmParams) => void;
  onSave: () => void;
  saveStatus: SaveStatus;
  isBackendRunning: boolean;
}

export function LlmCard(props: LlmCardProps) {
  const { modelsConfig, onModelsConfigChange, onSave, saveStatus, isBackendRunning } = props;

  return (
    <div className="space-y-6">
      {/* 默认模型配置 */}
      <Card>
        <CardBody>
          <div className="mb-4">
            <h3 className="text-lg font-semibold">默认模型</h3>
            <p className="text-sm text-[var(--color-text-secondary)]">
              用于日常对话的默认模型配置（始终启用）
            </p>
          </div>
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-sm font-medium mb-2 block">模型提供商</label>
                <select
                  value={modelsConfig.main.provider}
                  onChange={(e) =>
                    onModelsConfigChange({
                      ...modelsConfig,
                      main: { ...modelsConfig.main, provider: e.target.value },
                    })
                  }
                  className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                >
                  <option value="ollama">Ollama (本地)</option>
                  <option value="vllm">vLLM</option>
                  <option value="openai">OpenAI</option>
                </select>
              </div>
              <div>
                <label className="text-sm font-medium mb-2 block">模型名称</label>
                <input
                  type="text"
                  value={modelsConfig.main.model}
                  onChange={(e) =>
                    onModelsConfigChange({
                      ...modelsConfig,
                      main: { ...modelsConfig.main, model: e.target.value },
                    })
                  }
                  className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                  placeholder="llama3.2:3b"
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-sm font-medium mb-2 block">主机地址</label>
                <input
                  type="text"
                  value={modelsConfig.main.host}
                  onChange={(e) =>
                    onModelsConfigChange({
                      ...modelsConfig,
                      main: { ...modelsConfig.main, host: e.target.value },
                    })
                  }
                  className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                  placeholder="http://localhost:11434"
                />
              </div>
              <div>
                <label className="text-sm font-medium mb-2 block">API Key</label>
                <input
                  type="password"
                  value={modelsConfig.main.apiKey}
                  onChange={(e) =>
                    onModelsConfigChange({
                      ...modelsConfig,
                      main: { ...modelsConfig.main, apiKey: e.target.value },
                    })
                  }
                  className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                  placeholder="可选，用于 OpenAI 等需要认证的提供商"
                />
              </div>
            </div>
          </div>
        </CardBody>
      </Card>

      {/* 记忆管理模型配置 */}
      <Card>
        <CardBody>
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-lg font-semibold">记忆管理模型</h3>
              <p className="text-sm text-[var(--color-text-secondary)]">
                用于记忆归档、记忆合并等后台任务（未启用时使用默认模型）
              </p>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-sm text-[var(--color-text-secondary)]">启用</span>
              <button
                onClick={() =>
                  onModelsConfigChange({
                    ...modelsConfig,
                    memory: { ...modelsConfig.memory, enabled: !modelsConfig.memory.enabled },
                  })
                }
                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                  modelsConfig.memory.enabled
                    ? 'bg-[var(--color-accent)]'
                    : 'bg-[var(--color-border)]'
                }`}
              >
                <span
                  className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                    modelsConfig.memory.enabled ? 'translate-x-6' : 'translate-x-1'
                  }`}
                />
              </button>
            </div>
          </div>
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-sm font-medium mb-2 block">模型提供商</label>
                <select
                  value={modelsConfig.memory.provider}
                  onChange={(e) =>
                    onModelsConfigChange({
                      ...modelsConfig,
                      memory: { ...modelsConfig.memory, provider: e.target.value },
                    })
                  }
                  className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                >
                  <option value="ollama">Ollama (本地)</option>
                  <option value="vllm">vLLM</option>
                  <option value="openai">OpenAI</option>
                </select>
              </div>
              <div>
                <label className="text-sm font-medium mb-2 block">模型名称</label>
                <input
                  type="text"
                  value={modelsConfig.memory.model}
                  onChange={(e) =>
                    onModelsConfigChange({
                      ...modelsConfig,
                      memory: { ...modelsConfig.memory, model: e.target.value },
                    })
                  }
                  className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                  placeholder="llama3.2:3b"
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-sm font-medium mb-2 block">主机地址</label>
                <input
                  type="text"
                  value={modelsConfig.memory.host}
                  onChange={(e) =>
                    onModelsConfigChange({
                      ...modelsConfig,
                      memory: { ...modelsConfig.memory, host: e.target.value },
                    })
                  }
                  className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                  placeholder="http://localhost:11434"
                />
              </div>
              <div>
                <label className="text-sm font-medium mb-2 block">API Key</label>
                <input
                  type="password"
                  value={modelsConfig.memory.apiKey}
                  onChange={(e) =>
                    onModelsConfigChange({
                      ...modelsConfig,
                      memory: { ...modelsConfig.memory, apiKey: e.target.value },
                    })
                  }
                  className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                  placeholder="可选，用于 OpenAI 等需要认证的提供商"
                />
              </div>
            </div>
          </div>
        </CardBody>
      </Card>

      {/* 摘要模型配置 */}
      <Card>
        <CardBody>
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-lg font-semibold">摘要模型</h3>
              <p className="text-sm text-[var(--color-text-secondary)]">
                用于对话摘要生成（未启用时使用默认模型）
              </p>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-sm text-[var(--color-text-secondary)]">启用</span>
              <button
                onClick={() =>
                  onModelsConfigChange({
                    ...modelsConfig,
                    summary: { ...modelsConfig.summary, enabled: !modelsConfig.summary.enabled },
                  })
                }
                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                  modelsConfig.summary.enabled
                    ? 'bg-[var(--color-accent)]'
                    : 'bg-[var(--color-border)]'
                }`}
              >
                <span
                  className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                    modelsConfig.summary.enabled ? 'translate-x-6' : 'translate-x-1'
                  }`}
                />
              </button>
            </div>
          </div>
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-sm font-medium mb-2 block">模型提供商</label>
                <select
                  value={modelsConfig.summary.provider}
                  onChange={(e) =>
                    onModelsConfigChange({
                      ...modelsConfig,
                      summary: { ...modelsConfig.summary, provider: e.target.value },
                    })
                  }
                  className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                >
                  <option value="ollama">Ollama (本地)</option>
                  <option value="vllm">vLLM</option>
                  <option value="openai">OpenAI</option>
                </select>
              </div>
              <div>
                <label className="text-sm font-medium mb-2 block">模型名称</label>
                <input
                  type="text"
                  value={modelsConfig.summary.model}
                  onChange={(e) =>
                    onModelsConfigChange({
                      ...modelsConfig,
                      summary: { ...modelsConfig.summary, model: e.target.value },
                    })
                  }
                  className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                  placeholder="llama3.2:3b"
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-sm font-medium mb-2 block">主机地址</label>
                <input
                  type="text"
                  value={modelsConfig.summary.host}
                  onChange={(e) =>
                    onModelsConfigChange({
                      ...modelsConfig,
                      summary: { ...modelsConfig.summary, host: e.target.value },
                    })
                  }
                  className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                  placeholder="http://localhost:11434"
                />
              </div>
              <div>
                <label className="text-sm font-medium mb-2 block">API Key</label>
                <input
                  type="password"
                  value={modelsConfig.summary.apiKey}
                  onChange={(e) =>
                    onModelsConfigChange({
                      ...modelsConfig,
                      summary: { ...modelsConfig.summary, apiKey: e.target.value },
                    })
                  }
                  className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                  placeholder="可选，用于 OpenAI 等需要认证的提供商"
                />
              </div>
            </div>
          </div>
        </CardBody>
      </Card>

      {/* 保存按钮 */}
      <div className="flex justify-end">
        <Button
          onClick={onSave}
          loading={saveStatus === 'saving'}
          disabled={!isBackendRunning}
        >
          {saveStatus === 'saved' ? '已保存' : '保存配置'}
        </Button>
      </div>
    </div>
  );
}
