import { Button, Card, CardBody } from '@/components/ui-v2';
import { LiveClientStatus, FirewallConfig, DanmakuConfig, SaveStatus } from '../types';

export interface LiveCardProps {
  liveClientStatus: LiveClientStatus;
  newBlacklistUid: string;
  onNewBlacklistUidChange: (uid: string) => void;
  firewallConfig: FirewallConfig;
  onFirewallConfigChange: (config: FirewallConfig) => void;
  danmakuConfig: DanmakuConfig;
  onDanmakuConfigChange: (config: DanmakuConfig) => void;
  onDisconnectLive: () => void;
  onSave: () => void;
  saveStatus: SaveStatus;
}

export function LiveCard(props: LiveCardProps) {
  const {
    liveClientStatus,
    newBlacklistUid,
    onNewBlacklistUidChange,
    firewallConfig,
    onFirewallConfigChange,
    danmakuConfig,
    onDanmakuConfigChange,
    onDisconnectLive,
    onSave,
    saveStatus,
  } = props;

  return (
    <div className="space-y-6">
      {/* 直播客户端状态 */}
      <Card>
        <CardBody>
          <h3 className="text-lg font-semibold mb-4">直播客户端状态</h3>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className={`w-3 h-3 rounded-full ${liveClientStatus.connected ? 'bg-green-500' : 'bg-gray-400'}`} />
              <span className="text-sm font-medium">
                {liveClientStatus.connected ? '已连接' : '未连接'}
              </span>
              {liveClientStatus.connected && liveClientStatus.client_id && (
                <span className="text-xs text-[var(--color-text-tertiary)]">
                  ID: {liveClientStatus.client_id.slice(0, 8)}...
                </span>
              )}
            </div>
            <Button
              onClick={onDisconnectLive}
              disabled={!liveClientStatus.connected}
              variant="ghost"
              size="sm"
            >
              断开连接
            </Button>
          </div>
        </CardBody>
      </Card>

      {/* 弹幕 WebSocket 配置 */}
      <Card>
        <CardBody>
          <h3 className="text-lg font-semibold mb-4">弹幕 WebSocket 配置</h3>
          <div className="space-y-4">
            <div>
              <label className="text-sm font-medium mb-2 block">WebSocket 端点</label>
              <input
                type="text"
                value={danmakuConfig.websocket.endpoint}
                onChange={(e) =>
                  onDanmakuConfigChange({
                    ...danmakuConfig,
                    websocket: { ...danmakuConfig.websocket, endpoint: e.target.value },
                  })
                }
                className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                placeholder="/ws/live"
              />
            </div>
            <div>
              <label className="text-sm font-medium mb-2 block">最大连接数</label>
              <input
                type="number"
                value={danmakuConfig.websocket.max_connections}
                onChange={(e) =>
                  onDanmakuConfigChange({
                    ...danmakuConfig,
                    websocket: { ...danmakuConfig.websocket, max_connections: parseInt(e.target.value) || 100 },
                  })
                }
                className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
              />
            </div>
          </div>
        </CardBody>
      </Card>

      {/* 弹幕数据源配置 */}
      <Card>
        <CardBody>
          <h3 className="text-lg font-semibold mb-4">弹幕数据源</h3>
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <label className="text-sm font-medium">B站弹幕</label>
                <p className="text-xs text-[var(--color-text-tertiary)]">接入 B站 直播弹幕</p>
              </div>
              <button
                onClick={() =>
                  onDanmakuConfigChange({
                    ...danmakuConfig,
                    sources: {
                      ...danmakuConfig.sources,
                      bilibili: { ...danmakuConfig.sources.bilibili, enabled: !danmakuConfig.sources.bilibili.enabled },
                    },
                  })
                }
                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                  danmakuConfig.sources.bilibili.enabled ? 'bg-[var(--color-accent)]' : 'bg-[var(--color-border)]'
                }`}
              >
                <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${danmakuConfig.sources.bilibili.enabled ? 'translate-x-6' : 'translate-x-1'}`} />
              </button>
            </div>
            {danmakuConfig.sources.bilibili.enabled && (
              <div>
                <label className="text-sm font-medium mb-2 block">B站 WebSocket 地址</label>
                <input
                  type="text"
                  value={danmakuConfig.sources.bilibili.websocket_url}
                  onChange={(e) =>
                    onDanmakuConfigChange({
                      ...danmakuConfig,
                      sources: {
                        ...danmakuConfig.sources,
                        bilibili: { ...danmakuConfig.sources.bilibili, websocket_url: e.target.value },
                      },
                    })
                  }
                  className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                  placeholder="ws://localhost:8080"
                />
              </div>
            )}

            <div className="flex items-center justify-between">
              <div>
                <label className="text-sm font-medium">RDF 弹幕</label>
                <p className="text-xs text-[var(--color-text-tertiary)]">接入 RDF 直播弹幕</p>
              </div>
              <button
                onClick={() =>
                  onDanmakuConfigChange({
                    ...danmakuConfig,
                    sources: {
                      ...danmakuConfig.sources,
                      rdf: { ...danmakuConfig.sources.rdf, enabled: !danmakuConfig.sources.rdf.enabled },
                    },
                  })
                }
                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                  danmakuConfig.sources.rdf.enabled ? 'bg-[var(--color-accent)]' : 'bg-[var(--color-border)]'
                }`}
              >
                <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${danmakuConfig.sources.rdf.enabled ? 'translate-x-6' : 'translate-x-1'}`} />
              </button>
            </div>
            {danmakuConfig.sources.rdf.enabled && (
              <div>
                <label className="text-sm font-medium mb-2 block">RDF WebSocket 地址</label>
                <input
                  type="text"
                  value={danmakuConfig.sources.rdf.websocket_url}
                  onChange={(e) =>
                    onDanmakuConfigChange({
                      ...danmakuConfig,
                      sources: {
                        ...danmakuConfig.sources,
                        rdf: { ...danmakuConfig.sources.rdf, websocket_url: e.target.value },
                      },
                    })
                  }
                  className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                  placeholder="ws://localhost:9898"
                />
              </div>
            )}
          </div>
        </CardBody>
      </Card>

      {/* 弹幕防火墙配置 */}
      <Card>
        <CardBody>
          <h3 className="text-lg font-semibold mb-4">弹幕防火墙</h3>
          <div className="space-y-4">
            <div>
              <label className="text-sm font-medium mb-2 block">LLM 模型</label>
              <input
                type="text"
                value={firewallConfig.llm.default_model}
                onChange={(e) =>
                  onFirewallConfigChange({
                    ...firewallConfig,
                    llm: { ...firewallConfig.llm, default_model: e.target.value },
                  })
                }
                className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                placeholder="qwen2.5:latest"
              />
            </div>
            <div>
              <label className="text-sm font-medium mb-2 block">LLM 超时 (ms)</label>
              <input
                type="number"
                value={firewallConfig.decision.timeout_ms}
                onChange={(e) =>
                  onFirewallConfigChange({
                    ...firewallConfig,
                    decision: { ...firewallConfig.decision, timeout_ms: parseInt(e.target.value) || 5000 },
                  })
                }
                className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
              />
            </div>

            <div className="flex items-center justify-between">
              <div>
                <label className="text-sm font-medium">黑名单</label>
                <p className="text-xs text-[var(--color-text-tertiary)]">启用用户黑名单过滤</p>
              </div>
              <button
                onClick={() =>
                  onFirewallConfigChange({
                    ...firewallConfig,
                    blocking: { ...firewallConfig.blocking, blacklist_enabled: !firewallConfig.blocking.blacklist_enabled },
                  })
                }
                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                  firewallConfig.blocking.blacklist_enabled ? 'bg-[var(--color-accent)]' : 'bg-[var(--color-border)]'
                }`}
              >
                <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${firewallConfig.blocking.blacklist_enabled ? 'translate-x-6' : 'translate-x-1'}`} />
              </button>
            </div>

            {firewallConfig.blocking.blacklist_enabled && (
              <div>
                <label className="text-sm font-medium mb-2 block">黑名单 UID 列表</label>
                <div className="flex gap-2 mb-2">
                  <input
                    type="text"
                    value={newBlacklistUid}
                    onChange={(e) => onNewBlacklistUidChange(e.target.value)}
                    className="flex-1 px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
                    placeholder="输入 UID"
                  />
                  <Button
                    onClick={() => {
                      if (newBlacklistUid.trim()) {
                        onFirewallConfigChange({
                          ...firewallConfig,
                          blocking: {
                            ...firewallConfig.blocking,
                            blacklist: [...firewallConfig.blocking.blacklist, newBlacklistUid.trim()],
                          },
                        });
                        onNewBlacklistUidChange('');
                      }
                    }}
                    size="sm"
                  >
                    添加
                  </Button>
                </div>
                <div className="flex flex-wrap gap-2">
                  {firewallConfig.blocking.blacklist.map((uid) => (
                    <span
                      key={uid}
                      className="inline-flex items-center gap-1 px-2 py-1 bg-[var(--color-bg-tertiary)] rounded-[var(--radius-md)] text-sm"
                    >
                      {uid}
                      <button
                        onClick={() =>
                          onFirewallConfigChange({
                            ...firewallConfig,
                            blocking: {
                              ...firewallConfig.blocking,
                              blacklist: firewallConfig.blocking.blacklist.filter((u) => u !== uid),
                            },
                          })
                        }
                        className="text-[var(--color-text-tertiary)] hover:text-red-500"
                      >
                        ×
                      </button>
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        </CardBody>
      </Card>

      <div className="flex justify-end">
        <Button onClick={onSave} loading={saveStatus === 'saving'}>
          {saveStatus === 'saved' ? '已保存' : '保存配置'}
        </Button>
      </div>
    </div>
  );
}
