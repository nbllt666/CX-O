import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { PageHeader } from '../components/layout';
import { Card, CardBody, Button, SkeletonCard, EmptyStateIcon } from '../components/ui';
import { api } from '../api/client';

interface Stats {
  memoryCount: number;
  sessionCount: number;
  agentCount: number;
  todayMessages: number;
}

interface RecentActivity {
  id: string;
  type: 'chat' | 'memory' | 'agent';
  title: string;
  timestamp: string;
}

const StatCard: React.FC<{
  title: string;
  value: number | string;
  icon: React.ReactNode;
  color: string;
}> = ({ title, value, icon, color }) => (
  <Card className="p-4">
    <div className="flex items-center gap-4">
      <div
        className="w-12 h-12 rounded-[var(--radius-lg)] flex items-center justify-center"
        style={{ backgroundColor: `var(--color-${color}-light)` }}
      >
        <span style={{ color: `var(--color-${color})` }}>{icon}</span>
      </div>
      <div>
        <p className="text-sm text-[var(--color-text-secondary)]">{title}</p>
        <p className="text-2xl font-bold text-[var(--color-text-primary)]">{value}</p>
      </div>
    </div>
  </Card>
);

const QuickAction: React.FC<{ to: string; icon: React.ReactNode; label: string }> = ({
  to,
  icon,
  label,
}) => (
  <Link to={to}>
    <Button variant="secondary" className="w-full justify-start gap-2">
      {icon}
      {label}
    </Button>
  </Link>
);

export const DashboardPage: React.FC = () => {
  const { data: stats, isLoading: statsLoading } = useQuery<Stats>({
    queryKey: ['dashboard-stats'],
    queryFn: async () => {
      const [memories, sessions, agents] = await Promise.all([
        api.getMemories({ limit: 1 }),
        api.getSessions(),
        api.getAgents(),
      ]);
      return {
        memoryCount: memories.total || 0,
        sessionCount: sessions.length || 0,
        agentCount: agents.filter((a: { id: string }) => a.id !== 'memory-agent').length || 0,
        todayMessages: 0,
      };
    },
  });

  const { data: recentActivity, isLoading: activityLoading } = useQuery<RecentActivity[]>({
    queryKey: ['recent-activity'],
    queryFn: async () => {
      const sessions = await api.getSessions();
      return sessions.slice(0, 5).map((s: { id: string; title?: string; updated_at?: string }) => ({
        id: s.id,
        type: 'chat' as const,
        title: s.title || '新对话',
        timestamp: s.updated_at || new Date().toISOString(),
      }));
    },
  });

  return (
    <div className="max-w-6xl mx-auto">
      <PageHeader title="仪表盘" description="系统概览与快捷操作" />

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        {statsLoading ? (
          <>
            <SkeletonCard />
            <SkeletonCard />
            <SkeletonCard />
            <SkeletonCard />
          </>
        ) : (
          <>
            <StatCard
              title="记忆总数"
              value={stats?.memoryCount || 0}
              color="accent"
              icon={
                <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                  />
                </svg>
              }
            />
            <StatCard
              title="会话数"
              value={stats?.sessionCount || 0}
              color="success"
              icon={
                <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
                  />
                </svg>
              }
            />
            <StatCard
              title="Agent数"
              value={stats?.agentCount || 0}
              color="warning"
              icon={
                <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z"
                  />
                </svg>
              }
            />
            <StatCard
              title="今日消息"
              value={stats?.todayMessages || 0}
              color="info"
              icon={
                <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M7 8h10M7 12h4m1 8l-4-4H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-3l-4 4z"
                  />
                </svg>
              }
            />
          </>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card className="lg:col-span-2">
          <CardBody>
            <h2 className="text-lg font-semibold text-[var(--color-text-primary)] mb-4">
              最近活动
            </h2>
            {activityLoading ? (
              <div className="space-y-3">
                {[1, 2, 3].map((i) => (
                  <div key={i} className="animate-pulse flex items-center gap-3">
                    <div className="w-10 h-10 bg-[var(--color-bg-tertiary)] rounded-[var(--radius-md)]" />
                    <div className="flex-1">
                      <div className="h-4 bg-[var(--color-bg-tertiary)] rounded w-1/2 mb-2" />
                      <div className="h-3 bg-[var(--color-bg-tertiary)] rounded w-1/4" />
                    </div>
                  </div>
                ))}
              </div>
            ) : recentActivity && recentActivity.length > 0 ? (
              <div className="space-y-3">
                {recentActivity.map((activity) => (
                  <Link
                    key={activity.id}
                    to={`/${activity.type === 'chat' ? 'chat' : activity.type}`}
                    className="flex items-center gap-3 p-3 rounded-[var(--radius-md)] hover:bg-[var(--color-bg-hover)] transition-colors"
                  >
                    <div className="w-10 h-10 bg-[var(--color-bg-tertiary)] rounded-[var(--radius-md)] flex items-center justify-center">
                      <EmptyStateIcon type="chat" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-[var(--color-text-primary)] truncate">
                        {activity.title}
                      </p>
                      <p className="text-xs text-[var(--color-text-tertiary)]">
                        {new Date(activity.timestamp).toLocaleString('zh-CN')}
                      </p>
                    </div>
                  </Link>
                ))}
              </div>
            ) : (
              <div className="text-center py-8 text-[var(--color-text-tertiary)]">暂无最近活动</div>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardBody>
            <h2 className="text-lg font-semibold text-[var(--color-text-primary)] mb-4">
              快捷操作
            </h2>
            <div className="space-y-2">
              <QuickAction
                to="/chat"
                icon={
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M12 4v16m8-8H4"
                    />
                  </svg>
                }
                label="新对话"
              />
              <QuickAction
                to="/memories"
                icon={
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M12 4v16m8-8H4"
                    />
                  </svg>
                }
                label="新建记忆"
              />
              <QuickAction
                to="/agents"
                icon={
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M12 4v16m8-8H4"
                    />
                  </svg>
                }
                label="新建Agent"
              />
              <QuickAction
                to="/settings"
                icon={
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
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
                }
                label="系统设置"
              />
            </div>
          </CardBody>
        </Card>
      </div>
    </div>
  );
};
