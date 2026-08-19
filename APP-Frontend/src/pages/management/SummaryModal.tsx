import { useState, useRef, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { X, Send, Sparkles, Trash2, Bot, User } from 'lucide-react';
import { chatApi } from '@/api/clients/chat';
import { agentsApi } from '@/api/clients/agents';
import { MarkdownContent } from './MarkdownContent';
import { Button } from '@/components/ui-v2/button';
import { cn } from '@/lib/utils';

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
  autoStart?: boolean;
}

export function SummaryModal({
  isOpen,
  onClose,
  contextText,
  agentId,
  autoStart = false,
}: SummaryModalProps) {
  const { t } = useTranslation();
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
      content: t('management.chat.summaryAutoTrigger'),
      timestamp: new Date().toISOString(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setIsLoading(true);

    const assistantId = (Date.now() + 1).toString();
    const assistantMsg: SummaryMessage = {
      id: assistantId,
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

      await chatApi.sendMessageStream(
        fullPrompt,
        (chunk: Record<string, unknown>) => {
          setMessages((prev) => {
            const lastMsg = prev[prev.length - 1];
            if (lastMsg && lastMsg.role === 'assistant' && lastMsg.isStreaming) {
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
        agentId,
      );
    } catch (error) {
      console.error('自动摘要失败:', error);
      setMessages((prev) => [
        ...prev.slice(0, -1),
        {
          id: Date.now().toString(),
          role: 'assistant',
          content: t('management.chat.summaryFailed'),
          timestamp: new Date().toISOString(),
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  }, [isLoading, contextText, agentId, t]);

  // 初始系统消息
  useEffect(() => {
    if (isOpen && messages.length === 0) {
      const systemMsg: SummaryMessage = {
        id: 'system-1',
        role: 'assistant',
        content: t('management.chat.summaryPromptIntro'),
        timestamp: new Date().toISOString(),
      };
      setMessages([systemMsg]);
      autoStartedRef.current = false;
    }
  }, [isOpen, messages.length, t]);

  // 自动开始摘要
  useEffect(() => {
    if (isOpen && autoStart && !autoStartedRef.current && messages.length > 0) {
      autoStartedRef.current = true;
      setTimeout(() => {
        void handleAutoSummary();
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

      await chatApi.sendMessageStream(
        fullPrompt,
        (chunk: Record<string, unknown>) => {
          setMessages((prev) => {
            const lastMsg = prev[prev.length - 1];
            if (lastMsg && lastMsg.role === 'assistant' && lastMsg.isStreaming) {
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
        agentId,
      );
    } catch (error) {
      console.error('摘要生成失败:', error);
      setMessages((prev) => [
        ...prev.slice(0, -1),
        {
          id: Date.now().toString(),
          role: 'assistant',
          content: t('management.chat.summaryFailed'),
          timestamp: new Date().toISOString(),
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleClearContext = async () => {
    try {
      await agentsApi.clearAgentContext(`summary-${agentId}`);
      setMessages([]);
      const systemMsg: SummaryMessage = {
        id: 'system-1',
        role: 'assistant',
        content: t('management.chat.summaryPromptIntro'),
        timestamp: new Date().toISOString(),
      };
      setMessages([systemMsg]);
    } catch (error) {
      console.error('清空上下文失败:', error);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-md">
      <div className="glass-panel flex h-[80vh] w-full max-w-3xl flex-col p-6 shadow-2xl">
        {/* Header */}
        <div className="mb-3 flex shrink-0 items-center justify-between border-b border-[var(--glass-border)] pb-3">
          <div className="flex items-center gap-2">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary/15 text-primary">
              <Sparkles className="h-4 w-4" />
            </div>
            <h3 className="text-base font-semibold">
              {autoStart ? t('management.chat.autoSummary') : t('management.chat.customSummary')} - {t('management.chat.summaryModalTitle')}
            </h3>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void handleClearContext()}
              className="flex items-center gap-1 rounded-lg px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.08)] hover:text-red-400"
              title="清空当前摘要上下文"
            >
              <Trash2 className="h-3.5 w-3.5" />
              清空上下文
            </button>
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.08)] hover:text-foreground"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Messages */}
        <div className="flex-1 space-y-4 overflow-y-auto p-2">
          {messages.map((message) => {
            const isUser = message.role === 'user';
            return (
              <div
                key={message.id}
                className={cn('flex gap-3', isUser ? 'flex-row-reverse' : 'flex-row')}
              >
                <div
                  className={cn(
                    'flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-xs',
                    isUser ? 'bg-primary/15 text-primary' : 'bg-secondary/15 text-secondary',
                  )}
                >
                  {isUser ? <User className="h-3.5 w-3.5" /> : <Bot className="h-3.5 w-3.5" />}
                </div>
                <div
                  className={cn(
                    'max-w-[80%] rounded-xl px-4 py-2.5 text-sm leading-relaxed',
                    isUser
                      ? 'bg-primary/85 text-primary-foreground'
                      : 'border border-[var(--glass-border)] bg-[var(--glass-bg)]',
                  )}
                >
                  <MarkdownContent content={message.content} />
                  {message.isStreaming && (
                    <span className="ml-1 inline-block h-3 w-1.5 animate-pulse bg-current" />
                  )}
                </div>
              </div>
            );
          })}
          <div ref={messagesEndRef} />
        </div>

        {/* Input */}
        <div className="mt-3 shrink-0 border-t border-[var(--glass-border)] pt-3">
          <div className="flex items-center gap-2">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && void handleSend()}
              placeholder={t('management.chat.summaryInputPlaceholder')}
              className="min-w-0 flex-1 rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-4 py-2 text-sm focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
              disabled={isLoading}
            />
            <Button
              onClick={() => void handleSend()}
              disabled={!input.trim() || isLoading}
              loading={isLoading}
              size="sm"
              icon={<Send className="h-3.5 w-3.5" />}
            >
              {t('management.chat.send')}
            </Button>
          </div>
          <p className="mt-1.5 text-xs text-muted-foreground">
            {t('management.chat.summaryInputHint')}
          </p>
        </div>
      </div>
    </div>
  );
}