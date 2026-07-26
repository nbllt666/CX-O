/**
 * use-theme-store.ts — 主题状态管理（Zustand store + localStorage 持久化）
 * ============================================================================
 * 模块: 模块2 主题层
 * 契约: D3 theme.schema.json (stateManagement) + I2 frontend_theme.pyi (useThemeStore)
 * 上游: 模块1 token CSS 变量基础（dark-theme.css / light-theme.css）
 * 版本: 1.0.0
 *
 * 设计要点:
 *   - Zustand create + persist 中间件，storage key 固定为 'cx-o-theme'（D3 bootstrap.localStorageKey）
 *   - 序列化策略: json-only-current（D3 persistence.serialize）—— 仅持久化 theme 字段
 *   - 不硬编码主题名: 主题值通过 Theme 类型约束，storage key / default 通过常量定义
 *   - ThemeStoreCorruptionError (FE-THE-005): 反序列化失败 / 状态结构不合法 / 版本不匹配时抛出
 *   - Electron 兼容: 使用 createStorage() 适配器（复用项目既有模式）
 * ============================================================================
 */

import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { createStorage } from '../createStorage';

// ============================================================================
// 常量定义（配置驱动，不硬编码）
// ============================================================================

/** localStorage 持久化 key（D3 bootstrap.localStorageKey + persistence.key，固定值） */
const STORAGE_KEY = 'cx-o-theme';

/** 默认主题（D3 bootstrap.fallbackTheme = 'dark'） */
const DEFAULT_THEME = 'dark' as const;

/** 持久化数据版本（I2 ThemeState.version，用于迁移） */
const STATE_VERSION = 1;

// ============================================================================
// Theme 枚举（I2 Theme str Enum）
// ============================================================================

/**
 * 主题枚举（merged.md §1.3）。
 * DARK: 暗色主题（夜空深紫背景 #2D1B4E）
 * LIGHT: 亮色主题（晨曦米白背景 #FAF6F0）
 */
export const Theme = {
  DARK: 'dark',
  LIGHT: 'light',
} as const;

/** 主题类型（'dark' | 'light'） */
export type Theme = (typeof Theme)[keyof typeof Theme];

// ============================================================================
// 类型定义（I2 TypedDict 对应）
// ============================================================================

/**
 * Zustand store 状态结构（I2 ThemeState）。
 * 持久化到 localStorage，主题应用通过 <html data-theme="dark|light"> 属性 + CSS 变量重定义。
 */
export interface ThemeState {
  /** 当前主题（用户偏好） */
  theme: Theme;
  /** 默认主题（用于 store 损坏时重置） */
  defaultTheme: Theme;
  /** 持久化数据版本（用于迁移） */
  version: number;
}

/**
 * useThemeStore 返回值（I2 UseThemeStoreReturn）。
 */
export interface UseThemeStoreReturn {
  /** 当前主题 */
  theme: Theme;
  /** 获取当前主题 */
  getTheme: () => Theme;
  /** 设置主题（触发 crossfade + uniform 上传，由 ThemeProvider 编排） */
  setTheme: (theme: Theme) => void;
  /** 切换主题（dark <-> light） */
  toggleTheme: () => void;
  /** 订阅 store 变化，返回取消订阅函数 */
  subscribe: (listener: (state: ThemeState) => void) => () => void;
}

// ============================================================================
// 异常定义（I2 异常契约，FE-THE-005）
// ============================================================================

/**
 * 主题 store 状态损坏异常（I2 ThemeStoreCorruptionError）。
 *
 * 抛出条件: useThemeStore 读取 localStorage 时反序列化失败，或 store 状态结构不符合
 *   ThemeState schema，或持久化数据版本不匹配（版本迁移失败）。
 * 调用方处理: 捕获后重置 store 到默认状态（defaultTheme），清除损坏的 localStorage
 *   数据，上报错误码 FE-THE-005（对应 E1 主题 store 损坏，severity=fatal）。
 */
export class ThemeStoreCorruptionError extends Error {
  readonly errorCode: 'FE-THE-005';
  readonly fallbackTheme: Theme;

  constructor(message: string, fallbackTheme: Theme = DEFAULT_THEME) {
    super(message);
    this.name = 'ThemeStoreCorruptionError';
    this.errorCode = 'FE-THE-005';
    this.fallbackTheme = fallbackTheme;
    Object.setPrototypeOf(this, ThemeStoreCorruptionError.prototype);
  }
}

// ============================================================================
// 内部 store 接口（含 actions）
// ============================================================================

interface ThemeStoreInternal extends ThemeState {
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
}

// ============================================================================
// 校验工具
// ============================================================================

/** 校验值是否为合法 Theme */
function isValidTheme(value: unknown): value is Theme {
  return value === Theme.DARK || value === Theme.LIGHT;
}

// ============================================================================
// Zustand store 创建（模块级单例 + persist 中间件）
// ============================================================================

const store = create<ThemeStoreInternal>()(
  persist(
    (set, get) => ({
      theme: DEFAULT_THEME,
      defaultTheme: DEFAULT_THEME,
      version: STATE_VERSION,

      setTheme: (theme: Theme): void => {
        if (!isValidTheme(theme)) {
          throw new ThemeStoreCorruptionError(
            `Invalid theme value: ${String(theme)}`,
            get().defaultTheme,
          );
        }
        set({ theme });
      },

      toggleTheme: (): void => {
        const current = get().theme;
        const next: Theme = current === Theme.DARK ? Theme.LIGHT : Theme.DARK;
        set({ theme: next });
      },
    }),
    {
      name: STORAGE_KEY,
      storage: createStorage(),
      // D3 persistence.serialize = 'json-only-current'：仅持久化 theme 字段
      // defaultTheme / version 由初始状态提供，不持久化（运行时常量）
      partialize: (state): Pick<ThemeState, 'theme'> => ({
        theme: state.theme,
      }),
      version: STATE_VERSION,
      // D3 persistence.hydrateTiming = 'immediate-on-store-create'
      // hydrate 在 store 创建时立即执行（zustand persist 默认行为）
      onRehydrateStorage: () => (state: ThemeStoreInternal | undefined, error?: unknown): void => {
        if (error) {
          // 反序列化失败 → 抛出 ThemeStoreCorruptionError（FE-THE-005）
          throw new ThemeStoreCorruptionError(
            `Failed to rehydrate theme store: ${error instanceof Error ? error.message : String(error)}`,
            DEFAULT_THEME,
          );
        }
        if (state && !isValidTheme(state.theme)) {
          // 状态结构不合法 → 抛出 ThemeStoreCorruptionError（FE-THE-005）
          throw new ThemeStoreCorruptionError(
            `Corrupted theme value in storage: ${String(state.theme)}`,
            state.defaultTheme ?? DEFAULT_THEME,
          );
        }
      },
    },
  ),
);

// ============================================================================
// useThemeStore Hook（I2 签名匹配）
// ============================================================================

/**
 * Hook: useThemeStore — 主题状态管理（Zustand store, merged.md §1.3）。
 *
 * 主题状态由 Zustand store 管理，持久化到 localStorage（key: 'cx-o-theme'）。
 * 主题应用通过 <html data-theme="dark|light"> 属性 + CSS 变量重定义。
 *
 * @param defaultTheme - 默认主题（首次访问或 store 损坏时使用）。默认 Theme.DARK。
 * @returns 含 theme / getTheme / setTheme / toggleTheme / subscribe。
 * @throws ThemeStoreCorruptionError 读取 localStorage 时反序列化失败或状态结构不符合 schema。
 */
export function useThemeStore(defaultTheme: Theme = Theme.DARK): UseThemeStoreReturn {
  const theme = store((s) => s.theme);

  const getTheme = (): Theme => {
    const state = store.getState();
    return isValidTheme(state.theme) ? state.theme : defaultTheme;
  };

  const setTheme = (newTheme: Theme): void => {
    store.getState().setTheme(newTheme);
  };

  const toggleTheme = (): void => {
    store.getState().toggleTheme();
  };

  const subscribe = (listener: (state: ThemeState) => void): (() => void) => {
    return store.subscribe((state) => listener(state));
  };

  return { theme, getTheme, setTheme, toggleTheme, subscribe };
}

// ============================================================================
// 模块级导出：store 实例（供 ThemeProvider 直接订阅）
// ============================================================================

/** 模块级 store 实例（ThemeProvider 通过此引用订阅状态变化） */
export const themeStore = store;
