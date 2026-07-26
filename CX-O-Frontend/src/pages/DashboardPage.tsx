import React, { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import { PageHeader } from '@/components/business/layout';
import { Card, CardBody, Button } from '@/components/ui-v2';
import { SkeletonCard } from '@/components/business/ui';
import { api } from '../api/client';
import { CountUp, AnimatedList } from '@/components/business';

interface Stats {
  memoryCount: number;
  sessionCount: number;
  agentCount: number;
  todayMessages: number;
}

interface ServiceStats {
  total_memories: number;
  total_sessions: number;
  total_agents: number;
  archived_memories: number;
}

const StatCard: React.FC<{
  title: string;
  value: number | string;
  icon: React.ReactNode;
  color: string;
  index?: number;
}> = ({ title, value, icon, color, index = 0 }) => (
  <motion.div
    initial={{ opacity: 0, y: 20 }}
    animate={{ opacity: 1, y: 0 }}
    transition={{
      duration: 0.5,
      delay: index * 0.1,
      ease: 'easeOut',
    }}
  >
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
          <p className="text-2xl font-bold text-[var(--color-text-primary)]">
            {typeof value === 'number' ? (
              <CountUp end={value} />
            ) : (
              value
            )}
          </p>
        </div>
      </div>
    </Card>
  </motion.div>
);

const QuickAction: React.FC<{ to: string; icon: React.ReactNode; label: string }> = ({
  to,
  icon,
  label,
}) => (
  <Link to={to}>
    <motion.div whileHover={{ x: 4 }} transition={{ duration: 0.2 }}>
      <Button variant="secondary" className="w-full justify-start gap-2 group">
        {icon}
        <span>{label}</span>
        <svg
          className="w-4 h-4 ml-auto opacity-0 group-hover:opacity-100 transition-opacity duration-200"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M9 5l7 7-7 7"
          />
        </svg>
      </Button>
    </motion.div>
  </Link>
);

export const DashboardPage: React.FC = () => {
  const { data: rawData, isLoading: statsLoading } = useQuery<{
    statsResponse: ServiceStats;
    sessionsResponse: unknown[];
    agentsResponse: { id: string }[];
  }>({
    queryKey: ['dashboard-stats'],
    queryFn: async () => {
      const [statsResponse, sessionsResponse, agentsResponse] = await Promise.all([
        api.getStats(),
        api.getSessions(),
        api.getAgents(),
      ]);

      return {
        statsResponse: statsResponse as ServiceStats,
        sessionsResponse: Array.isArray(sessionsResponse) ? sessionsResponse : [],
        agentsResponse: Array.isArray(agentsResponse) ? agentsResponse : [],
      };
    },
  });

  const stats = useMemo<Stats | undefined>(() => {
    if (!rawData) return undefined;
    const { statsResponse, sessionsResponse, agentsResponse } = rawData;
    const sessions = sessionsResponse as Array<{ updated_at?: string }>;
    const sessionsTotal = sessions.length;

    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const todaySessions = sessions.filter((s) => {
      if (!s.updated_at) return false;
      const sessionDate = new Date(s.updated_at);
      return sessionDate >= today;
    });

    return {
      memoryCount: statsResponse.total_memories || 0,
      sessionCount: sessionsTotal,
      agentCount: agentsResponse.filter((a) => a.id !== 'memory-agent').length || 0,
      todayMessages: todaySessions.length || 0,
    };
  }, [rawData]);

  const serviceStats = useMemo<ServiceStats | undefined>(() => {
    if (!rawData) return undefined;
    return rawData.statsResponse;
  }, [rawData]);

  const serviceStatsLoading = statsLoading;

  const statCardsData = [
    {
      title: '记忆总数',
      value: stats?.memoryCount || 0,
      color: 'accent',
      icon: (
        <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
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
      title: '会话数',
      value: stats?.sessionCount || 0,
      color: 'success',
      icon: (
        <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
          />
        </svg>
      ),
    },
    {
      title: 'Agent数',
      value: stats?.agentCount || 0,
      color: 'warning',
      icon: (
        <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
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
      title: '今日消息',
      value: stats?.todayMessages || 0,
      color: 'info',
      icon: (
        <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M7 8h10M7 12h4m1 8l-4-4H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-3l-4 4z"
          />
        </svg>
      ),
    },
  ];

  const serviceStatItems = [
    {
      label: '记忆总数',
      value: serviceStats?.total_memories || 0,
      color: 'accent',
    },
    {
      label: '会话总数',
      value: serviceStats?.total_sessions || 0,
      color: 'success',
    },
    {
      label: 'Agent 总数',
      value: serviceStats?.total_agents || 0,
      color: 'warning',
    },
    {
      label: '已归档记忆',
      value: serviceStats?.archived_memories || 0,
      color: 'info',
    },
  ];

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
          <AnimatedList className="contents">
            {statCardsData.map((card, index) => (
              <StatCard
                key={card.title}
                title={card.title}
                value={card.value}
                color={card.color}
                icon={card.icon}
                index={index}
              />
            ))}
          </AnimatedList>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card className="lg:col-span-2">
          <CardBody>
            <h2 className="text-lg font-semibold text-[var(--color-text-primary)] mb-4">
              服务统计
            </h2>
            {serviceStatsLoading ? (
              <div className="grid grid-cols-2 gap-4">
                {[1, 2, 3, 4].map((i) => (
                  <div key={i} className="p-4 bg-[var(--color-bg-primary)] rounded-[var(--radius-md)] border border-[var(--color-border)] animate-shimmer relative overflow-hidden" style={{ backgroundImage: 'linear-gradient(90deg, transparent, color-mix(in srgb, var(--color-foreground) 6%, transparent), transparent)', backgroundSize: '200% 100%' }}>
                    <div className="h-4 bg-[var(--color-bg-tertiary)] rounded w-1/2 mb-2" />
                    <div className="h-8 bg-[var(--color-bg-tertiary)] rounded w-3/4" />
                  </div>
                ))}
              </div>
            ) : (
              <div className="grid grid-cols-2 gap-4">
                {serviceStatItems.map((item, index) => (
                  <motion.div
                    key={item.label}
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{
                      duration: 0.5,
                      delay: 0.5 + index * 0.1,
                      ease: 'easeOut',
                    }}
                    className="p-4 bg-[var(--color-bg-tertiary)] rounded-[var(--radius-md)]"
                  >
                    <p className="text-sm text-[var(--color-text-secondary)]">{item.label}</p>
                    <p className="text-2xl font-bold" style={{ color: `var(--color-${item.color})` }}>
                      <CountUp end={item.value} />
                    </p>
                  </motion.div>
                ))}
              </div>
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
              <QuickAction
                to="/live"
                icon={
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z"
                    />
                  </svg>
                }
                label="进入直播间"
              />
            </div>
          </CardBody>
        </Card>
      </div>
    </div>
  );
};
