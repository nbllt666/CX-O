/**
 * theme-provider.tsx — 主题上下文提供者（注入 <html data-theme> + Framer Motion 颜色过渡）
 * ============================================================================
 * 模块: 模块2 主题层
 * 契约: D3 theme.schema.json (switchAnimation) + I2 frontend_theme.pyi (ThemeProvider)
 * 上游: use-theme-store.ts (状态管理) + theme-crossfade.ts (crossfade + uniform 上传)
 *
 * 设计要点:
 *   - 包裹应用根节点，提供主题上下文给子组件消费
 *   - 内部调用 useThemeStore 管理状态，主题切换时触发 applyThemeChange
 *   - 300ms spring 颜色过渡：motion.div + themeColorTransition（Framer Motion 调度器）
 *   - 400ms 玻璃着色层 crossfade：applyThemeChange 内部 rAF 调度器（时序解耦）
 *   - disableTransition = true 时跳过过渡动画（D3 reducedMotionFallback instant-color-swap）
 *   - AnimatePresence mode='wait' variants 通过 themeEnterVariants 导出供子组件消费
 * ============================================================================
 */

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  type ReactNode,
} from 'react';
import { motion } from 'framer-motion';
import {
  useThemeStore,
  themeStore,
  type Theme,
  type ThemeState,
  type UseThemeStoreReturn,
} from './use-theme-store';
import {
  applyThemeChange,
  themeColorTransition,
  COLOR_TRANSITION_PROPERTIES,
  THEME_COLOR_TRANSITION_MS,
} from './theme-crossfade';

// ============================================================================
// 类型定义（I2 ThemeProviderProps）
// ============================================================================

/**
 * ThemeProvider 组件 props（I2 ThemeProviderProps）。
 */
export interface ThemeProviderProps {
  /** 默认主题（首次访问时使用） */
  defaultTheme: Theme;
  /** 子元素 */
  children: ReactNode;
  /** 是否禁用切换过渡动画（默认 false） */
  disableTransition?: boolean;
}

// ============================================================================
// 主题上下文
// ============================================================================

/** 主题上下文（提供 useThemeStore 返回值给子组件） */
const ThemeContext = createContext<UseThemeStoreReturn | null>(null);

// ============================================================================
// CSS 颜色过渡样式构建（300ms，镜像 --motion-bezier-ease-glass）
// ============================================================================

/**
 * 构建 CSS 颜色过渡字符串。
 * 使用 Module 1 primitive.css --motion-bezier-ease-glass: cubic-bezier(0.16, 1, 0.3, 1)
 * 近似 spring 物理曲线（CSS transition 不支持 spring physics，用 bezier 近似）。
 */
function buildColorTransitionStyle(disabled: boolean): string | undefined {
  if (disabled) return undefined;
  const easing = 'cubic-bezier(0.16, 1, 0.3, 1)'; // --motion-bezier-ease-glass
  const duration = `${THEME_COLOR_TRANSITION_MS}ms`;
  return COLOR_TRANSITION_PROPERTIES.map((prop) => {
    // camelCase → kebab-case (backgroundColor → background-color)
    const cssProp = prop.replace(/([A-Z])/g, '-$1').toLowerCase();
    return `${cssProp} ${duration} ${easing}`;
  }).join(', ');
}

// ============================================================================
// ThemeProvider 组件（I2 签名匹配）
// ============================================================================

/**
 * 组件: ThemeProvider — 主题上下文提供者（merged.md §1.3）。
 *
 * 包裹应用根节点，提供主题上下文给子组件消费。
 * 内部调用 useThemeStore 管理状态，并在主题切换时触发 applyThemeChange。
 *
 * 主题切换动效:
 *   - 300ms spring 颜色过渡: motion.div + themeColorTransition（Framer Motion 调度器）
 *   - 400ms 玻璃着色层 crossfade: applyThemeChange 内部 rAF（独立调度器，时序解耦）
 *
 * @param props - 组件 props（defaultTheme / children / disableTransition）
 * @returns 主题上下文 Provider 元素
 */
export function ThemeProvider({
  defaultTheme,
  children,
  disableTransition = false,
}: ThemeProviderProps): ReactNode {
  const { theme } = useThemeStore(defaultTheme);
  const previousThemeRef = useRef<Theme>(theme);
  const isInitialMount = useRef(true);

  // 主题变化时设置 data-theme + 触发 applyThemeChange
  useEffect(() => {
    if (isInitialMount.current) {
      // 首次挂载：直接设置 data-theme（bootstrap 可能已设置，此处确保一致）
      document.documentElement.setAttribute('data-theme', theme);
      isInitialMount.current = false;
      previousThemeRef.current = theme;
      return;
    }

    const fromTheme = previousThemeRef.current;
    if (fromTheme !== theme) {
      try {
        // 触发 crossfade + uniform 上传（applyThemeChange 内部设置 data-theme）
        applyThemeChange({
          fromTheme,
          toTheme: theme,
          disableTransition,
        });
      } catch {
        // 降级: 确保至少 data-theme 被设置（跳过过渡动画）
        document.documentElement.setAttribute('data-theme', theme);
      }
      previousThemeRef.current = theme;
    }
  }, [theme, disableTransition]);

  // 构建颜色过渡 CSS 样式（300ms，bezier 近似 spring）
  const colorTransitionStyle = buildColorTransitionStyle(disableTransition);

  // 上下文值（memoize，仅 theme 变化时重新计算）
  const contextValue = useMemo<UseThemeStoreReturn>(
    () => ({
      theme,
      getTheme: (): Theme => themeStore.getState().theme,
      setTheme: (newTheme: Theme): void => {
        themeStore.getState().setTheme(newTheme);
      },
      toggleTheme: (): void => {
        themeStore.getState().toggleTheme();
      },
      subscribe: (listener: (state: ThemeState) => void): (() => void) =>
        themeStore.subscribe((state) => listener(state)),
    }),
    [theme],
  );

  return (
    <ThemeContext.Provider value={contextValue}>
      <motion.div
        data-theme-provider=""
        transition={themeColorTransition}
        style={colorTransitionStyle ? { transition: colorTransitionStyle } : undefined}
      >
        {children}
      </motion.div>
    </ThemeContext.Provider>
  );
}

// ============================================================================
// useThemeContext Hook（子组件消费主题上下文）
// ============================================================================

/**
 * Hook: useThemeContext — 消费主题上下文。
 *
 * @returns 主题 store 返回值（theme / getTheme / setTheme / toggleTheme / subscribe）
 * @throws Error 如果在 ThemeProvider 外部调用
 */
export function useThemeContext(): UseThemeStoreReturn {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error('useThemeContext must be used within a ThemeProvider');
  }
  return context;
}
