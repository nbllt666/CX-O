import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import {
  MessageSquare,
  Brain,
  Archive,
  Settings,
  Sun,
  Moon,
  Monitor,
  Network,
  Wrench,
  Bot,
  ChevronDown,
  Plus,
  Trash2,
  X,
  Loader2,
  RefreshCw,
} from 'lucide-react';
import { useThemeStore } from '../store/themeStore';
import { useChatStore } from '../store/chatStore';
import { cn } from '../lib/utils';
import { useState, useEffect, useRef } from 'react';

const navigation = [
  { name: '对话', href: '/', icon: MessageSquare, hasSubmenu: true },
  { name: '助手', href: '/agents', icon: Bot },
  { name: '记忆', href: '/memories', icon: Brain },
  { name: '归档', href: '/archive', icon: Archive },
  { name: 'ACP', href: '/acp', icon: Network },
  { name: '工具', href: '/tools', icon: Wrench },
  { name: '设置', href: '/settings', icon: Settings },
];

export function Sidebar() {
  const location = useLocation();
  const navigate = useNavigate();
  const { theme, setTheme } = useThemeStore();
  const {
    agents,
    currentAgentId,
    setCurrentAgentId,
    sessions,
    currentSessionId,
    setCurrentSessionId,
    isChatExpanded,
    setIsChatExpanded,
    isLoadingAgents,
    isLoadingSessions,
    agentsError,
    sessionsError,
    fetchAgents,
    fetchSessions,
    createSession,
    deleteSession,
  } = useChatStore();

  const [showAgentSelector, setShowAgentSelector] = useState(false);
  const [showNewSessionModal, setShowNewSessionModal] = useState(false);

  const agentSelectorRef = useRef<HTMLDivElement>(null);

  const currentAgent = agents.find((a) => a.id === currentAgentId);
  const isChatPage = location.pathname === '/';

  // 在对话页面时自动展开
  useEffect(() => {
    if (isChatPage) {
      setIsChatExpanded(true);
    }
  }, [isChatPage, setIsChatExpanded]);

  // 加载数据
  useEffect(() => {
    const initData = async () => {
      await fetchAgents();
      await fetchSessions();
    };
    initData();
  }, [fetchAgents, fetchSessions]);

  const handleDeleteSession = async (sessionId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm('确定要删除这个对话吗？')) return;
    try {
      await deleteSession(sessionId);
    } catch (error) {
      console.error('删除会话失败:', error);
      alert('删除失败');
    }
  };

  const switchSession = (sessionId: string) => {
    setCurrentSessionId(sessionId);
    navigate('/');
  };

  const startNewChat = async (agentId: string) => {
    try {
      setShowNewSessionModal(false);
      navigate('/');

      const sessionId = await createSession(agentId);
      if (!sessionId) {
        alert('创建新会话失败，请重试');
      }
    } catch (error) {
      console.error('创建新会话失败:', error);
      alert('创建新会话失败，请重试');
    }
  };

  // 点击外部关闭 Agent 选择器
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (agentSelectorRef.current && !agentSelectorRef.current.contains(event.target as Node)) {
        setShowAgentSelector(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  return (
    <div className="w-64 bg-card border-r border-border flex flex-col h-full">
      {/* Logo */}
      <div className="h-16 flex items-center px-6 border-b border-border flex-shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center">
            <Brain className="w-5 h-5 text-primary-foreground" />
          </div>
          <div>
            <h1 className="font-semibold text-lg leading-tight">CXHMS</h1>
            <p className="text-xs text-muted-foreground">晨曦人格化记忆系统</p>
          </div>
        </div>
      </div>

      {/* Navigation - 可滚动区域 */}
      <nav className="flex-1 overflow-y-auto p-4 space-y-1">
        {navigation.map((item) => (
          <div key={item.name}>
            <NavLink
              to={item.href}
              onClick={() => {
                if (item.hasSubmenu) {
                  setIsChatExpanded(!isChatExpanded);
                }
              }}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors',
                  isActive || (item.hasSubmenu && isChatExpanded)
                    ? 'bg-primary/10 text-primary'
                    : 'text-muted-foreground hover:bg-accent hover:text-foreground'
                )
              }
            >
              <item.icon className="w-5 h-5" />
              <span className="flex-1">{item.name}</span>
              {item.hasSubmenu && (
                <ChevronDown
                  className={cn('w-4 h-4 transition-transform', isChatExpanded && 'rotate-180')}
                />
              )}
            </NavLink>

            {/* 对话子菜单 */}
            {item.hasSubmenu && isChatExpanded && (
              <div className="mt-2 ml-4 space-y-2">
                {/* Agent 选择器 */}
                <div className="px-2" ref={agentSelectorRef}>
                  <label className="text-xs text-muted-foreground mb-1 block">当前助手</label>
                  {isLoadingAgents ? (
                    <div className="flex items-center gap-2 px-2 py-1.5 text-sm text-muted-foreground">
                      <Loader2 className="w-3 h-3 animate-spin" />
                      加载中...
                    </div>
                  ) : agentsError ? (
                    <div className="flex items-center justify-between px-2 py-1.5">
                      <span className="text-sm text-destructive">{agentsError}</span>
                      <button onClick={fetchAgents} className="p-1 hover:bg-accent rounded">
                        <RefreshCw className="w-3 h-3" />
                      </button>
                    </div>
                  ) : (
                    <>
                      <button
                        onClick={() => setShowAgentSelector(!showAgentSelector)}
                        className="w-full flex items-center justify-between px-2 py-1.5 bg-muted rounded text-sm hover:bg-accent transition-colors"
                      >
                        <span className="truncate">{currentAgent?.name || '默认助手'}</span>
                        <ChevronDown
                          className={cn(
                            'w-3 h-3 transition-transform',
                            showAgentSelector && 'rotate-180'
                          )}
                        />
                      </button>

                      {showAgentSelector && (
                        <div className="mt-1 bg-popover border border-border rounded-lg shadow-lg z-50 max-h-48 overflow-y-auto">
                          <div className="p-1">
                            {agents.map((agent) => (
                              <button
                                key={agent.id}
                                onClick={() => {
                                  setCurrentAgentId(agent.id);
                                  setShowAgentSelector(false);
                                }}
                                className={cn(
                                  'w-full text-left px-2 py-1.5 rounded text-sm transition-colors',
                                  currentAgentId === agent.id
                                    ? 'bg-primary/10 text-primary'
                                    : 'hover:bg-accent'
                                )}
                              >
                                {agent.name}
                              </button>
                            ))}
                          </div>
                        </div>
                      )}
                    </>
                  )}
                </div>

                {/* 新建对话按钮 */}
                <div className="px-2">
                  <button
                    onClick={() => {
                      if (agents.length === 0) {
                        alert('暂无可用助手，请先创建助手');
                        return;
                      }
                      setShowNewSessionModal(true);
                    }}
                    disabled={agents.length === 0}
                    className="w-full flex items-center justify-center gap-1 px-3 py-2 bg-primary text-primary-foreground rounded-lg text-sm hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                  >
                    <Plus className="w-4 h-4" />
                    新建对话
                  </button>
                </div>

                {/* 历史会话列表 */}
                <div className="px-2">
                  <label className="text-xs text-muted-foreground mb-1 block">历史会话</label>
                  {isLoadingSessions ? (
                    <div className="flex items-center gap-2 px-2 py-2 text-sm text-muted-foreground">
                      <Loader2 className="w-3 h-3 animate-spin" />
                      加载中...
                    </div>
                  ) : sessionsError ? (
                    <div className="flex items-center justify-between px-2 py-2">
                      <span className="text-sm text-destructive">{sessionsError}</span>
                      <button onClick={fetchSessions} className="p-1 hover:bg-accent rounded">
                        <RefreshCw className="w-3 h-3" />
                      </button>
                    </div>
                  ) : sessions.length === 0 ? (
                    <div className="px-2 py-2 text-sm text-muted-foreground">暂无历史会话</div>
                  ) : (
                    <div className="space-y-1 max-h-64 overflow-y-auto">
                      {sessions.map((session) => (
                        <div
                          key={session.id}
                          onClick={() => switchSession(session.id)}
                          className={cn(
                            'group flex items-center gap-2 px-2 py-2 rounded-lg text-sm cursor-pointer transition-colors',
                            currentSessionId === session.id
                              ? 'bg-primary/10 text-primary'
                              : 'hover:bg-accent'
                          )}
                        >
                          <MessageSquare className="w-4 h-4 flex-shrink-0" />
                          <span className="flex-1 truncate">{session.title || '未命名'}</span>
                          <button
                            onClick={(e) => handleDeleteSession(session.id, e)}
                            className="opacity-0 group-hover:opacity-100 p-1 hover:bg-destructive/10 text-destructive rounded transition-all"
                            title="删除对话"
                          >
                            <Trash2 className="w-3 h-3" />
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        ))}
      </nav>

      {/* Theme Toggle */}
      <div className="p-4 border-t border-border flex-shrink-0">
        <div className="flex items-center justify-between">
          <span className="text-sm text-muted-foreground">主题</span>
          <div className="flex bg-muted rounded-lg p-1">
            <button
              onClick={() => setTheme('light')}
              className={cn(
                'p-1.5 rounded-md transition-colors',
                theme === 'light' ? 'bg-background shadow-sm' : 'hover:bg-accent'
              )}
              title="浅色"
            >
              <Sun className="w-4 h-4" />
            </button>
            <button
              onClick={() => setTheme('dark')}
              className={cn(
                'p-1.5 rounded-md transition-colors',
                theme === 'dark' ? 'bg-background shadow-sm' : 'hover:bg-accent'
              )}
              title="深色"
            >
              <Moon className="w-4 h-4" />
            </button>
            <button
              onClick={() => setTheme('system')}
              className={cn(
                'p-1.5 rounded-md transition-colors',
                theme === 'system' ? 'bg-background shadow-sm' : 'hover:bg-accent'
              )}
              title="跟随系统"
            >
              <Monitor className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>

      {/* New Session Modal */}
      {showNewSessionModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-background rounded-xl w-full max-w-md m-4 p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-xl font-semibold">选择助手开始新对话</h2>
              <button
                onClick={() => setShowNewSessionModal(false)}
                className="p-2 hover:bg-accent rounded-lg"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            {isLoadingAgents ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="w-8 h-8 animate-spin text-primary" />
              </div>
            ) : agents.length === 0 ? (
              <div className="text-center py-8 text-muted-foreground">
                <p>暂无可用助手</p>
                <button
                  onClick={() => navigate('/agents')}
                  className="mt-4 px-4 py-2 bg-primary text-primary-foreground rounded-lg"
                >
                  去创建助手
                </button>
              </div>
            ) : (
              <div className="space-y-2 max-h-[60vh] overflow-y-auto">
                {agents.map((agent) => (
                  <button
                    key={agent.id}
                    onClick={() => startNewChat(agent.id)}
                    className="w-full text-left p-4 rounded-lg border border-border hover:border-primary/50 hover:bg-primary/5 transition-all"
                  >
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center">
                        <Bot className="w-5 h-5 text-primary" />
                      </div>
                      <div className="flex-1">
                        <div className="font-medium">{agent.name}</div>
                        <div className="text-sm text-muted-foreground line-clamp-1">
                          {agent.description || agent.system_prompt}
                        </div>
                      </div>
                    </div>
                    <div className="flex gap-4 mt-2 text-xs text-muted-foreground">
                      <span>模型: {agent.model || '默认'}</span>
                      <span>{agent.use_memory ? '✓ 记忆' : '✗ 记忆'}</span>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
