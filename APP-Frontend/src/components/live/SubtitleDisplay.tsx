/**
 * SubtitleDisplay — 直播字幕显示组件（自包含，无管理布局依赖）。
 *
 * 职责：以打字机逐字效果展示 AI 回复字幕，可定位到底部/顶部/居中，
 * 支持最多行数、字体、颜色、背景、自动淡出。供直播分屏（live-overlay）
 * 与字幕源（subtitle-source）复用；配合透明背景可作为 OBS 浏览器源。
 *
 * 行为口径对齐 CX-O-Frontend components/Live/SubtitleDisplay.tsx。
 */
import { useEffect, useRef, useState } from 'react';
import type { CSSProperties } from 'react';

interface SubtitleDisplayProps {
  text: string;
  enabled?: boolean;
  position?: 'bottom' | 'top' | 'custom';
  maxLines?: number;
  fontSize?: number;
  fontFamily?: string;
  color?: string;
  background?: string;
  typingSpeed?: number;
  autoClear?: boolean;
  clearDelay?: number;
}

export function SubtitleDisplay({
  text,
  enabled = true,
  position = 'bottom',
  maxLines = 3,
  fontSize = 28,
  fontFamily = 'sans-serif',
  color = '#ffffff',
  background = 'rgba(0,0,0,0.6)',
  typingSpeed = 50,
  autoClear = true,
  clearDelay = 5000,
}: SubtitleDisplayProps) {
  const [displayedText, setDisplayedText] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [isVisible, setIsVisible] = useState(false);

  const rafRef = useRef<number>(0);
  const charIndexRef = useRef(0);
  const lastTimeRef = useRef(0);
  const textRef = useRef(text);
  const clearTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const typingConfigRef = useRef({ typingSpeed, autoClear, clearDelay });
  useEffect(() => {
    typingConfigRef.current = { typingSpeed, autoClear, clearDelay };
  }, [typingSpeed, autoClear, clearDelay]);

  useEffect(() => {
    if (rafRef.current) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = 0;
    }
    if (clearTimerRef.current) {
      clearTimeout(clearTimerRef.current);
      clearTimerRef.current = undefined;
    }

    if (!enabled) {
      setDisplayedText('');
      setIsTyping(false);
      setIsVisible(false);
      return;
    }

    textRef.current = text;
    if (!text) {
      setDisplayedText('');
      setIsTyping(false);
      setIsVisible(false);
      return;
    }

    charIndexRef.current = 0;
    setDisplayedText('');
    setIsTyping(true);
    setIsVisible(true);
    lastTimeRef.current = performance.now();

    const tick = (now: number) => {
      const {
        typingSpeed: speed,
        autoClear: shouldAutoClear,
        clearDelay: delay,
      } = typingConfigRef.current;
      const elapsed = now - lastTimeRef.current;
      if (elapsed >= speed) {
        const charsToAdd = Math.floor(elapsed / speed);
        const newIndex = Math.min(charIndexRef.current + charsToAdd, textRef.current.length);
        charIndexRef.current = newIndex;
        setDisplayedText(textRef.current.slice(0, newIndex));
        lastTimeRef.current = now - (elapsed % speed);

        if (newIndex >= textRef.current.length) {
          setIsTyping(false);
          if (shouldAutoClear && delay > 0) {
            clearTimerRef.current = setTimeout(() => {
              setIsVisible(false);
            }, delay);
          }
          return;
        }
      }
      rafRef.current = requestAnimationFrame(tick);
    };

    rafRef.current = requestAnimationFrame(tick);

    return () => {
      if (rafRef.current) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = 0;
      }
    };
  }, [text, enabled]);

  useEffect(() => {
    return () => {
      if (rafRef.current) {
        cancelAnimationFrame(rafRef.current);
      }
      if (clearTimerRef.current) {
        clearTimeout(clearTimerRef.current);
      }
    };
  }, []);

  const positionStyle: CSSProperties = (() => {
    switch (position) {
      case 'top':
        return { top: 40, bottom: 'auto' };
      case 'custom':
        return { top: '50%', transform: 'translateY(-50%)' };
      default:
        return { bottom: 40, top: 'auto' };
    }
  })();

  if (!enabled || !isVisible) return null;

  return (
    <div
      className="absolute left-0 right-0 flex justify-center px-4 transition-opacity duration-300"
      style={{ ...positionStyle, zIndex: 20, pointerEvents: 'none' }}
    >
      <div
        className="rounded-xl px-6 py-3"
        style={{
          backgroundColor: background,
          color,
          fontFamily,
          fontSize: `${fontSize}px`,
          lineHeight: 1.5,
          maxHeight: `${fontSize * 1.5 * maxLines + 24}px`,
          overflow: 'hidden',
          textShadow: '0 1px 3px rgba(0,0,0,0.4)',
        }}
      >
        <span>{displayedText}</span>
        {isTyping && (
          <span
            className="ml-1 inline-block h-[1em] w-[2px] align-middle animate-pulse"
            style={{ backgroundColor: color }}
          />
        )}
      </div>
    </div>
  );
}

export default SubtitleDisplay;
