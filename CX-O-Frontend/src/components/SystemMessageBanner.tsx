/**
 * 系统消息横幅组件。
 *
 * 迁移自 CXHMS frontend/src/components/SystemMessageBanner.tsx。
 * 适配点：
 * - 移除 i18n（useTranslation），改用硬编码中文
 * - CX-O Message 类型使用 `type?: string` 字段（CXHMS 用 `content_type`），故以 `type === 'diary_summary'` 判定日记摘要
 *
 * 用于聊天页面中以横幅样式展示系统消息，例如日记摘要提示。
 */
import { memo } from 'react';
import type { Message } from '../pages/chat/types';

interface Props {
  message: Message;
}

export const SystemMessageBanner = memo(function SystemMessageBanner({ message }: Props) {
  const isDiarySummary = message.type === 'diary_summary';

  return (
    <div className="flex justify-center my-2">
      <div
        className="px-4 py-2 max-w-[90%] rounded-md text-xs text-center
                   bg-[var(--color-bg-tertiary)] text-[var(--color-text-secondary)]
                   border border-[var(--color-border)] shadow-sm"
      >
        {isDiarySummary && (
          <span className="inline-flex items-center gap-1 mr-1 text-[var(--color-accent)]">
            <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
              />
            </svg>
            <span>日记摘要</span>
          </span>
        )}
        <span className="whitespace-pre-wrap">{message.content}</span>
      </div>
    </div>
  );
});
