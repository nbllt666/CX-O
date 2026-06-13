import { useState, useRef, useEffect, useCallback, forwardRef, useImperativeHandle } from 'react';
import { parseAvatarTags, type AvatarTag } from '../lib/avatarTagParser';
import type { IAvatarDriver } from '../components/Avatar/AvatarDriver';
import { api } from '../api/client';

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
        driver.setEmotion(tag.name, 1.0);
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

    return (
      <div className="flex flex-col h-full" style={{ backgroundColor: 'transparent' }}>
        {/* Message area */}
        <div
          className="flex-1 overflow-y-auto px-2 py-1 space-y-1.5"
          style={{ pointerEvents: displayMessages.length > 0 ? 'auto' : 'none' }}
        >
          {displayMessages.map((msg) => (
            <div
              key={msg.id}
              className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
            >
              <div
                className={`max-w-[85%] px-2.5 py-1.5 rounded-xl text-xs leading-relaxed ${
                  msg.role === 'user'
                    ? 'bg-[var(--color-accent)]/80 text-white backdrop-blur-sm'
                    : 'bg-[var(--color-bg-secondary)]/70 text-[var(--color-text-primary)] backdrop-blur-sm border border-[var(--color-border)]/50'
                }`}
                style={{ pointerEvents: 'auto' }}
              >
                {msg.content}
              </div>
            </div>
          ))}
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
            className="flex-1 min-h-[28px] px-2.5 py-1 rounded-lg text-xs bg-[var(--color-bg-secondary)]/70 backdrop-blur-sm border border-[var(--color-border)]/50 text-[var(--color-text-primary)] placeholder:text-[var(--color-text-tertiary)] focus:outline-none focus:border-[var(--color-accent)]/50"
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || isLoading}
            className="px-2.5 py-1 rounded-lg text-xs bg-[var(--color-accent)]/80 text-white backdrop-blur-sm hover:bg-[var(--color-accent)] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
            </svg>
          </button>
        </div>
      </div>
    );
  }
);
