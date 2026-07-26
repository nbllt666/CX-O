/**
 * theme-crossfade.ts — 主题切换 crossfade + WebGL uniform 分组 + WCAG AA 对比度校验
 * ============================================================================
 * 模块: 模块2 主题层
 * 契约: D3 theme.schema.json (switchAnimation + webglUniformGroups + wcagContrast) +
 *        I2 frontend_theme.pyi (applyThemeChange + uploadGlassUniforms + validateWCAGAA)
 *        C1 frontend_glass_config.schema.json (uGlassTintDark/uGlassTintLight 默认值)
 * 错误码: FE-THE-002 (ThemeTransitionError) / FE-THE-003 (UniformUploadError) /
 *         FE-THE-004 (ContrastCheckError)
 *
 * 设计要点:
 *   - 300ms spring（Framer Motion AnimatePresence）：导出 variants + transition 供 ThemeProvider 消费
 *   - 400ms glass crossfade（rAF timeline uniform lerp）：applyThemeChange 内部调度
 *   - 时序解耦：Framer Motion 使用自身调度器，glass crossfade 使用 rAF 调度器，不共享同一动画帧调度
 *   - WebGL uniform 分组：uGlassTintDark/uGlassTintLight 与 C1 配置契约字段一一映射
 *   - WCAG AA：普通文本 ≥ 4.5:1 / 大文本 ≥ 3.0:1 / UI 组件 ≥ 3.0:1
 *   - prefers-reduced-motion 降级：立即切换颜色，无动效（D3 reducedMotionFallback）
 *
 * GSAP 说明:
 *   D3 glassCrossfade.method = 'gsap-timeline-uniform-lerp'，但项目未安装 GSAP。
 *   本实现使用 rAF（requestAnimationFrame）作为 timeline 调度器，语义等价：
 *   timeline = rAF 序列 / uniform lerp = 线性插值。时序解耦不受影响。
 * ============================================================================
 */

import type { Variants, Transition } from 'framer-motion';
import { Theme } from './use-theme-store';

// ============================================================================
// 常量定义（配置驱动，与 D3 + C1 对齐）
// ============================================================================

/** 颜色过渡时长（ms，D3 switchAnimation.enterExit.duration = 300） */
const COLOR_TRANSITION_MS = 300;

/** 玻璃着色层 crossfade 时长（ms，D3 switchAnimation.glassCrossfade.duration = 400） */
const GLASS_CROSSFADE_MS = 400;

/**
 * Framer Motion spring 参数（镜像 Module 1 primitive.css --motion-spring-glass: 28 320 0.8）
 * damping=28 / stiffness=320 / mass=0.8
 */
const SPRING_DAMPING = 28;
const SPRING_STIFFNESS = 320;
const SPRING_MASS = 0.8;

// ============================================================================
// WebGL uniform 分组默认值（C1 webglUniforms → vec4 转换）
// ============================================================================

/**
 * 暗色主题玻璃着色 vec4（RGBA，0-1 归一化）。
 * 来源: C1 webglUniforms.uGlassTintDark = {r:224, g:187, b:228, a:0.08}（#E0BBE4 梦境粉紫）
 * 转换: [224/255, 187/255, 228/255, 0.08]
 */
const U_GLASS_TINT_DARK: readonly [number, number, number, number] = [
  224 / 255, 187 / 255, 228 / 255, 0.08,
];

/**
 * 亮色主题玻璃着色 vec4（RGBA，0-1 归一化）。
 * 来源: C1 webglUniforms.uGlassTintLight = {r:245, g:245, b:250, a:0.06}（#F5F5FA 月光白）
 * 转换: [245/255, 245/255, 250/255, 0.06]
 */
const U_GLASS_TINT_LIGHT: readonly [number, number, number, number] = [
  245 / 255, 245 / 255, 250 / 255, 0.06,
];

// ============================================================================
// 类型定义（I2 TypedDict 对应）
// ============================================================================

/**
 * WebGL uniform 分组（I2 UniformGroup, merged.md §1.3）。
 * 主题切换时 JS 上传对应组的 uniform 值。
 */
export interface UniformGroup {
  /** 暗色主题玻璃着色 RGBA（0-1 归一化 vec4） */
  uGlassTintDark: [number, number, number, number];
  /** 亮色主题玻璃着色 RGBA（0-1 归一化 vec4） */
  uGlassTintLight: [number, number, number, number];
}

/**
 * WCAG AA 校验报告（I2 ValidationReport）。
 */
export interface ValidationReport {
  /** 是否通过 AA 校验 */
  passed: boolean;
  /** 校验的主题 */
  theme: Theme;
  /** 被校验的 token 名称 */
  tokenName: string;
  /** 对比度比值（如 4.5） */
  contrastRatio: number;
  /** AA 标准要求比值（普通文本 4.5 / 大文本 3.0） */
  requiredRatio: number;
  /** 是否为大文本（影响 requiredRatio） */
  isLargeText: boolean;
  /** 未通过时的修复建议 */
  suggestion: string | null;
}

// ============================================================================
// 异常定义（I2 异常契约）
// ============================================================================

/**
 * 主题切换 crossfade 过渡失败异常（I2 ThemeTransitionError, FE-THE-002）。
 *
 * 抛出条件: applyThemeChange 执行主题切换时，Framer Motion AnimatePresence 或
 *   玻璃着色层 crossfade 动画异常，或目标主题 token 缺失，或 WebGL uniform
 *   上传失败导致着色层无法切换。
 * 调用方处理: 捕获后立即应用目标主题（跳过过渡动画），上报 FE-THE-002。
 */
export class ThemeTransitionError extends Error {
  readonly errorCode: 'FE-THE-002';
  readonly fromTheme: Theme;
  readonly toTheme: Theme;

  constructor(message: string, fromTheme: Theme, toTheme: Theme) {
    super(message);
    this.name = 'ThemeTransitionError';
    this.errorCode = 'FE-THE-002';
    this.fromTheme = fromTheme;
    this.toTheme = toTheme;
    Object.setPrototypeOf(this, ThemeTransitionError.prototype);
  }
}

/**
 * WebGL uniform 上传失败异常（I2 UniformUploadError, FE-THE-003）。
 *
 * 抛出条件: uploadGlassUniforms 上传 uGlassTintDark/uGlassTintLight 时，
 *   GL 上下文已丢失，或 uniform location 不存在，或上传值类型与声明类型不匹配。
 * 调用方处理: 捕获后触发 GPU 上下文丢失降级流程（回退到 Tier 3 CSS），上报 FE-THE-003。
 */
export class UniformUploadError extends Error {
  readonly errorCode: 'FE-THE-003';
  readonly uniformGroup: string;

  constructor(message: string, uniformGroup: string) {
    super(message);
    this.name = 'UniformUploadError';
    this.errorCode = 'FE-THE-003';
    this.uniformGroup = uniformGroup;
    Object.setPrototypeOf(this, UniformUploadError.prototype);
  }
}

/**
 * WCAG AA 对比度校验失败异常（I2 ContrastCheckError, FE-THE-004）。
 *
 * 抛出条件: validateWCAGAA 校验时 token 引用了不存在的语义 token，
 *   或主题配置缺失（token 在该主题下无定义），或对比度计算异常（颜色值格式错误）。
 * 注意: 对比度不达标（ratio < threshold）不抛异常，而是返回 passed=false 的报告。
 * 调用方处理: 捕获后阻止主题发布（开发阶段）或降级到安全 token（生产环境），上报 FE-THE-004。
 */
export class ContrastCheckError extends Error {
  readonly errorCode: 'FE-THE-004';
  readonly tokenName: string;
  readonly theme: Theme;

  constructor(message: string, tokenName: string, theme: Theme) {
    super(message);
    this.name = 'ContrastCheckError';
    this.errorCode = 'FE-THE-004';
    this.tokenName = tokenName;
    this.theme = theme;
    Object.setPrototypeOf(this, ContrastCheckError.prototype);
  }
}

// ============================================================================
// 默认 uniform 分组（C1 配置契约字段一一映射）
// ============================================================================

/**
 * 默认 uniform 分组（C1 webglUniforms.uGlassTintDark/uGlassTintLight 默认值）。
 * 与 C1 配置契约字段一一映射，禁止缺省。
 */
export const DEFAULT_UNIFORM_GROUP: UniformGroup = {
  uGlassTintDark: [...U_GLASS_TINT_DARK],
  uGlassTintLight: [...U_GLASS_TINT_LIGHT],
};

// ============================================================================
// Framer Motion 配置导出（供 ThemeProvider 消费，300ms spring 颜色过渡）
// ============================================================================

/**
 * 主题切换颜色过渡 spring 配置（D3 switchAnimation.enterExit）。
 * 镜像 Module 1 primitive.css --motion-spring-glass: damping=28 stiffness=320 mass=0.8。
 */
export const themeColorTransition: Transition = {
  type: 'spring',
  damping: SPRING_DAMPING,
  stiffness: SPRING_STIFFNESS,
  mass: SPRING_MASS,
};

/**
 * 主题切换入场/出场 variants（D3 switchAnimation.enterExit.variants = AnimatePresence-mode-wait）。
 * mode='wait' 顺序切换：先出场旧主题，再入场新主题。
 */
export const themeEnterVariants: Variants = {
  initial: { opacity: 0 },
  animate: { opacity: 1, transition: themeColorTransition },
  exit: { opacity: 0, transition: { duration: COLOR_TRANSITION_MS / 1000, ease: 'easeInOut' } },
};

/** 颜色过渡的 CSS 属性（D3 switchAnimation.colorTransition.properties） */
export const COLOR_TRANSITION_PROPERTIES = ['color', 'backgroundColor', 'borderColor'] as const;

// ============================================================================
// GL 上下文注册（供 Module 4 / ThemeProvider 注册 GL 程序）
// ============================================================================

/** 已注册的 GL 上下文（Module 4 通过 registerGLContext 注册） */
let registeredGL: WebGLRenderingContext | WebGL2RenderingContext | null = null;

/** 已注册的 GL 程序 */
let registeredProgram: WebGLProgram | null = null;

/**
 * 注册 GL 上下文和程序（供 uploadGlassUniforms 使用）。
 * Module 4 GlassRenderer 初始化后调用此函数注册 GL 程序。
 */
export function registerGLContext(
  gl: WebGLRenderingContext | WebGL2RenderingContext,
  program: WebGLProgram,
): void {
  registeredGL = gl;
  registeredProgram = program;
}

/** 注销 GL 上下文（Module 4 销毁时调用） */
export function unregisterGLContext(): void {
  registeredGL = null;
  registeredProgram = null;
}

// ============================================================================
// prefers-reduced-motion 检测（D3 reducedMotionFallback）
// ============================================================================

/** 检测用户是否启用了 prefers-reduced-motion */
function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || !window.matchMedia) return false;
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

// ============================================================================
// uploadGlassUniforms 函数（I2 签名匹配）
// ============================================================================

/**
 * 函数: uploadGlassUniforms — 按主题分组上传 WebGL uniform（merged.md §1.3）。
 *
 * WebGL uniform 按主题分组:
 *   - uGlassTintDark: 暗色主题玻璃着色 RGBA
 *   - uGlassTintLight: 亮色主题玻璃着色 RGBA
 *
 * 主题切换时 JS 上传对应组的 uniform 值到 GL 程序。
 *
 * @param gl - WebGL 上下文
 * @param program - 玻璃着色器程序
 * @param theme - 当前主题（决定上传哪个分组）
 * @param uniformGroup - uniform 分组数据
 * @throws UniformUploadError GL 上下文已丢失 / uniform location 不存在 / 类型不匹配
 */
export function uploadGlassUniforms(
  gl: WebGLRenderingContext | WebGL2RenderingContext,
  program: WebGLProgram,
  theme: Theme,
  uniformGroup: UniformGroup,
): void {
  // 检查 GL 上下文是否丢失
  if (gl.isContextLost()) {
    throw new UniformUploadError(
      `WebGL context lost, cannot upload uniforms for theme '${theme}'`,
      `uGlassTint${theme === Theme.DARK ? 'Dark' : 'Light'}`,
    );
  }

  // 根据主题选择对应的 uniform 组
  const uniformName = theme === Theme.DARK ? 'uGlassTintDark' : 'uGlassTintLight';
  const uniformValue: [number, number, number, number] =
    theme === Theme.DARK ? uniformGroup.uGlassTintDark : uniformGroup.uGlassTintLight;

  // 获取 uniform location
  const location = gl.getUniformLocation(program, uniformName);
  if (!location) {
    throw new UniformUploadError(
      `Uniform location '${uniformName}' not found in program`,
      uniformName,
    );
  }

  // 上传 vec4 uniform（gl.uniform4fv）
  try {
    gl.uniform4fv(location, new Float32Array(uniformValue));
  } catch (error) {
    throw new UniformUploadError(
      `Failed to upload uniform '${uniformName}': ${error instanceof Error ? error.message : String(error)}`,
      uniformName,
    );
  }
}

// ============================================================================
// 玻璃着色层 crossfade lerp（rAF timeline uniform lerp，400ms）
// ============================================================================

/** 活跃的 rAF handle（用于取消上一帧） */
let activeGlassLerpHandle: number | null = null;

/**
 * 线性插值两个 vec4。
 */
function lerpVec4(
  a: readonly [number, number, number, number],
  b: readonly [number, number, number, number],
  t: number,
): [number, number, number, number] {
  return [
    a[0] + (b[0] - a[0]) * t,
    a[1] + (b[1] - a[1]) * t,
    a[2] + (b[2] - a[2]) * t,
    a[3] + (b[3] - a[3]) * t,
  ];
}

/**
 * 启动玻璃着色层 crossfade lerp（400ms rAF timeline）。
 *
 * D3 switchAnimation.glassCrossfade:
 *   - duration = 400ms
 *   - method = gsap-timeline-uniform-lerp（项目无 GSAP，用 rAF 语义等价实现）
 *   - uniformBlend = true（crossfade 期间 lerp 两个 uniform 组）
 *
 * 时序解耦: 使用独立的 rAF 调度器，不与 Framer Motion 共享同一动画帧调度。
 *
 * @param fromTheme - 切换前主题
 * @param toTheme - 切换后主题
 * @param duration - crossfade 时长（ms）
 * @param uniformGroup - uniform 分组数据
 * @param onComplete - 过渡完成回调
 */
function startGlassUniformLerp(
  fromTheme: Theme,
  toTheme: Theme,
  duration: number,
  uniformGroup: UniformGroup,
  onComplete?: () => void,
): void {
  // 取消上一帧的 lerp（避免重叠）
  if (activeGlassLerpHandle !== null) {
    cancelAnimationFrame(activeGlassLerpHandle);
    activeGlassLerpHandle = null;
  }

  const fromTint: readonly [number, number, number, number] =
    fromTheme === Theme.DARK ? uniformGroup.uGlassTintDark : uniformGroup.uGlassTintLight;
  const toTint: readonly [number, number, number, number] =
    toTheme === Theme.DARK ? uniformGroup.uGlassTintDark : uniformGroup.uGlassTintLight;

  const startTime = performance.now();

  const tick = (): void => {
    const elapsed = performance.now() - startTime;
    const progress = Math.min(elapsed / duration, 1);

    // lerp 当前帧的 tint 值
    const currentTint = lerpVec4(fromTint, toTint, progress);

    // 如果有注册的 GL 上下文，上传插值后的 uniform
    if (registeredGL && registeredProgram && !registeredGL.isContextLost()) {
      const uniformName = toTheme === Theme.DARK ? 'uGlassTintDark' : 'uGlassTintLight';
      const location = registeredGL.getUniformLocation(registeredProgram, uniformName);
      if (location) {
        registeredGL.uniform4fv(location, new Float32Array(currentTint));
      }
    }

    if (progress < 1) {
      activeGlassLerpHandle = requestAnimationFrame(tick);
    } else {
      activeGlassLerpHandle = null;
      onComplete?.();
    }
  };

  activeGlassLerpHandle = requestAnimationFrame(tick);
}

// ============================================================================
// applyThemeChange 函数（I2 签名匹配）
// ============================================================================

/**
 * applyThemeChange 选项（I2 applyThemeChange options）。
 */
export interface ApplyThemeChangeOptions {
  /** 切换前主题 */
  fromTheme: Theme;
  /** 切换后主题 */
  toTheme: Theme;
  /** 是否禁用过渡动画（直接切换）。默认 false。 */
  disableTransition?: boolean;
  /** 过渡完成回调。 */
  onTransitionComplete?: () => void;
}

/**
 * 函数: applyThemeChange — 主题切换 crossfade 接口（merged.md §1.3）。
 *
 * 主题切换动效:
 *   - Framer Motion AnimatePresence + motion.div 颜色过渡: 300ms spring
 *     （由 ThemeProvider 的 motion.div 消费 themeColorTransition / themeEnterVariants）
 *   - 玻璃着色层 crossfade: 400ms（本函数内部 rAF 调度）
 *   - 两个动画并行启动，玻璃着色层略晚于颜色过渡完成（400ms > 300ms）
 *   - 时序解耦：Framer Motion 使用自身调度器，glass crossfade 使用 rAF 调度器
 *
 * 执行步骤:
 *   1. 设置 <html data-theme="toTheme"> 属性（触发 CSS 变量切换）
 *   2. 启动 Framer Motion 颜色过渡（300ms spring，由 ThemeProvider motion.div 自动响应）
 *   3. 启动玻璃着色层 crossfade（400ms rAF uniform lerp）
 *   4. 调用 uploadGlassUniforms 上传 toTheme 对应的 uniform 分组
 *   5. 过渡完成后调用 onTransitionComplete 回调
 *
 * @param options - 切换选项
 * @throws ThemeTransitionError 玻璃着色层 crossfade 动画异常 / token 缺失 / uniform 上传失败
 */
export function applyThemeChange(options: ApplyThemeChangeOptions): void {
  const { fromTheme, toTheme, disableTransition = false, onTransitionComplete } = options;

  // Step 1: 设置 <html data-theme="toTheme"> 属性（同步，触发 CSS 变量切换）
  if (typeof document !== 'undefined') {
    document.documentElement.setAttribute('data-theme', toTheme);
  }

  // Step 2: Framer Motion 颜色过渡（300ms spring）
  // 由 ThemeProvider 的 motion.div 自动响应 data-theme 变化触发
  // 本函数不直接控制 Framer Motion（React 驱动），仅通过 data-theme 变化间接触发

  // 检查 prefers-reduced-motion 降级（D3 reducedMotionFallback）
  if (disableTransition || prefersReducedMotion()) {
    // 降级策略: 立即切换颜色，无动效（instant-color-swap）
    // 仍然上传 toTheme 对应的 uniform（立即，不 lerp）
    if (registeredGL && registeredProgram) {
      try {
        uploadGlassUniforms(registeredGL, registeredProgram, toTheme, DEFAULT_UNIFORM_GROUP);
      } catch (error) {
        // uniform 上传失败不阻断主题切换（降级到 CSS 变量切换）
        // 上报 FE-THE-003 由调用方处理
        if (error instanceof UniformUploadError) {
          // 重新包装为 ThemeTransitionError（异常链式传播）
          throw new ThemeTransitionError(
            `Uniform upload failed during theme change: ${error.message}`,
            fromTheme,
            toTheme,
          );
        }
        throw error;
      }
    }
    onTransitionComplete?.();
    return;
  }

  // Step 3: 启动玻璃着色层 crossfade（400ms rAF uniform lerp）
  try {
    startGlassUniformLerp(fromTheme, toTheme, GLASS_CROSSFADE_MS, DEFAULT_UNIFORM_GROUP, () => {
      // Step 4: crossfade 完成后上传最终 uniform 值（确保精确）
      if (registeredGL && registeredProgram) {
        try {
          uploadGlassUniforms(registeredGL, registeredProgram, toTheme, DEFAULT_UNIFORM_GROUP);
        } catch {
          // 最终上传失败不阻断（crossfade 已完成，uniform 值已通过 lerp 上传）
        }
      }
      // Step 5: 过渡完成回调
      onTransitionComplete?.();
    });
  } catch (error) {
    throw new ThemeTransitionError(
      `Glass crossfade failed: ${error instanceof Error ? error.message : String(error)}`,
      fromTheme,
      toTheme,
    );
  }
}

// ============================================================================
// WCAG AA 对比度校验工具
// ============================================================================

/** WCAG AA 阈值（D3 wcagContrast） */
const WCAG_NORMAL_TEXT_THRESHOLD = 4.5;
const WCAG_LARGE_TEXT_THRESHOLD = 3.0;

/**
 * 解析 CSS 颜色值为 {r, g, b}（0-255）。
 * 支持 hex (#RGB / #RRGGBB) 和 rgb()/rgba() 格式。
 */
function parseColor(colorStr: string): { r: number; g: number; b: number } | null {
  const trimmed = colorStr.trim();

  // hex #RGB
  let match = trimmed.match(/^#([0-9a-fA-F]{3})$/);
  if (match) {
    const [, hex] = match;
    return {
      r: parseInt(hex[0] + hex[0], 16),
      g: parseInt(hex[1] + hex[1], 16),
      b: parseInt(hex[2] + hex[2], 16),
    };
  }

  // hex #RRGGBB
  match = trimmed.match(/^#([0-9a-fA-F]{6})$/);
  if (match) {
    const [, hex] = match;
    return {
      r: parseInt(hex.slice(0, 2), 16),
      g: parseInt(hex.slice(2, 4), 16),
      b: parseInt(hex.slice(4, 6), 16),
    };
  }

  // rgb(r, g, b) / rgba(r, g, b, a)
  match = trimmed.match(/^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
  if (match) {
    const [, r, g, b] = match;
    return { r: parseInt(r, 10), g: parseInt(g, 10), b: parseInt(b, 10) };
  }

  return null;
}

/**
 * 计算 sRGB 通道的线性值（WCAG 2.1 公式）。
 */
function linearizeChannel(value: number): number {
  const sRGB = value / 255;
  return sRGB <= 0.03928 ? sRGB / 12.92 : Math.pow((sRGB + 0.055) / 1.055, 2.4);
}

/**
 * 计算相对亮度（WCAG 2.1）。
 */
function relativeLuminance(color: { r: number; g: number; b: number }): number {
  const r = linearizeChannel(color.r);
  const g = linearizeChannel(color.g);
  const b = linearizeChannel(color.b);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/**
 * 计算两个颜色之间的对比度比值（WCAG 2.1）。
 * 返回值范围 [1, 21]。
 */
function contrastRatio(
  color1: { r: number; g: number; b: number },
  color2: { r: number; g: number; b: number },
): number {
  const l1 = relativeLuminance(color1);
  const l2 = relativeLuminance(color2);
  const lighter = Math.max(l1, l2);
  const darker = Math.min(l1, l2);
  return (lighter + 0.05) / (darker + 0.05);
}

/**
 * 读取指定主题下 CSS 变量的计算值。
 * 临时切换 data-theme 以读取目标主题的值，然后恢复。
 */
function readThemeTokenValue(tokenName: string, theme: Theme): string | null {
  if (typeof document === 'undefined') return null;

  const root = document.documentElement;
  const originalTheme = root.getAttribute('data-theme');

  try {
    root.setAttribute('data-theme', theme);
    const value = getComputedStyle(root).getPropertyValue(tokenName).trim();
    return value || null;
  } finally {
    // 恢复原始 data-theme
    if (originalTheme) {
      root.setAttribute('data-theme', originalTheme);
    } else {
      root.removeAttribute('data-theme');
    }
  }
}

// ============================================================================
// validateWCAGAA 函数（I2 签名匹配）
// ============================================================================

/**
 * validateWCAGAA 选项（I2 validateWCAGAA options）。
 */
export interface ValidateWCAGAAOptions {
  /** 待校验的 token 名称（如 '--color-foreground'） */
  tokenName: string;
  /** 校验的主题 */
  theme: Theme;
  /** 是否为大文本（影响 requiredRatio）。默认 false。 */
  isLargeText?: boolean;
}

/**
 * 函数: validateWCAGAA — 校验 token 在双主题下通过 WCAG AA 对比度（merged.md §1.3）。
 *
 * AA 标准:
 *   - 普通文本: 对比度 ≥ 4.5:1
 *   - 大文本（≥ 18pt 或 14pt bold）: 对比度 ≥ 3.0:1
 *
 * @param options - 校验选项
 * @returns 校验报告（含 passed / theme / tokenName / contrastRatio / requiredRatio / isLargeText / suggestion）
 * @throws ContrastCheckError token 引用不存在的语义 token / 主题配置缺失 / 颜色值格式错误
 */
export function validateWCAGAA(options: ValidateWCAGAAOptions): ValidationReport {
  const { tokenName, theme, isLargeText = false } = options;
  const requiredRatio = isLargeText ? WCAG_LARGE_TEXT_THRESHOLD : WCAG_NORMAL_TEXT_THRESHOLD;

  // 读取 token 颜色值
  const tokenValue = readThemeTokenValue(tokenName, theme);
  if (!tokenValue) {
    throw new ContrastCheckError(
      `Token '${tokenName}' not found in theme '${theme}'`,
      tokenName,
      theme,
    );
  }

  // 读取背景颜色值（D3 themes.dark/light background）
  const backgroundToken =
    theme === Theme.DARK ? '--color-background-dark' : '--color-background-light';
  const bgValue = readThemeTokenValue(backgroundToken, theme);
  if (!bgValue) {
    throw new ContrastCheckError(
      `Background token '${backgroundToken}' not found in theme '${theme}'`,
      tokenName,
      theme,
    );
  }

  // 解析颜色值
  const tokenColor = parseColor(tokenValue);
  const bgColor = parseColor(bgValue);

  if (!tokenColor) {
    throw new ContrastCheckError(
      `Cannot parse token color value: '${tokenValue}' for token '${tokenName}'`,
      tokenName,
      theme,
    );
  }
  if (!bgColor) {
    throw new ContrastCheckError(
      `Cannot parse background color value: '${bgValue}' for token '${backgroundToken}'`,
      tokenName,
      theme,
    );
  }

  // 计算对比度
  const ratio = contrastRatio(tokenColor, bgColor);
  const passed = ratio >= requiredRatio;

  return {
    passed,
    theme,
    tokenName,
    contrastRatio: Math.round(ratio * 100) / 100,
    requiredRatio,
    isLargeText,
    suggestion: passed
      ? null
      : `Token '${tokenName}' in ${theme} theme has contrast ratio ${ratio.toFixed(2)}:1, below WCAG AA threshold ${requiredRatio}:1. Consider adjusting the token value or using a different shade.`,
  };
}

// ============================================================================
// 导出常量（供外部引用）
// ============================================================================

/** 颜色过渡时长（ms） */
export const THEME_COLOR_TRANSITION_MS = COLOR_TRANSITION_MS;

/** 玻璃着色层 crossfade 时长（ms） */
export const THEME_GLASS_CROSSFADE_MS = GLASS_CROSSFADE_MS;

/** WCAG AA 正常文本对比度阈值 */
export const WCAG_AA_NORMAL_THRESHOLD = WCAG_NORMAL_TEXT_THRESHOLD;

/** WCAG AA 大文本对比度阈值 */
export const WCAG_AA_LARGE_THRESHOLD = WCAG_LARGE_TEXT_THRESHOLD;
