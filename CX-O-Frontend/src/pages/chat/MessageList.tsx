/**
 * H4 拆分：消息列表展示区。
 *
 * Presentational 组件 — 仅接收 props，不持有状态。
 * 包含空状态提示和消息渲染（user/assistant/system 三种角色）。
 * 使用 React.memo 优化，避免父组件状态变化导致的不必要重渲染。
 */
import { memo, type RefObject } from 'react';
import type { Message } from './types';
import { MarkdownContent } from './MarkdownContent';
import { ThinkingProcess } from './ThinkingProcess';
import { formatRelativeTime } from '../../lib/utils';
import { Card } from '@/components/ui-v2';
import type { Agent } from '../../api/client';

export interface MessageListProps {
  messages: Message[];
  isLoading: boolean;
  currentAgent?: Agent;
  chatContainerRef: RefObject<HTMLDivElement>;
  messagesEndRef: RefObject<HTMLDivElement>;
}

export const MessageList = memo(function MessageList({ messages, isLoading, currentAgent, chatContainerRef, messagesEndRef }: MessageListProps) {
  return (
    <div className="flex-1 min-h-0 overflow-y-auto space-y-4 mb-4 px-2" ref={chatContainerRef}>
      {messages.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-full text-center py-12">
          <div className="w-16 h-16 rounded-2xl bg-[var(--color-accent-light)] flex items-center justify-center mb-4">
            <svg
              className="w-8 h-8 text-[var(--color-accent)]"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
              />
            </svg>
          </div>
          <h3 className="text-xl font-semibold text-[var(--color-text-primary)] mb-2">
            开始对话
          </h3>
          <p className="text-[var(--color-text-secondary)] max-w-md mb-4">
            与 AI 助手进行对话，系统会自动检索相关记忆来辅助回答您的问题。
          </p>
          {currentAgent?.system_prompt && (
            <Card className="max-w-md p-3">
              <div className="text-sm font-medium text-[var(--color-text-secondary)] mb-1">
                系统提示词:
              </div>
              <div className="text-sm text-[var(--color-text-tertiary)] line-clamp-3">
                {currentAgent.system_prompt}
              </div>
            </Card>
          )}
        </div>
      ) : (
        messages.map((message) => (
          <div
            key={message.id}
            className={`flex gap-3 ${message.role === 'user' ? 'flex-row-reverse' : ''} ${message.role === 'system' ? 'justify-center' : ''}`}
          >
            {message.role === 'system' ? (
              <div className="max-w-[90%] px-4 py-2.5 rounded-xl bg-blue-50 border border-blue-200 text-blue-700 text-sm">
                <div className="flex items-center gap-2">
                  <svg className="w-4 h-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  <span>{message.content}</span>
                </div>
                <span className="text-xs text-blue-400 mt-1 block">
                  {formatRelativeTime(message.timestamp)}
                </span>
              </div>
            ) : (
            <>
            <div
              className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 ${
                message.role === 'user'
                  ? 'bg-[var(--color-accent)] text-white'
                  : 'bg-[var(--color-bg-tertiary)]'
              }`}
            >
              {message.role === 'user' ? (
                <span className="text-sm font-medium">我</span>
              ) : (
                <svg
                  className="w-5 h-5 text-[var(--color-text-secondary)]"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"
                  />
                </svg>
              )}
            </div>
            <div
              className={`max-w-[80%] ${message.role === 'user' ? 'items-end' : 'items-start'}`}
            >
              {message.role === 'assistant' && (
                <ThinkingProcess thinking={message.thinking} toolCalls={message.tool_calls} />
              )}

              <div
                className={`px-5 py-4 rounded-2xl overflow-hidden ${
                  message.role === 'user'
                    ? 'bg-[var(--color-accent)] text-white'
                    : 'bg-[var(--color-bg-primary)] border border-[var(--color-border)]'
                }`}
              >
                {message.role === 'user' ? (
                  <p className="whitespace-pre-wrap">{message.content}</p>
                ) : (
                  <MarkdownContent content={message.content} />
                )}
                {message.role === 'assistant' &&
                  isLoading &&
                  message.id === messages[messages.length - 1]?.id && (
                    <span className="inline-block w-2 h-4 ml-1 bg-[var(--color-accent)] animate-pulse" />
                  )}
              </div>
              <span className="text-xs text-[var(--color-text-tertiary)] mt-1 px-1">
                {formatRelativeTime(message.timestamp)}
              </span>

              {message.memory_refs && message.memory_refs.length > 0 && (
                <div className="mt-2 flex gap-2">
                  {message.memory_refs.map((ref) => (
                    <span
                      key={ref}
                      className="text-xs px-2 py-1 bg-[var(--color-accent-light)] text-[var(--color-accent)] rounded-full"
                    >
                      引用记忆 #{ref}
                    </span>
                  ))}
                </div>
              )}
            </div>
            </>
            )}
          </div>
        ))
      )}
      <div ref={messagesEndRef} />
    </div>
  );
});
