import { useEffect, useRef } from 'react';

export interface HotkeyOptions {
  ctrl?: boolean;
  alt?: boolean;
  shift?: boolean;
  meta?: boolean;
  preventDefault?: boolean;
  stopPropagation?: boolean;
  enabled?: boolean;
}

function normalizeKey(key: string): string {
  const keyMap: Record<string, string> = {
    esc: 'Escape',
    enter: 'Enter',
    return: 'Enter',
    space: ' ',
    up: 'ArrowUp',
    down: 'ArrowDown',
    left: 'ArrowLeft',
    right: 'ArrowRight',
    del: 'Delete',
    backspace: 'Backspace',
    tab: 'Tab',
  };
  return keyMap[key.toLowerCase()] || key.toLowerCase();
}

function matchModifiers(event: KeyboardEvent, options: HotkeyOptions): boolean {
  const { ctrl = false, alt = false, shift = false, meta = false } = options;

  return (
    event.ctrlKey === ctrl &&
    event.altKey === alt &&
    event.shiftKey === shift &&
    event.metaKey === meta
  );
}

export function useHotkey(key: string, callback: () => void, options: HotkeyOptions = {}): void {
  const callbackRef = useRef(callback);
  const optionsRef = useRef(options);

  useEffect(() => {
    callbackRef.current = callback;
    optionsRef.current = options;
  }, [callback, options]);

  useEffect(() => {
    const normalizedKey = normalizeKey(key);

    const handleKeyDown = (event: KeyboardEvent) => {
      const opts = optionsRef.current;
      if (opts.enabled === false) return;

      if (normalizedKey === normalizeKey(event.key) && matchModifiers(event, opts)) {
        if (opts.preventDefault ?? true) {
          event.preventDefault();
        }
        if (opts.stopPropagation) {
          event.stopPropagation();
        }
        callbackRef.current();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [key]);
}
