import { useState, useRef, useEffect, useCallback } from 'react';
import { X, Send, Sparkles, Trash2 } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { api } from '../api/client';

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
        (chunk: { type: string; content?: string; done?: boolean; error?: string }) => {
          setMessages((prev) => {
            const lastMsg = prev[prev.length - 1];
            if (lastMsg.role === 'assistant' && lastMsg.isStreaming) {
              return [
                ...prev.slice(0, -1),
                {
                  ...lastMsg,
                  content: lastMsg.content + (chunk.content || ''),
                  isStreaming: !chunk.done,
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

    // 添加助手消息占位
    const assistantMsg: SummaryMessage = {
      id: (Date.now() + 1).toString(),
      role: 'assistant',
      content: '',
      timestamp: new Date().toISOString(),
      isStreaming: true,
    };
    setMessages((prev) => [...prev, assistantMsg]);

    try {
      // 构建完整提示词
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
        (chunk: {
          type: string;
          content?: string;
          done?: boolean;
          error?: string;
          session_id?: string;
          tool_call?: Record<string, unknown>;
          tool_name?: string;
          result?: unknown;
        }) => {
          setMessages((prev) => {
            const lastMsg = prev[prev.length - 1];
            if (lastMsg.role === 'assistant' && lastMsg.isStreaming) {
              return [
                ...prev.slice(0, -1),
                {
                  ...lastMsg,
                  content: lastMsg.content + (chunk.content || ''),
                  isStreaming: !chunk.done,
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

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-background rounded-xl w-full max-w-3xl h-[80vh] flex flex-col m-4">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-border">
          <div className="flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-primary" />
            <h3 className="font-semibold">{autoStart ? '自动摘要' : '自定义摘要'} - 摘要助手</h3>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={handleClearContext}
              className="flex items-center gap-1 px-3 py-1.5 text-sm text-destructive hover:bg-destructive/10 rounded-lg transition-colors"
              title="清空当前对话的所有上下文"
            >
              <Trash2 className="w-4 h-4" />
              清空上下文
            </button>
            <button onClick={onClose} className="p-2 hover:bg-accent rounded-lg transition-colors">
              <X className="w-5 h-5" />
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
                className={`max-w-[80%] rounded-2xl px-4 py-2 ${
                  message.role === 'user' ? 'bg-primary text-primary-foreground' : 'bg-muted'
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
        <div className="p-4 border-t border-border">
          <div className="flex gap-2">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSend()}
              placeholder="告诉我如何摘要这段对话..."
              className="flex-1 px-4 py-2 bg-muted rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/50"
              disabled={isLoading}
            />
            <button
              onClick={handleSend}
              disabled={!input.trim() || isLoading}
              className="flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              <Send className="w-4 h-4" />
              发送
            </button>
          </div>
          <p className="text-xs text-muted-foreground mt-2">
            提示：可以直接发送"自动摘要"让我分析对话，或指定需要关注的内容
          </p>
        </div>
      </div>
    </div>
  );
}
