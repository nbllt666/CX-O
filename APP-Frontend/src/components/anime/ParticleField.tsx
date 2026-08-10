/**
 * ParticleField.tsx — 二次元装饰粒子场（轻量复刻 CX-O-Frontend 的 particle-field.tsx）
 *
 * 特性:
 *   - petal（樱花花瓣，粉色，飘落 + 摆动 + 旋转）/ star（星形粒子，闪烁）
 *   - density 控制粒子密度，maxAlpha 控制单粒子透明度（≤ 0.4）
 *   - 纯装饰层：pointer-events: none，不拦截点击
 *   - prefers-reduced-motion 下返回 null；无 matchMedia 环境（如 jsdom）安全降级为 false
 */
import { motion } from 'framer-motion';
import { useEffect, useMemo, useState, type CSSProperties, type ReactElement } from 'react';

export type ParticleType = 'petal' | 'star';

export interface ParticleFieldProps {
  particleType: ParticleType;
  /** 粒子密度（0~1 之间，越大越密） */
  density: number;
  /** 单粒子最大透明度（≤ 0.4） */
  maxAlpha: number;
}

interface Particle {
  id: number;
  x: number;
  y: number;
  size: number;
  duration: number;
  delay: number;
  sway: number;
}

const SAKURA_PINK = '#ffb7d5';
const STAR_WHITE = '#f8fafc';

function randomBetween(min: number, max: number): number {
  return min + Math.random() * (max - min);
}

/** 安全读取 prefers-reduced-motion（jsdom 等环境无 matchMedia 时返回 false） */
function readReducedMotion(): boolean {
  try {
    return typeof window.matchMedia === 'function'
      ? window.matchMedia('(prefers-reduced-motion: reduce)').matches
      : false;
  } catch {
    return false;
  }
}

/**
 * 装饰粒子场组件。
 * 常驻在管理布局顶层：position:absolute 铺满容器、pointer-events:none。
 * @param props 粒子配置
 * @returns 渲染后的粒子层；prefers-reduced-motion 时返回 null
 */
export function ParticleField(props: ParticleFieldProps): ReactElement | null {
  const { particleType, density, maxAlpha } = props;

  const [reduced, setReduced] = useState<boolean>(() => readReducedMotion());

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return;
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    const handler = (e: MediaQueryListEvent) => setReduced(e.matches);
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, []);

  const particles = useMemo<Particle[]>(() => {
    if (reduced) return [];
    const count = Math.min(Math.max(1, Math.round(density * 16)), 24);
    return Array.from({ length: count }, (_, i) => ({
      id: i,
      x: randomBetween(0, 100),
      y: randomBetween(0, 100),
      size: randomBetween(6, 14),
      duration: randomBetween(9, 18),
      delay: randomBetween(0, 6),
      sway: randomBetween(12, 34),
    }));
  }, [density, reduced]);

  if (reduced) return null;

  const clampedAlpha = Math.min(Math.max(maxAlpha, 0), 0.4);
  const containerStyle: CSSProperties = {
    position: 'absolute',
    inset: 0,
    overflow: 'hidden',
    pointerEvents: 'none',
  };

  return (
    <div data-particle-field={particleType} aria-hidden="true" style={containerStyle}>
      {particles.map((p) =>
        particleType === 'star' ? (
          <motion.svg
            key={p.id}
            width={p.size}
            height={p.size}
            viewBox="0 0 12 12"
            style={{ position: 'absolute', left: `${p.x}%`, top: `${p.y}%`, opacity: clampedAlpha }}
            animate={{ scale: [0.7, 1.3, 0.7], opacity: [clampedAlpha * 0.5, clampedAlpha, clampedAlpha * 0.5] }}
            transition={{
              duration: p.duration * 0.25,
              repeat: Infinity,
              delay: p.delay,
              ease: 'easeInOut',
            }}
          >
            <path d="M6 0L7.5 4.5L12 6L7.5 7.5L6 12L4.5 7.5L0 6L4.5 4.5Z" fill={STAR_WHITE} />
          </motion.svg>
        ) : (
          <motion.div
            key={p.id}
            style={{ position: 'absolute', left: `${p.x}%`, top: `${p.y}%`, color: SAKURA_PINK, opacity: clampedAlpha }}
            animate={{
              y: ['0vh', '105vh'],
              x: [0, p.sway, -p.sway * 0.5, 0],
              rotate: [0, 180, 360],
            }}
            transition={{
              duration: p.duration,
              repeat: Infinity,
              delay: p.delay,
              ease: 'linear',
            }}
          >
            <svg width={p.size + 2} height={p.size + 2} viewBox="0 0 14 14" fill="currentColor">
              <path d="M7 0C7 3 4 5 0 5C4 5 7 7 7 14C7 11 10 9 14 9C10 9 7 7 7 0Z" />
            </svg>
          </motion.div>
        ),
      )}
    </div>
  );
}
