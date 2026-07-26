import { Button, Card, CardBody } from '@/components/ui-v2';
import { BackendStatus } from '../types';

export interface ServiceCardProps {
  isBackendRunning: boolean;
  isProcessing: boolean;
  backendStatus: BackendStatus;
  logs: string;
  onRestartBackend: () => void;
  onStopBackend: () => void;
  onStartBackend: () => void;
}

export function ServiceCard(props: ServiceCardProps) {
  const {
    isBackendRunning,
    isProcessing,
    backendStatus,
    logs,
    onRestartBackend,
    onStopBackend,
    onStartBackend,
  } = props;

  return (
    <div className="space-y-6">
      <Card>
        <CardBody>
          <div className="flex items-center justify-between mb-6">
            <div>
              <h3 className="text-lg font-semibold">服务状态</h3>
              <p className="text-sm text-[var(--color-text-secondary)]">
                单体架构服务 - ASR/TTS 已集成
              </p>
            </div>
          </div>

          <div className="p-4 bg-[var(--color-bg-tertiary)] rounded-[var(--radius-lg)] mb-4">
            <div className="flex items-center gap-3 mb-3">
              <div className={`w-3 h-3 rounded-full ${isBackendRunning ? 'bg-green-500' : 'bg-gray-400'}`} />
              <span className="font-medium">
                {isBackendRunning ? '单体服务运行中' : '服务未运行'}
              </span>
            </div>
            <div className="text-sm text-[var(--color-text-secondary)]">
              <p>WebSocket: <code className="px-1 py-0.5 bg-[var(--color-bg-primary)] rounded">ws://127.0.0.1:8000/ws</code></p>
              <p>HTTP API: <code className="px-1 py-0.5 bg-[var(--color-bg-primary)] rounded">http://127.0.0.1:8000</code></p>
            </div>
          </div>

          <div className="p-3 bg-blue-500/10 border border-blue-500/30 rounded-[var(--radius-md)] text-sm text-blue-600 dark:text-blue-400">
            <p className="font-medium mb-1">架构变更说明</p>
            <p>系统已从微服务架构重构为单体架构。ASR（语音识别）和 TTS（语音合成）功能已直接集成到主服务中，无需单独配置微服务端点。</p>
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardBody>
          <div className="flex items-center justify-between mb-6">
            <div>
              <h3 className="text-lg font-semibold">服务管理</h3>
              <p className="text-sm text-[var(--color-text-secondary)]">
                启动/停止单体服务
              </p>
            </div>
            <div className="flex items-center gap-2">
              {isBackendRunning ? (
                <>
                  <Button
                    variant="secondary"
                    onClick={onRestartBackend}
                    loading={isProcessing}
                  >
                    重启
                  </Button>
                  <Button
                    variant="danger"
                    onClick={onStopBackend}
                    loading={isProcessing}
                  >
                    停止
                  </Button>
                </>
              ) : (
                <Button
                  onClick={onStartBackend}
                  loading={isProcessing}
                >
                  启动服务
                </Button>
              )}
            </div>
          </div>

          <div className="grid grid-cols-3 gap-4 p-4 bg-[var(--color-bg-tertiary)] rounded-[var(--radius-lg)]">
            <div>
              <span className="text-xs text-[var(--color-text-tertiary)]">状态</span>
              <p className="font-medium flex items-center gap-2">
                <span
                  className={`w-2 h-2 rounded-full ${isBackendRunning ? 'bg-green-500' : 'bg-red-500'}`}
                />
                {isBackendRunning ? '运行中' : '已停止'}
              </p>
            </div>
            <div>
              <span className="text-xs text-[var(--color-text-tertiary)]">端口</span>
              <p className="font-medium">8000</p>
            </div>
            <div>
              <span className="text-xs text-[var(--color-text-tertiary)]">进程 ID</span>
              <p className="font-medium">{backendStatus.pid || '-'}</p>
            </div>
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardBody>
          <h4 className="font-semibold mb-4">服务日志</h4>
          <div className="bg-[var(--color-bg-tertiary)] rounded-[var(--radius-lg)] p-4 font-mono text-sm text-[var(--color-success)] h-64 overflow-auto whitespace-pre-wrap">
            {logs}
          </div>
        </CardBody>
      </Card>
    </div>
  );
}
