import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';

import zhCN from './locales/zh-CN.json';
import enUS from './locales/en-US.json';

/**
 * i18n 入口：词条外置 locales/*.json，按模块扩充。
 *
 * 语言策略（2026-08 调整为中文优先）：
 * - 仅信任用户**显式**选择并持久化的语言（localStorage `cxo-pet-lang`）。
 * - 未显式选择过（首启 / 缓存清除）时**一律默认中文 zh-CN**，
 *   不再跟随 navigator/系统语言——避免英文系统下意外展示英文。
 * - 手动切换（顶栏 toggleLanguage）会写回 localStorage 并持久化，重启后保持。
 *
 * 注：不依赖 i18next-browser-languagedetector（它会让语言跟随浏览器/系统环境），
 * 语言完全由本模块显式管理，保证中文优先、行为可预期。
 */
const LANGUAGE_STORAGE_KEY = 'cxo-pet-lang';

function readStoredLanguage(): string {
  try {
    const stored = localStorage.getItem(LANGUAGE_STORAGE_KEY);
    if (stored === 'zh-CN' || stored === 'en-US') return stored;
    // 未显式选择过 → 默认中文
    return 'zh-CN';
  } catch {
    return 'zh-CN';
  }
}

function persistLanguage(lng: string): void {
  try {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, lng);
  } catch {
    /* storage 不可用时静默 */
  }
}

void i18n.use(initReactI18next).init({
  resources: {
    'zh-CN': { translation: zhCN },
    'en-US': { translation: enUS },
  },
  lng: readStoredLanguage(),
  // 目标语言缺省/异常时回退中文，绝不在未显式选择时切到英文
  fallbackLng: 'zh-CN',
  interpolation: { escapeValue: false },
});

export default i18n;

export const supportedLanguages = [
  { code: 'zh-CN', name: '简体中文' },
  { code: 'en-US', name: 'English' },
] as const;

/** 切换语言并持久化（用户显式选择后才改变，重启保持）。 */
export const changeLanguage = (lng: string) => {
  persistLanguage(lng);
  return i18n.changeLanguage(lng);
};

export const getCurrentLanguage = () => i18n.language;
