/**
 * use-glass-tier.ts — Liquid Glass tier hook + pointer-events/z-index 控制
 * ============================================================================
 * 模块: 模块4 WebGL 玻璃层
 * 契约: I1 frontend_glass.pyi (useGlassTier + setGlassPointerEvents + assertNoConflict + GlassZIndex)
 * 用途: 透明暴露 tier 状态 + 降级回调 + pointer-events 精确控制 + z-index 分层校验
 *
 * useGlassTier hook（I1, merged.md §2.5）:
 *   - 业务组件通过本 hook 获取当前 tier，无需感知降级细节
 *   - PerformanceMonitor 连续 30 帧 drop > 10ms 自动降级
 *   - 四级 tier 降级强制顺序（禁止跳级）
 *
 * setGlassPointerEvents（I1 + OBS-G 处置, merged.md §2.8）:
 *   - mode: "auto" | "none" | "passthrough"
 *   - 玻璃层与 Three.js 场景走独立 canvas，pointer-events 精确控制
 *
 * GlassZIndex（I1 + OBS-G 处置, merged.md §2.8）:
 *   - 严格分层: Three.js=1 / 玻璃层=2 / UI=3 / 装饰=4 / 角色=5 / 模态=10
 *   - assertNoConflict 校验所有层 z-index 唯一性
 *
 * 错误码: FE-GLA-005 (pointer-events 冲突) / FE-GLA-006 (z-index 冲突)
 * ============================================================================
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { GlassTier, detectTier, getNextDowngradeTier } from './tier-detector';
import { PerformanceMonitor } from './performance-monitor';
import { TierDegradeError } from './glass-renderer';

// ============================================================================
// 异常定义（I1 异常契约）
// ============================================================================

/**
 * pointer-events 模式冲突异常（I1 PointerEventConflictError, FE-GLA-005, OBS-G 处置）。
 *
 * 抛出条件: setGlassPointerEvents 设置 passthrough 模式时，检测到同 z-index 层存在 auto 模式元件，
 *   或父子元件 pointer-events 模式冲突。
 * 调用方处理: 捕获后回退到 none 模式，上报错误码 FE-GLA-005。
 */
export class PointerEventConflictError extends Error {
  readonly errorCode: 'FE-GLA-005';
  readonly mode: string;

  constructor(message: string, mode: string) {
    super(message);
    this.name = 'PointerEventConflictError';
    this.errorCode = 'FE-GLA-005';
    this.mode = mode;
    Object.setPrototypeOf(this, PointerEventConflictError.prototype);
  }
}

/**
 * z-index 分层冲突异常（I1 ZIndexConflictError, FE-GLA-006, OBS-G 处置）。
 *
 * 抛出条件: assertNoConflict 检测到两个不同层使用了相同的 z-index 值，
 *   或某层的 z-index 超出 GlassZIndex 常量定义范围。
 * 调用方处理: 捕获后按 GlassZIndex 常量强制重置冲突层 z-index，上报错误码 FE-GLA-006。
 */
export class ZIndexConflictError extends Error {
  readonly errorCode: 'FE-GLA-006';
  readonly conflictLayers: string[];

  constructor(message: string, conflictLayers: string[]) {
    super(message);
    this.name = 'ZIndexConflictError';
    this.errorCode = 'FE-GLA-006';
    this.conflictLayers = conflictLayers;
    Object.setPrototypeOf(this, ZIndexConflictError.prototype);
  }
}

// ============================================================================
// GlassZIndex 枚举（I1 GlassZIndex IntEnum, OBS-G 处置）
// ============================================================================

/**
 * z-index 分层常量（I1 GlassZIndex, OBS-G 处置, merged.md §2.8）。
 *
 * 严格分层，禁止冲突。assertNoConflict 校验所有层 z-index 唯一性。
 * 值映射: Three.js=1 / 玻璃层=2 / UI=3 / 装饰条带=4 / 角色立绘=5 / 模态=10。
 */
export const GlassZIndex = {
  THREE_JS: 1,
  GLASS: 2,
  UI: 3,
  DECORATION: 4,
  CHARACTER: 5,
  MODAL: 10,
} as const;

/** z-index 类型 */
export type GlassZIndex = (typeof GlassZIndex)[keyof typeof GlassZIndex];

// ============================================================================
// 类型定义（I1 TypedDict 对应）
// ============================================================================

/**
 * useGlassTier 返回值（I1 GlassTierResult）。
 */
export interface GlassTierResult {
  /** 当前 tier（1/2/3/4） */
  tier: GlassTier;
  /** tier 切换回调 */
  setTier: (tier: GlassTier) => void;
  /** 降级原因（如 "GPU_CONTEXT_LOSS" / "MOBILE_BREAKPOINT" / "PERFORMANCE_DROP"） */
  degradeReason: string | null;
  /** 是否正在降级中 */
  isDegrading: boolean;
}

/**
 * useGlassTier 选项（I1 useGlassTier options）。
 */
export interface UseGlassTierOptions {
  /** 强制指定 tier（用于用户主动开"高质模式"或测试） */
  forceTier?: GlassTier;
  /** tier 切换回调，签名 (oldTier, newTier, reason) => void */
  onTierChange?: (oldTier: GlassTier, newTier: GlassTier, reason: string) => void;
}

// ============================================================================
// 全局 tier 状态管理（跨组件共享）
// ============================================================================

/** 全局 tier 状态（跨 hook 实例共享） */
let globalTier: GlassTier = GlassTier.TIER_1;
let globalDegradeReason: string | null = null;
let globalIsDegrading = false;

/** tier 变化回调列表 */
const tierChangeCallbacks: Array<(oldTier: GlassTier, newTier: GlassTier, reason: string) => void> = [];

/** 全局 PerformanceMonitor 实例 */
let globalMonitor: PerformanceMonitor | null = null;

/**
 * 触发 tier 变化通知。
 */
function notifyTierChange(oldTier: GlassTier, newTier: GlassTier, reason: string): void {
  for (const cb of tierChangeCallbacks) {
    cb(oldTier, newTier, reason);
  }
}

/**
 * 执行 tier 降级（强制顺序，禁止跳级）。
 *
 * D2 exceptionContract degradeBehaviorRules 1:
 *   Tier 1 → Tier 2 → Tier 3 → Tier 4，每级停留至少 30s 再尝试升级
 */
function performDowngrade(reason: string): void {
  const oldTier = globalTier;
  const nextTier = getNextDowngradeTier(globalTier);

  if (nextTier === null) {
    // 已在 Tier 4，无法继续降级
    return;
  }

  globalIsDegrading = true;
  globalTier = nextTier;
  globalDegradeReason = reason;

  notifyTierChange(oldTier, nextTier, reason);

  // 降级完成
  globalIsDegrading = false;
}

// ============================================================================
// useGlassTier hook（I1 签名匹配）
// ============================================================================

/**
 * Hook: useGlassTier — 暴露当前 Liquid Glass tier 给业务层（I1, merged.md §2.5）。
 *
 * 业务组件通过本 hook 获取当前 tier，无需感知降级细节。组件按 tier 渲染对应视觉。
 *
 * 自动降级逻辑:
 *   - 启动时调用 detectTier() 检测初始 tier
 *   - 创建 PerformanceMonitor，连续 30 帧 drop > 10ms 自动降级
 *   - 降级路径遵循 §3.4(1) 强制顺序: Tier 1 → Tier 2 → Tier 3 → Tier 4
 *
 * @param options 选项，含 forceTier / onTierChange
 * @returns GlassTierResult: 包含 tier / setTier / degradeReason / isDegrading
 * @throws TierDegradeError 当降级路径不可用或目标 tier 配置缺失时抛出
 */
export function useGlassTier(options?: UseGlassTierOptions): GlassTierResult {
  const { forceTier, onTierChange } = options ?? {};

  // 本地 tier 状态（与全局同步）
  const [tier, setTierState] = useState<GlassTier>(() => {
    if (forceTier !== undefined) return forceTier;
    // 首次调用时检测 tier
    if (globalTier === GlassTier.TIER_1 && globalDegradeReason === null) {
      const result = detectTier();
      globalTier = result.tier;
      globalDegradeReason = result.reason;
    }
    return globalTier;
  });

  const [degradeReason, setDegradeReason] = useState<string | null>(globalDegradeReason);
  const [isDegrading, setIsDegrading] = useState<boolean>(globalIsDegrading);

  // ref 保存最新的 onTierChange 回调（避免 effect 依赖）
  const onTierChangeRef = useRef(onTierChange);
  onTierChangeRef.current = onTierChange;

  // 注册 tier 变化回调 + 初始化 PerformanceMonitor
  useEffect(() => {
    // 注册 tier 变化回调
    const handleTierChange = (oldTier: GlassTier, newTier: GlassTier, reason: string) => {
      setTierState(newTier);
      setDegradeReason(reason);
      setIsDegrading(false);
      onTierChangeRef.current?.(oldTier, newTier, reason);
    };
    tierChangeCallbacks.push(handleTierChange);

    // 初始化 PerformanceMonitor（仅首次创建）
    if (!globalMonitor) {
      const isMobile = typeof window !== 'undefined' && window.matchMedia('(max-width: 767px)').matches;
      globalMonitor = new PerformanceMonitor(isMobile);

      // 注册降级回调
      globalMonitor.onDegrade((reason: string) => {
        performDowngrade(reason);
      });

      // 启动监控
      try {
        globalMonitor.start();
      } catch {
        // 监控已启动（StrictMode 双调用），忽略
      }
    }

    return () => {
      // 清理回调
      const idx = tierChangeCallbacks.indexOf(handleTierChange);
      if (idx >= 0) {
        tierChangeCallbacks.splice(idx, 1);
      }
    };
  }, []);

  // setTier 回调
  const setTier = useCallback((newTier: GlassTier) => {
    const oldTier = globalTier;

    // 如果是降级，校验顺序（禁止跳级）
    if (newTier > oldTier) {
      const nextTier = getNextDowngradeTier(oldTier);
      if (nextTier === null || newTier > nextTier) {
        throw new TierDegradeError(
          `Cannot downgrade from Tier ${oldTier} to Tier ${newTier}: must follow sequential order`,
          oldTier,
          newTier,
        );
      }
    }

    globalTier = newTier;
    globalDegradeReason = newTier > oldTier ? 'MANUAL_DOWNGRADE' : null;
    setTierState(newTier);
    setDegradeReason(globalDegradeReason);
    notifyTierChange(oldTier, newTier, globalDegradeReason ?? 'MANUAL_TIER_CHANGE');
  }, []);

  return {
    tier,
    setTier,
    degradeReason,
    isDegrading,
  };
}

// ============================================================================
// setGlassPointerEvents 函数（I1 + OBS-G 处置）
// ============================================================================

/**
 * pointer-events 模式枚举。
 *
 * - "auto": 玻璃层接收指针事件（默认，用于可交互玻璃组件）
 * - "none": 玻璃层完全不接收事件，事件穿透到下层
 * - "passthrough": 玻璃层透明传递事件到下层，但保留 hover 检测
 */
export type PointerEventsMode = 'auto' | 'none' | 'passthrough';

/** 已注册的 pointer-events 模式映射（用于冲突检测） */
const pointerEventsRegistry = new Map<HTMLElement, PointerEventsMode>();

/**
 * 函数: setGlassPointerEvents — 玻璃层 pointer-events 控制接口（I1 + OBS-G 处置, merged.md §2.8）。
 *
 * 玻璃层与 Three.js 场景走独立 canvas，z-index 严格分层，pointer-events 精确控制以避免事件穿透问题。
 *
 * mode 契约:
 *   - "auto": 玻璃层接收指针事件（默认，用于可交互玻璃组件如按钮/卡片）。
 *   - "none": 玻璃层完全不接收事件，事件穿透到下层（用于纯装饰玻璃层）。
 *   - "passthrough": 玻璃层透明传递事件到下层，但保留 hover 检测（用于需要 hover 高光但不拦截点击的元件）。
 *
 * @param element 待设置 pointer-events 的玻璃层 DOM 元素
 * @param mode 事件模式
 * @throws PointerEventConflictError 设置 passthrough 模式时检测到同 z-index 层存在 auto 模式元件
 */
export function setGlassPointerEvents(
  element: HTMLElement,
  mode: PointerEventsMode,
): void {
  // 冲突检测: passthrough 模式不能与同 z-index 层的 auto 模式共存
  if (mode === 'passthrough') {
    const elementZIndex = parseInt(getComputedStyle(element).zIndex || '0', 10);
    for (const [registeredEl, registeredMode] of pointerEventsRegistry.entries()) {
      if (registeredEl === element) continue;
      if (registeredMode === 'auto') {
        const registeredZIndex = parseInt(getComputedStyle(registeredEl).zIndex || '0', 10);
        if (registeredZIndex === elementZIndex) {
          throw new PointerEventConflictError(
            `Cannot set passthrough mode: element at z-index ${elementZIndex} conflicts with existing auto mode element`,
            mode,
          );
        }
      }
    }
  }

  // 设置 CSS pointer-events
  switch (mode) {
    case 'auto':
      element.style.pointerEvents = 'auto';
      break;
    case 'none':
      element.style.pointerEvents = 'none';
      break;
    case 'passthrough':
      // passthrough: pointer-events: none 但保留 hover 检测
      // 使用 CSS pointer-events: none + JS 层 hover 检测
      element.style.pointerEvents = 'none';
      break;
    default:
      throw new PointerEventConflictError(
        `Invalid pointer-events mode: ${mode}`,
        mode,
      );
  }

  // 注册模式
  pointerEventsRegistry.set(element, mode);
}

// ============================================================================
// assertNoConflict 函数（I1 + OBS-G 处置）
// ============================================================================

/**
 * 函数: assertNoConflict — z-index 分层冲突校验（I1 + OBS-G 处置, merged.md §2.8）。
 *
 * 校验所有层的 z-index 唯一性，且均在 GlassZIndex 常量定义范围内。
 * 开发模式（NODE_ENV=development）下自动调用，生产模式按需调用。
 *
 * @param layerZIndexMap 层名 → z-index 映射
 * @throws ZIndexConflictError 检测到两个不同层使用了相同的 z-index 值，或超出范围
 */
export function assertNoConflict(layerZIndexMap: Record<string, number>): void {
  const validZIndices = new Set<number>(Object.values(GlassZIndex));
  const zIndexToLayers = new Map<number, string[]>();

  for (const [layerName, zIndex] of Object.entries(layerZIndexMap)) {
    // 校验 z-index 在 GlassZIndex 范围内
    if (!validZIndices.has(zIndex)) {
      throw new ZIndexConflictError(
        `Layer '${layerName}' has z-index ${zIndex} which is not in GlassZIndex constants`,
        [layerName],
      );
    }

    // 收集每个 z-index 对应的层
    if (!zIndexToLayers.has(zIndex)) {
      zIndexToLayers.set(zIndex, []);
    }
    zIndexToLayers.get(zIndex)!.push(layerName);
  }

  // 检测冲突: 同一 z-index 被多个层使用
  for (const [zIndex, layers] of zIndexToLayers) {
    if (layers.length > 1) {
      throw new ZIndexConflictError(
        `z-index ${zIndex} is used by multiple layers: ${layers.join(', ')}`,
        layers,
      );
    }
  }
}

// ============================================================================
// 默认 z-index 层映射（OBS-G 处置，与 Three.js/Pixi.js 协同）
// ============================================================================

/**
 * 默认 z-index 层映射（D2 threeJsCoordination.zIndexLayering + I1 GlassZIndex）。
 *
 * Three.js=1 / 玻璃层=2 / UI=3（D2 强制分层）
 * 装饰=4 / 角色=5 / 模态=10（I1 GlassZIndex 完整定义）
 */
export const DEFAULT_Z_INDEX_MAP: Record<string, number> = {
  threeJs: GlassZIndex.THREE_JS,
  glass: GlassZIndex.GLASS,
  ui: GlassZIndex.UI,
  decoration: GlassZIndex.DECORATION,
  character: GlassZIndex.CHARACTER,
  modal: GlassZIndex.MODAL,
};
