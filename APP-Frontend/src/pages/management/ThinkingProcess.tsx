/**
 * 思考过程折叠块（Task 8 功能增强 #2）
 *
 * 从 ChatPage 内联 thinking 折叠块抽取为独立组件：
 * - 展开 / 收起（按钮 + 状态，替代原生 <details>）
 * - 加载态：流式思考中（thinking 为空）时显示"思考中…"spinner
 * - 工具调用计数徽章：有 toolCalls 时在头部展示数量
 * - 收起态仅显示头部；展开后展示思考文本与 ToolCallItem 列表
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { BrainCircuit, ChevronDown, Loader2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { ToolCallItem } from './chatStream';
import { ToolCallItem as ToolCallItemView } from './ToolCallItem';

interface ThinkingProcessProps {
  thinking?: string;
  toolCalls?: ToolCallItem[];
  loading?: boolean;
}

export function ThinkingProcess({ thinking, toolCalls, loading }: ThinkingProcessProps) {
  const { t } = useTranslation();
  const [isExpanded, setIsExpanded] = useState(false);

  const hasThinking = Boolean(thinking?.trim());
  const hasToolCalls = Boolean(toolCalls && toolCalls.length > 0);
  const toolCallCount = toolCalls?.length ?? 0;

  // 无思考、无工具调用、且非加载态 → 不渲染空块
  if (!hasThinking && !hasToolCalls && !loading) return null;

  return (
    <div className="overflow-hidden rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.03)]">
      <button
        type="button"
        onClick={() => setIsExpanded((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs font-medium text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.04)]"
      >
        <BrainCircuit className="h-3.5 w-3.5 shrink-0 text-accent" />
        <span>{t('management.chat.thinking')}</span>

        {loading && !hasThinking && (
          <span className="flex items-center gap-1 font-normal text-muted-foreground">
            <Loader2 className="h-3 w-3 animate-spin" />
            {t('management.chat.thinkingInProgress')}
          </span>
        )}

        {hasToolCalls && (
          <span className="rounded-full bg-accent/15 px-1.5 py-0.5 text-[10px] font-normal text-accent">
            {t('management.chat.toolCallCount', { count: toolCallCount })}
          </span>
        )}

        <ChevronDown
          className={cn(
            'ml-auto h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform',
            isExpanded && 'rotate-180',
          )}
        />
      </button>

      {isExpanded && (
        <div className="space-y-3 border-t border-[var(--glass-border)] px-3 py-2 text-xs">
          {hasThinking && (
            <p className="whitespace-pre-wrap break-words text-muted-foreground">{thinking}</p>
          )}
          {hasToolCalls && toolCalls && (
            <div className="space-y-1">
              {toolCalls.map((tc) => (
                <ToolCallItemView key={tc.id} toolCall={tc} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}