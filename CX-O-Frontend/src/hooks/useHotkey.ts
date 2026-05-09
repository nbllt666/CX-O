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

export interface HotkeyConfig extends HotkeyOptions {
  key: string;
  callback: () => void;
  description?: string;
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
    const { enabled = true, preventDefault = true, stopPropagation = false } = optionsRef.current;

    if (!enabled) return;

    const normalizedKey = normalizeKey(key);

    const handleKeyDown = (event: KeyboardEvent) => {
      if (normalizedKey === normalizeKey(event.key) && matchModifiers(event, optionsRef.current)) {
        if (preventDefault) {
          event.preventDefault();
        }
        if (stopPropagation) {
          event.stopPropagation();
        }
        callbackRef.current();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [key]);
}

export function useHotkeys(hotkeys: HotkeyConfig[]): void {
  const hotkeysRef = useRef(hotkeys);

  useEffect(() => {
    hotkeysRef.current = hotkeys;
  }, [hotkeys]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      for (const config of hotkeysRef.current) {
        const {
          key,
          callback,
          enabled = true,
          preventDefault = true,
          stopPropagation = false,
          ctrl = false,
          alt = false,
          shift = false,
          meta = false,
        } = config;

        if (!enabled) continue;

        const normalizedKey = normalizeKey(key);

        if (
          normalizedKey === normalizeKey(event.key) &&
          event.ctrlKey === ctrl &&
          event.altKey === alt &&
          event.shiftKey === shift &&
          event.metaKey === meta
        ) {
          if (preventDefault) {
            event.preventDefault();
          }
          if (stopPropagation) {
            event.stopPropagation();
          }
          callback();
          break;
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);
}

export function formatHotkey(config: HotkeyOptions & { key: string }): string {
  const parts: string[] = [];

  if (config.ctrl) parts.push('Ctrl');
  if (config.alt) parts.push('Alt');
  if (config.shift) parts.push('Shift');
  if (config.meta) parts.push('⌘');

  parts.push(config.key.toUpperCase());

  return parts.join('+');
}

export const commonHotkeys = {
  search: { key: 'k', ctrl: true, description: '搜索' },
  newChat: { key: 'n', ctrl: true, description: '新建对话' },
  save: { key: 's', ctrl: true, description: '保存' },
  close: { key: 'Escape', description: '关闭/取消' },
  confirm: { key: 'Enter', description: '确认' },
  theme: { key: 'd', ctrl: true, shift: true, description: '切换主题' },
  help: { key: '/', ctrl: true, description: '显示帮助' },
};
