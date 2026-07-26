import { useState } from 'react';
import { Button } from '@/components/ui-v2';
import type { ToolCall } from './types';
import { ToolCallItem } from './ToolCallItem';

export function ThinkingProcess({ thinking, toolCalls }: { thinking?: string; toolCalls?: ToolCall[] }) {
  const [isExpanded, setIsExpanded] = useState(false);

  if (!thinking && (!toolCalls || toolCalls.length === 0)) return null;

  return (
    <div className="mb-3 border border-[var(--color-border)] rounded-[var(--radius-md)] overflow-hidden">
      <Button
        variant="ghost"
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center justify-between px-3 py-2 bg-[var(--color-bg-tertiary)] hover:bg-[var(--color-bg-hover)] transition-colors text-xs text-[var(--color-text-secondary)]"
      >
        <span className="flex items-center gap-2">
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"
            />
          </svg>
          思考过程
          {toolCalls && toolCalls.length > 0 && (
            <span className="px-1.5 py-0.5 bg-[var(--color-accent-light)] text-[var(--color-accent)] rounded-full text-[10px]">
              {toolCalls.length} 个工具调用
            </span>
          )}
        </span>
        <svg
          className={`w-4 h-4 transition-transform ${isExpanded ? 'rotate-180' : ''}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </Button>

      {isExpanded && (
        <div className="px-3 py-2 bg-[var(--color-bg-secondary)] text-xs space-y-3">
          {thinking && (
            <div className="text-[var(--color-text-tertiary)] whitespace-pre-wrap">{thinking}</div>
          )}

          {toolCalls && toolCalls.length > 0 && (
            <div className="space-y-1">
              {toolCalls.map((toolCall, idx) => (
                <ToolCallItem key={idx} toolCall={toolCall} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
