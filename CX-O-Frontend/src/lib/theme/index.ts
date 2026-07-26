/**
 * index.ts — 模块2 主题层 统一导出入口
 * ============================================================================
 * 模块: 模块2 主题层
 * 落点: src/lib/theme/
 * 上游依赖: 模块1（Token 设计系统层，CSS 变量基础）
 * 下游被依赖: 模块4（玻璃层 uniform 分组）、模块6（基础组件双主题）
 *
 * 导出内容:
 *   - Theme 枚举/类型 + ThemeState + UseThemeStoreReturn（use-theme-store.ts）
 *   - useThemeStore hook + themeStore 实例 + ThemeStoreCorruptionError（FE-THE-005）
 *   - ThemeProvider 组件 + ThemeProviderProps + useThemeContext（theme-provider.tsx）
 *   - ThemeBootstrap 函数 + BootstrapInjectionError（FE-THE-001）（theme-bootstrap.ts）
 *   - applyThemeChange + uploadGlassUniforms + validateWCAGAA（theme-crossfade.ts）
 *   - ThemeTransitionError（FE-THE-002）+ UniformUploadError（FE-THE-003）+ ContrastCheckError（FE-THE-004）
 *   - UniformGroup + ValidationReport 类型
 *   - DEFAULT_UNIFORM_GROUP + Framer Motion 配置 + 常量
 *   - registerGLContext / unregisterGLContext（GL 上下文注册）
 * ============================================================================
 */

// ============================================================================
// use-theme-store.ts 导出
// ============================================================================

export {
  Theme,
  useThemeStore,
  themeStore,
} from './use-theme-store';

export type {
  ThemeState,
  UseThemeStoreReturn,
} from './use-theme-store';

export { ThemeStoreCorruptionError } from './use-theme-store';

// ============================================================================
// theme-provider.tsx 导出
// ============================================================================

export {
  ThemeProvider,
  useThemeContext,
} from './theme-provider';

export type { ThemeProviderProps } from './theme-provider';

// ============================================================================
// theme-bootstrap.ts 导出
// ============================================================================

export {
  ThemeBootstrap,
  getBootstrapScriptContent,
  validateBootstrapInjection,
  BOOTSTRAP_SIZE_BUDGET,
  BOOTSTRAP_STORAGE_KEY,
} from './theme-bootstrap';

export type { ThemeBootstrapOptions } from './theme-bootstrap';

export { BootstrapInjectionError } from './theme-bootstrap';

// ============================================================================
// theme-crossfade.ts 导出
// ============================================================================

export {
  // 函数
  applyThemeChange,
  uploadGlassUniforms,
  validateWCAGAA,
  registerGLContext,
  unregisterGLContext,
  // Framer Motion 配置
  themeColorTransition,
  themeEnterVariants,
  COLOR_TRANSITION_PROPERTIES,
  // 常量
  DEFAULT_UNIFORM_GROUP,
  THEME_COLOR_TRANSITION_MS,
  THEME_GLASS_CROSSFADE_MS,
  WCAG_AA_NORMAL_THRESHOLD,
  WCAG_AA_LARGE_THRESHOLD,
} from './theme-crossfade';

export type {
  UniformGroup,
  ValidationReport,
  ApplyThemeChangeOptions,
  ValidateWCAGAAOptions,
} from './theme-crossfade';

export {
  ThemeTransitionError,
  UniformUploadError,
  ContrastCheckError,
} from './theme-crossfade';
