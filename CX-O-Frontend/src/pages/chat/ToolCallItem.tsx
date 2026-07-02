import { useState } from 'react';
import type { ToolCall } from './types';

export function ToolCallItem({ toolCall }: { toolCall: ToolCall }) {
  const [isExpanded, setIsExpanded] = useState(false);

  return (
    <div className="p-2 bg-[var(--color-bg-tertiary)] rounded border border-[var(--color-border)] mb-2">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center justify-between text-left"
      >
        <div className="flex items-center gap-2">
          <span className="font-medium text-[var(--color-text-primary)]">
            🔧 {toolCall.name}
          </span>
          {toolCall.status === 'executing' && (
            <span className="animate-pulse text-[var(--color-info)]">执行中...</span>
          )}
          {toolCall.status === 'completed' && (
            <span className="text-[var(--color-success)]">✓ 完成</span>
          )}
          {toolCall.status === 'failed' && (
            <span className="text-[var(--color-error)]">✗ 失败</span>
          )}
        </div>
        <svg
          className={`w-4 h-4 transition-transform ${isExpanded ? 'rotate-180' : ''}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {isExpanded && (
        <div className="mt-2 space-y-1">
          {Boolean(toolCall.arguments) && (
            <div className="text-[var(--color-text-tertiary)] font-mono text-[10px]">
              <div className="font-medium mb-1">参数:</div>
              <pre className="bg-[var(--color-bg-secondary)] p-2 rounded overflow-x-auto">
                {JSON.stringify(toolCall.arguments, null, 2)}
              </pre>
            </div>
          )}
          {toolCall.result !== undefined && (
            <div className="text-[var(--color-text-tertiary)] font-mono text-[10px]">
              <div className="font-medium mb-1">结果:</div>
              <pre className="bg-[var(--color-bg-secondary)] p-2 rounded overflow-x-auto">
                {JSON.stringify(toolCall.result, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
