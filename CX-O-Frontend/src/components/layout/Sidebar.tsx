import React, { useState, useEffect } from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
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
          d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z"
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
    label: '音频控制',
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M15.536 8.464a5 5 0 010 7.072m2.828-9.9a9 9 0 010 12.728M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z"
        />
      </svg>
    ),
  },
  {
    path: '/audio-test',
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
    path: '/plugins',
    label: '插件',
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M12 2L2 7l10 5 10-5-10-5z"
        />
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M2 17l10 5 10-5"
        />
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M2 12l10 5 10-5"
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

const sidebarVariants = {
  expanded: {
    width: '260px',
    transition: {
      duration: 0.3,
      ease: [0.4, 0, 0.2, 1],
    },
  },
  collapsed: {
    width: '72px',
    transition: {
      duration: 0.3,
      ease: [0.4, 0, 0.2, 1],
    },
  },
};

const labelVariants = {
  visible: {
    opacity: 1,
    x: 0,
    transition: {
      duration: 0.2,
      ease: 'easeOut',
    },
  },
  hidden: {
    opacity: 0,
    x: -10,
    transition: {
      duration: 0.15,
      ease: 'easeIn',
    },
  },
};

const navItemVariants = {
  inactive: {
    backgroundColor: 'transparent',
    color: 'var(--color-text-secondary)',
    transition: {
      duration: 0.2,
      ease: 'easeInOut',
    },
  },
  active: {
    backgroundColor: 'var(--color-accent-light)',
    color: 'var(--color-accent)',
    transition: {
      duration: 0.2,
      ease: 'easeInOut',
    },
  },
};

const indicatorVariants = {
  inactive: {
    scaleY: 0,
    opacity: 0,
    transition: {
      duration: 0.2,
      ease: 'easeInOut',
    },
  },
  active: {
    scaleY: 1,
    opacity: 1,
    transition: {
      duration: 0.2,
      ease: 'easeInOut',
    },
  },
};

const submenuVariants = {
  visible: {
    opacity: 1,
    height: 'auto',
    transition: {
      staggerChildren: 0.05,
      delayChildren: 0.05,
      duration: 0.25,
      ease: [0.4, 0, 0.2, 1],
    },
  },
  hidden: {
    opacity: 0,
    height: 0,
    transition: {
      staggerChildren: 0.03,
      staggerDirection: -1,
      when: 'afterChildren',
      duration: 0.2,
      ease: [0.4, 0, 0.2, 1],
    },
  },
};

const submenuItemVariants = {
  visible: {
    opacity: 1,
    x: 0,
    transition: {
      duration: 0.2,
      ease: 'easeOut',
    },
  },
  hidden: {
    opacity: 0,
    x: -10,
    transition: {
      duration: 0.15,
      ease: 'easeIn',
    },
  },
};

const chevronVariants = {
  expanded: {
    rotate: 180,
    transition: {
      duration: 0.3,
      ease: [0.4, 0, 0.2, 1],
    },
  },
  collapsed: {
    rotate: 0,
    transition: {
      duration: 0.3,
      ease: [0.4, 0, 0.2, 1],
    },
  },
};

const collapseButtonVariants = {
  expanded: {
    rotate: 0,
    transition: {
      duration: 0.3,
      ease: [0.4, 0, 0.2, 1],
    },
  },
  collapsed: {
    rotate: 180,
    transition: {
      duration: 0.3,
      ease: [0.4, 0, 0.2, 1],
    },
  },
};

export const Sidebar: React.FC<SidebarProps> = ({ collapsed, setCollapsed }) => {
  const location = useLocation();
  const navigate = useNavigate();
  const [agents, setAgents] = useState<Agent[]>([]);
  const [isChatExpanded, setIsChatExpanded] = useState(false);
  const { currentAgentId, setCurrentAgentId } = useChatStore();

  useEffect(() => {
    const loadAgents = async () => {
      try {
        const data = await api.getAgents();
        const agentList = Array.isArray(data) ? data : [];
        const filteredAgents = agentList.filter((agent: Agent) => agent.id !== 'memory-agent');
        setAgents(filteredAgents);
      } catch (error) {
        console.error('加载Agent列表失败:', error);
      }
    };
    loadAgents();
  }, []);

  useEffect(() => {
    if (location.pathname === '/chat') {
      setIsChatExpanded(true);
    }
  }, [location.pathname]);

  const handleAgentClick = (agentId: string) => {
    setCurrentAgentId(agentId);
    navigate('/chat');
  };

  return (
    <motion.aside
      className="h-full flex flex-col py-4 bg-[var(--color-bg-primary)] border-r border-[var(--color-border)] overflow-hidden"
      variants={sidebarVariants}
      animate={collapsed ? 'collapsed' : 'expanded'}
      initial={false}
    >
      <div className="flex-1 px-3 space-y-1 overflow-y-auto">
        {navItems.map((item) => {
          const isActive = location.pathname === item.path;
          const isChat = item.path === '/chat';

          if (collapsed) {
            return (
              <Tooltip key={item.path} content={item.label} position="right">
                <NavLink to={item.path} className="block">
                  <motion.div
                    className="relative flex items-center justify-center pl-4 pr-3 py-2.5 rounded-[var(--radius-md)]"
                    variants={navItemVariants}
                    animate={isActive ? 'active' : 'inactive'}
                    whileHover={{
                      backgroundColor: isActive ? 'var(--color-accent-light)' : 'var(--color-bg-hover)',
                      color: isActive ? 'var(--color-accent)' : 'var(--color-text-primary)',
                      transition: { duration: 0.15 },
                    }}
                  >
                    <motion.div
                      className="absolute left-0 inset-y-0 w-[5px] bg-[var(--color-accent)]/85 rounded-l-full origin-center"
                      variants={indicatorVariants}
                      animate={isActive ? 'active' : 'inactive'}
                    />
                    <span className="flex-shrink-0">{item.icon}</span>
                  </motion.div>
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
                    <motion.div
                      className="relative flex items-center gap-3 pl-4 pr-3 py-2.5 rounded-[var(--radius-md)]"
                      variants={navItemVariants}
                      animate={isActive ? 'active' : 'inactive'}
                      whileHover={{
                        backgroundColor: isActive ? 'var(--color-accent-light)' : 'var(--color-bg-hover)',
                        color: isActive ? 'var(--color-accent)' : 'var(--color-text-primary)',
                        transition: { duration: 0.15 },
                      }}
                    >
                      <motion.div
                        className="absolute left-0 inset-y-0 w-[5px] bg-[var(--color-accent)]/85 rounded-l-full origin-center"
                      variants={indicatorVariants}
                      animate={isActive ? 'active' : 'inactive'}
                    />
                    <span className="flex-shrink-0">{item.icon}</span>
                    <motion.span
                      className="text-sm font-medium"
                      variants={labelVariants}
                      initial="visible"
                      animate="visible"
                    >
                      {item.label}
                    </motion.span>
                    <motion.svg
                        className="w-4 h-4 ml-auto"
                        variants={chevronVariants}
                        animate={isChatExpanded ? 'expanded' : 'collapsed'}
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke="currentColor"
                      >
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                      </motion.svg>
                    </motion.div>
                  </button>

                  <AnimatePresence initial={false}>
                    {isChatExpanded && agents.length > 0 && (
                      <motion.ul
                        className="mt-1 ml-4 pl-3 border-l border-[var(--color-border)] space-y-1 overflow-hidden"
                        variants={submenuVariants}
                        initial="hidden"
                        animate="visible"
                        exit="hidden"
                      >
                        {agents.map((agent) => (
                          <motion.li key={agent.id} variants={submenuItemVariants}>
                            <button
                              onClick={() => handleAgentClick(agent.id)}
                              className={cn(
                                'w-full flex items-center gap-2 pl-3 pr-3 py-2 rounded-[var(--radius-md)] text-left relative'
                              )}
                            >
                              <motion.div
                                className="absolute -left-[13px] inset-y-1 w-[2px] bg-[var(--color-accent)]/85 rounded-l-full origin-center"
                                initial={{ scaleY: 0, opacity: 0 }}
                                animate={
                                  currentAgentId === agent.id
                                    ? { scaleY: 1, opacity: 1 }
                                    : { scaleY: 0, opacity: 0 }
                                }
                                transition={{ duration: 0.2, ease: 'easeInOut' }}
                              />
                              <div
                                className={cn(
                                  'w-2 h-2 rounded-full flex-shrink-0 transition-colors duration-200',
                                  currentAgentId === agent.id
                                    ? 'bg-[var(--color-accent)]'
                                    : 'bg-[var(--color-border)]'
                                )}
                              />
                              <span
                                className={cn(
                                  'text-sm truncate transition-colors duration-200',
                                  currentAgentId === agent.id
                                    ? 'text-[var(--color-accent)] font-medium'
                                    : 'text-[var(--color-text-tertiary)] hover:text-[var(--color-text-primary)]'
                                )}
                              >
                                {agent.name}
                              </span>
                            </button>
                          </motion.li>
                        ))}
                      </motion.ul>
                    )}
                  </AnimatePresence>
                </>
              ) : (
                <NavLink to={item.path} className="block">
                  <motion.div
                    className="relative flex items-center gap-3 pl-4 pr-3 py-2.5 rounded-[var(--radius-md)]"
                    variants={navItemVariants}
                    animate={isActive ? 'active' : 'inactive'}
                    whileHover={{
                      backgroundColor: isActive ? 'var(--color-accent-light)' : 'var(--color-bg-hover)',
                      color: isActive ? 'var(--color-accent)' : 'var(--color-text-primary)',
                      transition: { duration: 0.15 },
                    }}
                  >
                    <motion.div
                      className="absolute left-0 inset-y-0 w-[5px] bg-[var(--color-accent)]/85 rounded-l-full origin-center"
                      variants={indicatorVariants}
                      animate={isActive ? 'active' : 'inactive'}
                    />
                    <span className="flex-shrink-0">{item.icon}</span>
                    <motion.span
                      className="text-sm font-medium"
                      variants={labelVariants}
                      initial="visible"
                      animate="visible"
                    >
                      {item.label}
                    </motion.span>
                  </motion.div>
                </NavLink>
              )}
            </div>
          );
        })}
      </div>

      {setCollapsed && (
        <div className="px-3 pt-4 border-t border-[var(--color-border)]">
          <motion.button
            onClick={() => setCollapsed(!collapsed)}
            className={cn(
              'w-full flex items-center justify-center gap-2 px-3 py-2',
              'text-[var(--color-text-tertiary)] hover:text-[var(--color-text-primary)]',
              'rounded-[var(--radius-md)] hover:bg-[var(--color-bg-hover)]'
            )}
            whileHover={{
              scale: 1.02,
              backgroundColor: 'var(--color-bg-hover)',
              transition: { duration: 0.15 },
            }}
            whileTap={{ scale: 0.98 }}
          >
            <motion.svg
              className="w-5 h-5"
              variants={collapseButtonVariants}
              animate={collapsed ? 'collapsed' : 'expanded'}
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
            </motion.svg>
            <AnimatePresence mode="wait">
              {!collapsed && (
                <motion.span
                  className="text-sm"
                  variants={labelVariants}
                  initial="hidden"
                  animate="visible"
                  exit="hidden"
                  key="collapse-label"
                >
                  收起侧边栏
                </motion.span>
              )}
            </AnimatePresence>
          </motion.button>
        </div>
      )}
    </motion.aside>
  );
};
