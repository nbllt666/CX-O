/**
 * use-glow-pulse.ts — 光晕脉动装饰动效 hook
 *
 * 模块: 模块5 二次元元素层
 * 对应 D4 §decorationAnimations.haloPulse:
 *   - trigger: glass-component-hover
 *   - implementation: box-shadow animation + spring
 *   - frequencyLimit.constraint: natural-interaction-unlimited（自然交互不限）
 *
 * 上游依赖:
 *   - 模块3 springs.ts（bouncy spring）
 *   - 模块3 gsap-utils.ts（prefersReducedMotion 检测）
 *
 * @version 1.0.0
 */

import { useEffect, useMemo, useState } from 'react';
import { getSpringTransition } from '@/lib/motion/springs';
import { prefersReducedMotion } from '@/lib/motion/gsap-utils';
import { ANIME_PALETTE, USAGE_BOUNDARIES, type AnimeDecorationTrigger } from './anime-palette';

/** 光晕脉动配置 */
export interface GlowPulseConfig {
  /** 初始 box-shadow（无光晕） */
  initialBoxShadow: string;
  /** 激活态 box-shadow（带光晕，使用樱花粉/梦境紫/星海青之一） */
  activeBoxShadow: string;
  /** 光晕颜色 */
  glowColor: string;
  /** 光晕扩散半径（px） */
  spread: number;
}

/** useGlowPulse hook 参数 */
export interface UseGlowPulseOptions {
  /** 单元素 opacity 上限 ≤ 0.4 */
  opacity: number;
  /** 触发场景 */
  trigger: AnimeDecorationTrigger;
  /** 光晕颜色（默认樱花粉 #FFB7E1） */
  glowColor?: string;
  /** 光晕扩散半径（默认 16px） */
  spread?: number;
}

/** useGlowPulse hook 返回值 */
export interface UseGlowPulseResult {
  /** 是否激活动效 */
  active: boolean;
  /** 光晕脉动配置 */
  config: GlowPulseConfig;
  /** Framer Motion transition 配置（bouncy spring） */
  transition: ReturnType<typeof getSpringTransition>;
  /** 单元素 opacity（已钳制 ≤ 0.4） */
  opacity: number;
  /** 触发场景 */
  trigger: AnimeDecorationTrigger;
  /** prefers-reduced-motion 是否命中 */
  reducedMotion: boolean;
}

/**
 * 光晕脉动装饰动效 hook。
 *
 * 实现细节（D4 §decorationAnimations.haloPulse）:
 *   - box-shadow 动画 + spring
 *   - 自然交互不限（glass-component-hover）
 *   - prefers-reduced-motion 命中时 active=false，返回静态 box-shadow
 *
 * @param options 动效配置
 * @returns 光晕动效配置
 */
export function useGlowPulse(options: UseGlowPulseOptions): UseGlowPulseResult {
  const {
    opacity,
    trigger,
    glowColor = ANIME_PALETTE.sakuraPink,
    spread = 16,
  } = options;

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

  const clampedOpacity = Math.min(opacity, USAGE_BOUNDARIES.singleElementOpacity);

  const config = useMemo<GlowPulseConfig>(() => {
    const initialBoxShadow = '0 0 0px 0px transparent';
    const activeBoxShadow = `0 0 ${spread}px ${spread / 2}px ${glowColor}`;
    return {
      initialBoxShadow,
      activeBoxShadow,
      glowColor,
      spread,
    };
  }, [glowColor, spread]);

  const transition = useMemo(() => getSpringTransition('bouncy'), []);

  return {
    active: !reducedMotion,
    config,
    transition,
    opacity: clampedOpacity,
    trigger,
    reducedMotion,
  };
}
