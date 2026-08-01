/**
 * @file use-mobile-degradation.ts
 * @module 模块9b/移动端降级层
 *
 * 移动端降级组合 hook。组合 useBreakpoint + useMobileDetect + mobile-degradation，
 * 并调用模块4 useGlassTier.setTier 执行 tier 降级（降级规则 1：WebGL 强制 Tier 3）。
 *
 * 契约对齐：
 * - 数据契约 D6 responsive_breakpoints.schema.json §mobileDegrades（9 项 + triggerCondition）
 * - 配置契约 C3 frontend_responsive_config.schema.json §mobileDegrade（8 项参数，配置驱动）
 * - 错误码契约 E1 frontend_error_codes.schema.json FE-RES-003（移动端降级失败 响应式层）
 * - 模块4 契约 I1 frontend_glass.pyi useGlassTier（tier 切换接口）
 *
 * 跨模块导入（AGENTS.md §4.3）：
 * - 允许：模块9a（useBreakpoint / useMobileDetect / breakpoints 常量）
 * - 允许：模块4 useGlassTier + GlassTier 枚举（仅限契约接口，用于 tier 切换）
 * - 禁止：模块1/2/3/5/6/7/8 任何内部实现（横切层不得反向依赖业务模块）
 *
 * tier 降级顺序约束（D2 exceptionContract degradeBehaviorRules 1）：
 * - useGlassTier.setTier 禁止跳级（Tier 1 → Tier 2 → Tier 3 → Tier 4）
 * - 移动端降级目标为 Tier 3，若当前 Tier 1 则逐级降级（Tier 1 → Tier 2 → Tier 3）
 * - 每级 setTier 调用后 globalTier 同步更新，支持循环内连续降级
 *
 * @example 基础用法
 * ```tsx
 * import { useMobileDegrade } from '@/lib/responsive/use-mobile-degradation';
 *
 * function App() {
 *   const { isDegrading, rules, currentTier } = useMobileDegrade();
 *
 *   if (isDegrading) {
 *     // 应用 9 项降级规则
 *     const webglRule = rules.find(r => r.key === 'webgl-force-tier-3');
 *     console.log(`Mobile degrade active, tier=${currentTier}`);
 *   }
 *
 *   return <main>...</main>;
 * }
 * ```
 *
 * @example 配置驱动（消费 C3）
 * ```tsx
 * const { config, actions } = useMobileDegrade({
 *   config: { mobileDefaultTier: 3, mobileParticleDensity: 0.1 },
 * });
 * ```
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

// ============================================================================
// 本地 GlassTier 定义（原 @/lib/glass 旧 tier 系统已于波5删除）
// 新架构（LiquidGlassHost）自身处理 WebGL 降级与移动端适配，
// 此处保留 GlassTier/useGlassTier 仅用于 useMobileDegrade hook 的 API 兼容。
// ============================================================================

/**
 * Liquid Glass 四级 tier 枚举（本地兼容定义）。
 * 新架构不再使用 tier 降级，保留以维持 useMobileDegrade 返回值类型完整性。
 */
const GlassTier = {
  TIER_1: 1,
  TIER_2: 2,
  TIER_3: 3,
  TIER_4: 4,
} as const;

/** Tier 类型（1 | 2 | 3 | 4） */
type GlassTier = (typeof GlassTier)[keyof typeof GlassTier];

/**
 * useGlassTier 本地兼容 stub（原 use-glass-tier.ts 已于波5删除）。
 * 新架构由 LiquidGlassHost 自身处理降级，此 stub 仅提供 tier 状态读写，
 * setTier 仅更新本地 state，不触发任何全局副作用。
 */
function useGlassTier(): {
  tier: GlassTier;
  setTier: (tier: GlassTier) => void;
  degradeReason: string | null;
  isDegrading: boolean;
} {
  const [tier, setTier] = useState<GlassTier>(GlassTier.TIER_1);
  return { tier, setTier, degradeReason: null, isDegrading: false };
}

// 模块9a 产出（同模块内部）
import { useBreakpoint } from './use-breakpoint';
import { useMobileDetect } from './use-mobile-detect';

// 模块9b 产出
import {
  buildMobileDegradeRules,
  DEFAULT_MOBILE_DEGRADE_CONFIG,
  type MobileDegradeConfig,
  type MobileDegradeRule,
  type MobileDegradeRuleKey,
  type MobileDegradeRuleParams,
} from './degradation-rules';
import {
  buildDegradeActions,
  mergeWithDefaults,
  MobileDegradeError,
  shouldApplyMobileDegrade,
  type DegradeAction,
} from './mobile-degradation';

// ============================================================================
// 一、hook 选项与返回值类型
// ============================================================================

/**
 * useMobileDegrade hook 选项。
 */
export interface UseMobileDegradeOptions {
  /**
   * 移动端降级配置（部分）。与 DEFAULT_MOBILE_DEGRADE_CONFIG 合并（merge-with-defaults）。
   *
   * 配置驱动（rules-3 §三）：所有降级参数从 config 读取，不硬编码。
   * 缺失字段以 C3 default 值补齐。
   */
  config?: Partial<MobileDegradeConfig>;

  /**
   * 降级动作执行回调。每项降级规则应用时触发，供业务方按分类消费。
   *
   * @param ruleKey - 规则 key
   * @param action - 降级动作描述
   */
  onDegrade?: (ruleKey: MobileDegradeRuleKey, action: DegradeAction) => void;

  /**
   * 降级失败回调。降级异常时触发（FE-RES-003）。
   *
   * @param error - 降级异常
   */
  onError?: (error: MobileDegradeError) => void;
}

/**
 * useMobileDegrade hook 返回值。
 */
export interface UseMobileDegradeResult {
  /**
   * 是否触发移动端降级。
   *
   * 触发条件（对齐 D6 mobileDegrades.triggerCondition）：
   * - useMobileDetect().isMobile === true（UA 移动 || 视口 < 768px）
   * - 或 shouldApplyMobileDegrade() === true（matchMedia('(max-width: 767px)') 匹配）
   *
   * SSR 环境返回 false（桌面端为主战场，不降级）。
   */
  isDegrading: boolean;

  /** 9 项降级规则列表（顺序固定 1-9） */
  rules: MobileDegradeRule[];

  /** 合并默认值后的完整降级配置（对齐 C3 mobileDegrade） */
  config: MobileDegradeConfig;

  /** 降级动作清单（仅 enabled 规则，供业务方按 category 路由消费） */
  actions: DegradeAction[];

  /** 当前 Glass tier（来自 useGlassTier，1/2/3/4） */
  currentTier: GlassTier;

  /** 目标 tier（移动端降级目标，对齐 C3 mobileDefaultTier，默认 TIER_3） */
  targetTier: GlassTier;

  /** 降级触发原因（"MOBILE_BREAKPOINT" 或 null） */
  degradeReason: string | null;

  /** 是否降级失败（FE-RES-003） */
  hasError: boolean;

  /** 降级失败异常（hasError=true 时非 null） */
  error: MobileDegradeError | null;

  /** 便捷查询：指定规则是否启用 */
  isRuleEnabled: (key: MobileDegradeRuleKey) => boolean;

  /** 便捷查询：指定规则的参数（未找到返回 null） */
  getRuleParams: (key: MobileDegradeRuleKey) => MobileDegradeRuleParams | null;
}

// ============================================================================
// 二、tier 逐级降级辅助（遵循 useGlassTier 禁止跳级约束）
// ============================================================================

/**
 * 逐级降级到目标 tier。
 *
 * useGlassTier.setTier 禁止跳级（D2 exceptionContract degradeBehaviorRules 1），
 * 若当前 tier 与目标 tier 跨度 > 1，需逐级调用 setTier。
 *
 * globalTier 在 setTier 调用后同步更新（use-glass-tier.ts setTier 实现），
 * 因此循环内连续调用 setTier 时，每次 oldTier 读取的是最新 globalTier。
 *
 * @param currentTier - 当前 tier（hook 返回的 React state）
 * @param targetTier - 目标 tier
 * @param setTier - useGlassTier.setTier 回调
 * @returns 实际降级到的 tier（可能因异常提前终止）
 */
function downgradeToTier(
  currentTier: GlassTier,
  targetTier: GlassTier,
  setTier: (tier: GlassTier) => void,
): GlassTier {
  // 已经在目标或更低 tier，无需降级
  if (currentTier >= targetTier) {
    return currentTier;
  }

  let current = currentTier;
  while (current < targetTier) {
    // 下一级 tier = current + 1（GlassTier.TIER_1=1, TIER_2=2, TIER_3=3, TIER_4=4）
    const next = (current + 1) as GlassTier;
    try {
      setTier(next);
      current = next;
    } catch {
      // setTier 抛异常（TierDegradeError 或其他），终止降级
      break;
    }
  }
  return current;
}

// ============================================================================
// 三、useMobileDegrade hook
// ============================================================================

/**
 * 移动端降级组合 hook。
 *
 * 组合 useBreakpoint + useMobileDetect 检测移动端，加载降级配置（C3 配置驱动），
 * 构建 9 项降级规则，并调用 useGlassTier.setTier 执行 tier 降级。
 *
 * 特性：
 * - 配置驱动：消费 C3 mobileDegrade 8 项参数（merge-with-defaults）
 * - 9 项降级规则：对齐闭合判据 + D6 mobileDegrades.items
 * - tier 降级：移动端触发时调用 useGlassTier.setTier(TIER_3)，逐级降级
 * - 错误处理：降级失败抛 FE-RES-003（MobileDegradeError），通过 onError 回调上报
 * - SSR 安全：服务端返回 isDegrading=false，不执行 tier 降级
 *
 * @param options - hook 选项（config / onDegrade / onError）
 * @returns 降级状态与规则
 *
 * @example
 * ```tsx
 * function GlassPanel() {
 *   const { isDegrading, currentTier, getRuleParams } = useMobileDegrade();
 *
 *   const blurParams = getRuleParams('backdrop-filter-cap');
 *   const blurValue = isDegrading ? blurParams?.blurValue : 'blur(24px) saturate(1.8)';
 *
 *   return <div style={{ backdropFilter: blurValue }}>...</div>;
 * }
 * ```
 */
export function useMobileDegrade(options?: UseMobileDegradeOptions): UseMobileDegradeResult {
  const { config: partialConfig, onDegrade, onError } = options ?? {};

  // 模块9a：断点 + 移动端检测
  const { isMobile: isMobileByBreakpoint } = useBreakpoint();
  const { isMobile: isMobileByDetect } = useMobileDetect();

  // 模块4：Glass tier（AGENTS.md §4.3 允许：仅限 tier 切换接口）
  const { tier: currentTier, setTier } = useGlassTier();

  // ref 保存最新回调（避免 effect 依赖；必须在 useState 初始化前声明以避免 TDZ）
  const onDegradeRef = useRef(onDegrade);
  onDegradeRef.current = onDegrade;
  const onErrorRef = useRef(onError);
  onErrorRef.current = onError;

  // 降级配置（合并默认值 + 校验）
  const [mergedConfig, setMergedConfig] = useState<MobileDegradeConfig>(() => {
    try {
      return mergeWithDefaults(partialConfig ?? {});
    } catch (err) {
      // 配置校验失败，使用默认配置并记录错误
      const configError =
        err instanceof MobileDegradeError
          ? err
          : new MobileDegradeError(
              'Failed to merge mobile degrade config',
              { failureType: 'config-invalid' },
            );
      onErrorRef.current?.(configError);
      return DEFAULT_MOBILE_DEGRADE_CONFIG;
    }
  });

  // 错误状态
  const [error, setError] = useState<MobileDegradeError | null>(null);

  // config 变化时重新合并
  useEffect(() => {
    try {
      const merged = mergeWithDefaults(partialConfig ?? {});
      setMergedConfig(merged);
      setError(null);
    } catch (err) {
      const e =
        err instanceof MobileDegradeError
          ? err
          : new MobileDegradeError('Config validation failed', { failureType: 'config-invalid' });
      setError(e);
      onErrorRef.current?.(e);
    }
  }, [partialConfig]);

  // 降级触发判定（对齐 D6 mobileDegrades.triggerCondition）
  const isDegrading: boolean = isMobileByBreakpoint || isMobileByDetect || shouldApplyMobileDegrade();

  // 目标 tier（对齐 C3 mobileDefaultTier，默认 TIER_3）
  const targetTier: GlassTier = mergedConfig.mobileDefaultTier as GlassTier;

  // 构建 9 项降级规则（useMemo 保证配置不变时引用稳定）
  const rules: MobileDegradeRule[] = useMemo(
    () => buildMobileDegradeRules(mergedConfig),
    [mergedConfig],
  );

  // 构建降级动作清单
  const actions: DegradeAction[] = useMemo(() => buildDegradeActions(rules), [rules]);

  // tier 降级 effect：移动端触发时逐级降级到 targetTier
  useEffect(() => {
    if (!isDegrading) return;
    if (currentTier >= targetTier) return; // 已在目标或更低 tier

    try {
      const reached = downgradeToTier(currentTier, targetTier, setTier);
      if (reached < targetTier) {
        // 降级未达目标，记录警告但不抛异常（可能因 useGlassTier 顺序约束）
        console.warn(
          `[FE-RES-003] Mobile degrade: tier only reached ${reached}, target ${targetTier}. ` +
            'May be blocked by useGlassTier sequential downgrade constraint.'
        );
      }

      // 触发 tier 降级动作回调（降级规则 1：webgl-force-tier-3）
      const tierAction = actions.find((a) => a.ruleKey === 'webgl-force-tier-3');
      if (tierAction) {
        onDegradeRef.current?.('webgl-force-tier-3', tierAction);
      }
    } catch (err) {
      // setTier 抛异常（TierDegradeError 或其他）→ 转为 MobileDegradeError
      const mobileErr = new MobileDegradeError(
        `[FE-RES-003] Mobile degrade tier switch failed: ${err instanceof Error ? err.message : String(err)}`,
        { ruleKey: 'webgl-force-tier-3', failureType: 'apply-failed' },
      );
      setError(mobileErr);
      onErrorRef.current?.(mobileErr);
    }
  }, [isDegrading, currentTier, targetTier, setTier, actions]);

  // 便捷查询函数
  const isRuleEnabled = useCallback(
    (key: MobileDegradeRuleKey): boolean => {
      const rule = rules.find((r) => r.key === key);
      return rule?.enabled ?? false;
    },
    [rules],
  );

  const getRuleParams = useCallback(
    (key: MobileDegradeRuleKey): MobileDegradeRuleParams | null => {
      const rule = rules.find((r) => r.key === key);
      return rule?.params ?? null;
    },
    [rules],
  );

  return {
    isDegrading,
    rules,
    config: mergedConfig,
    actions,
    currentTier,
    targetTier,
    degradeReason: isDegrading ? 'MOBILE_BREAKPOINT' : null,
    hasError: error !== null,
    error,
    isRuleEnabled,
    getRuleParams,
  };
}

// ============================================================================
// 四、便捷 hook
// ============================================================================

/**
 * useIsMobileDegrade 返回值类型。
 */
export interface UseIsMobileDegradeResult {
  /** 是否触发移动端降级 */
  isDegrading: boolean;
  /** 当前 Glass tier */
  currentTier: GlassTier;
  /** 目标 tier（移动端 TIER_3） */
  targetTier: GlassTier;
}

/**
 * 移动端降级便捷 hook（仅返回降级状态，不执行 tier 切换）。
 *
 * 供只需要判定是否降级的场景（如组件按 isDegrading 切换样式），
 * 不触发 tier 切换副作用。如需执行 tier 降级，请使用 useMobileDegrade。
 *
 * @returns { isDegrading, currentTier, targetTier }
 *
 * @example
 * ```tsx
 * import { useIsMobileDegrade } from '@/lib/responsive/use-mobile-degradation';
 *
 * function Card() {
 *   const { isDegrading } = useIsMobileDegrade();
 *   return <div className={isDegrading ? 'mobile-degraded' : 'desktop-full'} />;
 * }
 * ```
 */
export function useIsMobileDegrade(): UseIsMobileDegradeResult {
  const { isMobile: isMobileByBreakpoint } = useBreakpoint();
  const { isMobile: isMobileByDetect } = useMobileDetect();
  const { tier: currentTier } = useGlassTier();

  const isDegrading: boolean =
    isMobileByBreakpoint || isMobileByDetect || shouldApplyMobileDegrade();

  return {
    isDegrading,
    currentTier,
    targetTier: GlassTier.TIER_3,
  };
}
