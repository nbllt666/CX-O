/**
 * @file mobile-degradation.ts
 * @module 模块9b/移动端降级层
 *
 * 移动端降级配置校验、触发条件判定、降级辅助逻辑。纯函数层，不依赖 React hook。
 * 实际的 tier 切换动作（useGlassTier.setTier）在 use-mobile-degradation.ts hook 中执行。
 *
 * 契约对齐：
 * - 数据契约 D6 responsive_breakpoints.schema.json §mobileDegrades.triggerCondition
 *   "matchMedia('(max-width: 767px)')"
 * - 配置契约 C3 frontend_responsive_config.schema.json §mobileDegrade（8 项参数 + 范围约束）
 * - 配置契约 C3 §errorCodes.mobileDegradeFailed（FE-RES-003）
 * - 错误码契约 E1 frontend_error_codes.schema.json FE-RES-003（移动端降级失败 响应式层）
 *
 * 错误码说明：
 * - FE-RES-003 移动端降级失败（响应式层）：
 *   trigger = matchMedia('(max-width: 767px)') 匹配但降级项执行失败
 *   recovery = 强制关闭复杂动效，强制 Tier 3，上报 FE-RES-003
 *   注意：与 FE-PER-003（性能监控层自动降级失败）区分——本错误码是响应式层降级失败
 *
 * 跨模块约束（AGENTS.md §4.3）：
 * - 不 import 模块1/2/3/5/6/7/8 任何内部实现
 * - 仅 import 模块9a（breakpoints 常量）+ 模块9b（degradation-rules 类型）
 * - useGlassTier 调用在 use-mobile-degradation.ts 中完成（React hook 层）
 */

import {
  MOBILE_BREAKPOINT_THRESHOLD,
  MOBILE_MEDIA_QUERY,
} from './breakpoints';
import {
  DEFAULT_MOBILE_DEGRADE_CONFIG,
  type MobileDegradeConfig,
  type MobileDegradeRule,
  type MobileDegradeRuleKey,
} from './degradation-rules';

// ============================================================================
// 一、错误码常量（对齐 E1 FE-RES-003 + C3 errorCodes.mobileDegradeFailed）
// ============================================================================

/**
 * 移动端降级层错误码。对齐 E1 frontend_error_codes.schema.json RES 模块 + C3 errorCodes。
 *
 * 模块9a 已定义 FE-RES-001（断点检测失败）/ FE-RES-002（栅格计算错误），
 * 模块9b 补充 FE-RES-003（移动端降级失败 响应式层）。
 *
 * 注意：E1 契约中 RES 段共 3 个错误码（FE-RES-001/002/003），均已在 E1 注册。
 * 本常量仅声明模块9b 使用的错误码，不重复声明模块9a 的错误码。
 */
export const MOBILE_DEGRADE_ERROR_CODES = {
  /** 移动端降级失败（响应式层）— severity: error, recoveryAction: fallback-to-default-degrade */
  MOBILE_DEGRADE_FAILED: 'FE-RES-003',
} as const;

// ============================================================================
// 二、降级异常类（携带 errorCode，对齐 E1 exceptionContract 抛出条件规则 2）
// ============================================================================

/**
 * 移动端降级失败异常（响应式层，FE-RES-003）。
 *
 * 抛出条件（对齐 E1 FE-RES-003 trigger + C3 errorCodes.mobileDegradeFailed）：
 * - 降级配置校验失败（mobileDefaultTier 越界 / mobileCharacterAsset 非法值等）
 * - 降级动作执行失败（如 setTier 抛异常）
 * - matchMedia('(max-width: 767px)') 匹配但降级项未正确应用
 *
 * 调用方处理（对齐 E1 exceptionContract callerHandlingRules）：
 * - 捕获后读取 errorCode，按 FE-RES-003 recoveryStrategy 执行恢复
 * - 不得按异常类型 catch，必须按 errorCode 路由
 * - 不得吞没异常，必须上报到监控 dashboard
 *
 * 跨模块歧义消解（对齐 E1 crossModuleDisambiguation 降级失败条目）：
 * - FE-GLA-004: GlassRenderer 执行层降级失败
 * - FE-PER-003: PerformanceMonitor 监控层自动降级失败
 * - FE-MOT-005: prefers-reduced-motion 动效层降级失败
 * - FE-RES-003: matchMedia 响应式层降级失败（本错误码）
 */
export class MobileDegradeError extends Error {
  readonly errorCode: typeof MOBILE_DEGRADE_ERROR_CODES.MOBILE_DEGRADE_FAILED;
  /** 失败的降级规则 key（如配置校验失败时为 null） */
  readonly ruleKey: MobileDegradeRuleKey | null;
  /** 失败原因分类 */
  readonly failureType: 'config-invalid' | 'apply-failed' | 'media-query-error';

  constructor(
    message: string,
    options: {
      ruleKey?: MobileDegradeRuleKey | null;
      failureType: 'config-invalid' | 'apply-failed' | 'media-query-error';
    },
  ) {
    super(message);
    this.name = 'MobileDegradeError';
    this.errorCode = MOBILE_DEGRADE_ERROR_CODES.MOBILE_DEGRADE_FAILED;
    this.ruleKey = options.ruleKey ?? null;
    this.failureType = options.failureType;
    Object.setPrototypeOf(this, MobileDegradeError.prototype);
  }
}

// ============================================================================
// 三、降级配置校验（对齐 C3 mobileDegrade 范围约束）
// ============================================================================

/**
 * 校验移动端降级配置合法性。
 *
 * 校验规则对齐 C3 frontend_responsive_config.schema.json §mobileDegrade 的约束：
 * - mobileDefaultTier: integer, minimum 1, maximum 4
 * - mobileCharacterAsset: enum ["static-2d", "live2d", "vrm"]
 * - mobileParticleDensity: number, minimum 0
 * - mobileParticleMaxAlpha: number, minimum 0, maximum 1
 * - mobileFramerMotionDurationFactor: number, minimum 0.1, maximum 1.0
 * - mobileGsapTimelineMaxElements: integer, minimum 0
 * - mobileComplexMotionDisabled: boolean
 * - mobileToolbarStrategy: enum ["bottom-tab-drawer", "sidebar", "top-bar"]
 *
 * @param config - 待校验的降级配置
 * @throws MobileDegradeError 配置不合法时抛出（failureType='config-invalid'）
 */
export function validateMobileDegradeConfig(config: MobileDegradeConfig): void {
  // mobileDefaultTier: 1-4
  if (
    !Number.isInteger(config.mobileDefaultTier) ||
    config.mobileDefaultTier < 1 ||
    config.mobileDefaultTier > 4
  ) {
    throw new MobileDegradeError(
      `[${MOBILE_DEGRADE_ERROR_CODES.MOBILE_DEGRADE_FAILED}] ` +
        `mobileDefaultTier must be integer in [1, 4], got ${config.mobileDefaultTier}`,
      { failureType: 'config-invalid' },
    );
  }

  // mobileCharacterAsset: enum
  const validAssets: readonly string[] = ['static-2d', 'live2d', 'vrm'];
  if (!validAssets.includes(config.mobileCharacterAsset)) {
    throw new MobileDegradeError(
      `[${MOBILE_DEGRADE_ERROR_CODES.MOBILE_DEGRADE_FAILED}] ` +
        `mobileCharacterAsset must be one of ${validAssets.join('/')}, got ${config.mobileCharacterAsset}`,
      { failureType: 'config-invalid' },
    );
  }

  // mobileParticleDensity: >= 0
  if (
    typeof config.mobileParticleDensity !== 'number' ||
    config.mobileParticleDensity < 0
  ) {
    throw new MobileDegradeError(
      `[${MOBILE_DEGRADE_ERROR_CODES.MOBILE_DEGRADE_FAILED}] ` +
        `mobileParticleDensity must be number >= 0, got ${config.mobileParticleDensity}`,
      { failureType: 'config-invalid' },
    );
  }

  // mobileParticleMaxAlpha: 0-1
  if (
    typeof config.mobileParticleMaxAlpha !== 'number' ||
    config.mobileParticleMaxAlpha < 0 ||
    config.mobileParticleMaxAlpha > 1
  ) {
    throw new MobileDegradeError(
      `[${MOBILE_DEGRADE_ERROR_CODES.MOBILE_DEGRADE_FAILED}] ` +
        `mobileParticleMaxAlpha must be number in [0, 1], got ${config.mobileParticleMaxAlpha}`,
      { failureType: 'config-invalid' },
    );
  }

  // mobileFramerMotionDurationFactor: 0.1-1.0
  if (
    typeof config.mobileFramerMotionDurationFactor !== 'number' ||
    config.mobileFramerMotionDurationFactor < 0.1 ||
    config.mobileFramerMotionDurationFactor > 1.0
  ) {
    throw new MobileDegradeError(
      `[${MOBILE_DEGRADE_ERROR_CODES.MOBILE_DEGRADE_FAILED}] ` +
        `mobileFramerMotionDurationFactor must be number in [0.1, 1.0], got ${config.mobileFramerMotionDurationFactor}`,
      { failureType: 'config-invalid' },
    );
  }

  // mobileGsapTimelineMaxElements: integer >= 0
  if (
    !Number.isInteger(config.mobileGsapTimelineMaxElements) ||
    config.mobileGsapTimelineMaxElements < 0
  ) {
    throw new MobileDegradeError(
      `[${MOBILE_DEGRADE_ERROR_CODES.MOBILE_DEGRADE_FAILED}] ` +
        `mobileGsapTimelineMaxElements must be integer >= 0, got ${config.mobileGsapTimelineMaxElements}`,
      { failureType: 'config-invalid' },
    );
  }

  // mobileComplexMotionDisabled: boolean
  if (typeof config.mobileComplexMotionDisabled !== 'boolean') {
    throw new MobileDegradeError(
      `[${MOBILE_DEGRADE_ERROR_CODES.MOBILE_DEGRADE_FAILED}] ` +
        `mobileComplexMotionDisabled must be boolean, got ${typeof config.mobileComplexMotionDisabled}`,
      { failureType: 'config-invalid' },
    );
  }

  // mobileToolbarStrategy: enum
  const validStrategies: readonly string[] = ['bottom-tab-drawer', 'sidebar', 'top-bar'];
  if (!validStrategies.includes(config.mobileToolbarStrategy)) {
    throw new MobileDegradeError(
      `[${MOBILE_DEGRADE_ERROR_CODES.MOBILE_DEGRADE_FAILED}] ` +
        `mobileToolbarStrategy must be one of ${validStrategies.join('/')}, got ${config.mobileToolbarStrategy}`,
      { failureType: 'config-invalid' },
    );
  }
}

/**
 * 合并配置与默认值（对齐 C3 autoFill strategy=merge-with-defaults）。
 *
 * 缺失字段以 DEFAULT_MOBILE_DEGRADE_CONFIG 补齐，保证配置完整性。
 * 合并后自动校验合法性，校验失败抛出 MobileDegradeError。
 *
 * @param partial - 部分配置（可能缺失字段）
 * @returns 合并默认值后的完整配置
 * @throws MobileDegradeError 合并后配置仍不合法时抛出
 */
export function mergeWithDefaults(partial: Partial<MobileDegradeConfig>): MobileDegradeConfig {
  const merged: MobileDegradeConfig = {
    ...DEFAULT_MOBILE_DEGRADE_CONFIG,
    ...partial,
  };
  validateMobileDegradeConfig(merged);
  return merged;
}

// ============================================================================
// 四、降级触发条件判定（对齐 D6 mobileDegrades.triggerCondition）
// ============================================================================

/**
 * 判定当前是否应触发移动端降级。
 *
 * 触发条件对齐 D6 responsive_breakpoints.schema.json §mobileDegrades.triggerCondition：
 *   "matchMedia('(max-width: 767px)')"
 *
 * 即视口宽度 < 768px（< md 断点）时触发移动端降级策略 9 项。
 *
 * SSR 环境或 matchMedia 不可用时返回 false（不降级，对齐桌面端为主战场裁决）。
 *
 * @returns 是否触发移动端降级
 */
export function shouldApplyMobileDegrade(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    // SSR 或 matchMedia 不可用：不降级（桌面端为主战场）
    return false;
  }
  try {
    return window.matchMedia(MOBILE_MEDIA_QUERY).matches;
  } catch {
    // matchMedia 抛异常（如非法查询）：记录并返回 false
    console.warn(
      `[${MOBILE_DEGRADE_ERROR_CODES.MOBILE_DEGRADE_FAILED}] ` +
        `matchMedia('${MOBILE_MEDIA_QUERY}') threw error. Falling back to no-degrade (desktop-first).`
    );
    return false;
  }
}

/**
 * 获取移动端降级触发条件的描述信息。
 *
 * 用于降级事件埋点与监控上报，记录触发源（matchMedia 响应式层）。
 *
 * @returns 触发条件描述对象
 */
export function getDegradeTriggerInfo(): {
  /** 触发条件（对齐 D6 mobileDegrades.triggerCondition） */
  triggerCondition: string;
  /** 触发阈值（px，< md 断点） */
  threshold: number;
  /** 触发源分类（对齐 E1 crossModuleDisambiguation 降级失败 disambiguationKey） */
  source: 'matchMedia-responsive-layer';
} {
  return {
    triggerCondition: `matchMedia('(max-width: ${MOBILE_BREAKPOINT_THRESHOLD}px)')`,
    threshold: MOBILE_BREAKPOINT_THRESHOLD,
    source: 'matchMedia-responsive-layer',
  };
}

// ============================================================================
// 五、backdrop-filter CSS 变量覆盖（降级规则 4：backdrop-filter ≤ 16px）
// ============================================================================

/**
 * backdrop-filter CSS 变量覆盖映射。
 *
 * 移动端降级规则 4：backdrop-filter ≤ 16px。
 * 通过覆盖 CSS 变量实现，不修改组件内联样式（保持样式一致性）。
 *
 * 变量名约定（对齐模块1 Token 设计系统层命名规范 --{category}-{semantic}-{state}）：
 * - --glass-blur-mobile: 移动端 blur 值
 * - --glass-blur-saturate-mobile: 移动端 saturate 值
 */
export interface BackdropFilterCssOverride {
  /** CSS 变量名 → 值映射 */
  variables: Record<string, string>;
  /** 完整的 blur CSS 值（如 "blur(16px) saturate(1.8)"） */
  blurValue: string;
  /** blur px 上限 */
  maxBlurPx: number;
}

/**
 * 生成 backdrop-filter CSS 变量覆盖映射。
 *
 * 用于 useMobileDegrade hook 注入到 <style> 或容器 style 属性，
 * 覆盖桌面端 blur(24px) 为移动端 blur(16px)。
 *
 * @param blurValue - blur CSS 值字符串（如 "blur(16px) saturate(1.8)"）
 * @param maxBlurPx - blur px 上限（默认 16）
 * @returns CSS 变量覆盖映射
 *
 * @example
 * ```ts
 * const override = getBackdropFilterCssOverride('blur(16px) saturate(1.8)', 16);
 * // override.variables = { '--glass-blur-mobile': '16px', '--glass-blur-saturate-mobile': '1.8' }
 * ```
 */
export function getBackdropFilterCssOverride(
  blurValue: string,
  maxBlurPx: number = 16,
): BackdropFilterCssOverride {
  // 解析 blur(Npx) saturate(M) 格式（对齐 D6 blurValue pattern）
  const blurMatch = blurValue.match(/blur\((\d+)px\)/);
  const saturateMatch = blurValue.match(/saturate\(([0-9.]+)\)/);

  const blurPx = blurMatch ? blurMatch[1] : String(maxBlurPx);
  const saturate = saturateMatch ? saturateMatch[1] : '1.8';

  return {
    variables: {
      '--glass-blur-mobile': `${blurPx}px`,
      '--glass-blur-saturate-mobile': saturate,
    },
    blurValue,
    maxBlurPx,
  };
}

// ============================================================================
// 六、视口外懒挂载 IntersectionObserver 工厂（降级规则 6）
// ============================================================================

/**
 * 视口外懒挂载回调接口。
 */
export interface LazyMountCallbacks {
  /** 元素进入视口时回调（挂载） */
  onEnter: (element: Element) => void;
  /** 元素离开视口时回调（卸载） */
  onLeave?: (element: Element) => void;
}

/**
 * 创建视口外懒挂载 IntersectionObserver。
 *
 * 降级规则 6：视口外懒挂载。元素离开视口时卸载，进入视口时挂载，
 * 减少移动端 DOM 节点数与渲染压力。
 *
 * SSR 环境或 IntersectionObserver 不可用时返回 null，调用方应回退为始终挂载。
 *
 * @param rootMargin - rootMargin（默认 "200px"，提前预加载）
 * @param threshold - 触发阈值（默认 0.01，刚进入视口即触发）
 * @param callbacks - 挂载/卸载回调
 * @returns IntersectionObserver 实例，不可用时返回 null
 *
 * @example
 * ```tsx
 * const observer = createLazyMountObserver('200px', 0.01, {
 *   onEnter: (el) => el.classList.add('mounted'),
 *   onLeave: (el) => el.classList.remove('mounted'),
 * });
 * if (observer) observer.observe(ref.current);
 * ```
 */
export function createLazyMountObserver(
  rootMargin: string,
  threshold: number,
  callbacks: LazyMountCallbacks,
): IntersectionObserver | null {
  if (typeof window === 'undefined' || typeof IntersectionObserver === 'undefined') {
    // SSR 或 IntersectionObserver 不可用：返回 null，调用方回退为始终挂载
    return null;
  }

  try {
    return new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            callbacks.onEnter(entry.target);
          } else {
            callbacks.onLeave?.(entry.target);
          }
        }
      },
      { rootMargin, threshold },
    );
  } catch {
    // IntersectionObserver 构造抛异常（如非法 rootMargin）：返回 null
    console.warn(
      `[${MOBILE_DEGRADE_ERROR_CODES.MOBILE_DEGRADE_FAILED}] ` +
        `IntersectionObserver creation failed. Falling back to always-mount.`
    );
    return null;
  }
}

// ============================================================================
// 七、降级规则应用辅助（生成降级动作清单，供 hook 执行）
// ============================================================================

/**
 * 降级动作描述。描述每项规则对应的具体动作，供 useMobileDegrade hook 执行。
 *
 * 注意：本类型仅描述动作，不执行。实际执行在 hook 中（如调用 useGlassTier.setTier）。
 */
export interface DegradeAction {
  /** 关联的规则 key */
  ruleKey: MobileDegradeRuleKey;
  /** 动作描述（中文） */
  action: string;
  /** 动作分类（用于 hook 路由执行） */
  category:
    | 'tier-switch'      // tier 切换（调用 useGlassTier.setTier）
    | 'css-override'     // CSS 变量覆盖（backdrop-filter）
    | 'asset-switch'     // 资产切换（静态立绘/2D 渲染）
    | 'motion-config'    // 动效配置（spring 减弱/时长压缩）
    | 'lazy-mount'       // 懒挂载（IntersectionObserver）
    | 'virtual-list'     // 虚拟列表（react-window）
    | 'gpu-optimize'     // GPU 优化（will-change）
    | 'decoration-off';  // 装饰动效关闭
}

/**
 * 根据降级规则列表生成降级动作清单。
 *
 * 将 9 项规则映射为具体的降级动作分类，供 useMobileDegrade hook 按分类路由执行。
 * hook 根据 category 决定执行方式（如 tier-switch 调用 useGlassTier.setTier）。
 *
 * @param rules - 降级规则列表（仅处理 enabled=true 的规则）
 * @returns 降级动作清单
 */
export function buildDegradeActions(rules: readonly MobileDegradeRule[]): DegradeAction[] {
  const actions: DegradeAction[] = [];

  for (const rule of rules) {
    if (!rule.enabled) continue;

    const action = mapRuleToAction(rule);
    if (action) {
      actions.push(action);
    }
  }

  return actions;
}

/**
 * 规则 key → 降级动作映射。
 */
function mapRuleToAction(rule: MobileDegradeRule): DegradeAction | null {
  switch (rule.key) {
    case 'webgl-force-tier-3':
      return {
        ruleKey: rule.key,
        action: `强制 Glass Tier ${rule.params.forceTier ?? 3}（CSS backdrop-filter 渲染）`,
        category: 'tier-switch',
      };

    case 'static-character-portrait':
      return {
        ruleKey: rule.key,
        action: `CharacterHost 切换为静态立绘（${rule.params.characterAsset ?? 'static-2d'}）`,
        category: 'asset-switch',
      };

    case 'motion-simplify':
      return {
        ruleKey: rule.key,
        action: `Framer Motion 时长压缩 ${rule.params.framerMotionDurationFactor ?? 0.7} 倍 + spring 阻尼减弱 ${rule.params.springDampingFactor ?? 0.8}`,
        category: 'motion-config',
      };

    case 'backdrop-filter-cap':
      return {
        ruleKey: rule.key,
        action: `backdrop-filter blur 上限 ${rule.params.maxBlurPx ?? 16}px（CSS 变量覆盖）`,
        category: 'css-override',
      };

    case 'force-2d-render':
      return {
        ruleKey: rule.key,
        action: `禁用 3D 渲染引擎（Live2D 物理摆动关闭 / VRM 切 2D 立绘）`,
        category: 'asset-switch',
      };

    case 'viewport-lazy-mount':
      return {
        ruleKey: rule.key,
        action: `视口外懒挂载（IntersectionObserver rootMargin=${rule.params.lazyMountRootMargin ?? '200px'}）`,
        category: 'lazy-mount',
      };

    case 'virtual-list':
      return {
        ruleKey: rule.key,
        action: `列表项 >= ${rule.params.virtualListThreshold ?? 50} 启用虚拟列表（react-window overscan=${rule.params.virtualListOverscan ?? 3}）`,
        category: 'virtual-list',
      };

    case 'transform-opacity-gpu':
      return {
        ruleKey: rule.key,
        action: `will-change 优化（${(rule.params.willChangeProperties ?? ['transform', 'opacity']).join(', ')}）`,
        category: 'gpu-optimize',
      };

    case 'decoration-disable':
      return {
        ruleKey: rule.key,
        action: `AnimeDecoration 返回 null + 粒子密度 ${rule.params.particleDensity ?? 0.1}/m²`,
        category: 'decoration-off',
      };

    default: {
      // 穷尽性检查
      const _exhaustive: never = rule.key;
      return _exhaustive;
    }
  }
}
