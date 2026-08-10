import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import LanguageDetector from 'i18next-browser-languagedetector';

import zhCN from './locales/zh-CN.json';
import enUS from './locales/en-US.json';

/**
 * i18n 入口：词条外置 locales/*.json，按模块扩充。
 * 语言检测顺序 localStorage(cxo-pet-lang) → navigator → htmlTag，
 * 选择结果回写 localStorage，重启后保持。
 */
void i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      'zh-CN': { translation: zhCN },
      'en-US': { translation: enUS },
    },
    fallbackLng: { en: ['en-US'], default: ['zh-CN'] },
    interpolation: { escapeValue: false },
    detection: {
      order: ['localStorage', 'navigator', 'htmlTag'],
      caches: ['localStorage'],
      lookupLocalStorage: 'cxo-pet-lang',
    },
  });

export default i18n;

export const supportedLanguages = [
  { code: 'zh-CN', name: '简体中文' },
  { code: 'en-US', name: 'English' },
] as const;

export const changeLanguage = (lng: string) => i18n.changeLanguage(lng);

export const getCurrentLanguage = () => i18n.language;
