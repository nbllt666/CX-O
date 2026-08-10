/**
 * PetChat — 桌宠对话气泡区。
 *
 * 行为口径对齐 CX-O-Frontend PetChat：
 * - 消息流式累积（updateLastAssistantMessage 追加增量）
 * - 收尾时解析头像驱动标签（parseAvatarTags → applyAvatarTags 下发驱动），
 *   气泡只显示剥离标签后的干净文本
 * - 仅保留最近 5 条做紧凑展示，新消息自动滚动到底
 *
 * 差异：TTS 不经本组件 HTTP 拉取——语音块由 useWebSocket 内部播放器自动播放，
 * 口型经 useTtsLipSync 频谱分接驱动。
 */
import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { SendHorizonal } from 'lucide-react';
import { parseAvatarTags } from '../../avatar/tagParser';
import { applyAvatarTags } from '../../avatar/applyTags';
import type { IAvatarDriver } from '../../avatar/types';

export interface PetMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
}

export interface PetChatHandle {
  addMessage: (msg: PetMessage) => void;
  /** 流式追加：把增量内容拼到最后一条助手消息上 */
  updateLastAssistantMessage: (delta: string) => void;
  /** 收尾：解析完整文本中的驱动标签并下发驱动，气泡替换为干净文本 */
  finalizeLastAssistantMessage: (fullContent: string) => void;
  /** 按 id 整体替换消息内容（ASR interim → final 就地更新气泡） */
  updateMessageContent: (id: string, content: string) => void;
}

interface PetChatProps {
  driver: IAvatarDriver | null;
  onSend: (message: string) => void;
  isLoading: boolean;
  isConnected: boolean;
  /** 输入行左侧附件槽（如「发送当前画面」按钮），由 PetPage 注入 */
  inputAccessory?: ReactNode;
}

/** 紧凑展示窗口：仅保留最近 N 条 */
const MAX_DISPLAY_MESSAGES = 5;

export const PetChat = forwardRef<PetChatHandle, PetChatProps>(function PetChat(
  { driver, onSend, isLoading, isConnected, inputAccessory },
  ref,
) {
  const { t } = useTranslation();
  const [messages, setMessages] = useState<PetMessage[]>([]);
  const [input, setInput] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  // driver 经 ref 透传给 finalize，避免流式回调因驱动切换过期
  const driverRef = useRef<IAvatarDriver | null>(null);
  driverRef.current = driver;

  const addMessage = useCallback((msg: PetMessage) => {
    setMessages((prev) => [...prev, msg]);
  }, []);

  const updateLastAssistantMessage = useCallback((delta: string) => {
    setMessages((prev) => {
      const last = prev[prev.length - 1];
      if (last && last.role === 'assistant') {
        return [...prev.slice(0, -1), { ...last, content: last.content + delta }];
      }
      return prev;
    });
  }, []);

  const finalizeLastAssistantMessage = useCallback((fullContent: string) => {
    setMessages((prev) => {
      const last = prev[prev.length - 1];
      if (!last || last.role !== 'assistant') return prev;
      const { cleanText, tags } = parseAvatarTags(fullContent);
      if (driverRef.current && tags.length > 0) {
        applyAvatarTags(driverRef.current, tags);
      }
      return [...prev.slice(0, -1), { ...last, content: cleanText }];
    });
  }, []);

  const updateMessageContent = useCallback((id: string, content: string) => {
    setMessages((prev) => prev.map((msg) => (msg.id === id ? { ...msg, content } : msg)));
  }, []);

  useImperativeHandle(
    ref,
    () => ({
      addMessage,
      updateLastAssistantMessage,
      finalizeLastAssistantMessage,
      updateMessageContent,
    }),
    [addMessage, updateLastAssistantMessage, finalizeLastAssistantMessage, updateMessageContent],
  );

  const displayMessages = messages.slice(-MAX_DISPLAY_MESSAGES);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [displayMessages.length]);

  const handleSend = () => {
    const text = input.trim();
    if (!text || isLoading) return;
    addMessage({
      id: `u-${Date.now()}`,
      role: 'user',
      content: text,
      timestamp: new Date().toISOString(),
    });
    onSend(text);
    setInput('');
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="flex h-full flex-col" style={{ backgroundColor: 'transparent' }}>
      {/* 消息气泡区 */}
      <div className="flex-1 space-y-1.5 overflow-y-auto px-2 py-1">
        {displayMessages.map((msg) => (
          <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div
              className={`max-w-[85%] whitespace-pre-wrap break-words rounded-xl px-2.5 py-1.5 text-xs leading-relaxed backdrop-blur-md ${
                msg.role === 'user'
                  ? 'bg-primary/80 text-primary-foreground'
                  : 'glass-panel text-foreground'
              }`}
            >
              {msg.content}
            </div>
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* 输入行 */}
      <div className="flex items-center gap-1.5 px-2 py-1.5">
        {inputAccessory}
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={isConnected ? t('pet.chat.placeholder') : t('pet.chat.offline')}
          disabled={isLoading}
          aria-label={t('pet.chat.placeholder')}
          className="glass-panel min-h-[28px] flex-1 rounded-lg px-2.5 py-1 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary/60 disabled:opacity-60"
        />
        <button
          type="button"
          onClick={handleSend}
          disabled={!input.trim() || isLoading}
          aria-label={t('pet.chat.send')}
          className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary/85 text-primary-foreground transition-opacity duration-fast hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <SendHorizonal className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
});
