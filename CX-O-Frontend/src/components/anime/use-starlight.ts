/**
 * use-starlight.ts — 星光闪烁装饰动效 hook
 *
 * 模块: 模块5 二次元元素层
 * 对应 D4 §decorationAnimations.starTwinkle:
 *   - trigger: important-operation-success-feedback
 *   - implementation: Framer Motion animate + repeat: Infinity + random duration 2-4s
 *   - frequencyLimit.perScreen: 3（每屏 ≤ 3 处）
 *
 * 上游依赖:
 *   - 模块3 springs.ts（bouncy spring: damping 14 / stiffness 280 / mass 1）
 *   - 模块3 gsap-utils.ts（prefersReducedMotion 检测）
 *
 * 使用边界（D4 §usageBoundaries）:
 *   - 单元素 opacity ≤ 0.4
 *   - prefers-reduced-motion 命中时全部关闭
 *
 * @version 1.0.0
 */

import { useEffect, useMemo, useState } from 'react';
import { getSpringTransition } from '@/lib/motion/springs';
import { prefersReducedMotion } from '@/lib/motion/gsap-utils';
import { USAGE_BOUNDARIES, type AnimeDecorationTrigger } from './anime-palette';

/** 星光粒子配置 */
export interface StarlightParticle {
  /** 粒子唯一 ID */
  id: number;
  /** 横向位置百分比（0-100） */
  x: number;
  /** 纵向位置百分比（0-100） */
  y: number;
  /** 动画时长（2-4s 随机） */
  duration: number;
  /** 动画延迟（0-2s 随机） */
  delay: number;
  /** 粒子尺寸（4-12px 随机） */
  size: number;
}

/** useStarlight hook 参数 */
export interface UseStarlightOptions {
  /** 粒子密度（个/m²） */
  density: number;
  /** 单元素 opacity 上限 ≤ 0.4 */
  opacity: number;
  /** 触发场景 */
  trigger: AnimeDecorationTrigger;
  /** 粒子数量上限（D4 starTwinkle.frequencyLimit.perScreen 默认 3） */
  maxCount?: number;
}

/** useStarlight hook 返回值 */
export interface UseStarlightResult {
  /** 是否激活动效（prefers-reduced-motion 命中时为 false） */
  active: boolean;
  /** 星光粒子配置数组 */
  particles: StarlightParticle[];
  /** Framer Motion transition 配置（bouncy spring） */
  transition: ReturnType<typeof getSpringTransition>;
  /** 单元素 opacity（已钳制 ≤ 0.4） */
  opacity: number;
  /** 触发场景（回传供调用方决策） */
  trigger: AnimeDecorationTrigger;
  /** prefers-reduced-motion 是否命中 */
  reducedMotion: boolean;
}

/** 随机数生成 [min, max] */
function randomBetween(min: number, max: number): number {
  return min + Math.random() * (max - min);
}

/**
 * 星光闪烁装饰动效 hook。
 *
 * 实现细节（D4 §decorationAnimations.starTwinkle）:
 *   - Framer Motion animate + repeat: Infinity + random duration 2-4s
 *   - 每屏 ≤ 3 处（maxCount 默认 3）
 *   - prefers-reduced-motion 命中时 active=false，particles 为空数组
 *
 * @param options 动效配置
 * @returns 星光动效配置
 */
export function useStarlight(options: UseStarlightOptions): UseStarlightResult {
  const { density, opacity, trigger, maxCount = 3 } = options;

  // 响应式检测 prefers-reduced-motion
  const [reducedMotion, setReducedMotion] = useState<boolean>(() => {
    const result = prefersReducedMotion();
    return result.reduced;
  });

  useEffect(() => {
    const mediaQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
    const handler = (e: MediaQueryListEvent) => setReducedMotion(e.matches);
    mediaQuery.addEventListener('change', handler);
    return () => mediaQuery.removeEventListener('change', handler);
  }, []);

  // 钳制 opacity ≤ 0.4（D4 §usageBoundaries.singleElementOpacity）
  const clampedOpacity = Math.min(opacity, USAGE_BOUNDARIES.singleElementOpacity);

  // 生成星光粒子（基于密度，上限 maxCount）
  const particles = useMemo<StarlightParticle[]>(() => {
    if (reducedMotion) return [];
    const count = Math.min(Math.max(1, Math.round(density * 3)), maxCount);
    return Array.from({ length: count }, (_, i) => ({
      id: i,
      x: randomBetween(5, 95),
      y: randomBetween(5, 95),
      duration: randomBetween(2, 4),
      delay: randomBetween(0, 2),
      size: randomBetween(4, 12),
    }));
  }, [density, maxCount, reducedMotion]);

  // bouncy spring transition（模块3 装饰专用 spring）
  const transition = useMemo(() => getSpringTransition('bouncy'), []);

  // trigger 回传供调用方决策（如仅在 'success' 时激活）
  return {
    active: !reducedMotion,
    particles,
    transition,
    opacity: clampedOpacity,
    trigger,
    reducedMotion,
  };
}
