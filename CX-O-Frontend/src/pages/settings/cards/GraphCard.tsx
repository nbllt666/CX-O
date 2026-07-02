import { Button, Card, CardBody } from '../../../components/ui';
import { GraphHealth, GraphStats, SaveStatus } from '../types';

export interface GraphCardProps {
  graphHealth: GraphHealth | null;
  graphStats: GraphStats | null;
  onSave: () => void;
  saveStatus: SaveStatus;
  isBackendRunning: boolean;
  onRefreshStats: () => void;
  onHealthCheck: () => void;
}

export function GraphCard(props: GraphCardProps) {
  const {
    graphHealth,
    graphStats,
    onSave,
    saveStatus,
    isBackendRunning,
    onRefreshStats,
    onHealthCheck,
  } = props;

  return (
    <div className="space-y-6">
      <Card>
        <CardBody>
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold">图数据库状态</h3>
            <div className="flex items-center gap-2">
              <span
                className={`w-3 h-3 rounded-full ${
                  graphHealth?.connected
                    ? 'bg-green-500'
                    : graphHealth?.graph_enabled
                    ? 'bg-red-500'
                    : 'bg-gray-400'
                }`}
              />
              <span className="text-sm">
                {graphHealth?.connected
                  ? '已连接'
                  : graphHealth?.graph_enabled
                  ? '连接失败'
                  : '未启用'}
              </span>
            </div>
          </div>
          {graphHealth?.message && (
            <p className="text-sm text-[var(--color-text-secondary)]">{graphHealth.message}</p>
          )}
          {graphStats?.connected && graphStats.libraries && (
            <div className="grid grid-cols-4 gap-4 mt-4">
              {Object.entries(graphStats.libraries).map(([name, stats]) => (
                <div
                  key={name}
                  className="p-3 bg-[var(--color-bg-tertiary)] rounded-[var(--radius-lg)]"
                >
                  <div className="text-xs text-[var(--color-text-tertiary)] uppercase">{name}</div>
                  <div className="text-lg font-semibold">{stats.entity_count}</div>
                  <div className="text-xs text-[var(--color-text-secondary)]">
                    实体 / {stats.relation_count} 关系
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardBody>
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-lg font-semibold">图数据库配置</h3>
              <p className="text-sm text-[var(--color-text-secondary)]">
                SQLite + Weaviate 语义图数据库，支持语义检索和图遍历
              </p>
            </div>
          </div>

          <div className="space-y-4">
            <div className="p-4 bg-[var(--color-bg-tertiary)] rounded-[var(--radius-lg)]">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <span className="text-sm font-medium">数据库路径</span>
                  <p className="text-xs text-[var(--color-text-tertiary)] mt-1">
                    data/graph.db
                  </p>
                </div>
                <div>
                  <span className="text-sm font-medium">状态</span>
                  <p className="text-xs text-[var(--color-text-tertiary)] mt-1">
                    {graphHealth?.connected ? '已连接' : '未连接'}
                  </p>
                </div>
              </div>
            </div>

            <div className="p-4 bg-[var(--color-bg-tertiary)] rounded-[var(--radius-lg)]">
              <h4 className="text-sm font-medium mb-3">图数据库功能</h4>
              <div className="grid grid-cols-3 gap-4">
                <div className="text-center">
                  <div className="text-lg font-semibold">
                    {Object.values(graphStats?.libraries || {}).reduce((sum, lib) => sum + (lib.entity_count || 0), 0)}
                  </div>
                  <div className="text-xs text-[var(--color-text-tertiary)]">节点</div>
                </div>
                <div className="text-center">
                  <div className="text-lg font-semibold">
                    {Object.values(graphStats?.libraries || {}).reduce((sum, lib) => sum + (lib.relation_count || 0), 0)}
                  </div>
                  <div className="text-xs text-[var(--color-text-tertiary)]">边</div>
                </div>
                <div className="text-center">
                  <div className="text-lg font-semibold">
                    {graphStats?.graph_enabled ? '启用' : '禁用'}
                  </div>
                  <div className="text-xs text-[var(--color-text-tertiary)]">图存储</div>
                </div>
              </div>
            </div>

            <div className="flex gap-2 flex-wrap">
              <Button size="sm" variant="secondary" onClick={onRefreshStats}>
                刷新统计
              </Button>
              <Button size="sm" variant="secondary" onClick={onHealthCheck}>
                健康检查
              </Button>
            </div>
          </div>
        </CardBody>
      </Card>

      <div className="flex justify-end mt-6">
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
