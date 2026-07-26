/**
 * tier-detector.ts — Liquid Glass 四级 tier 检测器
 * ============================================================================
 * 模块: 模块4 WebGL 玻璃层
 * 契约: D2 glass_tier_config.schema.json (tiers) +
 *        C1 frontend_glass_config.schema.json (tierTriggers) +
 *        I1 frontend_glass.pyi (GlassTier enum)
 * 用途: 启动时按 tier1→tier4 顺序首次命中即定级，业务层通过 useGlassTier() 透明获取
 *
 * 四级 tier 降级（强制顺序，禁止跳级, D2 tiers + C1 tierTriggers）:
 *   - Tier 1: WebGL2 可用 + 桌面端 + GPU 性能充足（C1 tierTriggers.tier1）
 *   - Tier 2: WebGL2 不可用 + WebGL1 可用（C1 tierTriggers.tier2）
 *   - Tier 3: WebGL 不可用 / 移动端 / GPU 性能不足（C1 tierTriggers.tier3）
 *   - Tier 4: 老旧浏览器不支持 backdrop-filter（C1 tierTriggers.tier4）
 *
 * 降级路径（D2 exceptionContract degradeBehaviorRules 1）:
 *   Tier 1 → Tier 2 → Tier 3 → Tier 4，每级停留至少 30s 再尝试升级
 * ============================================================================
 */

// ============================================================================
// GlassTier 枚举（I1 frontend_glass.pyi GlassTier IntEnum）
// ============================================================================

/**
 * Liquid Glass 四级 tier 枚举（I1 GlassTier, merged.md §2.5）。
 *
 * TIER_1: WebGL2（完整效果：折射+色散+高光）
 * TIER_2: WebGL1（关闭色散层）
 * TIER_3: CSS backdrop-filter（blur(16px) saturate(1.8) + 多层 box-shadow）
 * TIER_4: background-color 半透明兜底
 */
export const GlassTier = {
  TIER_1: 1,
  TIER_2: 2,
  TIER_3: 3,
  TIER_4: 4,
} as const;

/** Tier 类型（1 | 2 | 3 | 4） */
export type GlassTier = (typeof GlassTier)[keyof typeof GlassTier];

// ============================================================================
// 检测结果类型
// ============================================================================

/**
 * Tier 检测结果（含检测到的 tier 和降级原因）。
 */
export interface TierDetectionResult {
  /** 检测到的 tier（1/2/3/4） */
  tier: GlassTier;
  /** 降级原因（如 "WEBGL2_UNAVAILABLE" / "MOBILE_VIEWPORT" / "GPU_UNDERPERFORMED" / "LEGACY_BROWSER"） */
  reason: string;
  /** WebGL2 是否可用 */
  webgl2Available: boolean;
  /** WebGL1 是否可用 */
  webgl1Available: boolean;
  /** 是否为移动端（< md 断点 768px） */
  isMobile: boolean;
  /** backdrop-filter 是否可用 */
  backdropFilterAvailable: boolean;
}

// ============================================================================
// 内部检测工具函数
// ============================================================================

/**
 * 检测 WebGL2 上下文是否可用。
 * 尝试在临时 canvas 上创建 webgl2 上下文（C1 tierTriggers.tier1.webgl2Available）。
 */
function detectWebGL2(): boolean {
  if (typeof document === 'undefined') return false;
  try {
    const canvas = document.createElement('canvas');
    const gl = canvas.getContext('webgl2');
    return gl !== null;
  } catch {
    return false;
  }
}

/**
 * 检测 WebGL1 上下文是否可用。
 * 尝试在临时 canvas 上创建 webgl 上下文（C1 tierTriggers.tier2.webgl1Available）。
 */
function detectWebGL1(): boolean {
  if (typeof document === 'undefined') return false;
  try {
    const canvas = document.createElement('canvas');
    const gl = canvas.getContext('webgl') ?? canvas.getContext('experimental-webgl');
    return gl !== null;
  } catch {
    return false;
  }
}

/**
 * 检测是否为移动端视口（< md 断点 768px）。
 * C1 tierTriggers.tier3.isMobile + D2 constraints.mobileDefaultTier = 3。
 */
function detectMobile(): boolean {
  if (typeof window === 'undefined' || !window.matchMedia) return false;
  return window.matchMedia('(max-width: 767px)').matches;
}

/**
 * 检测 CSS backdrop-filter 是否可用（含 -webkit- 前缀）。
 * C1 tierTriggers.tier4.backdropFilterUnsupported。
 */
function detectBackdropFilter(): boolean {
  if (typeof document === 'undefined') return false;
  const el = document.createElement('div');
  // 检测标准属性和 webkit 前缀
  return (
    'backdropFilter' in el.style ||
    'webkitBackdropFilter' in el.style
  );
}

// ============================================================================
// 桌面端检测（C1 tierTriggers.tier1.isDesktop）
// ============================================================================

/**
 * 检测是否为桌面端（非移动端 + 非触摸设备）。
 * C1 tierTriggers.tier1.isDesktop = true。
 */
function detectDesktop(): boolean {
  if (typeof window === 'undefined') return false;
  // 移动端视口检测
  if (detectMobile()) return false;
  // 触摸设备检测（补充判断）
  const hasTouch = 'ontouchstart' in window || navigator.maxTouchPoints > 0;
  // 桌面端：非移动视口 + 非触摸为主设备
  return !hasTouch || window.matchMedia('(pointer: fine)').matches;
}

// ============================================================================
// 主检测函数
// ============================================================================

/**
 * 检测当前环境应使用的 Liquid Glass tier。
 *
 * 检测顺序（强制，禁止跳级, D2 tiers + C1 tierTriggers）:
 *   1. Tier 1: WebGL2 可用 + 桌面端 → TIER_1
 *   2. Tier 2: WebGL2 不可用 + WebGL1 可用 → TIER_2
 *   3. Tier 3: WebGL 不可用 / 移动端 → TIER_3
 *   4. Tier 4: backdrop-filter 不可用 → TIER_4
 *
 * 注意：GPU 性能不足（连续 30 帧 drop > 10ms）由 PerformanceMonitor 运行时检测，
 *   此处仅做启动时静态检测。运行时降级由 useGlassTier + PerformanceMonitor 协同处理。
 *
 * @returns TierDetectionResult 检测结果
 */
export function detectTier(): TierDetectionResult {
  const webgl2Available = detectWebGL2();
  const webgl1Available = detectWebGL1();
  const isMobile = detectMobile();
  const backdropFilterAvailable = detectBackdropFilter();
  const isDesktop = detectDesktop();

  // Tier 1: WebGL2 可用 + 桌面端（C1 tierTriggers.tier1）
  // GPU 性能充足由 PerformanceMonitor 运行时检测，启动时假设充足
  if (webgl2Available && isDesktop) {
    return {
      tier: GlassTier.TIER_1,
      reason: 'WEBGL2_AVAILABLE_DESKTOP',
      webgl2Available,
      webgl1Available,
      isMobile,
      backdropFilterAvailable,
    };
  }

  // Tier 2: WebGL2 不可用 + WebGL1 可用（C1 tierTriggers.tier2）
  if (!webgl2Available && webgl1Available) {
    return {
      tier: GlassTier.TIER_2,
      reason: 'WEBGL2_UNAVAILABLE_WEBGL1_AVAILABLE',
      webgl2Available,
      webgl1Available,
      isMobile,
      backdropFilterAvailable,
    };
  }

  // Tier 3: WebGL 不可用 / 移动端（C1 tierTriggers.tier3）
  if (backdropFilterAvailable) {
    return {
      tier: GlassTier.TIER_3,
      reason: isMobile ? 'MOBILE_VIEWPORT' : 'WEBGL_UNAVAILABLE',
      webgl2Available,
      webgl1Available,
      isMobile,
      backdropFilterAvailable,
    };
  }

  // Tier 4: 老旧浏览器不支持 backdrop-filter（C1 tierTriggers.tier4）
  return {
    tier: GlassTier.TIER_4,
    reason: 'LEGACY_BROWSER',
    webgl2Available,
    webgl1Available,
    isMobile,
    backdropFilterAvailable,
  };
}

/**
 * 获取下一级降级 tier（强制顺序，禁止跳级）。
 *
 * 降级路径（D2 exceptionContract degradeBehaviorRules 1）:
 *   Tier 1 → Tier 2 → Tier 3 → Tier 4
 *
 * @param currentTier 当前 tier
 * @returns 下一级 tier，若已在 Tier 4 则返回 null（无法继续降级）
 */
export function getNextDowngradeTier(currentTier: GlassTier): GlassTier | null {
  switch (currentTier) {
    case GlassTier.TIER_1:
      return GlassTier.TIER_2;
    case GlassTier.TIER_2:
      return GlassTier.TIER_3;
    case GlassTier.TIER_3:
      return GlassTier.TIER_4;
    case GlassTier.TIER_4:
      return null; // 已在最低 tier，无法继续降级
    default:
      return null;
  }
}
