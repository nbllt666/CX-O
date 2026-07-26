/**
 * @file language-switcher.tsx — LanguageSwitcher 业务组件重组（模块7）
 * ============================================================================
 * 模块: 模块7 业务组件重组层 — A 组系统类
 * 落点: C:\CX-O\CX-O-Frontend\src\components\business\language-switcher.tsx
 * 原组件: src/components/LanguageSwitcher.tsx
 *
 * 重组策略（MODULE-7 AGENTS.md §2.4）:
 *   - 保留现有业务逻辑（useTranslation / useState / useRef / useEffect / handleLanguageChange 不变）
 *   - UI 层换用模块6 ui-v2 基础组件（Button）
 *   - 注入 Liquid Glass + data-glass + motion variants（下拉菜单动画）
 *   - 通过 className 消费 token，不硬编码颜色
 *
 * 跨模块导入约束（rules-0 §四 + MODULE-7 AGENTS.md §2.3）:
 *   - 仅 import 模块6 ui-v2 公开产出
 *   - 仅 import 共享基础设施（@/i18n / @/lib/utils）
 *   - 禁止 import 模块8/9 内部实现
 * ============================================================================
 */

import { useTranslation } from 'react-i18next';
import { Globe } from 'lucide-react';
import { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence, type Variants } from 'framer-motion';
import { cn } from '@/lib/utils';
import { supportedLanguages, changeLanguage } from '@/i18n';
import { Button } from '@/components/ui-v2';
import {
  buildGlassDataAttributes,
  getComponentMotionVariants,
} from '@/components/ui-v2';

// 下拉菜单 motion variants（基于模块6 getComponentMotionVariants 工厂，snappy spring）
const dropdownVariants: Variants = getComponentMotionVariants({
  componentName: 'Button',
  springKey: 'snappy',
});

export function LanguageSwitcher() {
  const { i18n, t } = useTranslation();
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // 点击外部关闭下拉菜单
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleLanguageChange = async (langCode: string) => {
    await changeLanguage(langCode);
    setIsOpen(false);
  };

  const currentLang =
    supportedLanguages.find((l) => l.code === i18n.language) || supportedLanguages[0];

  const glassAttributes = buildGlassDataAttributes(true, 3);

  return (
    <div className="relative" ref={dropdownRef}>
      <Button
        variant="ghost"
        size="sm"
        title={t('settings.language')}
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-2"
      >
        <Globe className="w-4 h-4" />
        <span className="hidden sm:inline">
          {currentLang.flag} {currentLang.name}
        </span>
        <span className="sm:hidden">{currentLang.flag}</span>
      </Button>

      <AnimatePresence>
        {isOpen && (
          <motion.div
            variants={dropdownVariants}
            initial="initial"
            animate="animate"
            exit="exit"
            className={cn(
              'absolute right-0 mt-2 w-48 py-1 z-50',
              'bg-[var(--color-bg-primary)] rounded-[var(--radius-lg)]',
              'shadow-[var(--shadow-lg)] border border-[var(--color-border)]',
            )}
            {...glassAttributes}
          >
            {supportedLanguages.map((lang) => (
              <button
                key={lang.code}
                onClick={() => handleLanguageChange(lang.code)}
                className={cn(
                  'w-full flex items-center gap-3 px-4 py-2 text-sm text-left',
                  i18n.language === lang.code
                    ? 'bg-[var(--color-accent-light)] text-[var(--color-accent)]'
                    : 'text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text-primary)]',
                )}
              >
                <span className="text-lg">{lang.flag}</span>
                <span>{lang.name}</span>
                {i18n.language === lang.code && (
                  <svg
                    className="w-4 h-4 ml-auto text-[var(--color-accent)]"
                    fill="currentColor"
                    viewBox="0 0 20 20"
                  >
                    <path
                      fillRule="evenodd"
                      d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                      clipRule="evenodd"
                    />
                  </svg>
                )}
              </button>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
