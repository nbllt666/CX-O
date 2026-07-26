/**
 * @file pet-chat.tsx — PetChat 业务组件重组（模块7）
 * ============================================================================
 * 模块: 模块7 业务组件重组层 — B 组宠物/二次元类
 * 落点: C:\CX-O\CX-O-Frontend\src\components\business\pet-chat.tsx
 * 原组件: src/components/PetChat.tsx
 *
 * 重组策略（MODULE-7 AGENTS.md §2.4）:
 *   - 保留现有业务逻辑（消息状态、TTS 播放、avatar tags 解析与驱动、流式更新）
 *   - UI 层换用模块6 ui-v2 Button + glass 工具函数
 *   - 注入 Liquid Glass + data-glass + motion variants + AnimatePresence 消息进出场
 *   - 通过 className 消费 token，不硬编码颜色
 *
 * 跨模块导入约束:
 *   - import business/avatar/avatar-driver（重组产物）
 *   - 仅 import 模块6 ui-v2 + 业务逻辑依赖（@/lib, @/api）
 *   - 禁止 import 模块8/9 内部实现 + 旧 @/components/ 下组件
 * ============================================================================
 */

import { useState, useRef, useEffect, useCallback, forwardRef, useImperativeHandle } from 'react';
import { motion, AnimatePresence, type Variants } from 'framer-motion';
import { parseAvatarTags, type AvatarTag } from '@/lib/avatarTagParser';
import type { IAvatarDriver } from './avatar/avatar-driver';
import { api } from '@/api/client';
import {
  Button,
  buildGlassDataAttributes,
  injectGlassClassName,
  isValidGlassTier,
  getComponentSpringTransition,
} from '@/components/ui-v2';

interface PetChatProps {
  driver: IAvatarDriver | null;
  onSend: (message: string) => void;
  isLoading: boolean;
  enableTTS?: boolean;
}

export interface PetMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
}

export interface PetChatHandle {
  addMessage: (msg: PetMessage) => void;
  updateLastAssistantMessage: (content: string) => void;
  finalizeLastAssistantMessage: (content: string) => void;
}

export function applyAvatarTags(driver: IAvatarDriver, tags: AvatarTag[]) {
  for (const tag of tags) {
    switch (tag.type) {
      case 'emotion':
        driver.setEmotion(tag.emotion, 1.0);
        break;
      case 'blend':
        driver.setBlendShapes([{ name: tag.name, weight: tag.weight }]);
        break;
      case 'bone':
        driver.setBoneRotations([{ boneName: tag.boneName, rotation: tag.rotation, speed: tag.speed }]);
        break;
      case 'pose':
        driver.holdPose(tag.durationMs);
        break;
      case 'release':
        driver.releasePose();
        break;
      case 'wind':
        driver.setWind(tag);
        break;
      case 'sleep':
        break;
    }
  }
}

export const PetChat = forwardRef<PetChatHandle, PetChatProps>(
  function PetChat({ driver, onSend, isLoading, enableTTS = false }, ref) {
    const [messages, setMessages] = useState<PetMessage[]>([]);
    const [input, setInput] = useState('');
    const messagesEndRef = useRef<HTMLDivElement>(null);
    const audioRef = useRef<HTMLAudioElement | null>(null);

    const addMessage = useCallback((msg: PetMessage) => {
      setMessages(prev => [...prev, msg]);
    }, []);

    const updateLastAssistantMessage = useCallback((content: string) => {
      setMessages(prev => {
        const last = prev[prev.length - 1];
        if (last && last.role === 'assistant') {
          return [...prev.slice(0, -1), { ...last, content: last.content + content }];
        }
        return prev;
      });
    }, []);

    const finalizeLastAssistantMessage = useCallback((content: string) => {
      setMessages(prev => {
        const last = prev[prev.length - 1];
        if (last && last.role === 'assistant') {
          const { cleanText, tags } = parseAvatarTags(content);
          if (driver) {
            applyAvatarTags(driver, tags);
          }
          // TTS playback
          if (enableTTS && cleanText) {
            api.textToSpeech(cleanText).then((audioBlob: Blob) => {
              audioBlob.arrayBuffer().then((arrayBuffer: ArrayBuffer) => {
                const blob = new Blob([arrayBuffer], { type: 'audio/mp3' });
                const url = URL.createObjectURL(blob);
                const audio = new Audio(url);
                audioRef.current = audio;
                driver?.setMouthOpen(0.6);
                audio.onended = () => {
                  URL.revokeObjectURL(url);
                  driver?.setMouthOpen(0);
                };
                audio.play().catch(console.error);
              });
            }).catch(console.error);
          }
          return [...prev.slice(0, -1), { ...last, content: cleanText }];
        }
        return prev;
      });
    }, [driver, enableTTS]);

    useImperativeHandle(ref, () => ({
      addMessage,
      updateLastAssistantMessage,
      finalizeLastAssistantMessage,
    }), [addMessage, updateLastAssistantMessage, finalizeLastAssistantMessage]);

    // Keep only last 5 messages for compact display
    const displayMessages = messages.slice(-5);

    useEffect(() => {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [displayMessages]);

    const handleSend = () => {
      if (!input.trim() || isLoading) return;
      const userMsg: PetMessage = {
        id: Date.now().toString(),
        role: 'user',
        content: input.trim(),
        timestamp: new Date().toISOString(),
      };
      setMessages(prev => [...prev, userMsg]);
      onSend(input.trim());
      setInput('');
    };

    const handleKeyDown = (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    };

    // Liquid Glass: data-glass + motion variants
    const glassTier = 'tier-3';
    const validTier = isValidGlassTier(glassTier) ? glassTier : undefined;
    const glassAttributes = buildGlassDataAttributes(true, validTier);
    const messageSpring = getComponentSpringTransition('snappy');
    const messageVariants: Variants = {
      initial: { opacity: 0, y: 8 },
      animate: { opacity: 1, y: 0, transition: messageSpring },
      exit: { opacity: 0, y: -8, transition: messageSpring },
    };

    const containerBaseClassName = 'flex flex-col h-full transition-none';
    const composedClassName = validTier
      ? injectGlassClassName(containerBaseClassName, validTier)
      : containerBaseClassName;

    return (
      <motion.div
        className={composedClassName}
        data-glass={glassAttributes['data-glass'] ?? undefined}
        data-glass-tier={glassAttributes['data-glass-tier'] ?? undefined}
        style={{ backgroundColor: 'transparent' }}
      >
        {/* Message area */}
        <div
          className="flex-1 overflow-y-auto px-2 py-1 space-y-1.5"
          style={{ pointerEvents: displayMessages.length > 0 ? 'auto' : 'none' }}
        >
          <AnimatePresence initial={false}>
            {displayMessages.map((msg) => (
              <motion.div
                key={msg.id}
                variants={messageVariants}
                initial="initial"
                animate="animate"
                exit="exit"
                className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
              >
                <div
                  className={`max-w-[85%] px-2.5 py-1.5 rounded-[var(--radius-lg)] text-xs leading-relaxed ${
                    msg.role === 'user'
                      ? 'bg-[var(--color-accent)] text-[var(--color-accent-text)]'
                      : 'bg-[var(--color-bg-secondary)] text-[var(--color-text-primary)] border border-[var(--color-border)]'
                  }`}
                  style={{ pointerEvents: 'auto' }}
                >
                  {msg.content}
                </div>
              </motion.div>
            ))}
          </AnimatePresence>
          <div ref={messagesEndRef} />
        </div>

        {/* Input area */}
        <div className="flex gap-1.5 px-2 py-1.5" style={{ pointerEvents: 'auto' }}>
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="发送消息..."
            disabled={isLoading}
            className="flex-1 min-h-[28px] px-2.5 py-1 rounded-[var(--radius-sm)] text-xs bg-[var(--color-bg-secondary)] border border-[var(--color-border)] text-[var(--color-text-primary)] placeholder:text-[var(--color-text-tertiary)] focus:outline-none focus:border-[var(--color-accent)]"
          />
          <Button
            variant="primary"
            size="sm"
            onClick={handleSend}
            disabled={!input.trim() || isLoading}
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
            </svg>
          </Button>
        </div>
      </motion.div>
    );
  }
);
