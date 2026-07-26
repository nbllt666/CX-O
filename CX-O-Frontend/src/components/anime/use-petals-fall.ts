/**
 * use-petals-fall.ts — 花瓣飘落装饰动效 hook
 *
 * 模块: 模块5 二次元元素层
 * 对应 D4 §decorationAnimations.petalFall:
 *   - trigger: page-transition + theme-switch
 *   - implementation: GSAP timeline + CSS transform
 *   - frequencyLimit.timing: switch-moment-only（仅切换瞬间）
 *
 * 上游依赖:
 *   - 模块3 gsap-utils.ts（loadGsap 动态加载 GSAP + prefersReducedMotion 检测 + GsapTimeline 类型）
 *   - 模块3 springs.ts（bouncy spring，降级时备用）
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
import { USAGE_BOUNDARIES, type AnimeDecorationTrigger } from './anime-palette';

/** 花瓣粒子配置 */
export interface PetalParticle {
  /** 粒子唯一 ID */
  id: number;
  /** 起始横向位置百分比（0-100） */
  startX: number;
  /** 飘落距离（50-100vh） */
  fallDistance: number;
  /** 动画时长（2-5s 随机） */
  duration: number;
  /** 动画延迟（0-1.5s 随机） */
  delay: number;
  /** 水平摆动幅度（-20 ~ +20） */
  swayX: number;
  /** 旋转角度（0-360 度） */
  rotate: number;
  /** 粒子尺寸（8-16px 随机） */
  size: number;
}

/** usePetalsFall hook 参数 */
export interface UsePetalsFallOptions {
  /** 粒子密度（个/m²） */
  density: number;
  /** 单元素 opacity 上限 ≤ 0.4 */
  opacity: number;
  /** 触发场景 */
  trigger: AnimeDecorationTrigger;
  /** 粒子数量上限 */
  maxCount?: number;
}

/** usePetalsFall hook 返回值 */
export interface UsePetalsFallResult {
  /** 是否激活动效 */
  active: boolean;
  /** 花瓣粒子配置数组 */
  particles: PetalParticle[];
  /** Framer Motion transition 配置（bouncy spring，GSAP 不可用时降级） */
  transition: ReturnType<typeof getSpringTransition>;
  /** 单元素 opacity（已钳制 ≤ 0.4） */
  opacity: number;
  /** 触发场景 */
  trigger: AnimeDecorationTrigger;
  /** prefers-reduced-motion 是否命中 */
  reducedMotion: boolean;
  /** GSAP timeline 引用（已创建时非 null，供组件层控制） */
  timeline: GsapTimeline | null;
}

function randomBetween(min: number, max: number): number {
  return min + Math.random() * (max - min);
}

/**
 * 花瓣飘落装饰动效 hook。
 *
 * 实现细节（D4 §decorationAnimations.petalFall）:
 *   - GSAP timeline + CSS transform
 *   - 仅切换瞬间（page-transition / theme-switch）
 *   - prefers-reduced-motion 命中时 active=false，particles 为空数组
 *   - GSAP 动态加载失败时降级为 Framer Motion（bouncy spring）
 *
 * @param options 动效配置
 * @returns 花瓣动效配置
 */
export function usePetalsFall(options: UsePetalsFallOptions): UsePetalsFallResult {
  const { density, opacity, trigger, maxCount = 8 } = options;

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

  // GSAP 动态加载 + timeline 创建（仅切换瞬间激活）
  useEffect(() => {
    if (reducedMotion) return;
    let cancelled = false;
    loadGsap()
      .then((gsap) => {
        if (cancelled) return;
        timelineRef.current = gsap.timeline({ defaults: { ease: 'power1.inOut' } });
      })
      .catch(() => {
        // GSAP 加载失败时静默降级为 Framer Motion（transition 已提供 bouncy spring）
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

  const particles = useMemo<PetalParticle[]>(() => {
    if (reducedMotion) return [];
    const count = Math.min(Math.max(1, Math.round(density * 8)), maxCount);
    return Array.from({ length: count }, (_, i) => ({
      id: i,
      startX: randomBetween(0, 100),
      fallDistance: randomBetween(50, 100),
      duration: randomBetween(2, 5),
      delay: randomBetween(0, 1.5),
      swayX: randomBetween(-20, 20),
      rotate: randomBetween(0, 360),
      size: randomBetween(8, 16),
    }));
  }, [density, maxCount, reducedMotion]);

  const transition = useMemo(() => getSpringTransition('bouncy'), []);

  return {
    active: !reducedMotion,
    particles,
    transition,
    opacity: clampedOpacity,
    trigger,
    reducedMotion,
    timeline: timelineRef.current,
  };
}
