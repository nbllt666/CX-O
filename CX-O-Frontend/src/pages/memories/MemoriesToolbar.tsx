import { Input, Button } from '@/components/ui-v2';
import type { ViewMode } from './types';

interface AgentOption {
  agent_id: string;
}

interface MemoriesToolbarProps {
  searchQuery: string;
  filterType: 'all' | 'long_term' | 'short_term' | 'permanent';
  currentAgentId: string;
  viewMode: ViewMode;
  isBatchMode: boolean;
  agents: AgentOption[];
  onSearchChange: (value: string) => void;
  onFilterTypeChange: (value: 'all' | 'long_term' | 'short_term' | 'permanent') => void;
  onAgentChange: (value: string) => void;
  onViewModeChange: (mode: ViewMode) => void;
  onBatchModeToggle: () => void;
}

export function MemoriesToolbar({
  searchQuery,
  filterType,
  currentAgentId,
  viewMode,
  isBatchMode,
  agents,
  onSearchChange,
  onFilterTypeChange,
  onAgentChange,
  onViewModeChange,
  onBatchModeToggle,
}: MemoriesToolbarProps) {
  return (
    <div className="flex items-center gap-4 mb-6">
      <div className="flex-1">
        <Input
          placeholder="搜索记忆内容或标签..."
          value={searchQuery}
          onChange={(e) => onSearchChange(e.target.value)}
          className="w-full"
        />
      </div>

      <select
        value={filterType}
        onChange={(e) => onFilterTypeChange(e.target.value as MemoriesToolbarProps['filterType'])}
        className="px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)] text-sm"
      >
        <option value="all">全部类型</option>
        <option value="permanent">永久记忆</option>
        <option value="long_term">长期记忆</option>
        <option value="short_term">短期记忆</option>
      </select>

      <select
        value={currentAgentId}
        onChange={(e) => onAgentChange(e.target.value)}
        className="px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)] text-sm"
      >
        <option value="default">默认Agent</option>
        {agents
          ?.filter((a) => a.agent_id !== 'default')
          .map((agent) => (
            <option key={agent.agent_id} value={agent.agent_id}>
              {agent.agent_id}
            </option>
          ))}
      </select>

      <div className="flex items-center border border-[var(--color-border)] rounded-[var(--radius-md)] overflow-hidden">
        <button
          onClick={() => onViewModeChange('card')}
          className={`px-3 py-2 text-sm ${viewMode === 'card' ? 'bg-[var(--color-accent)] text-white' : 'bg-[var(--color-bg-primary)]'}`}
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z" />
          </svg>
        </button>
        <button
          onClick={() => onViewModeChange('list')}
          className={`px-3 py-2 text-sm ${viewMode === 'list' ? 'bg-[var(--color-accent)] text-white' : 'bg-[var(--color-bg-primary)]'}`}
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 10h16M4 14h16M4 18h16" />
          </svg>
        </button>
      </div>

      <Button
        variant={isBatchMode ? 'primary' : 'secondary'}
        onClick={onBatchModeToggle}
      >
        {isBatchMode ? '退出批量' : '批量操作'}
      </Button>
    </div>
  );
}
