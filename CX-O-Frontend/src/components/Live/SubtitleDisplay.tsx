import { useEffect, useRef, useCallback, useState } from 'react';

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
  const clearTimerRef = useRef<ReturnType<typeof setTimeout>>();

  const startTyping = useCallback(() => {
    charIndexRef.current = 0;
    setDisplayedText('');
    setIsTyping(true);
    setIsVisible(true);

    if (clearTimerRef.current) {
      clearTimeout(clearTimerRef.current);
    }

    lastTimeRef.current = performance.now();

    const tick = (now: number) => {
      const elapsed = now - lastTimeRef.current;
      if (elapsed >= typingSpeed) {
        const charsToAdd = Math.floor(elapsed / typingSpeed);
        const newIndex = Math.min(charIndexRef.current + charsToAdd, textRef.current.length);
        charIndexRef.current = newIndex;
        setDisplayedText(textRef.current.slice(0, newIndex));
        lastTimeRef.current = now - (elapsed % typingSpeed);

        if (newIndex >= textRef.current.length) {
          setIsTyping(false);
          if (autoClear && clearDelay > 0) {
            clearTimerRef.current = setTimeout(() => {
              setIsVisible(false);
            }, clearDelay);
          }
          return;
        }
      }
      rafRef.current = requestAnimationFrame(tick);
    };

    rafRef.current = requestAnimationFrame(tick);
  }, [typingSpeed, autoClear, clearDelay]);

  useEffect(() => {
    if (!enabled) {
      setDisplayedText('');
      setIsVisible(false);
      return;
    }

    if (text !== textRef.current) {
      textRef.current = text;
      if (rafRef.current) {
        cancelAnimationFrame(rafRef.current);
      }
      if (!text) {
        setDisplayedText('');
        setIsTyping(false);
        setIsVisible(false);
        return;
      }
      startTyping();
    }

    return () => {
      if (rafRef.current) {
        cancelAnimationFrame(rafRef.current);
      }
    };
  }, [text, enabled, startTyping]);

  useEffect(() => {
    return () => {
      if (clearTimerRef.current) {
        clearTimeout(clearTimerRef.current);
      }
    };
  }, []);

  const positionStyle = (() => {
    switch (position) {
      case 'top':
        return { top: 40, bottom: 'auto' as const };
      case 'custom':
        return { top: '50%', transform: 'translateY(-50%)' as const };
      default:
        return { bottom: 40, top: 'auto' as const };
    }
  })();

  if (!enabled || !isVisible) return null;

  return (
    <div
      className="absolute left-0 right-0 flex justify-center px-4 transition-opacity duration-300"
      style={{
        ...positionStyle,
        zIndex: 20,
        pointerEvents: 'none',
      }}
    >
      <div
        className="px-6 py-3 rounded-xl max-w-4xl transition-opacity duration-300"
        style={{
          backgroundColor: background,
          color,
          fontFamily,
          fontSize: `${fontSize}px`,
          lineHeight: 1.5,
          maxHeight: `${fontSize * 1.5 * maxLines + 24}px`,
          overflow: 'hidden',
          WebkitLineClamp: maxLines,
          display: '-webkitBox',
          WebkitBoxOrient: 'vertical',
          textShadow: '0 1px 3px rgba(0,0,0,0.4)',
        }}
      >
        <span>{displayedText}</span>
        {isTyping && (
          <span
            className="inline-block w-[2px] h-[1em] ml-1 align-middle animate-pulse"
            style={{ backgroundColor: color }}
          />
        )}
      </div>
    </div>
  );
}

export default SubtitleDisplay;
