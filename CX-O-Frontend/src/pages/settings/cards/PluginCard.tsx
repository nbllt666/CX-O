import type { CxfcPlugin, CxfcSkill } from '../../../api/client';
import { Button, Card, CardBody, Input, Badge, Dialog } from '@/components/ui-v2';

export interface PluginCardProps {
  plugins: CxfcPlugin[];
  skills: CxfcSkill[];
  showConnectDialog: boolean;
  connectHost: string;
  connectPort: number;
  onScanPlugins: () => void;
  onConnectPlugin: () => void;
  onDisconnectPlugin: (id: string) => void;
  onRefreshPlugin: (id: string) => void;
  onShowConnectDialogChange: (show: boolean) => void;
  onConnectHostChange: (host: string) => void;
  onConnectPortChange: (port: number) => void;
}

export function PluginCard(props: PluginCardProps) {
  const {
    plugins,
    skills,
    showConnectDialog,
    connectHost,
    connectPort,
    onScanPlugins,
    onConnectPlugin,
    onDisconnectPlugin,
    onRefreshPlugin,
    onShowConnectDialogChange,
    onConnectHostChange,
    onConnectPortChange,
  } = props;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-medium">插件管理</h3>
        <div className="flex gap-2">
          <Button variant="secondary" size="sm" onClick={onScanPlugins}>
            扫描局域网
          </Button>
          <Button variant="primary" size="sm" onClick={() => onShowConnectDialogChange(true)}>
            连接插件
          </Button>
        </div>
      </div>

      {plugins.length === 0 ? (
        <div className="text-center py-8 text-[var(--color-text-tertiary)]">
          <p>暂无已连接的插件</p>
          <p className="text-sm mt-1">点击&ldquo;连接插件&rdquo;或&ldquo;扫描局域网&rdquo;来发现和连接插件</p>
        </div>
      ) : (
        <div className="space-y-3">
          {plugins.map(plugin => (
            <Card key={plugin.plugin_id}>
              <CardBody className="p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{plugin.name || plugin.plugin_id}</span>
                      <Badge variant={plugin.status === 'connected' ? 'success' : 'error'} size="sm">
                        {plugin.status === 'connected' ? '已连接' : '已断开'}
                      </Badge>
                    </div>
                    <div className="text-sm text-[var(--color-text-secondary)] mt-1">
                      {plugin.host}:{plugin.port} &middot; {plugin.tools.length} 个工具 &middot; {plugin.skills.length} 个Skills
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <Button variant="ghost" size="sm" onClick={() => onRefreshPlugin(plugin.plugin_id)}>
                      刷新
                    </Button>
                    <Button variant="danger" size="sm" onClick={() => onDisconnectPlugin(plugin.plugin_id)}>
                      断开
                    </Button>
                  </div>
                </div>
                {plugin.capabilities.length > 0 && (
                  <div className="flex gap-1 mt-2 flex-wrap">
                    {plugin.capabilities.map(cap => (
                      <Badge key={cap} variant="secondary" size="sm">{cap}</Badge>
                    ))}
                  </div>
                )}
              </CardBody>
            </Card>
          ))}
        </div>
      )}

      {skills.length > 0 && (
        <div className="mt-6">
          <h4 className="text-md font-medium mb-3">Skills 列表</h4>
          <div className="space-y-2">
            {skills.map(skill => (
              <Card key={`${skill.source_plugin_id}:${skill.name}`}>
                <CardBody className="p-3">
                  <div className="flex items-center justify-between">
                    <span className="font-medium">{skill.name}</span>
                    <span className="text-xs text-[var(--color-text-tertiary)]">来自 {skill.source_plugin_id}</span>
                  </div>
                  <p className="text-sm text-[var(--color-text-secondary)] mt-1">{skill.description}</p>
                  {skill.trigger_keywords.length > 0 && (
                    <div className="flex gap-1 mt-2 flex-wrap">
                      {skill.trigger_keywords.map(kw => (
                        <Badge key={kw} variant="warning" size="sm">{kw}</Badge>
                      ))}
                    </div>
                  )}
                </CardBody>
              </Card>
            ))}
          </div>
        </div>
      )}

      <Dialog
        open={showConnectDialog}
        onOpenChange={onShowConnectDialogChange}
        title="连接插件"
        size="sm"
        footer={
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => onShowConnectDialogChange(false)}>
              取消
            </Button>
            <Button variant="primary" onClick={onConnectPlugin}>
              连接
            </Button>
          </div>
        }
      >
        <div className="space-y-3">
          <div>
            <label className="block text-sm font-medium mb-1">主机地址</label>
            <Input
              type="text"
              value={connectHost}
              onChange={e => onConnectHostChange(e.target.value)}
              placeholder="localhost"
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">端口</label>
            <Input
              type="number"
              value={connectPort}
              onChange={e => onConnectPortChange(Number(e.target.value))}
              placeholder="8081"
            />
          </div>
        </div>
      </Dialog>
    </div>
  );
}
