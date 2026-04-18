import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { PageHeader } from '../components/layout';
import { Card, CardBody, Button, SkeletonCard } from '../components/ui';
import { api } from '../api/client';

interface Stats {
  memoryCount: number;
  sessionCount: number;
  agentCount: number;
  todayMessages: number;
}

interface ServiceStats {
  tts_count: number;
  asr_count: number;
  llm_count: number;
  client_count: number;
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
      // 获取记忆总数（使用较大的 limit 来获取实际总数）
      const memoriesResponse = await api.getMemories({ limit: 10000 });
      const sessionsResponse = await api.getSessions();
      const agentsResponse = await api.getAgents();
      
      // API 返回格式：{ status: "success", memories: [], total: number }
      const memories = memoriesResponse.memories || [];
      const memoriesTotal = memoriesResponse.total || memories.length;
      
      // API 返回格式：{ status: "success", sessions: [], total: number }
      const sessions = sessionsResponse.sessions || [];
      const sessionsTotal = sessionsResponse.total || sessions.length;
      
      // API 返回格式：{ status: "success", agents: [], total: number }
      const agents = agentsResponse.agents || agentsResponse || [];
      
      // 计算今日消息数（从会话中统计今天更新的会话）
      const today = new Date();
      today.setHours(0, 0, 0, 0);
      const todaySessions = sessions.filter((s: { updated_at?: string }) => {
        if (!s.updated_at) return false;
        const sessionDate = new Date(s.updated_at);
        return sessionDate >= today;
      });

      return {
        memoryCount: memoriesTotal,
        sessionCount: sessionsTotal,
        agentCount: agents.filter((a: { id: string }) => a.id !== 'memory-agent').length || 0,
        todayMessages: todaySessions.length || 0,
      };
    },
  });

  const { data: serviceStats, isLoading: serviceStatsLoading } = useQuery<ServiceStats>({
    queryKey: ['service-stats'],
    queryFn: async () => {
      return await api.getStats();
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
              服务统计
            </h2>
            {serviceStatsLoading ? (
              <div className="grid grid-cols-2 gap-4">
                {[1, 2, 3, 4].map((i) => (
                  <div key={i} className="animate-pulse p-4 bg-[var(--color-bg-tertiary)] rounded-[var(--radius-md)]">
                    <div className="h-4 bg-[var(--color-bg-secondary)] rounded w-1/2 mb-2" />
                    <div className="h-8 bg-[var(--color-bg-secondary)] rounded w-3/4" />
                  </div>
                ))}
              </div>
            ) : (
              <div className="grid grid-cols-2 gap-4">
                <div className="p-4 bg-[var(--color-bg-tertiary)] rounded-[var(--radius-md)]">
                  <p className="text-sm text-[var(--color-text-secondary)]">TTS 合成次数</p>
                  <p className="text-2xl font-bold text-[var(--color-accent)]">{serviceStats?.tts_count || 0}</p>
                </div>
                <div className="p-4 bg-[var(--color-bg-tertiary)] rounded-[var(--radius-md)]">
                  <p className="text-sm text-[var(--color-text-secondary)]">ASR 识别次数</p>
                  <p className="text-2xl font-bold text-[var(--color-success)]">{serviceStats?.asr_count || 0}</p>
                </div>
                <div className="p-4 bg-[var(--color-bg-tertiary)] rounded-[var(--radius-md)]">
                  <p className="text-sm text-[var(--color-text-secondary)]">LLM 调用次数</p>
                  <p className="text-2xl font-bold text-[var(--color-warning)]">{serviceStats?.llm_count || 0}</p>
                </div>
                <div className="p-4 bg-[var(--color-bg-tertiary)] rounded-[var(--radius-md)]">
                  <p className="text-sm text-[var(--color-text-secondary)]">在线客户端数</p>
                  <p className="text-2xl font-bold text-[var(--color-info)]">{serviceStats?.client_count || 0}</p>
                </div>
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
            </div>
          </CardBody>
        </Card>
      </div>
    </div>
  );
};
