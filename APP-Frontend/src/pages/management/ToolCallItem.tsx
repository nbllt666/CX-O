/**
 * 工具调用条目（Task 8 功能增强 #3）
 *
 * 从 ChatPage 内联工具调用徽章抽取为独立组件：
 * - pending / executing / completed / failed 状态徽章
 * - 参数摘要、结果折叠展示（arguments / result 来自 chatStream 事件归约）
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { CheckCircle2, ChevronDown, Loader2, Wrench, XCircle } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { ToolCallItem as ToolCall } from './chatStream';

interface ToolCallItemProps {
  toolCall: ToolCall;
}

export function ToolCallItem({ toolCall }: ToolCallItemProps) {
  const { t } = useTranslation();
  const [isExpanded, setIsExpanded] = useState(false);
  const { status } = toolCall;
  const hasDetail = toolCall.arguments !== undefined || toolCall.result !== undefined;

  return (
    <div className="rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.04)] px-2.5 py-1.5">
      <button
        type="button"
        onClick={() => setIsExpanded((v) => !v)}
        className="flex w-full items-center gap-2 text-left text-xs"
      >
        <Wrench className="h-3 w-3 shrink-0 text-accent" />
        <span className="truncate font-medium">{toolCall.name}</span>

        <span className="ml-auto flex shrink-0 items-center gap-1 font-medium">
          {status === 'pending' && <span className="text-muted-foreground">{t('management.chat.toolPending')}</span>}
          {status === 'executing' && (
            <span className="flex items-center gap-1 font-normal text-amber-400">
              <Loader2 className="h-3 w-3 animate-spin" />
              {t('management.chat.toolExecuting')}
            </span>
          )}
          {status === 'completed' && (
            <span className="flex items-center gap-1 font-normal text-emerald-400">
              <CheckCircle2 className="h-3 w-3" />
              {t('management.chat.toolCompleted')}
            </span>
          )}
          {status === 'failed' && (
            <span className="flex items-center gap-1 font-normal text-red-400">
              <XCircle className="h-3 w-3" />
              {t('management.chat.toolFailed')}
            </span>
          )}
        </span>

        {hasDetail && (
          <ChevronDown
            className={cn('h-3 w-3 shrink-0 transition-transform', isExpanded && 'rotate-180')}
          />
        )}
      </button>

      {isExpanded && hasDetail && (
        <div className="mt-2 space-y-2 border-t border-[var(--glass-border)] pt-2">
          {toolCall.arguments !== undefined && (
            <DetailBlock label={t('management.chat.toolArguments')} value={toolCall.arguments} />
          )}
          {toolCall.result !== undefined && (
            <DetailBlock label={t('management.chat.toolResult')} value={toolCall.result} />
          )}
        </div>
      )}
    </div>
  );
}

function DetailBlock({ label, value }: { label: string; value: unknown }) {
  let text: string;
  try {
    text = typeof value === 'string' ? value : JSON.stringify(value, null, 2);
  } catch {
    text = String(value);
  }
  return (
    <div className="min-w-0">
      <div className="mb-0.5 font-medium text-muted-foreground">{label}</div>
      <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-words rounded bg-[rgba(255,255,255,0.05)] p-2 font-mono text-[10px] text-muted-foreground">
        {text}
      </pre>
    </div>
  );
}