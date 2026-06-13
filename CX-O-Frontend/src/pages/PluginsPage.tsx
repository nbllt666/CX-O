import { useState, useEffect, useCallback } from 'react';
import {
  Layers,
  Plus,
  RefreshCw,
  Wifi,
  WifiOff,
  Search,
  Loader2,
  Zap,
  Network,
  X,
} from 'lucide-react';
import { api, type CxfcPlugin, type CxfcSkill, type CxfcDiscoveredPlugin } from '../api/client';
import { cn } from '../lib/utils';

const PluginsPage: React.FC = () => {
  const [plugins, setPlugins] = useState<CxfcPlugin[]>([]);
  const [skills, setSkills] = useState<CxfcSkill[]>([]);
  const [discovered, setDiscovered] = useState<CxfcDiscoveredPlugin[]>([]);
  const [loading, setLoading] = useState(false);
  const [showConnect, setShowConnect] = useState(false);
  const [connectHost, setConnectHost] = useState('localhost');
  const [connectPort, setConnectPort] = useState(8081);
  const [showScan, setShowScan] = useState(false);
  const [activeTab, setActiveTab] = useState<'plugins' | 'skills' | 'discover'>('plugins');

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [pluginData, skillData] = await Promise.all([
        api.getCxfcPlugins(),
        api.getCxfcSkills(),
      ]);
      setPlugins(pluginData || []);
      setSkills(skillData || []);
    } catch (e) {
      console.error('加载插件数据失败:', e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleConnect = async () => {
    try {
      await api.connectCxfcPlugin(connectHost, connectPort);
      setShowConnect(false);
      loadData();
    } catch {
      alert('连接失败，请检查插件地址和端口');
    }
  };

  const handleDisconnect = async (pluginId: string) => {
    if (!confirm('确定要断开此插件吗？')) return;
    try {
      await api.disconnectCxfcPlugin(pluginId);
      loadData();
    } catch { /* 忽略错误，已通过 UI 状态处理 */ }
  };

  const handleRefresh = async (pluginId: string) => {
    try {
      await api.refreshCxfcPlugin(pluginId);
      loadData();
    } catch { /* 忽略错误，已通过 UI 状态处理 */ }
  };

  const handleScan = async () => {
    setShowScan(true);
    setActiveTab('discover');
    try {
      const result = await api.discoverCxfcPlugins(true);
      setDiscovered(result?.remote || []);
    } catch {
      setDiscovered([]);
    }
  };

  const handleConnectDiscovered = async (plugin: CxfcDiscoveredPlugin) => {
    try {
      await api.connectCxfcPlugin(plugin.host, plugin.port);
      loadData();
    } catch {
      alert('连接失败');
    }
  };

  const connectedCount = plugins.filter(p => p.status === 'connected').length;
  const totalTools = plugins.reduce((sum, p) => sum + p.tools.length, 0);
  const totalSkills = skills.length;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Layers className="w-6 h-6 text-primary" />
            插件管理
          </h1>
          <p className="text-muted-foreground mt-1">管理 CXFC 插件连接、Skills 和局域网发现</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={handleScan}
            className="flex items-center gap-2 px-4 py-2 bg-muted text-foreground rounded-lg hover:bg-accent transition-colors text-sm"
          >
            <Search className="w-4 h-4" />
            扫描局域网
          </button>
          <button
            onClick={() => setShowConnect(true)}
            className="flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors text-sm"
          >
            <Plus className="w-4 h-4" />
            连接插件
          </button>
          <button
            onClick={loadData}
            className="flex items-center gap-2 px-4 py-2 bg-muted text-foreground rounded-lg hover:bg-accent transition-colors text-sm"
          >
            <RefreshCw className="w-4 h-4" />
            刷新
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <StatCard title="已连接插件" value={connectedCount} icon={Wifi} loading={loading} />
        <StatCard title="总插件数" value={plugins.length} icon={Layers} loading={loading} />
        <StatCard title="提供工具" value={totalTools} icon={Zap} loading={loading} />
        <StatCard title="Skills" value={totalSkills} icon={Network} loading={loading} />
      </div>

      <div className="flex gap-2">
        {(['plugins', 'skills', 'discover'] as const).map(tab => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={cn(
              'px-4 py-2 rounded-lg text-sm font-medium transition-colors',
              activeTab === tab
                ? 'bg-primary text-primary-foreground'
                : 'bg-muted text-muted-foreground hover:bg-accent'
            )}
          >
            {tab === 'plugins' ? '插件列表' : tab === 'skills' ? 'Skills' : '局域网发现'}
          </button>
        ))}
      </div>

      {loading && (
        <div className="flex justify-center py-12">
          <Loader2 className="w-8 h-8 animate-spin text-primary" />
        </div>
      )}

      {!loading && activeTab === 'plugins' && (
        <div className="space-y-4">
          {plugins.length === 0 ? (
            <div className="text-center py-12 text-muted-foreground">
              <Layers className="w-12 h-12 mx-auto mb-3 opacity-50" />
              <p>暂无已连接的插件</p>
              <p className="text-sm mt-2">点击"连接插件"或"扫描局域网"来发现和连接插件</p>
            </div>
          ) : (
            plugins.map(plugin => (
              <div
                key={plugin.plugin_id}
                className="bg-card rounded-lg border border-border p-4 hover:shadow-md transition-shadow"
              >
                <div className="flex items-center justify-between">
                  <div>
                    <div className="flex items-center gap-3">
                      <div
                        className={cn(
                          'w-10 h-10 rounded-lg flex items-center justify-center',
                          plugin.status === 'connected'
                            ? 'bg-green-500/10'
                            : 'bg-red-500/10'
                        )}
                      >
                        {plugin.status === 'connected' ? (
                          <Wifi className="w-5 h-5 text-green-500" />
                        ) : (
                          <WifiOff className="w-5 h-5 text-red-500" />
                        )}
                      </div>
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-semibold">{plugin.name || plugin.plugin_id}</span>
                          <span
                            className={cn(
                              'text-xs px-2 py-0.5 rounded-full font-medium',
                              plugin.status === 'connected'
                                ? 'bg-green-500/10 text-green-600'
                                : 'bg-red-500/10 text-red-600'
                            )}
                          >
                            {plugin.status === 'connected' ? '已连接' : '已断开'}
                          </span>
                          {plugin.version && (
                            <span className="text-xs text-muted-foreground">v{plugin.version}</span>
                          )}
                        </div>
                        <div className="text-sm text-muted-foreground mt-1">
                          {plugin.host}:{plugin.port}
                          {plugin.tools.length > 0 && ` · ${plugin.tools.length} 个工具`}
                          {plugin.skills.length > 0 && ` · ${plugin.skills.length} 个Skills`}
                          {plugin.last_seen && ` · 最后心跳: ${new Date(plugin.last_seen).toLocaleTimeString()}`}
                        </div>
                      </div>
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => handleRefresh(plugin.plugin_id)}
                      className="p-2 hover:bg-accent rounded-lg transition-colors"
                      title="刷新"
                    >
                      <RefreshCw className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => handleDisconnect(plugin.plugin_id)}
                      className="p-2 hover:bg-red-500/10 hover:text-red-500 rounded-lg transition-colors"
                      title="断开"
                    >
                      <WifiOff className="w-4 h-4" />
                    </button>
                  </div>
                </div>
                {plugin.capabilities.length > 0 && (
                  <div className="flex gap-1.5 mt-3">
                    {plugin.capabilities.map(cap => (
                      <span key={cap} className="text-xs px-2 py-0.5 bg-primary/10 text-primary rounded-full">
                        {cap}
                      </span>
                    ))}
                  </div>
                )}
                {plugin.tools.length > 0 && (
                  <div className="mt-3 pt-3 border-t border-border">
                    <div className="text-xs font-medium text-muted-foreground mb-1.5">提供的工具</div>
                    <div className="flex flex-wrap gap-1.5">
                      {plugin.tools.map((tool, i) => (
                        <span key={i} className="text-xs px-2 py-0.5 bg-muted text-muted-foreground rounded">
                          {tool.name || `tool_${i}`}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      )}

      {!loading && activeTab === 'skills' && (
        <div className="space-y-3">
          {skills.length === 0 ? (
            <div className="text-center py-12 text-muted-foreground">
              <Zap className="w-12 h-12 mx-auto mb-3 opacity-50" />
              <p>暂无已注册的 Skills</p>
              <p className="text-sm mt-2">连接插件后，其声明的 Skills 将自动注册</p>
            </div>
          ) : (
            skills.map(skill => (
              <div
                key={`${skill.source_plugin_id}:${skill.name}`}
                className="bg-card rounded-lg border border-border p-4"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{skill.name}</span>
                    {skill.auto_inject && (
                      <span className="text-xs px-1.5 py-0.5 bg-purple-500/10 text-purple-600 rounded-full">自动注入</span>
                    )}
                  </div>
                  <span className="text-xs text-muted-foreground">来自 {skill.source_plugin_id}</span>
                </div>
                {skill.description && (
                  <p className="text-sm text-muted-foreground mt-1">{skill.description}</p>
                )}
                {skill.prompt_template && (
                  <div className="mt-2 p-2 bg-muted rounded text-xs font-mono text-muted-foreground max-h-24 overflow-y-auto">
                    {skill.prompt_template}
                  </div>
                )}
                <div className="flex gap-4 mt-2">
                  {skill.trigger_keywords.length > 0 && (
                    <div>
                      <span className="text-xs text-muted-foreground">触发关键词:</span>
                      <div className="flex gap-1 mt-1">
                        {skill.trigger_keywords.map(kw => (
                          <span key={kw} className="text-xs px-1.5 py-0.5 bg-yellow-500/10 text-yellow-700 rounded">
                            {kw}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                  {skill.trigger_events.length > 0 && (
                    <div>
                      <span className="text-xs text-muted-foreground">触发事件:</span>
                      <div className="flex gap-1 mt-1">
                        {skill.trigger_events.map(ev => (
                          <span key={ev} className="text-xs px-1.5 py-0.5 bg-orange-500/10 text-orange-700 rounded">
                            {ev}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            ))
          )}
        </div>
      )}

      {!loading && activeTab === 'discover' && (
        <div>
          <div className="flex items-center justify-between mb-4">
            <p className="text-sm text-muted-foreground">
              {showScan ? `发现 ${discovered.length} 个局域网插件` : '点击扫描按钮搜索局域网中的 CXFC 插件'}
            </p>
            <button
              onClick={handleScan}
              className="flex items-center gap-2 px-3 py-1.5 text-sm border border-border rounded-lg hover:bg-accent transition-colors"
            >
              <Search className="w-4 h-4" />
              重新扫描
            </button>
          </div>
          {discovered.length === 0 && showScan ? (
            <div className="text-center py-8 text-muted-foreground">
              <Network className="w-12 h-12 mx-auto mb-3 opacity-50" />
              <p>未发现局域网插件</p>
            </div>
          ) : (
            <div className="space-y-3">
              {discovered.map((plugin, i) => (
                <div
                  key={`${plugin.host}:${plugin.port}:${i}`}
                  className="bg-card rounded-lg border border-border p-4 flex items-center justify-between"
                >
                  <div>
                    <span className="font-medium">{plugin.name || '未知插件'}</span>
                    <div className="text-sm text-muted-foreground">{plugin.host}:{plugin.port} · v{plugin.version || '?'}</div>
                    {plugin.capabilities.length > 0 && (
                      <div className="flex gap-1 mt-1">
                        {plugin.capabilities.map(cap => (
                          <span key={cap} className="text-xs px-1.5 py-0.5 bg-primary/10 text-primary rounded">{cap}</span>
                        ))}
                      </div>
                    )}
                  </div>
                  <button
                    onClick={() => handleConnectDiscovered(plugin)}
                    className="flex items-center gap-2 px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
                  >
                    <Wifi className="w-4 h-4" />
                    连接
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {showConnect && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-card rounded-lg border border-border w-full max-w-md p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-xl font-semibold">连接插件</h2>
              <button onClick={() => setShowConnect(false)} className="text-muted-foreground hover:text-foreground">
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium mb-1">主机地址</label>
                <input
                  type="text"
                  value={connectHost}
                  onChange={e => setConnectHost(e.target.value)}
                  className="w-full px-3 py-2 bg-muted rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/50"
                  placeholder="localhost"
                />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">端口</label>
                <input
                  type="number"
                  value={connectPort}
                  onChange={e => setConnectPort(Number(e.target.value))}
                  className="w-full px-3 py-2 bg-muted rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/50"
                  placeholder="8081"
                />
              </div>
            </div>
            <div className="flex justify-end gap-3 pt-6 mt-6 border-t border-border">
              <button
                onClick={() => setShowConnect(false)}
                className="px-4 py-2 text-muted-foreground hover:text-foreground transition-colors"
              >
                取消
              </button>
              <button
                onClick={handleConnect}
                className="px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
              >
                连接
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

function StatCard({
  title,
  value,
  icon: Icon,
  loading,
}: {
  title: string;
  value: number;
  icon: React.ElementType;
  loading?: boolean;
}) {
  return (
    <div className="bg-card rounded-lg border border-border p-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm text-muted-foreground">{title}</p>
          {loading ? (
            <div className="h-8 w-16 bg-muted rounded animate-pulse mt-1" />
          ) : (
            <p className="text-2xl font-bold mt-1">{value}</p>
          )}
        </div>
        <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center">
          <Icon className="w-5 h-5 text-primary" />
        </div>
      </div>
    </div>
  );
}

export default PluginsPage;
