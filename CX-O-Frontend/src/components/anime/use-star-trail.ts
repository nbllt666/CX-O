/**
 * use-star-trail.ts — 星轨流光装饰动效 hook
 *
 * 模块: 模块5 二次元元素层
 * 对应 D4 §decorationAnimations.starTrail:
 *   - trigger: navigation-active-state
 *   - implementation: SVG path + GSAP DrawSVG
 *   - frequencyLimit.timing: active-state-only（仅激活时）
 *
 * 上游依赖:
 *   - 模块3 gsap-utils.ts（loadGsap 动态加载 GSAP + prefersReducedMotion 检测 + GsapTimeline 类型）
 *   - 模块3 springs.ts（bouncy spring，降级时备用）
 *
 * 注意: GSAP DrawSVG 是 GSAP 付费插件，此处用 SVG stroke-dashoffset 模拟实现，
 *       避免引入付费依赖。GSAP 不可用时不阻断，降级为 CSS stroke-dashoffset 动画。
 *
 * @version 1.0.0
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { getSpringTransition } from '@/lib/motion/springs';
import {
  loadGsap,
  prefersReducedMotion,
  type GsapTimeline,
} from '@/lib/motion/gsap-utils';
import { ANIME_PALETTE, USAGE_BOUNDARIES, type AnimeDecorationTrigger } from './anime-palette';

/** 星轨路径配置 */
export interface StarTrailPath {
  /** SVG path d 属性值 */
  d: string;
  /** 路径总长度（px，用于 stroke-dashoffset 动画） */
  pathLength: number;
  /** 描边颜色（默认星海青 #7CD8FF） */
  strokeColor: string;
  /** 描边宽度（默认 2px） */
  strokeWidth: number;
}

/** useStarTrail hook 参数 */
export interface UseStarTrailOptions {
  /** 单元素 opacity 上限 ≤ 0.4 */
  opacity: number;
  /** 触发场景 */
  trigger: AnimeDecorationTrigger;
  /** 星轨路径 d 属性（SVG path） */
  pathD: string;
  /** 路径长度（默认 200） */
  pathLength?: number;
  /** 描边颜色（默认星海青） */
  strokeColor?: string;
  /** 描边宽度（默认 2） */
  strokeWidth?: number;
}

/** useStarTrail hook 返回值 */
export interface UseStarTrailResult {
  /** 是否激活动效 */
  active: boolean;
  /** 星轨路径配置 */
  path: StarTrailPath;
  /** Framer Motion transition 配置（bouncy spring，GSAP 不可用时降级） */
  transition: ReturnType<typeof getSpringTransition>;
  /** 单元素 opacity（已钳制 ≤ 0.4） */
  opacity: number;
  /** 触发场景 */
  trigger: AnimeDecorationTrigger;
  /** prefers-reduced-motion 是否命中 */
  reducedMotion: boolean;
  /** GSAP timeline 引用（已创建时非 null） */
  timeline: GsapTimeline | null;
  /** CSS 降级动画样式（GSAP 不可用时使用 stroke-dashoffset） */
  cssFallbackStyle: {
    strokeDasharray: string;
    strokeDashoffset: number;
    animation: string;
  };
}

/**
 * 星轨流光装饰动效 hook。
 *
 * 实现细节（D4 §decorationAnimations.starTrail）:
 *   - SVG path + GSAP DrawSVG（此处用 stroke-dashoffset 模拟）
 *   - 仅激活时（navigation-active-state）
 *   - prefers-reduced-motion 命中时 active=false，返回静态路径
 *   - GSAP 不可用时不阻断，降级为 CSS stroke-dashoffset 动画
 *
 * @param options 动效配置
 * @returns 星轨动效配置
 */
export function useStarTrail(options: UseStarTrailOptions): UseStarTrailResult {
  const {
    opacity,
    trigger,
    pathD,
    pathLength = 200,
    strokeColor = ANIME_PALETTE.starSeaCyan,
    strokeWidth = 2,
  } = options;

  const [reducedMotion, setReducedMotion] = useState<boolean>(() => {
    const result = prefersReducedMotion();
    return result.reduced;
  });

  const timelineRef = useRef<GsapTimeline | null>(null);

  useEffect(() => {
    const mediaQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
    const handler = (e: MediaQueryListEvent) => setReducedMotion(e.matches);
    mediaQuery.addEventListener('change', handler);
    return () => mediaQuery.removeEventListener('change', handler);
  }, []);

  // GSAP 动态加载 + timeline 创建（仅激活态）
  useEffect(() => {
    if (reducedMotion) return;
    let cancelled = false;
    loadGsap()
      .then((gsap) => {
        if (cancelled) return;
        timelineRef.current = gsap.timeline({ defaults: { ease: 'none' } });
      })
      .catch(() => {
        timelineRef.current = null;
      });
    return () => {
      cancelled = true;
      if (timelineRef.current) {
        timelineRef.current.kill();
        timelineRef.current = null;
      }
    };
  }, [reducedMotion]);

  const clampedOpacity = Math.min(opacity, USAGE_BOUNDARIES.singleElementOpacity);

  const path = useMemo<StarTrailPath>(
    () => ({
      d: pathD,
      pathLength,
      strokeColor,
      strokeWidth,
    }),
    [pathD, pathLength, strokeColor, strokeWidth],
  );

  const transition = useMemo(() => getSpringTransition('bouncy'), []);

  // CSS 降级动画（GSAP 不可用时使用 stroke-dashoffset）
  const cssFallbackStyle = useMemo(
    () => ({
      strokeDasharray: `${pathLength}`,
      strokeDashoffset: reducedMotion ? 0 : pathLength,
      animation: reducedMotion
        ? 'none'
        : `star-trail-draw 1.5s ease-in-out forwards`,
    }),
    [pathLength, reducedMotion],
  );

  return {
    active: !reducedMotion,
    path,
    transition,
    opacity: clampedOpacity,
    trigger,
    reducedMotion,
    timeline: timelineRef.current,
    cssFallbackStyle,
  };
}
