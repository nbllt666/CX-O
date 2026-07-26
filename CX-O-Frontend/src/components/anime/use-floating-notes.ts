/**
 * use-floating-notes.ts — 音符飘动装饰动效 hook
 *
 * 模块: 模块5 二次元元素层
 * 对应 D4 §decorationAnimations.noteFloat:
 *   - trigger: chat-send-receive-message
 *   - implementation: Framer Motion motion.div + random path
 *   - frequencyLimit.perMessage: 5（每次消息 ≤ 5 粒子）
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
import { USAGE_BOUNDARIES, type AnimeDecorationTrigger } from './anime-palette';

/** 音符粒子配置（含随机飘动路径） */
export interface FloatingNoteParticle {
  /** 粒子唯一 ID */
  id: number;
  /** 起始横向位置百分比（0-100） */
  startX: number;
  /** 起始纵向位置百分比（0-100） */
  startY: number;
  /** 飘动终点横向偏移（-30 ~ +30） */
  endX: number;
  /** 飘动终点纵向偏移（-60 ~ -20，向上飘） */
  endY: number;
  /** 动画时长（1.5-3s 随机） */
  duration: number;
  /** 动画延迟（0-1s 随机） */
  delay: number;
  /** 旋转角度（-30 ~ +30 度） */
  rotate: number;
}

/** useFloatingNotes hook 参数 */
export interface UseFloatingNotesOptions {
  /** 粒子密度（个/m²） */
  density: number;
  /** 单元素 opacity 上限 ≤ 0.4 */
  opacity: number;
  /** 触发场景 */
  trigger: AnimeDecorationTrigger;
  /** 每次消息粒子数上限（D4 noteFloat.frequencyLimit.perMessage 默认 5） */
  maxPerMessage?: number;
}

/** useFloatingNotes hook 返回值 */
export interface UseFloatingNotesResult {
  /** 是否激活动效 */
  active: boolean;
  /** 音符粒子配置数组 */
  particles: FloatingNoteParticle[];
  /** Framer Motion transition 配置（bouncy spring） */
  transition: ReturnType<typeof getSpringTransition>;
  /** 单元素 opacity（已钳制 ≤ 0.4） */
  opacity: number;
  /** 触发场景 */
  trigger: AnimeDecorationTrigger;
  /** prefers-reduced-motion 是否命中 */
  reducedMotion: boolean;
}

function randomBetween(min: number, max: number): number {
  return min + Math.random() * (max - min);
}

/**
 * 音符飘动装饰动效 hook。
 *
 * 实现细节（D4 §decorationAnimations.noteFloat）:
 *   - Framer Motion motion.div + 随机路径
 *   - 每次消息 ≤ 5 个粒子（maxPerMessage 默认 5）
 *   - prefers-reduced-motion 命中时 active=false，particles 为空数组
 *
 * @param options 动效配置
 * @returns 音符动效配置
 */
export function useFloatingNotes(options: UseFloatingNotesOptions): UseFloatingNotesResult {
  const { density, opacity, trigger, maxPerMessage = 5 } = options;

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

  const particles = useMemo<FloatingNoteParticle[]>(() => {
    if (reducedMotion) return [];
    const count = Math.min(Math.max(1, Math.round(density * 5)), maxPerMessage);
    return Array.from({ length: count }, (_, i) => ({
      id: i,
      startX: randomBetween(10, 90),
      startY: randomBetween(40, 80),
      endX: randomBetween(-30, 30),
      endY: randomBetween(-60, -20),
      duration: randomBetween(1.5, 3),
      delay: randomBetween(0, 1),
      rotate: randomBetween(-30, 30),
    }));
  }, [density, maxPerMessage, reducedMotion]);

  const transition = useMemo(() => getSpringTransition('bouncy'), []);

  return {
    active: !reducedMotion,
    particles,
    transition,
    opacity: clampedOpacity,
    trigger,
    reducedMotion,
  };
}
