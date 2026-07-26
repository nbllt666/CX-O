/**
 * @file use-breakpoint.ts
 * @module 模块9a/响应式断点层
 *
 * 响应式断点检测 hook。基于 React 18 useSyncExternalStore 订阅 window.matchMedia，
 * 实时检测当前视口所属断点（sm/md/lg/xl/2xl），并提供 isAtLeast / isMobile / isDesktop
 * 便捷判定。
 *
 * 契约对齐：
 * - 断点值对齐 D6 responsive_breakpoints.schema.json（sm 640 / md 768 / lg 1024 / xl 1280 / 2xl 1536）
 * - 移动端判定对齐 D6 mobileDegrades.triggerCondition "matchMedia('(max-width: 767px)')"
 * - 桌面端为主战场对齐 spec §四裁决 + merged.md §6.1（lg 1024 为桌面主战场起点）
 * - prefers-reduced-motion 对齐 merged.md §3.5 克制原则与失败回退锚点
 * - 错误码 FE-RES-001 对齐 C3 errorCodes.breakpointDetectFailed（fallback-to-desktop）
 *
 * SSR 安全：
 * - 服务端渲染时 typeof window === 'undefined'，返回 DEFAULT_BREAKPOINT（'lg'）
 * - getServerSnapshot 返回固定值，避免水合不匹配（FOUC）
 * - 客户端 hydration 后自动切换为真实断点
 *
 * @example 基础用法
 * ```tsx
 * import { useBreakpoint } from '@/lib/responsive/use-breakpoint';
 *
 * function MyComponent() {
 *   const { current, isAtLeast, isMobile, isDesktop } = useBreakpoint();
 *
 *   if (isMobile) return <MobileLayout />;
 *   if (isDesktop) return <DesktopLayout />;
 *   return <TabletLayout />;
 * }
 * ```
 *
 * @example isAtLeast 判定
 * ```tsx
 * const { isAtLeast } = useBreakpoint();
 * const showSidebar = isAtLeast('lg'); // 视口 >= 1024px 时显示侧边栏
 * const cols = isAtLeast('xl') ? 4 : isAtLeast('md') ? 2 : 1;
 * ```
 *
 * @example prefers-reduced-motion
 * ```tsx
 * const { prefersReducedMotion } = useBreakpoint();
 * const duration = prefersReducedMotion ? 0 : 300;
 * ```
 */

import { useCallback, useSyncExternalStore } from 'react';

import {
  BREAKPOINT_MEDIA_QUERIES,
  DEFAULT_BREAKPOINT,
  RESPONSIVE_ERROR_CODES,
  REDUCED_MOTION_MEDIA_QUERY,
  isBreakpointAtLeast,
  type BreakpointKey,
} from './breakpoints';

// ============================================================================
// 一、内部类型与常量
// ============================================================================

/**
 * 内部断点类型。额外包含 'base' 表示 < sm（640px）的区间。
 *
 * D6 契约只定义了 5 个断点（sm/md/lg/xl/2xl），未定义 base。
 * 内部使用 'base' 精确区分 < sm 的场景，保证 isAtLeast('sm') 在 < 640px 时返回 false。
 * 对外暴露时 'base' 映射为 'sm'（最小断点，且 D6 sm.isMobile=true）。
 */
type InternalBreakpoint = 'base' | BreakpointKey;

// ============================================================================
// 二、matchMedia 订阅器（useSyncExternalStore 底层）
// ============================================================================

/**
 * 获取当前内部断点（同步查询 matchMedia）。
 *
 * 从最大断点（2xl）开始向下检查，返回第一个匹配的断点。
 * 全部不匹配时返回 'base'（< 640px）。
 *
 * SSR 环境或 matchMedia 不可用时返回 DEFAULT_BREAKPOINT（'lg'），
 * 并在客户端 matchMedia 不可用时记录 FE-RES-001 警告。
 *
 * @returns 当前内部断点
 */
function getInternalBreakpoint(): InternalBreakpoint {
  if (typeof window === 'undefined') {
    return DEFAULT_BREAKPOINT;
  }
  if (typeof window.matchMedia !== 'function') {
    console.warn(
      `[${RESPONSIVE_ERROR_CODES.BREAKPOINT_DETECT_FAILED}] ` +
        'Responsive breakpoint detection failed: window.matchMedia is not available. ' +
        'Falling back to desktop breakpoint (lg).'
    );
    return DEFAULT_BREAKPOINT;
  }

  if (window.matchMedia(BREAKPOINT_MEDIA_QUERIES['2xl']).matches) return '2xl';
  if (window.matchMedia(BREAKPOINT_MEDIA_QUERIES.xl).matches) return 'xl';
  if (window.matchMedia(BREAKPOINT_MEDIA_QUERIES.lg).matches) return 'lg';
  if (window.matchMedia(BREAKPOINT_MEDIA_QUERIES.md).matches) return 'md';
  if (window.matchMedia(BREAKPOINT_MEDIA_QUERIES.sm).matches) return 'sm';
  return 'base';
}

/**
 * 订阅断点变化。注册 5 个 matchMedia change 监听器，任一断点变化时触发回调。
 *
 * @param callback - 断点变化时的回调函数
 * @returns 取消订阅函数
 */
function subscribeBreakpoint(callback: () => void): () => void {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return () => {};
  }

  const queries = Object.values(BREAKPOINT_MEDIA_QUERIES);
  const mqls = queries.map((q) => window.matchMedia(q));
  const handler = () => callback();

  mqls.forEach((mql) => mql.addEventListener('change', handler));
  return () => {
    mqls.forEach((mql) => mql.removeEventListener('change', handler));
  };
}

/**
 * SSR 快照：返回默认断点 'lg'（桌面主战场起点）。
 */
function getServerBreakpoint(): InternalBreakpoint {
  return DEFAULT_BREAKPOINT;
}

// ============================================================================
// 三、prefers-reduced-motion 订阅器
// ============================================================================

/**
 * 获取 prefers-reduced-motion 系统偏好。
 *
 * 对齐 merged.md §3.5 克制原则：用户启用"减少动效"时，装饰动效全部关闭，
 * Apple 主交互保留但参数减弱。
 *
 * @returns 是否启用了减少动效
 */
function getReducedMotion(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return false;
  }
  return window.matchMedia(REDUCED_MOTION_MEDIA_QUERY).matches;
}

/**
 * 订阅 prefers-reduced-motion 变化。
 */
function subscribeReducedMotion(callback: () => void): () => void {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return () => {};
  }

  const mql = window.matchMedia(REDUCED_MOTION_MEDIA_QUERY);
  const handler = () => callback();
  mql.addEventListener('change', handler);
  return () => mql.removeEventListener('change', handler);
}

/**
 * SSR 快照：默认不启用减少动效。
 */
function getServerReducedMotion(): boolean {
  return false;
}

// ============================================================================
// 四、useBreakpoint hook
// ============================================================================

/**
 * useBreakpoint 返回值类型。
 */
export interface UseBreakpointResult {
  /**
   * 当前生效的最高断点。
   *
   * 视口 >= 某断点 minWidth 时该断点"激活"，current 为所有激活断点中最大的。
   * < 640px 时返回 'sm'（D6 未定义 base 断点，sm 是最小断点且 isMobile=true）。
   *
   * SSR 环境下返回 'lg'（桌面主战场起点，避免水合不匹配）。
   */
  current: BreakpointKey;

  /**
   * 判断当前视口是否 >= 指定断点的 minWidth。
   *
   * 基于 matchMedia 精确查询，不是简单的 current 值比较。
   * < 640px 时 isAtLeast('sm') 返回 false（虽然 current 为 'sm'）。
   *
   * @param key - 目标断点
   * @returns 当前视口 >= key.minWidth 时返回 true
   */
  isAtLeast: (key: BreakpointKey) => boolean;

  /**
   * 是否移动端（视口 < md 768px）。
   *
   * 对齐 D6 mobileDegrades.triggerCondition "matchMedia('(max-width: 767px)')"。
   * 触发移动端降级策略 9 项（9b 职责）。
   */
  isMobile: boolean;

  /**
   * 是否桌面端（视口 >= lg 1024px）。
   *
   * 对齐 merged.md §6.1：lg 1024 为桌面主战场起点。
   */
  isDesktop: boolean;

  /**
   * 用户是否启用了"减少动效"系统偏好。
   *
   * 对齐 merged.md §3.5：启用时装饰动效全部关闭，主交互参数减弱。
   * 供动效模块（模块3）消费。
   */
  prefersReducedMotion: boolean;
}

/**
 * 响应式断点检测 hook。
 *
 * 基于 React 18 useSyncExternalStore 订阅 window.matchMedia，
 * 在断点变化时自动触发组件 re-render。
 *
 * 特性：
 * - 实时检测 5 个断点（sm/md/lg/xl/2xl）
 * - isAtLeast 精确判定视口是否达到某断点
 * - isMobile / isDesktop 便捷属性
 * - prefersReducedMotion 系统偏好检测
 * - SSR 安全（服务端返回 'lg'，客户端 hydration 后自动切换）
 *
 * @returns 断点信息对象
 *
 * @example
 * ```tsx
 * function Dashboard() {
 *   const { current, isAtLeast, isMobile } = useBreakpoint();
 *
 *   // 响应式列数
 *   const cols = isAtLeast('xl') ? 4 : isAtLeast('lg') ? 3 : isAtLeast('md') ? 2 : 1;
 *
 *   // 移动端隐藏侧边栏
 *   if (isMobile) return <MobileDashboard />;
 *
 *   return <DesktopDashboard cols={cols} />;
 * }
 * ```
 */
export function useBreakpoint(): UseBreakpointResult {
  const internal = useSyncExternalStore(
    subscribeBreakpoint,
    getInternalBreakpoint,
    getServerBreakpoint
  );

  const prefersReducedMotion = useSyncExternalStore(
    subscribeReducedMotion,
    getReducedMotion,
    getServerReducedMotion
  );

  // 'base' 映射为 'sm'（D6 未定义 base 断点，< sm 仍属移动端范畴）
  const current: BreakpointKey = internal === 'base' ? 'sm' : internal;

  // isAtLeast 基于 internal 精确比较：base 时任何 isAtLeast 都返回 false
  const isAtLeast = useCallback(
    (key: BreakpointKey): boolean => {
      if (internal === 'base') {
        return false;
      }
      return isBreakpointAtLeast(internal, key);
    },
    [internal]
  );

  // isMobile = < md（base 或 sm）
  const isMobile: boolean = internal === 'base' || internal === 'sm';

  // isDesktop = >= lg
  const isDesktop: boolean =
    internal === 'lg' || internal === 'xl' || internal === '2xl';

  return { current, isAtLeast, isMobile, isDesktop, prefersReducedMotion };
}

// ============================================================================
// 五、便捷 hook 与纯函数
// ============================================================================

/**
 * usePrefersReducedMotion 返回值类型。
 */
export interface UsePrefersReducedMotionResult {
  /**
   * 用户是否启用了"减少动效"系统偏好。
   */
  prefersReducedMotion: boolean;
}

/**
 * prefers-reduced-motion 检测 hook（独立订阅）。
 *
 * 供动效模块（模块3）单独消费，避免引入完整 useBreakpoint 的断点订阅开销。
 * 仅在 prefers-reduced-motion 变化时触发 re-render。
 *
 * @returns { prefersReducedMotion } 是否启用减少动效
 *
 * @example
 * ```tsx
 * import { usePrefersReducedMotion } from '@/lib/responsive/use-breakpoint';
 *
 * function AnimatedComponent() {
 *   const { prefersReducedMotion } = usePrefersReducedMotion();
 *   const springConfig = prefersReducedMotion
 *     ? { duration: 0 }
 *     : { type: 'spring', stiffness: 300, damping: 30 };
 *   return <motion.div animate={{ opacity: 1 }} transition={springConfig} />;
 * }
 * ```
 */
export function usePrefersReducedMotion(): UsePrefersReducedMotionResult {
  const prefersReducedMotion = useSyncExternalStore(
    subscribeReducedMotion,
    getReducedMotion,
    getServerReducedMotion
  );
  return { prefersReducedMotion };
}

/**
 * 同步获取当前断点（非 React 纯函数）。
 *
 * 适用于非 React 场景（如工具函数、SSR 首次渲染、事件处理器内部）。
 * 不会自动订阅断点变化，每次调用都重新查询 matchMedia。
 *
 * @returns 当前断点 key（< 640px 返回 'sm'，SSR 返回 'lg'）
 *
 * @example
 * ```ts
 * import { getCurrentBreakpoint } from '@/lib/responsive/use-breakpoint';
 *
 * // 在事件处理器中同步获取
 * const handleResize = () => {
 *   const bp = getCurrentBreakpoint();
 *   console.log('Current breakpoint:', bp);
 * };
 * ```
 */
export function getCurrentBreakpoint(): BreakpointKey {
  const internal = getInternalBreakpoint();
  return internal === 'base' ? 'sm' : internal;
}
