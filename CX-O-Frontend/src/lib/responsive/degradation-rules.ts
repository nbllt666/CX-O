/**
 * @file degradation-rules.ts
 * @module 模块9b/移动端降级层
 *
 * 移动端降级策略 9 项规则定义。纯数据 + 类型 + 规则构建函数，不依赖 React。
 *
 * 契约对齐：
 * - 数据契约 D6 responsive_breakpoints.schema.json §mobileDegrades（9 项 MD-01~MD-09 + triggerCondition）
 * - 配置契约 C3 frontend_responsive_config.schema.json §mobileDegrade（8 项参数，配置驱动）
 * - 配置契约 C3 §touchAdaptation（4 项触摸适配参数）
 * - 错误码契约 E1 frontend_error_codes.schema.json（FE-RES-003 移动端降级失败）
 * - 方案 merged.md §6.3（移动端降级策略 9 项）
 *
 * 9 项降级规则与 D6 MD-01~MD-09 / 闭合判据的映射：
 *  1. webgl-force-tier-3        — WebGL 强制 Tier 3（D6 MD-01/MD-06，C3 mobileDefaultTier=3）
 *  2. static-character-portrait — 角色资产切静态立绘（D6 MD-02，C3 mobileCharacterAsset="static-2d"）
 *  3. motion-simplify           — 动效简化（D6 MD-04/MD-05，C3 mobileFramerMotionDurationFactor=0.7）
 *  4. backdrop-filter-cap       — backdrop-filter ≤ 16px（D6 MD-06 blurValue，sm 断点 blur(16px)）
 *  5. force-2d-render           — Live2D/VRM 强制 2D（D6 MD-02 延伸，禁用 3D 渲染引擎）
 *  6. viewport-lazy-mount       — 视口外懒挂载（IntersectionObserver，无 C3 参数，通用性能优化）
 *  7. virtual-list              — 虚拟列表启用（react-window，无 C3 参数，通用性能优化）
 *  8. transform-opacity-gpu     — transform/opacity 避重排（will-change，无 C3 参数，通用性能优化）
 *  9. decoration-disable        — 装饰动效关闭（D6 MD-07，C3 mobileComplexMotionDisabled + mobileParticleDensity=0.1）
 *
 * 配置驱动原则（rules-3 §三）：
 * - 所有可配置参数从 C3 mobileDegrade / touchAdaptation 加载，禁止硬编码
 * - C3 无对应参数的规则（6/7/8）使用通用性能优化默认值，不引入业务配置
 * - 默认值对齐 C3 schema default，保证 autoFill 合并后行为一致
 *
 * 跨模块约束（AGENTS.md §4.3）：
 * - 本文件为纯数据/类型，不 import 任何业务模块（模块1-8）内部实现
 * - spring 减弱因子 / 装饰动效关闭标志作为规则参数输出，由业务方（模块3/5）消费
 * - 模块9b 不反向依赖模块3/5 的实现，仅输出参数供消费方读取
 */

// ============================================================================
// 一、降级规则 key 枚举（9 项，对齐闭合判据 + D6 mobileDegrades.items）
// ============================================================================

/**
 * 移动端降级规则 key。9 项规则的唯一标识符。
 *
 * 顺序固定（1-9），与闭合判据逐项对应。key 命名采用 kebab-case，语义自解释。
 */
export type MobileDegradeRuleKey =
  | 'webgl-force-tier-3'
  | 'static-character-portrait'
  | 'motion-simplify'
  | 'backdrop-filter-cap'
  | 'force-2d-render'
  | 'viewport-lazy-mount'
  | 'virtual-list'
  | 'transform-opacity-gpu'
  | 'decoration-disable';

/**
 * 9 项降级规则 key 的有序数组。索引 0-8 对应规则序号 1-9。
 *
 * 用于规则遍历与顺序校验，保证 buildMobileDegradeRules 输出顺序稳定。
 */
export const MOBILE_DEGRADE_RULE_KEYS: readonly MobileDegradeRuleKey[] = [
  'webgl-force-tier-3',
  'static-character-portrait',
  'motion-simplify',
  'backdrop-filter-cap',
  'force-2d-render',
  'viewport-lazy-mount',
  'virtual-list',
  'transform-opacity-gpu',
  'decoration-disable',
] as const;

/**
 * 规则 key → 序号映射（1-9）。用于规则索引查询。
 */
export const RULE_KEY_TO_INDEX: Record<MobileDegradeRuleKey, number> = {
  'webgl-force-tier-3': 1,
  'static-character-portrait': 2,
  'motion-simplify': 3,
  'backdrop-filter-cap': 4,
  'force-2d-render': 5,
  'viewport-lazy-mount': 6,
  'virtual-list': 7,
  'transform-opacity-gpu': 8,
  'decoration-disable': 9,
};

// ============================================================================
// 二、降级规则参数类型（各规则不同参数，统一为可选字段对象）
// ============================================================================

/**
 * 角色资产形态。对齐 C3 mobileDegrade.mobileCharacterAsset 枚举。
 */
export type CharacterAssetMode = 'static-2d' | 'live2d' | 'vrm';

/**
 * 工具栏策略。对齐 C3 mobileDegrade.mobileToolbarStrategy 枚举。
 */
export type ToolbarStrategy = 'bottom-tab-drawer' | 'sidebar' | 'top-bar';

/**
 * 降级规则参数。所有规则的参数合并为统一对象（可选字段），便于规则构建与消费。
 *
 * 各字段来源：
 * - forceTier: C3 mobileDefaultTier（默认 3）
 * - characterAsset: C3 mobileCharacterAsset（默认 "static-2d"）
 * - framerMotionDurationFactor: C3 mobileFramerMotionDurationFactor（默认 0.7）
 * - springDampingFactor: 本地定义（spring 阻尼减弱因子，默认 0.8，业务方模块3 消费）
 * - springStiffnessFactor: 本地定义（spring 刚度减弱因子，默认 0.85，业务方模块3 消费）
 * - maxBlurPx: D6 breakpoints.sm.blurValue 解析出的 blur px 上限（默认 16）
 * - blurValue: D6 breakpoints.sm.blurValue 完整字符串（默认 "blur(16px) saturate(1.8)"）
 * - lazyMountRootMargin: IntersectionObserver rootMargin（默认 "200px"，无 C3 参数）
 * - lazyMountThreshold: IntersectionObserver threshold（默认 0.01，无 C3 参数）
 * - virtualListThreshold: 启用虚拟列表的最小列表项数（默认 50，无 C3 参数）
 * - virtualListOverscan: react-window overscan 预渲染数（默认 3，无 C3 参数）
 * - willChangeProperties: will-change 优化属性列表（默认 ["transform","opacity"]，无 C3 参数）
 * - complexMotionDisabled: C3 mobileComplexMotionDisabled（默认 true）
 * - gsapTimelineMaxElements: C3 mobileGsapTimelineMaxElements（默认 3）
 * - particleDensity: C3 mobileParticleDensity（默认 0.1）
 * - particleMaxAlpha: C3 mobileParticleMaxAlpha（默认 0.2）
 * - toolbarStrategy: C3 mobileToolbarStrategy（默认 "bottom-tab-drawer"）
 */
export interface MobileDegradeRuleParams {
  /** WebGL 强制 tier 值（1-4，移动端默认 3）。来源 C3 mobileDefaultTier。 */
  forceTier?: number;
  /** 角色资产形态。来源 C3 mobileCharacterAsset。 */
  characterAsset?: CharacterAssetMode;
  /** Framer Motion 时长压缩因子（0.1-1.0）。来源 C3 mobileFramerMotionDurationFactor。 */
  framerMotionDurationFactor?: number;
  /** spring 阻尼减弱因子（0.1-1.0，相对桌面端的比例）。本地定义，业务方模块3 消费。 */
  springDampingFactor?: number;
  /** spring 刚度减弱因子（0.1-1.0，相对桌面端的比例）。本地定义，业务方模块3 消费。 */
  springStiffnessFactor?: number;
  /** backdrop-filter blur px 上限（移动端 ≤ 16）。来源 D6 breakpoints.sm.blurValue 解析。 */
  maxBlurPx?: number;
  /** backdrop-filter blur 完整 CSS 值。来源 D6 breakpoints.sm.blurValue。 */
  blurValue?: string;
  /** IntersectionObserver rootMargin（视口外懒挂载预加载距离）。本地定义。 */
  lazyMountRootMargin?: string;
  /** IntersectionObserver threshold（视口外懒挂载触发阈值）。本地定义。 */
  lazyMountThreshold?: number;
  /** 启用虚拟列表的最小列表项数。本地定义。 */
  virtualListThreshold?: number;
  /** react-window overscan 预渲染项数。本地定义。 */
  virtualListOverscan?: number;
  /** will-change 优化属性列表（避重排）。本地定义。 */
  willChangeProperties?: string[];
  /** 是否关闭复杂动效（GSAP 时间线/ScrollTrigger）。来源 C3 mobileComplexMotionDisabled。 */
  complexMotionDisabled?: boolean;
  /** GSAP 复杂时间线最大参与元素数。来源 C3 mobileGsapTimelineMaxElements。 */
  gsapTimelineMaxElements?: number;
  /** 装饰粒子密度（粒子数/m²）。来源 C3 mobileParticleDensity。 */
  particleDensity?: number;
  /** 装饰粒子 alpha 总和上限。来源 C3 mobileParticleMaxAlpha。 */
  particleMaxAlpha?: number;
  /** 移动端工具栏策略。来源 C3 mobileToolbarStrategy。 */
  toolbarStrategy?: ToolbarStrategy;
}

// ============================================================================
// 三、降级规则接口
// ============================================================================

/**
 * 移动端降级规则定义。每项规则含 key、序号、描述、启用状态、参数。
 *
 * 规则参数从 C3 mobileDegrade 配置加载（配置驱动），保证不硬编码。
 * 业务方（模块3/4/5/6/7/8）通过 useMobileDegrade hook 读取规则列表，
 * 按各自职责应用对应规则的参数。
 */
export interface MobileDegradeRule {
  /** 规则 key（唯一标识符） */
  key: MobileDegradeRuleKey;
  /** 规则序号（1-9，对齐闭合判据） */
  index: number;
  /** 规则中文描述（无歧义） */
  description: string;
  /** 是否启用（默认全部启用，对齐 D6 mobileDegrades.items[].enabled default=true） */
  enabled: boolean;
  /** 规则参数（从 C3 配置加载） */
  params: MobileDegradeRuleParams;
}

// ============================================================================
// 四、移动端降级配置类型（从 C3 mobileDegrade 加载）
// ============================================================================

/**
 * 移动端降级配置。字段名与 C3 frontend_responsive_config.schema.json §mobileDegrade 逐一对齐。
 *
 * 加载方式：配置加载器读取 C3 配置文件，autoFill 合并默认值后得到本对象。
 * 本模块不直接读取配置文件，由 useMobileDegrade hook 接收外部传入的配置对象。
 */
export interface MobileDegradeConfig {
  /** 移动端默认 Liquid Glass tier（1-4，默认 3）。C3 mobileDefaultTier。 */
  mobileDefaultTier: number;
  /** 移动端角色资产形态。C3 mobileCharacterAsset。 */
  mobileCharacterAsset: CharacterAssetMode;
  /** 移动端装饰粒子密度（粒子数/m²）。C3 mobileParticleDensity。 */
  mobileParticleDensity: number;
  /** 移动端装饰粒子 alpha 总和上限。C3 mobileParticleMaxAlpha。 */
  mobileParticleMaxAlpha: number;
  /** 移动端 Framer Motion 时长压缩因子（0.1-1.0）。C3 mobileFramerMotionDurationFactor。 */
  mobileFramerMotionDurationFactor: number;
  /** 移动端 GSAP 复杂时间线最大参与元素数。C3 mobileGsapTimelineMaxElements。 */
  mobileGsapTimelineMaxElements: number;
  /** 移动端是否关闭复杂动效。C3 mobileComplexMotionDisabled。 */
  mobileComplexMotionDisabled: boolean;
  /** 移动端工具栏策略。C3 mobileToolbarStrategy。 */
  mobileToolbarStrategy: ToolbarStrategy;
}

/**
 * 默认移动端降级配置。对齐 C3 mobileDegrade default 值。
 *
 * 用于 autoFill fallback 与配置缺失时的安全兜底。
 * 任何字段缺失时回退到本默认值（对齐 C3 autoFill.fallbackToDefaults=true）。
 */
export const DEFAULT_MOBILE_DEGRADE_CONFIG: MobileDegradeConfig = {
  mobileDefaultTier: 3,
  mobileCharacterAsset: 'static-2d',
  mobileParticleDensity: 0.1,
  mobileParticleMaxAlpha: 0.2,
  mobileFramerMotionDurationFactor: 0.7,
  mobileGsapTimelineMaxElements: 3,
  mobileComplexMotionDisabled: true,
  mobileToolbarStrategy: 'bottom-tab-drawer',
};

// ============================================================================
// 五、触摸适配配置类型（从 C3 touchAdaptation 加载）
// ============================================================================

/**
 * 触摸适配配置。字段名与 C3 frontend_responsive_config.schema.json §touchAdaptation 对齐。
 *
 * 用于 touch-adapter.tsx 组件消费，配置驱动（不硬编码 44px 等参数）。
 */
export interface TouchAdaptationConfig {
  /** 最小点击区域尺寸（px，Apple HIG 44）。C3 touchAdaptation.minTouchTargetSize。 */
  minTouchTargetSize: number;
  /** hover 态在 pointer: coarse 设备是否降级为 active 态。C3 hoverToActiveOnCoarsePointer。 */
  hoverToActiveOnCoarsePointer: boolean;
  /** 是否启用长按手势替代右键菜单。C3 longPressForContextMenu。 */
  longPressForContextMenu: boolean;
  /** rubber-band 滚动是否仅在 iOS 原生滚动容器启用。C3 rubberBandOnlyIOS。 */
  rubberBandOnlyIOS: boolean;
}

/**
 * 默认触摸适配配置。对齐 C3 touchAdaptation default 值 + D6 touchAdaptation。
 */
export const DEFAULT_TOUCH_ADAPTATION_CONFIG: TouchAdaptationConfig = {
  minTouchTargetSize: 44,
  hoverToActiveOnCoarsePointer: true,
  longPressForContextMenu: true,
  rubberBandOnlyIOS: true,
};

// ============================================================================
// 六、降级规则描述（中文，对齐闭合判据 9 项）
// ============================================================================

/**
 * 9 项降级规则的中文描述。对齐闭合判据逐项描述。
 *
 * key → 描述映射，保证描述与规则 key 一一对应，无歧义。
 */
export const MOBILE_DEGRADE_RULE_DESCRIPTIONS: Record<MobileDegradeRuleKey, string> = {
  'webgl-force-tier-3': 'WebGL 强制 Tier 3（调用 useGlassTier.setTier(TIER_3)，CSS backdrop-filter 渲染）',
  'static-character-portrait': '角色资产切静态立绘（CharacterHost 降级为静态 2D 图）',
  'motion-simplify': '动效简化（Framer Motion 时长压缩 0.7 倍 + spring 阻尼/刚度减弱）',
  'backdrop-filter-cap': 'backdrop-filter ≤ 16px（CSS 变量覆盖，移动端 blur 上限 16px）',
  'force-2d-render': 'Live2D/VRM 强制 2D（禁用 3D 渲染引擎，物理摆动关闭）',
  'viewport-lazy-mount': '视口外懒挂载（IntersectionObserver，离开视口卸载）',
  'virtual-list': '虚拟列表启用（react-window，大列表渲染不重排）',
  'transform-opacity-gpu': 'transform/opacity 避重排（will-change 优化，GPU 加速合成）',
  'decoration-disable': '装饰动效关闭（AnimeDecoration 返回 null + 粒子密度 0.1/m²）',
};

// ============================================================================
// 七、降级规则构建函数（配置驱动）
// ============================================================================

/**
 * 根据 C3 mobileDegrade 配置构建 9 项降级规则。
 *
 * 配置驱动：所有可配置参数从 config 读取，不硬编码。
 * C3 无对应参数的规则（viewport-lazy-mount / virtual-list / transform-opacity-gpu）
 * 使用通用性能优化默认值（本地定义，非业务配置）。
 *
 * @param config - 移动端降级配置（从 C3 mobileDegrade 加载）
 * @returns 9 项降级规则数组（顺序固定 1-9）
 *
 * @example
 * ```ts
 * import { buildMobileDegradeRules, DEFAULT_MOBILE_DEGRADE_CONFIG } from '@/lib/responsive/degradation-rules';
 *
 * const rules = buildMobileDegradeRules(DEFAULT_MOBILE_DEGRADE_CONFIG);
 * console.log(rules.length); // 9
 * console.log(rules[0].key); // 'webgl-force-tier-3'
 * console.log(rules[0].params.forceTier); // 3
 * ```
 */
export function buildMobileDegradeRules(config: MobileDegradeConfig): MobileDegradeRule[] {
  return MOBILE_DEGRADE_RULE_KEYS.map((key): MobileDegradeRule => {
    const index = RULE_KEY_TO_INDEX[key];
    const description = MOBILE_DEGRADE_RULE_DESCRIPTIONS[key];
    const params = buildRuleParams(key, config);

    return {
      key,
      index,
      description,
      enabled: true, // 9 项默认全部启用（对齐 D6 mobileDegrades.items[].enabled default=true）
      params,
    };
  });
}

/**
 * 根据规则 key 与配置构建该规则的参数对象。
 *
 * 各规则的参数来源：
 * - C3 有对应字段：从 config 读取（配置驱动）
 * - C3 无对应字段：使用本地通用默认值（性能优化通用参数）
 *
 * @param key - 规则 key
 * @param config - 移动端降级配置
 * @returns 规则参数对象
 */
function buildRuleParams(
  key: MobileDegradeRuleKey,
  config: MobileDegradeConfig,
): MobileDegradeRuleParams {
  switch (key) {
    case 'webgl-force-tier-3':
      return {
        forceTier: config.mobileDefaultTier,
      };

    case 'static-character-portrait':
      return {
        characterAsset: config.mobileCharacterAsset,
      };

    case 'motion-simplify':
      return {
        framerMotionDurationFactor: config.mobileFramerMotionDurationFactor,
        // spring 减弱因子（本地定义，业务方模块3 消费）
        // 阻尼减弱到 0.8 倍（更柔和），刚度减弱到 0.85 倍（更慢）
        springDampingFactor: 0.8,
        springStiffnessFactor: 0.85,
        complexMotionDisabled: config.mobileComplexMotionDisabled,
        gsapTimelineMaxElements: config.mobileGsapTimelineMaxElements,
      };

    case 'backdrop-filter-cap':
      return {
        // blur 上限 16px（D6 breakpoints.sm.blurValue = "blur(16px) saturate(1.8)"）
        maxBlurPx: 16,
        blurValue: 'blur(16px) saturate(1.8)',
      };

    case 'force-2d-render':
      return {
        characterAsset: config.mobileCharacterAsset,
        // force-2d-render 与 static-character-portrait 共享 characterAsset 配置
        // 但语义不同：force-2d-render 聚焦"禁用 3D 渲染引擎"（Live2D 物理摆动关闭 / VRM 切 2D）
      };

    case 'viewport-lazy-mount':
      return {
        // IntersectionObserver 通用参数（无 C3 配置，本地默认值）
        lazyMountRootMargin: '200px',
        lazyMountThreshold: 0.01,
      };

    case 'virtual-list':
      return {
        // react-window 通用参数（无 C3 配置，本地默认值）
        virtualListThreshold: 50,
        virtualListOverscan: 3,
      };

    case 'transform-opacity-gpu':
      return {
        // will-change 通用参数（无 C3 配置，本地默认值）
        willChangeProperties: ['transform', 'opacity'],
      };

    case 'decoration-disable':
      return {
        complexMotionDisabled: config.mobileComplexMotionDisabled,
        gsapTimelineMaxElements: config.mobileGsapTimelineMaxElements,
        particleDensity: config.mobileParticleDensity,
        particleMaxAlpha: config.mobileParticleMaxAlpha,
      };

    default: {
      // 穷尽性检查（exhaustive check）：新增规则 key 未处理时编译报错
      const _exhaustive: never = key;
      return _exhaustive;
    }
  }
}

// ============================================================================
// 八、降级规则查询工具函数
// ============================================================================

/**
 * 根据规则 key 从规则列表中查找指定规则。
 *
 * @param rules - 降级规则列表
 * @param key - 规则 key
 * @returns 匹配的规则，未找到返回 null
 *
 * @example
 * ```ts
 * const rule = findRuleByKey(rules, 'webgl-force-tier-3');
 * if (rule?.enabled && rule.params.forceTier === 3) {
 *   useGlassTier().setTier(GlassTier.TIER_3);
 * }
 * ```
 */
export function findRuleByKey(
  rules: readonly MobileDegradeRule[],
  key: MobileDegradeRuleKey,
): MobileDegradeRule | null {
  return rules.find((r) => r.key === key) ?? null;
}

/**
 * 过滤出已启用的降级规则。
 *
 * @param rules - 降级规则列表
 * @returns 已启用的规则列表
 */
export function filterEnabledRules(
  rules: readonly MobileDegradeRule[],
): MobileDegradeRule[] {
  return rules.filter((r) => r.enabled);
}

/**
 * 统计已启用的降级规则数量。
 *
 * @param rules - 降级规则列表
 * @returns 已启用规则数（0-9）
 */
export function countEnabledRules(rules: readonly MobileDegradeRule[]): number {
  return rules.reduce((count, r) => count + (r.enabled ? 1 : 0), 0);
}
