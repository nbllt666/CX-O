import { Button, Card, CardBody } from '@/components/ui-v2';
import { VectorConfig, SaveStatus } from '../types';

export interface VectorCardProps {
  vectorConfig: VectorConfig;
  onVectorConfigChange: (config: VectorConfig) => void;
  onSave: () => void;
  saveStatus: SaveStatus;
  isBackendRunning: boolean;
}

export function VectorCard(props: VectorCardProps) {
  const { vectorConfig, onVectorConfigChange, onSave, saveStatus, isBackendRunning } = props;

  return (
    <div className="space-y-6">
      <Card>
        <CardBody>
          <h3 className="text-lg font-semibold mb-4">向量存储配置</h3>
          <p className="text-sm text-[var(--color-text-secondary)] mb-4">
            向量存储用于语义搜索和记忆检索
          </p>
          <div className="space-y-4">
            <div>
              <label className="text-sm font-medium mb-2 block">向量存储后端</label>
              <select
                value={vectorConfig.backend}
                onChange={(e) =>
                  onVectorConfigChange({ ...vectorConfig, backend: e.target.value })
                }
                className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
              >
                <option value="weaviate">Weaviate (独立服务)</option>
                <option value="weaviate_embedded">Weaviate Embedded (内置)</option>
              </select>
              <p className="text-xs text-[var(--color-text-tertiary)] mt-1">
                仅支持 Weaviate。Chroma、Milvus Lite、Qdrant 已不再支持。
              </p>
            </div>
            <div>
              <label className="text-sm font-medium mb-2 block">向量维度</label>
              <select
                value={vectorConfig.vectorSize}
                onChange={(e) =>
                  onVectorConfigChange({ ...vectorConfig, vectorSize: parseInt(e.target.value) })
                }
                className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
              >
                <option value={384}>384 (小型模型)</option>
                <option value={768}>768 (中型模型)</option>
                <option value={1024}>1024 (大型模型)</option>
                <option value={1536}>1536 (OpenAI)</option>
              </select>
            </div>
            {vectorConfig.backend === 'weaviate' && (
              <>
                <div>
                  <label className="text-sm font-medium mb-2 block">Weaviate 主机</label>
                  <input
                    type="text"
                    value={vectorConfig.weaviateHost}
                    onChange={(e) =>
                      onVectorConfigChange({ ...vectorConfig, weaviateHost: e.target.value })
                    }
                    className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                    placeholder="localhost"
                  />
                </div>
                <div>
                  <label className="text-sm font-medium mb-2 block">Weaviate 端口</label>
                  <input
                    type="number"
                    value={vectorConfig.weaviatePort}
                    onChange={(e) =>
                      onVectorConfigChange({
                        ...vectorConfig,
                        weaviatePort: parseInt(e.target.value),
                      })
                    }
                    className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                    placeholder="8090"
                  />
                </div>
              </>
            )}
            {vectorConfig.backend === 'weaviate_embedded' && (
              <div className="p-3 bg-[var(--color-bg-tertiary)] rounded-[var(--radius-md)] text-sm text-[var(--color-text-secondary)]">
                Weaviate Embedded 模式将使用内置向量引擎，无需配置主机和端口。
              </div>
            )}
          </div>
          <div className="flex justify-end mt-6">
            <Button
              onClick={onSave}
              loading={saveStatus === 'saving'}
              disabled={!isBackendRunning}
            >
              {saveStatus === 'saved' ? '已保存' : '保存配置'}
            </Button>
          </div>
        </CardBody>
      </Card>
      <Card>
        <CardBody>
          <h3 className="text-lg font-semibold mb-4">嵌入模型配置</h3>
          <p className="text-sm text-[var(--color-text-secondary)] mb-4">
            选择用于生成向量的嵌入模型提供方
          </p>
          <div className="space-y-4">
            <div>
              <label className="text-sm font-medium mb-2 block">嵌入提供方</label>
              <select
                value={vectorConfig.embeddingProvider}
                onChange={(e) =>
                  onVectorConfigChange({ ...vectorConfig, embeddingProvider: e.target.value })
                }
                className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
              >
                <option value="ollama">Ollama</option>
                <option value="sentence-transformers">Sentence Transformers</option>
                <option value="vllm">vLLM (OpenAI 兼容)</option>
              </select>
              <p className="text-xs text-[var(--color-text-tertiary)] mt-1">
                vLLM 通过 /v1/embeddings 接口提供嵌入；Ollama 与 Sentence Transformers 走默认 LLM 客户端。
              </p>
            </div>
            <div>
              <label className="text-sm font-medium mb-2 block">嵌入模型名称</label>
              <input
                type="text"
                value={vectorConfig.embeddingModel}
                onChange={(e) =>
                  onVectorConfigChange({ ...vectorConfig, embeddingModel: e.target.value })
                }
                className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                placeholder="nomic-embed-text / bge-m3 / ..."
              />
            </div>
            {vectorConfig.embeddingProvider === 'vllm' && (
              <>
                <div>
                  <label className="text-sm font-medium mb-2 block">嵌入维度</label>
                  <input
                    type="number"
                    value={vectorConfig.vectorSize}
                    onChange={(e) =>
                      onVectorConfigChange({
                        ...vectorConfig,
                        vectorSize: parseInt(e.target.value) || 768,
                      })
                    }
                    className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                    placeholder="1024"
                  />
                  <p className="text-xs text-[var(--color-text-tertiary)] mt-1">
                    与上方「向量维度」共用，需与 vLLM 嵌入模型实际输出维度一致。
                  </p>
                </div>
                <div>
                  <label className="text-sm font-medium mb-2 block">vLLM API Base</label>
                  <input
                    type="text"
                    value={vectorConfig.embeddingApiBase}
                    onChange={(e) =>
                      onVectorConfigChange({ ...vectorConfig, embeddingApiBase: e.target.value })
                    }
                    className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                    placeholder="http://localhost:8000"
                  />
                </div>
                <div>
                  <label className="text-sm font-medium mb-2 block">vLLM API Key (可选)</label>
                  <input
                    type="password"
                    value={vectorConfig.embeddingApiKey}
                    onChange={(e) =>
                      onVectorConfigChange({ ...vectorConfig, embeddingApiKey: e.target.value })
                    }
                    className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                    placeholder="sk-..."
                  />
                </div>
              </>
            )}
          </div>
          <div className="flex justify-end mt-6">
            <Button
              onClick={onSave}
              loading={saveStatus === 'saving'}
              disabled={!isBackendRunning}
            >
              {saveStatus === 'saved' ? '已保存' : '保存配置'}
            </Button>
          </div>
        </CardBody>
      </Card>
    </div>
  );
}
