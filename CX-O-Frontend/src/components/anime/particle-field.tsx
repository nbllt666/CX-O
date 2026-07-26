/**
 * particle-field.tsx — 装饰粒子场组件
 *
 * 模块: 模块5 二次元元素层
 * 对应 I4 frontend_anime.pyi §ParticleField:
 *   - props: { particleType, density, maxAlpha, trigger }
 *   - 根据 particleType 渲染对应粒子
 *   - density 控制粒子密度
 *   - maxAlpha 控制单屏 alpha 总和上限（≤ 0.4）
 *   - 超过时抛出 ParticleLimitError
 *   - z-index=4（装饰条带层 OBS-H）
 *   - prefers-reduced-motion 下关闭
 *
 * @version 1.0.0
 */

import { motion } from 'framer-motion';
import { useEffect, useMemo, useState, type CSSProperties, type ReactElement } from 'react';
import { getSpringTransition } from '@/lib/motion/springs';
import { prefersReducedMotion } from '@/lib/motion/gsap-utils';
import {
  ANIME_PALETTE,
  ParticleLimitError,
  USAGE_BOUNDARIES,
  Z_INDEX_LAYERS,
  type AnimeDecorationType,
  type ParticleFieldProps,
} from './anime-palette';

/** 单个粒子配置 */
interface Particle {
  id: number;
  x: number;
  y: number;
  size: number;
  duration: number;
  delay: number;
}

/** 随机数生成 [min, max] */
function randomBetween(min: number, max: number): number {
  return min + Math.random() * (max - min);
}

/**
 * 装饰粒子场组件。
 *
 * 对应 I4 frontend_anime.pyi §ParticleField。
 *
 * 实现细节:
 *   - 根据 particleType 渲染对应粒子（star/music-note/petal/glow/star-trail）
 *   - density 控制粒子密度（移动端降至 0.1/m²）
 *   - maxAlpha 控制单屏 alpha 总和上限（≤ 0.4）
 *   - 超过 maxAlpha 时抛出 ParticleLimitError
 *   - z-index=4（装饰条带层 OBS-H）
 *   - prefers-reduced-motion 下返回 null
 *
 * @param props 粒子场配置
 * @returns 渲染后的粒子场
 * @throws {ParticleLimitError} 当 maxAlpha > 0.4 或单屏 alpha 总和 > 0.4 时抛出
 */
export function ParticleField(props: ParticleFieldProps): ReactElement | null {
  const { particleType, density, maxAlpha, trigger } = props;

  // --- 校验 maxAlpha ≤ 0.4 ---
  if (maxAlpha > USAGE_BOUNDARIES.singleScreenAlphaSum) {
    throw new ParticleLimitError(
      `ParticleField: maxAlpha=${maxAlpha} 超过单屏 alpha 总和上限 ${USAGE_BOUNDARIES.singleScreenAlphaSum}。`,
    );
  }

  // --- prefers-reduced-motion 响应式检测 ---
  const [reduced, setReduced] = useState<boolean>(() => {
    const result = prefersReducedMotion();
    return result.reduced;
  });

  useEffect(() => {
    const mediaQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
    const handler = (e: MediaQueryListEvent) => setReduced(e.matches);
    mediaQuery.addEventListener('change', handler);
    return () => mediaQuery.removeEventListener('change', handler);
  }, []);

  // --- 移动端密度降级 ---
  const [isMobile, setIsMobile] = useState<boolean>(false);
  useEffect(() => {
    const mediaQuery = window.matchMedia('(max-width: 767px)');
    setIsMobile(mediaQuery.matches);
    const handler = (e: MediaQueryListEvent) => setIsMobile(e.matches);
    mediaQuery.addEventListener('change', handler);
    return () => mediaQuery.removeEventListener('change', handler);
  }, []);

  // --- 生成粒子 ---
  const effectiveDensity = isMobile ? Math.min(density, 0.1) : density;
  const effectiveMaxAlpha = isMobile ? Math.min(maxAlpha, 0.2) : maxAlpha;

  const particles = useMemo<Particle[]>(() => {
    if (reduced) return [];
    const count = Math.min(Math.max(1, Math.round(effectiveDensity * 10)), 20);
    return Array.from({ length: count }, (_, i) => ({
      id: i,
      x: randomBetween(0, 100),
      y: randomBetween(0, 100),
      size: randomBetween(4, 12),
      duration: randomBetween(2, 4),
      delay: randomBetween(0, 2),
    }));
  }, [effectiveDensity, reduced]);

  // --- 计算实际 alpha 总和（粒子数 × 单粒子 alpha） ---
  const particleAlpha = particles.length > 0 ? effectiveMaxAlpha / particles.length : 0;
  const actualAlphaSum = particles.length * particleAlpha;
  if (actualAlphaSum > USAGE_BOUNDARIES.singleScreenAlphaSum) {
    throw new ParticleLimitError(
      `ParticleField: 单屏 alpha 总和 ${actualAlphaSum.toFixed(3)} 超过上限 ${USAGE_BOUNDARIES.singleScreenAlphaSum}。`,
    );
  }

  // --- prefers-reduced-motion 返回 null ---
  if (reduced) {
    return null;
  }

  const transition = getSpringTransition('bouncy');
  const containerStyle: CSSProperties = {
    zIndex: Z_INDEX_LAYERS['decoration-band'],
    pointerEvents: 'none',
    position: 'absolute',
    inset: 0,
    overflow: 'hidden',
  };

  void trigger;

  return (
    <div data-particle-field={particleType} style={containerStyle}>
      {particles.map((p) => (
        <ParticleRenderer
          key={p.id}
          particle={p}
          particleType={particleType}
          alpha={particleAlpha}
          transition={transition}
        />
      ))}
    </div>
  );
}

/** 单粒子渲染器 */
function ParticleRenderer(props: {
  particle: Particle;
  particleType: AnimeDecorationType;
  alpha: number;
  transition: ReturnType<typeof getSpringTransition>;
}): ReactElement {
  const { particle, particleType, alpha, transition } = props;

  const baseStyle: CSSProperties = {
    position: 'absolute',
    left: `${particle.x}%`,
    top: `${particle.y}%`,
    opacity: alpha,
  };

  switch (particleType) {
    case 'star':
      return (
        <motion.svg
          width={particle.size}
          height={particle.size}
          viewBox="0 0 12 12"
          style={baseStyle}
          animate={{ scale: [0.8, 1.2, 0.8], opacity: [alpha * 0.5, alpha, alpha * 0.5] }}
          transition={{ ...transition, duration: particle.duration, repeat: Infinity, delay: particle.delay }}
        >
          <path d="M6 0L7.5 4.5L12 6L7.5 7.5L6 12L4.5 7.5L0 6L4.5 4.5Z" fill={ANIME_PALETTE.moonlightWhite} />
        </motion.svg>
      );
    case 'music-note':
      return (
        <motion.div
          style={{ ...baseStyle, color: ANIME_PALETTE.sakuraPink }}
          animate={{ y: [0, -40], opacity: [alpha, 0] }}
          transition={{ ...transition, duration: particle.duration, repeat: Infinity, delay: particle.delay }}
        >
          <svg width={particle.size + 4} height={particle.size + 4} viewBox="0 0 16 16" fill="currentColor">
            <path d="M6 2v8.5a2.5 2.5 0 1 1-1-2V4l5-1v5.5a2.5 2.5 0 1 1-1-2V2H6z" />
          </svg>
        </motion.div>
      );
    case 'petal':
      return (
        <motion.div
          style={{ ...baseStyle, color: ANIME_PALETTE.sakuraPink }}
          animate={{ y: [0, 100], x: [0, 15, 0], rotate: [0, 360] }}
          transition={{ ...transition, duration: particle.duration, repeat: Infinity, delay: particle.delay }}
        >
          <svg width={particle.size + 2} height={particle.size + 2} viewBox="0 0 14 14" fill="currentColor">
            <path d="M7 0C7 3 4 5 0 5C4 5 7 7 7 14C7 11 10 9 14 9C10 9 7 7 7 0Z" />
          </svg>
        </motion.div>
      );
    case 'glow':
      return (
        <motion.div
          style={{
            ...baseStyle,
            borderRadius: '50%',
            background: `radial-gradient(circle, ${ANIME_PALETTE.sakuraPink} 0%, transparent 70%)`,
            width: `${particle.size * 4}px`,
            height: `${particle.size * 4}px`,
          }}
          animate={{ scale: [1, 1.3, 1], opacity: [alpha * 0.5, alpha, alpha * 0.5] }}
          transition={{ ...transition, duration: particle.duration, repeat: Infinity, delay: particle.delay }}
        />
      );
    case 'star-trail':
      return (
        <motion.svg
          width={particle.size * 10}
          height={particle.size * 3}
          viewBox="0 0 120 40"
          style={baseStyle}
          animate={{ opacity: [alpha * 0.3, alpha, alpha * 0.3] }}
          transition={{ ...transition, duration: particle.duration, repeat: Infinity, delay: particle.delay }}
        >
          <motion.path
            d="M0 20 Q30 0 60 20 T120 20"
            fill="none"
            stroke={ANIME_PALETTE.starSeaCyan}
            strokeWidth={2}
            strokeDasharray={200}
            initial={{ strokeDashoffset: 200 }}
            animate={{ strokeDashoffset: [200, 0] }}
            transition={{ ...transition, duration: 1.5, repeat: Infinity, delay: particle.delay }}
          />
        </motion.svg>
      );
    default:
      return <div style={baseStyle} />;
  }
}
