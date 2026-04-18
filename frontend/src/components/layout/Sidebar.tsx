import React, { useState, useEffect } from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import { cn } from '../../lib/utils';
import { Tooltip } from '../ui';
import { useChatStore } from '../../store/chatStore';
import { api } from '../../api/client';

interface SidebarProps {
  collapsed?: boolean;
  setCollapsed?: (collapsed: boolean) => void;
}

interface NavItem {
  path: string;
  label: string;
  icon: React.ReactNode;
  hasSubmenu?: boolean;
}

interface Agent {
  id: string;
  name: string;
  description?: string;
}

const navItems: NavItem[] = [
  {
    path: '/dashboard',
    label: '仪表盘',
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z"
        />
      </svg>
    ),
  },
  {
    path: '/chat',
    label: '对话',
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
        />
      </svg>
    ),
    hasSubmenu: true,
  },
  {
    path: '/memories',
    label: '记忆',
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
        />
      </svg>
    ),
  },
  {
    path: '/agents',
    label: 'Agent',
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z"
        />
      </svg>
    ),
  },
  {
    path: '/tools',
    label: '工具',
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"
        />
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"
        />
      </svg>
    ),
  },
  {
    path: '/audio',
    label: '音频测试',
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z"
        />
      </svg>
    ),
  },
  {
    path: '/archive',
    label: '归档',
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M5 8h14M5 8a2 2 0 110-4h14a2 2 0 110 4M5 8v10a2 2 0 002 2h10a2 2 0 002-2V8m-9 4h4"
        />
      </svg>
    ),
  },
  {
    path: '/acp',
    label: 'ACP',
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z"
        />
      </svg>
    ),
  },
  {
    path: '/settings',
    label: '设置',
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4"
        />
      </svg>
    ),
  },
  {
    path: '/graph-data',
    label: '图数据',
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"
        />
      </svg>
    ),
  },
  {
    path: '/vector-data',
    label: '向量数据',
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4"
        />
      </svg>
    ),
  },
];

export const Sidebar: React.FC<SidebarProps> = ({ collapsed, setCollapsed }) => {
  const location = useLocation();
  const navigate = useNavigate();
  const [agents, setAgents] = useState<Agent[]>([]);
  const [isChatExpanded, setIsChatExpanded] = useState(false);
  const { currentAgentId, setCurrentAgentId } = useChatStore();

  // 加载Agent列表
  useEffect(() => {
    const loadAgents = async () => {
      try {
        const data = await api.getAgents();
        // API 返回的是数组格式
        let agentList = Array.isArray(data) ? data : data.agents || [];
        // 过滤掉记忆管理助手（memory-agent），它有独立的入口
        agentList = agentList.filter((agent: Agent) => agent.id !== 'memory-agent');
        setAgents(agentList);
      } catch (error) {
        console.error('加载Agent列表失败:', error);
      }
    };
    loadAgents();
  }, []);

  // 当在对话页面时自动展开
  useEffect(() => {
    if (location.pathname === '/chat') {
      setIsChatExpanded(true);
    }
  }, [location.pathname]);

  const handleAgentClick = (agentId: string) => {
    setCurrentAgentId(agentId);
    navigate('/chat');
  };

  const NavItemContent = ({ item, isActive }: { item: NavItem; isActive: boolean }) => (
    <div
      className={cn(
        'flex items-center gap-3 px-3 py-2.5 rounded-[var(--radius-md)]',
        'transition-all duration-[var(--transition-fast)]',
        isActive
          ? 'bg-[var(--color-accent-light)] text-[var(--color-accent)]'
          : 'text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text-primary)]'
      )}
    >
      <span className="flex-shrink-0">{item.icon}</span>
      {!collapsed && <span className="text-sm font-medium">{item.label}</span>}
      {!collapsed && item.hasSubmenu && (
        <svg
          className={cn('w-4 h-4 ml-auto transition-transform', isChatExpanded && 'rotate-180')}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      )}
    </div>
  );

  return (
    <div className="h-full flex flex-col py-4">
      <div className="flex-1 px-3 space-y-1">
        {navItems.map((item) => {
          const isActive = location.pathname === item.path;
          const isChat = item.path === '/chat';

          if (collapsed) {
            return (
              <Tooltip key={item.path} content={item.label} position="right">
                <NavLink to={item.path} className="block">
                  <NavItemContent item={item} isActive={isActive} />
                </NavLink>
              </Tooltip>
            );
          }

          return (
            <div key={item.path}>
              {isChat ? (
                <>
                  <button
                    onClick={() => setIsChatExpanded(!isChatExpanded)}
                    className="w-full block"
                  >
                    <NavItemContent item={item} isActive={isActive} />
                  </button>
                  {/* Agent 选择列表 */}
                  {isChatExpanded && agents.length > 0 && (
                    <div className="mt-1 ml-4 pl-3 border-l border-[var(--color-border)] space-y-1">
                      {agents.map((agent) => (
                        <button
                          key={agent.id}
                          onClick={() => handleAgentClick(agent.id)}
                          className={cn(
                            'w-full flex items-center gap-2 px-3 py-2 rounded-[var(--radius-md)] text-left',
                            'transition-all duration-[var(--transition-fast)]',
                            currentAgentId === agent.id
                              ? 'bg-[var(--color-accent-light)] text-[var(--color-accent)]'
                              : 'text-[var(--color-text-tertiary)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text-primary)]'
                          )}
                        >
                          <div
                            className={cn(
                              'w-2 h-2 rounded-full flex-shrink-0',
                              currentAgentId === agent.id
                                ? 'bg-[var(--color-accent)]'
                                : 'bg-[var(--color-border)]'
                            )}
                          />
                          <span className="text-sm truncate">{agent.name}</span>
                        </button>
                      ))}
                    </div>
                  )}
                </>
              ) : (
                <NavLink to={item.path} className="block">
                  <NavItemContent item={item} isActive={isActive} />
                </NavLink>
              )}
            </div>
          );
        })}
      </div>

      {setCollapsed && (
        <div className="px-3 pt-4 border-t border-[var(--color-border)]">
          <button
            onClick={() => setCollapsed(!collapsed)}
            className={cn(
              'w-full flex items-center justify-center gap-2 px-3 py-2',
              'text-[var(--color-text-tertiary)] hover:text-[var(--color-text-primary)]',
              'rounded-[var(--radius-md)] hover:bg-[var(--color-bg-hover)]',
              'transition-all duration-[var(--transition-fast)]'
            )}
          >
            <svg
              className={cn('w-5 h-5 transition-transform', collapsed && 'rotate-180')}
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M11 19l-7-7 7-7m8 14l-7-7 7-7"
              />
            </svg>
            {!collapsed && <span className="text-sm">收起侧边栏</span>}
          </button>
        </div>
      )}
    </div>
  );
};
