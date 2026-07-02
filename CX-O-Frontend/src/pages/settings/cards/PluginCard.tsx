import type { CxfcPlugin, CxfcSkill } from '../../../api/client';

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
          <button
            onClick={onScanPlugins}
            className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded hover:bg-blue-700"
          >
            扫描局域网
          </button>
          <button
            onClick={() => onShowConnectDialogChange(true)}
            className="px-3 py-1.5 text-sm bg-green-600 text-white rounded hover:bg-green-700"
          >
            连接插件
          </button>
        </div>
      </div>

      {plugins.length === 0 ? (
        <div className="text-center py-8 text-gray-500">
          <p>暂无已连接的插件</p>
          <p className="text-sm mt-1">点击"连接插件"或"扫描局域网"来发现和连接插件</p>
        </div>
      ) : (
        <div className="space-y-3">
          {plugins.map(plugin => (
            <div key={plugin.plugin_id} className="border rounded-lg p-4">
              <div className="flex items-center justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{plugin.name || plugin.plugin_id}</span>
                    <span className={`text-xs px-2 py-0.5 rounded ${plugin.status === 'connected' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
                      {plugin.status === 'connected' ? '已连接' : '已断开'}
                    </span>
                  </div>
                  <div className="text-sm text-gray-500 mt-1">
                    {plugin.host}:{plugin.port} · {plugin.tools.length} 个工具 · {plugin.skills.length} 个Skills
                  </div>
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => onRefreshPlugin(plugin.plugin_id)}
                    className="px-2 py-1 text-xs bg-gray-100 rounded hover:bg-gray-200"
                  >
                    刷新
                  </button>
                  <button
                    onClick={() => onDisconnectPlugin(plugin.plugin_id)}
                    className="px-2 py-1 text-xs bg-red-100 text-red-600 rounded hover:bg-red-200"
                  >
                    断开
                  </button>
                </div>
              </div>
              {plugin.capabilities.length > 0 && (
                <div className="flex gap-1 mt-2">
                  {plugin.capabilities.map(cap => (
                    <span key={cap} className="text-xs px-2 py-0.5 bg-blue-50 text-blue-600 rounded">
                      {cap}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {skills.length > 0 && (
        <div className="mt-6">
          <h4 className="text-md font-medium mb-3">Skills 列表</h4>
          <div className="space-y-2">
            {skills.map(skill => (
              <div key={`${skill.source_plugin_id}:${skill.name}`} className="border rounded p-3">
                <div className="flex items-center justify-between">
                  <span className="font-medium">{skill.name}</span>
                  <span className="text-xs text-gray-500">来自 {skill.source_plugin_id}</span>
                </div>
                <p className="text-sm text-gray-600 mt-1">{skill.description}</p>
                {skill.trigger_keywords.length > 0 && (
                  <div className="flex gap-1 mt-2">
                    {skill.trigger_keywords.map(kw => (
                      <span key={kw} className="text-xs px-1.5 py-0.5 bg-yellow-50 text-yellow-700 rounded">
                        {kw}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {showConnectDialog && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 w-96">
            <h4 className="text-lg font-medium mb-4">连接插件</h4>
            <div className="space-y-3">
              <div>
                <label className="block text-sm font-medium mb-1">主机地址</label>
                <input
                  type="text"
                  value={connectHost}
                  onChange={e => onConnectHostChange(e.target.value)}
                  className="w-full border rounded px-3 py-2"
                  placeholder="localhost"
                />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">端口</label>
                <input
                  type="number"
                  value={connectPort}
                  onChange={e => onConnectPortChange(Number(e.target.value))}
                  className="w-full border rounded px-3 py-2"
                  placeholder="8081"
                />
              </div>
            </div>
            <div className="flex justify-end gap-2 mt-4">
              <button
                onClick={() => onShowConnectDialogChange(false)}
                className="px-4 py-2 text-sm border rounded hover:bg-gray-50"
              >
                取消
              </button>
              <button
                onClick={onConnectPlugin}
                className="px-4 py-2 text-sm bg-green-600 text-white rounded hover:bg-green-700"
              >
                连接
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
