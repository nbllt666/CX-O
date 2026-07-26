/**
 * @file system-message-banner.tsx — SystemMessageBanner 业务组件重组（模块7）
 * ============================================================================
 * 模块: 模块7 业务组件重组层 — A 组系统类
 * 落点: C:\CX-O\CX-O-Frontend\src\components\business\system-message-banner.tsx
 * 原组件: src/components/SystemMessageBanner.tsx
 *
 * 重组策略（MODULE-7 AGENTS.md §2.4）:
 *   - 保留现有业务逻辑（memo / isDiarySummary 判定 / message 渲染不变）
 *   - UI 层换用模块6 ui-v2 基础组件（Card）
 *   - 注入 Liquid Glass + data-glass + motion variants
 *   - 通过 className 消费 token，不硬编码颜色
 *
 * 跨模块导入约束（rules-0 §四 + MODULE-7 AGENTS.md §2.3）:
 *   - 仅 import 模块6 ui-v2 公开产出
 *   - 禁止 import 模块8/9 内部实现（原组件 import ../pages/chat/types 已替换为本地接口定义）
 * ============================================================================
 */

import { memo } from 'react';
import { motion, type Variants } from 'framer-motion';
import { cn } from '@/lib/utils';
import { Card } from '@/components/ui-v2';
import {
  buildGlassDataAttributes,
  getComponentMotionVariants,
} from '@/components/ui-v2';

/**
 * 系统消息类型（本地定义，对齐原 src/pages/chat/types.ts Message 的子集）。
 *
 * 重组说明: 原组件从 @/pages/chat/types 导入 Message 类型，但模块7 禁止 import 模块8（pages）
 * 内部实现。此处定义与原类型兼容的最小子集（type + content），保留 isDiarySummary 判定逻辑。
 */
interface SystemMessage {
  type?: string;
  content: string;
}

interface Props {
  message: SystemMessage;
}

// 入场 motion variants（基于模块6 getComponentMotionVariants 工厂，gentle spring）
const bannerVariants: Variants = getComponentMotionVariants({
  componentName: 'Dialog',
  springKey: 'gentle',
});

/**
 * 系统消息横幅组件（重组版）。
 *
 * 业务逻辑保留: memo / isDiarySummary 判定 / message.content 渲染原样保留。
 * UI 层重组: 容器换用 ui-v2 Card，挂载 data-glass，注入 motion variants。
 *
 * 适配点（保留自原组件）:
 *   - 移除 i18n（useTranslation），改用硬编码中文
 *   - CX-O Message 类型使用 `type?: string` 字段，故以 `type === 'diary_summary'` 判定日记摘要
 */
export const SystemMessageBanner = memo(function SystemMessageBanner({ message }: Props) {
  const isDiarySummary = message.type === 'diary_summary';
  const glassAttributes = buildGlassDataAttributes(true, 3);

  return (
    <div className="flex justify-center my-2">
      <motion.div
        variants={bannerVariants}
        initial="initial"
        animate="animate"
        exit="exit"
      >
        <Card
          className={cn(
            'px-4 py-2 max-w-[90%]',
            'text-xs text-center',
            'text-[var(--color-text-secondary)]',
          )}
          dataGlass={true}
          glassTier={3}
        >
          <div {...glassAttributes}>
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
        </Card>
      </motion.div>
    </div>
  );
});
