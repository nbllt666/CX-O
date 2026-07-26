/**
 * @file use-mobile-detect.ts
 * @module 模块9a/响应式断点层
 *
 * 移动端设备检测 hook。综合 UA 检测、视口宽度、触摸能力、hover 能力、pointer 精度
 * 多维度判定设备类型，供触摸适配与移动端降级（9b）消费。
 *
 * 契约对齐：
 * - 移动端视口判定对齐 D6 mobileDegrades.triggerCondition "matchMedia('(max-width: 767px)')"
 * - hover 降级对齐 D6 touchAdaptation.hoverDegradeOnCoarsePointer.mediaQuery "(pointer: coarse)"
 * - hover 支持 detection 对齐 D6 touchAdaptation（hover:hover 设备才展示 hover 态）
 * - 最小点击区域对齐 D6 touchAdaptation.minTapTarget 44×44px（Apple HIG）
 *
 * SSR 安全：
 * - 服务端渲染时所有检测值返回 false / 默认值
 * - 客户端 hydration 后自动切换为真实检测值
 * - useSyncExternalStore 保证水合一致性
 *
 * @example 基础用法
 * ```tsx
 * import { useMobileDetect } from '@/lib/responsive/use-mobile-detect';
 *
 * function Button() {
 *   const { isTouch, hasHover } = useMobileDetect();
 *
 *   // 触摸设备：增大点击区域到 44×44px（Apple HIG）
 *   const minSize = isTouch ? 44 : 'auto';
 *
 *   // 无 hover 能力：用 active 态替代 hover 态
 *   const interactionClass = hasHover ? 'hover:bg-gray-100' : 'active:bg-gray-200';
 *
 *   return <button style={{ minWidth: minSize, minHeight: minSize }} />;
 * }
 * ```
 *
 * @example 移动端综合判定
 * ```tsx
 * const { isMobile, isMobileByUA, isMobileByViewport } = useMobileDetect();
 *
 * // isMobile = isMobileByUA || isMobileByViewport
 * // 桌面浏览器缩小窗口 → isMobileByViewport=true → isMobile=true（触发移动端布局）
 * // 手机访问 → isMobileByUA=true → isMobile=true
 * if (isMobile) {
 *   applyMobileDegradeStrategies(); // 9b 移动端降级 9 项
 * }
 * ```
 */

import { useSyncExternalStore } from 'react';

import {
  COARSE_POINTER_MEDIA_QUERY,
  HOVER_MEDIA_QUERY,
  MOBILE_MEDIA_QUERY,
} from './breakpoints';

// ============================================================================
// 一、UA 检测（静态值，客户端不变）
// ============================================================================

/**
 * 移动设备 UA 正则表达式。
 *
 * 覆盖主流移动设备：Android / iPhone / iPad / iPod / Windows Phone / BlackBerry 等。
 * 注意：iPadOS 13+ 的 UA 伪装为 macOS，需配合 maxTouchPoints 检测。
 */
const MOBILE_UA_PATTERN =
  /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini|Mobile|Tablet/i;

/**
 * UA 检测是否移动设备。
 *
 * 模块级缓存，同一会话内只检测一次。
 * SSR 环境返回 false。
 *
 * @returns UA 是否匹配移动设备
 */
function detectMobileByUA(): boolean {
  if (typeof window === 'undefined' || typeof navigator === 'undefined') {
    return false;
  }
  return MOBILE_UA_PATTERN.test(navigator.userAgent);
}

/**
 * 检测是否触摸设备。
 *
 * 检测条件（任一满足即为触摸设备）：
 * - 'ontouchstart' in window（支持触摸事件）
 * - navigator.maxTouchPoints > 0（有多点触控能力）
 *
 * 注意：部分二合一笔记本的触摸屏也会返回 true。
 * 模块级缓存，同一会话内只检测一次。
 * SSR 环境返回 false。
 *
 * @returns 是否触摸设备
 */
function detectTouchDevice(): boolean {
  if (typeof window === 'undefined' || typeof navigator === 'undefined') {
    return false;
  }
  return 'ontouchstart' in window || navigator.maxTouchPoints > 0;
}

// ============================================================================
// 二、动态检测快照（matchMedia 订阅）
// ============================================================================

/**
 * 动态检测快照类型。包含需要订阅 matchMedia 变化的检测值。
 */
interface DynamicDetectSnapshot {
  /** 视口是否 < 768px（移动端视口，对齐 D6 mobileDegrades.triggerCondition） */
  isMobileByViewport: boolean;
  /** 是否支持 hover（鼠标/触控笔，对齐 D6 touchAdaptation.hoverDegradeOnCoarsePointer） */
  hasHover: boolean;
  /** 是否 coarse pointer（触摸屏，对齐 D6 touchAdaptation.hoverDegradeOnCoarsePointer.mediaQuery） */
  isCoarsePointer: boolean;
}

/**
 * 静态检测快照类型。包含设备特性（客户端不变）。
 */
interface StaticDetectSnapshot {
  /** UA 检测是否移动设备 */
  isMobileByUA: boolean;
  /** 是否触摸设备 */
  isTouch: boolean;
}

/**
 * SSR 环境下的动态检测快照（全部为安全默认值）。
 */
const SSR_DYNAMIC_SNAPSHOT: DynamicDetectSnapshot = {
  isMobileByViewport: false,
  hasHover: false,
  isCoarsePointer: false,
};

/**
 * SSR 环境下的静态检测快照（全部为 false）。
 */
const SSR_STATIC_SNAPSHOT: StaticDetectSnapshot = {
  isMobileByUA: false,
  isTouch: false,
};

// 模块级快照缓存（保证 useSyncExternalStore getSnapshot 返回稳定引用）
let cachedDynamicSnapshot: DynamicDetectSnapshot = SSR_DYNAMIC_SNAPSHOT;
let cachedDynamicKey = '';
let cachedStaticSnapshot: StaticDetectSnapshot = SSR_STATIC_SNAPSHOT;
let cachedStaticKey = '';

/**
 * 获取动态检测快照。
 *
 * 查询 3 个 matchMedia（mobile/hover/coarse），组合为快照对象。
 * 使用模块级缓存保证相同状态返回相同引用（useSyncExternalStore 要求）。
 */
function getDynamicSnapshot(): DynamicDetectSnapshot {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return SSR_DYNAMIC_SNAPSHOT;
  }

  const isMobileByViewport = window.matchMedia(MOBILE_MEDIA_QUERY).matches;
  const hasHover = window.matchMedia(HOVER_MEDIA_QUERY).matches;
  const isCoarsePointer = window.matchMedia(COARSE_POINTER_MEDIA_QUERY).matches;

  const key = `${isMobileByViewport}:${hasHover}:${isCoarsePointer}`;
  if (key !== cachedDynamicKey) {
    cachedDynamicKey = key;
    cachedDynamicSnapshot = {
      isMobileByViewport,
      hasHover,
      isCoarsePointer,
    };
  }
  return cachedDynamicSnapshot;
}

/**
 * 获取静态检测快照。
 *
 * 检测 UA + 触摸能力，组合为快照对象。
 * 使用模块级缓存保证相同状态返回相同引用。
 */
function getStaticSnapshot(): StaticDetectSnapshot {
  if (typeof window === 'undefined') {
    return SSR_STATIC_SNAPSHOT;
  }

  const isMobileByUA = detectMobileByUA();
  const isTouch = detectTouchDevice();

  const key = `${isMobileByUA}:${isTouch}`;
  if (key !== cachedStaticKey) {
    cachedStaticKey = key;
    cachedStaticSnapshot = { isMobileByUA, isTouch };
  }
  return cachedStaticSnapshot;
}

/**
 * 订阅动态检测变化（3 个 matchMedia）。
 */
function subscribeDynamicDetect(callback: () => void): () => void {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return () => {};
  }

  const mqls = [
    window.matchMedia(MOBILE_MEDIA_QUERY),
    window.matchMedia(HOVER_MEDIA_QUERY),
    window.matchMedia(COARSE_POINTER_MEDIA_QUERY),
  ];
  const handler = () => callback();

  mqls.forEach((mql) => mql.addEventListener('change', handler));
  return () => {
    mqls.forEach((mql) => mql.removeEventListener('change', handler));
  };
}

/**
 * 订阅静态检测变化（noop，静态值不变）。
 *
 * useSyncExternalStore 在 hydration 后会自动检测 getSnapshot 与 getServerSnapshot
 * 的差异并触发 re-render，因此不需要实际订阅。
 */
function subscribeStaticDetect(): () => void {
  return () => {};
}

// ============================================================================
// 三、useMobileDetect hook
// ============================================================================

/**
 * useMobileDetect 返回值类型。
 */
export interface UseMobileDetectResult {
  /**
   * 是否移动设备（综合判定：UA 移动 || 视口 < 768）。
   *
   * 桌面浏览器缩小窗口到 < 768px 时也会返回 true（触发移动端布局）。
   * 对齐 D6 mobileDegrades.triggerCondition。
   */
  isMobile: boolean;

  /**
   * UA 检测是否移动设备。
   *
   * 基于 navigator.userAgent 正则匹配。
   * 注意：iPadOS 13+ UA 伪装为 macOS，可能返回 false（需配合 isTouch 判定）。
   */
  isMobileByUA: boolean;

  /**
   * 视口是否 < 768px（移动端视口）。
   *
   * 对齐 D6 mobileDegrades.triggerCondition "matchMedia('(max-width: 767px)')"。
   * 订阅 matchMedia 变化，窗口缩放时自动更新。
   */
  isMobileByViewport: boolean;

  /**
   * 是否触摸设备。
   *
   * 检测条件（任一满足）：
   * - 'ontouchstart' in window
   * - navigator.maxTouchPoints > 0
   *
   * 注意：二合一笔记本的触摸屏也会返回 true。
   */
  isTouch: boolean;

  /**
   * 是否支持 hover。
   *
   * matchMedia('(hover: hover)') 检测。
   * 鼠标/触控笔设备返回 true，纯触摸设备返回 false。
   * 对齐 D6 touchAdaptation.hoverDegradeOnCoarsePointer。
   */
  hasHover: boolean;

  /**
   * 是否 coarse pointer（触摸屏）。
   *
   * matchMedia('(pointer: coarse)') 检测。
   * 触摸屏返回 true，鼠标设备返回 false。
   * 对齐 D6 touchAdaptation.hoverDegradeOnCoarsePointer.mediaQuery。
   */
  isCoarsePointer: boolean;
}

/**
 * 移动端设备检测 hook。
 *
 * 综合 UA 检测、视口宽度、触摸能力、hover 能力、pointer 精度多维度判定设备类型。
 * 基于 React 18 useSyncExternalStore 订阅 matchMedia 变化，SSR 安全。
 *
 * 检测维度：
 * - isMobile：综合判定（UA 移动 || 视口 < 768）
 * - isMobileByUA：UA 检测
 * - isMobileByViewport：视口 < 768
 * - isTouch：触摸设备
 * - hasHover：支持 hover
 * - isCoarsePointer：coarse pointer（触摸屏）
 *
 * @returns 设备检测信息对象
 *
 * @example 触摸适配
 * ```tsx
 * function TouchTarget({ children }) {
 *   const { isTouch } = useMobileDetect();
 *   // Apple HIG: 触摸设备最小点击区域 44×44px
 *   const style = isTouch
 *     ? { minWidth: 44, minHeight: 44 }
 *     : undefined;
 *   return <button style={style}>{children}</button>;
 * }
 * ```
 *
 * @example hover 降级
 * ```tsx
 * function HoverCard() {
 *   const { hasHover } = useMobileDetect();
 *   // 无 hover 能力时用 active 态替代
 *   return <div className={hasHover ? 'hover:shadow-lg' : 'active:shadow-lg'} />;
 * }
 * ```
 */
export function useMobileDetect(): UseMobileDetectResult {
  const dynamic = useSyncExternalStore(
    subscribeDynamicDetect,
    getDynamicSnapshot,
    () => SSR_DYNAMIC_SNAPSHOT
  );

  const staticDetect = useSyncExternalStore(
    subscribeStaticDetect,
    getStaticSnapshot,
    () => SSR_STATIC_SNAPSHOT
  );

  const isMobile: boolean = staticDetect.isMobileByUA || dynamic.isMobileByViewport;

  return {
    isMobile,
    isMobileByUA: staticDetect.isMobileByUA,
    isMobileByViewport: dynamic.isMobileByViewport,
    isTouch: staticDetect.isTouch,
    hasHover: dynamic.hasHover,
    isCoarsePointer: dynamic.isCoarsePointer,
  };
}

// ============================================================================
// 四、便捷 hook
// ============================================================================

/**
 * useIsMobile 返回值类型。
 */
export interface UseIsMobileResult {
  /** 是否移动设备（UA 移动 || 视口 < 768） */
  isMobile: boolean;
}

/**
 * 移动端检测便捷 hook（仅返回 isMobile）。
 *
 * 供只需要移动端判定的场景，减少不必要的 re-render。
 * 只在 isMobile 状态变化时触发 re-render。
 *
 * @returns { isMobile } 是否移动设备
 *
 * @example
 * ```tsx
 * import { useIsMobile } from '@/lib/responsive/use-mobile-detect';
 *
 * function Layout() {
 *   const { isMobile } = useIsMobile();
 *   return isMobile ? <MobileNav /> : <DesktopNav />;
 * }
 * ```
 */
export function useIsMobile(): UseIsMobileResult {
  const dynamic = useSyncExternalStore(
    subscribeDynamicDetect,
    getDynamicSnapshot,
    () => SSR_DYNAMIC_SNAPSHOT
  );

  const staticDetect = useSyncExternalStore(
    subscribeStaticDetect,
    getStaticSnapshot,
    () => SSR_STATIC_SNAPSHOT
  );

  const isMobile: boolean = staticDetect.isMobileByUA || dynamic.isMobileByViewport;
  return { isMobile };
}

/**
 * useIsTouch 返回值类型。
 */
export interface UseIsTouchResult {
  /** 是否触摸设备 */
  isTouch: boolean;
}

/**
 * 触摸设备检测便捷 hook（仅返回 isTouch）。
 *
 * 供只需要触摸判定的场景（如触摸适配），减少不必要的 re-render。
 *
 * @returns { isTouch } 是否触摸设备
 *
 * @example
 * ```tsx
 * import { useIsTouch } from '@/lib/responsive/use-mobile-detect';
 *
 * function Button() {
 *   const { isTouch } = useIsTouch();
 *   return <button style={isTouch ? { minHeight: 44 } : undefined} />;
 * }
 * ```
 */
export function useIsTouch(): UseIsTouchResult {
  const staticDetect = useSyncExternalStore(
    subscribeStaticDetect,
    getStaticSnapshot,
    () => SSR_STATIC_SNAPSHOT
  );
  return { isTouch: staticDetect.isTouch };
}
