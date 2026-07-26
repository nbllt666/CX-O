/**
 * @file summary-modal.tsx — SummaryModal 业务组件重组（模块7）
 * ============================================================================
 * 模块: 模块7 业务组件重组层 — B 组弹窗类
 * 落点: C:\CX-O\CX-O-Frontend\src\components\business\summary-modal.tsx
 * 原组件: src/components/SummaryModal.tsx
 *
 * 重组策略（MODULE-7 AGENTS.md §2.4）:
 *   - 保留现有业务逻辑（流式消息、自动摘要、清空上下文）
 *   - UI 层换用模块6 ui-v2 Button + glass 工具函数
 *   - 注入 Liquid Glass + data-glass + motion variants（Dialog gentle spring）
 *   - 通过 className 消费 token，不硬编码颜色
 *
 * 跨模块导入约束:
 *   - 仅 import 模块6 ui-v2 + 业务逻辑依赖（@/api/client）
 *   - 禁止 import 模块8/9 内部实现 + 旧 @/components/ 下组件
 * ============================================================================
 */

import { useState, useRef, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence, type Variants } from 'framer-motion';
import { Send, Sparkles, Trash2 } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  Button,
  buildGlassDataAttributes,
  injectGlassClassName,
  isValidGlassTier,
  getComponentSpringTransition,
} from '@/components/ui-v2';
import { api } from '@/api/client';

interface SummaryMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  isStreaming?: boolean;
}

interface SummaryModalProps {
  isOpen: boolean;
  onClose: () => void;
  contextText: string;
  agentId: string;
  sessionId?: string;
  autoStart?: boolean;
}

export function SummaryModal({
  isOpen,
  onClose,
  contextText,
  agentId,
  autoStart = false,
}: SummaryModalProps) {
  const [messages, setMessages] = useState<SummaryMessage[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const autoStartedRef = useRef(false);

  const handleAutoSummary = useCallback(async () => {
    if (isLoading) return;

    const userMessage: SummaryMessage = {
      id: Date.now().toString(),
      role: 'user',
      content: '请自动摘要当前对话',
      timestamp: new Date().toISOString(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setIsLoading(true);

    const assistantMsg: SummaryMessage = {
      id: (Date.now() + 1).toString(),
      role: 'assistant',
      content: '',
      timestamp: new Date().toISOString(),
      isStreaming: true,
    };
    setMessages((prev) => [...prev, assistantMsg]);

    try {
      const fullPrompt = `请对以下对话进行自动摘要，生成多条记忆。每条记忆应包含：
1. 内容（简洁明了）
2. 重要性（1-10，10为最重要）
3. 时间（格式：yyyymmddhhmm，如202602112235）

对话内容：
${contextText}

请使用 save_summary_memory 工具保存每条记忆。你可以保存多条记忆。`;

      await api.sendMessageStream(
        fullPrompt,
        (chunk: Record<string, unknown>) => {
          setMessages((prev) => {
            const lastMsg = prev[prev.length - 1];
            if (lastMsg.role === 'assistant' && lastMsg.isStreaming) {
              return [
                ...prev.slice(0, -1),
                {
                  ...lastMsg,
                  content: lastMsg.content + String(chunk.content ?? ''),
                  isStreaming: chunk.done !== true,
                },
              ];
            }
            return prev;
          });
        },
        agentId
      );
    } catch (error) {
      console.error('自动摘要失败:', error);
      setMessages((prev) => [
        ...prev.slice(0, -1),
        {
          id: Date.now().toString(),
          role: 'assistant',
          content: '抱歉，自动摘要失败，请重试。',
          timestamp: new Date().toISOString(),
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  }, [isLoading, contextText, agentId]);

  // 初始系统消息
  useEffect(() => {
    if (isOpen && messages.length === 0) {
      const systemMsg: SummaryMessage = {
        id: 'system-1',
        role: 'assistant',
        content: `我是摘要助手。我会分析这段对话并生成摘要记忆。\n\n你可以：\n1. 直接让我自动摘要\n2. 告诉我需要关注哪些方面\n3. 指定每条记忆的重要性和时间\n\n我会将摘要保存为多条记忆，每条包含：内容、重要性(1-10)、时间(yyyymmddhhmm格式)。`,
        timestamp: new Date().toISOString(),
      };
      setMessages([systemMsg]);
      autoStartedRef.current = false;
    }
  }, [isOpen, messages.length]);

  // 自动开始摘要
  useEffect(() => {
    if (isOpen && autoStart && !autoStartedRef.current && messages.length > 0) {
      autoStartedRef.current = true;
      setTimeout(() => {
        handleAutoSummary();
      }, 100);
    }
  }, [isOpen, autoStart, messages.length, handleAutoSummary]);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleSend = async () => {
    if (!input.trim() || isLoading) return;

    const userMessage: SummaryMessage = {
      id: Date.now().toString(),
      role: 'user',
      content: input,
      timestamp: new Date().toISOString(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput('');
    setIsLoading(true);

    const assistantMsg: SummaryMessage = {
      id: (Date.now() + 1).toString(),
      role: 'assistant',
      content: '',
      timestamp: new Date().toISOString(),
      isStreaming: true,
    };
    setMessages((prev) => [...prev, assistantMsg]);

    try {
      const fullPrompt = `请对以下对话进行摘要，生成多条记忆。每条记忆应包含：
1. 内容（简洁明了）
2. 重要性（1-10，10为最重要）
3. 时间（格式：yyyymmddhhmm，如202602112235）

对话内容：
${contextText}

用户指令：${input}

请使用 save_summary_memory 工具保存每条记忆。你可以保存多条记忆。`;

      await api.sendMessageStream(
        fullPrompt,
        (chunk: Record<string, unknown>) => {
          setMessages((prev) => {
            const lastMsg = prev[prev.length - 1];
            if (lastMsg.role === 'assistant' && lastMsg.isStreaming) {
              return [
                ...prev.slice(0, -1),
                {
                  ...lastMsg,
                  content: lastMsg.content + String(chunk.content ?? ''),
                  isStreaming: chunk.done !== true,
                },
              ];
            }
            return prev;
          });
        },
        agentId
      );
    } catch (error) {
      console.error('摘要生成失败:', error);
      setMessages((prev) => [
        ...prev.slice(0, -1),
        {
          id: Date.now().toString(),
          role: 'assistant',
          content: '抱歉，摘要生成失败，请重试。',
          timestamp: new Date().toISOString(),
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleClearContext = async () => {
    if (!confirm('确定要清空当前对话的所有上下文吗？')) return;

    try {
      const summarySessionId = `summary-${agentId}`;
      await api.deleteSession(summarySessionId);
      setMessages([]);
      const systemMsg: SummaryMessage = {
        id: 'system-1',
        role: 'assistant',
        content: `我是摘要助手。我会分析这段对话并生成摘要记忆。\n\n你可以：\n1. 直接让我自动摘要\n2. 告诉我需要关注哪些方面\n3. 指定每条记忆的重要性和时间\n\n我会将摘要保存为多条记忆，每条包含：内容、重要性(1-10)、时间(yyyymmddhhmm格式)。`,
        timestamp: new Date().toISOString(),
      };
      setMessages([systemMsg]);
    } catch (error) {
      console.error('清空上下文失败:', error);
      alert('清空上下文失败');
    }
  };

  // Liquid Glass: data-glass + motion variants
  const glassTier = 'tier-2';
  const validTier = isValidGlassTier(glassTier) ? glassTier : undefined;
  const glassAttributes = buildGlassDataAttributes(true, validTier);
  const springTransition = getComponentSpringTransition('gentle');
  const contentVariants: Variants = {
    initial: { opacity: 0, scale: 0.96, y: 8 },
    animate: { opacity: 1, scale: 1, y: 0, transition: springTransition },
    exit: { opacity: 0, scale: 0.96, y: 8, transition: springTransition },
  };
  const overlayVariants: Variants = {
    initial: { opacity: 0 },
    animate: { opacity: 1, transition: springTransition },
    exit: { opacity: 0, transition: springTransition },
  };

  const contentBaseClassName =
    'bg-[var(--dialog-bg)] border border-[var(--dialog-border)] rounded-[var(--dialog-radius)] shadow-[var(--dialog-shadow)] w-full max-w-3xl h-[80vh] flex flex-col m-4 transition-none';
  const composedContentClassName = validTier
    ? injectGlassClassName(contentBaseClassName, validTier)
    : contentBaseClassName;

  if (typeof document === 'undefined') return null;

  return createPortal(
    <AnimatePresence>
      {isOpen && (
        <motion.div className="fixed inset-0 z-50 flex items-center justify-center">
          <motion.div
            className="absolute inset-0 bg-[var(--dialog-overlay)] backdrop-blur-[var(--dialog-backdrop-blur)]"
            variants={overlayVariants}
            initial="initial"
            animate="animate"
            exit="exit"
            onClick={onClose}
            aria-hidden="true"
          />
          <motion.div
            className={composedContentClassName}
            data-glass={glassAttributes['data-glass'] ?? undefined}
            data-glass-tier={glassAttributes['data-glass-tier'] ?? undefined}
            variants={contentVariants}
            initial="initial"
            animate="animate"
            exit="exit"
            role="dialog"
            aria-modal="true"
          >
            {/* Header */}
            <div className="flex items-center justify-between p-4 border-b border-[var(--dialog-border)]">
              <div className="flex items-center gap-2">
                <Sparkles className="w-5 h-5 text-[var(--color-accent)]" />
                <h3 className="font-semibold text-[var(--color-text-primary)]">
                  {autoStart ? '自动摘要' : '自定义摘要'} - 摘要助手
                </h3>
              </div>
              <div className="flex items-center gap-2">
                <Button variant="ghost" size="sm" onClick={handleClearContext} title="清空当前对话的所有上下文">
                  <Trash2 className="w-4 h-4" />
                  清空上下文
                </Button>
                <button
                  onClick={onClose}
                  className="p-2 hover:bg-[var(--color-bg-hover)] rounded-[var(--radius-sm)] transition-none text-[var(--color-text-tertiary)]"
                  aria-label="关闭"
                >
                  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
            </div>

            {/* Messages */}
            <div className="flex-1 overflow-y-auto p-4 space-y-4">
              {messages.map((message) => (
                <div
                  key={message.id}
                  className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
                >
                  <div
                    className={`max-w-[80%] rounded-[var(--radius-lg)] px-4 py-2 ${
                      message.role === 'user'
                        ? 'bg-[var(--color-accent)] text-[var(--color-accent-text)]'
                        : 'bg-[var(--color-bg-secondary)] text-[var(--color-text-primary)]'
                    }`}
                  >
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm]}
                      className="prose prose-sm dark:prose-invert max-w-none"
                    >
                      {message.content}
                    </ReactMarkdown>
                    {message.isStreaming && (
                      <span className="inline-block w-2 h-4 bg-current animate-pulse ml-1" />
                    )}
                  </div>
                </div>
              ))}
              <div ref={messagesEndRef} />
            </div>

            {/* Input */}
            <div className="p-4 border-t border-[var(--dialog-border)]">
              <div className="flex gap-2">
                <input
                  type="text"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleSend()}
                  placeholder="告诉我如何摘要这段对话..."
                  className="flex-1 px-4 py-2 bg-[var(--color-bg-secondary)] rounded-[var(--radius-md)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent-light)] text-[var(--color-text-primary)]"
                  disabled={isLoading}
                />
                <Button
                  variant="primary"
                  size="md"
                  onClick={handleSend}
                  disabled={!input.trim() || isLoading}
                >
                  <Send className="w-4 h-4" />
                  发送
                </Button>
              </div>
              <p className="text-xs text-[var(--color-text-tertiary)] mt-2">
                提示：可以直接发送"自动摘要"让我分析对话，或指定需要关注的内容
              </p>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body,
  );
}
