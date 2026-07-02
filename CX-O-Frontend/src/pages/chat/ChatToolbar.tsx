/**
 * H4 拆分：聊天页工具栏（页头 + 动作按钮组）。
 *
 * Presentational 组件 — 仅接收 props 与回调，不持有状态。
 */
import { PageHeader } from '../../components/layout';
import { Button } from '../../components/ui';
import { AvatarTypeSelector } from '../../components/Avatar';
import type { Agent } from '../../api/client';

export interface ChatToolbarProps {
  currentAgent?: Agent;
  hasMessages: boolean;
  onArchiveMemory: () => void;
  onClearContext: () => void;
  onAutoSummary: () => void;
  onShowSummaryModal: () => void;
}

export function ChatToolbar({
  currentAgent,
  hasMessages,
  onArchiveMemory,
  onClearContext,
  onAutoSummary,
  onShowSummaryModal,
}: ChatToolbarProps) {
  return (
    <PageHeader
      title={currentAgent?.name || '对话'}
      description={currentAgent?.description}
      actions={
        <div className="flex gap-2">
          {/* 虚拟形象选择器 */}
          <AvatarTypeSelector />
          <Button
            variant="secondary"
            size="sm"
            onClick={onArchiveMemory}
            icon={
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M5 8h14M5 8a2 2 0 110-4h14a2 2 0 110 4M5 8v10a2 2 0 002 2h10a2 2 0 002-2V8m-9 4h4"
                />
              </svg>
            }
          >
            记忆归档
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={onClearContext}
            icon={
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
                />
              </svg>
            }
          >
            清空上下文
          </Button>
          {hasMessages && (
            <>
              <Button
                variant="secondary"
                size="sm"
                onClick={onAutoSummary}
                icon={
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M13 10V3L4 14h7v7l9-11h-7z"
                    />
                  </svg>
                }
              >
                自动摘要
              </Button>
              <Button
                variant="secondary"
                size="sm"
                onClick={onShowSummaryModal}
                icon={
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"
                    />
                  </svg>
                }
              >
                自定义摘要
              </Button>
            </>
          )}
        </div>
      }
    />
  );
}
