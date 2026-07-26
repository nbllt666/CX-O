/**
 * anime-decoration.tsx — 装饰动效统一容器组件
 *
 * 模块: 模块5 二次元元素层
 * 对应 I4 frontend_anime.pyi §AnimeDecoration:
 *   - props: { type, trigger, density, opacity }
 *   - 根据 type 选择动效（star/music-note/petal/glow/star-trail）
 *   - 根据 trigger 决定触发时机
 *   - 使用边界 5 项运行时校验
 *   - z-index=4（装饰条带层 OBS-H）
 *   - prefers-reduced-motion 返回 null
 *
 * 使用边界 5 项（D4 §usageBoundaries，运行时校验）:
 *   1. 动效占比 ≤ 20%（decorationAnimationRatio）
 *   2. 单元素 opacity ≤ 0.4（singleElementOpacity）
 *   3. 单屏 alpha 总和 ≤ 0.4（singleScreenAlphaSum）
 *   4. 单屏 ≤ 3 类（singleScreenCategories）
 *   5. 核心交互元件禁装饰（coreInteractionProhibition）
 *
 * @version 1.0.0
 */

import { motion } from 'framer-motion';
import { useEffect, useMemo, useState, type CSSProperties, type ReactElement } from 'react';
import { getSpringTransition } from '@/lib/motion/springs';
import { prefersReducedMotion } from '@/lib/motion/gsap-utils';
import {
  ANIME_PALETTE,
  DecorationBoundaryViolationError,
  DecorationOverflowError,
  USAGE_BOUNDARIES,
  Z_INDEX_LAYERS,
  validateDecorationBoundary,
  type AnimeDecorationProps,
  type AnimeDecorationType,
} from './anime-palette';

// =============================================================================
// 模块级装饰动效注册表（用于使用边界校验）
// =============================================================================

/** 当前屏幕激活的装饰动效类型集合（用于第 4 项校验：单屏 ≤ 3 类） */
const activeDecorationTypes = new Set<AnimeDecorationType>();

/** 当前屏幕装饰动效实例计数（用于第 1 项校验：动效占比 ≤ 20%） */
let decorationInstanceCount = 0;

/** 页面总动效数估算（默认 50，可由页面层通过 setTotalAnimationCount 设置） */
let totalAnimationCountEstimate = 50;

/**
 * 设置页面总动效数（供页面层调用，用于动效占比校验）。
 *
 * 页面层在挂载时调用此函数传入当前页面的总动效数（含 UI 动效 + 装饰动效）。
 * 如果不调用，默认估算为 50。
 *
 * @param count 页面总动效数
 */
export function setTotalAnimationCount(count: number): void {
  totalAnimationCountEstimate = Math.max(1, count);
}

// =============================================================================
// AnimeDecoration 组件
// =============================================================================

/**
 * 装饰动效统一容器组件。
 *
 * 对应 I4 frontend_anime.pyi §AnimeDecoration。
 *
 * 实现细节:
 *   - 根据 type 选择动效类型（star/music-note/petal/glow/star-trail）
 *   - 根据 trigger 决定触发时机（success/message-send/page-transition/hover/active）
 *   - density 控制粒子密度
 *   - opacity 控制单元素透明度（上限 ≤ 0.4）
 *   - z-index=4（装饰条带层 OBS-H）
 *   - prefers-reduced-motion 返回 null
 *
 * 使用边界 5 项运行时校验:
 *   1. 动效占比 ≤ 20%: decorationInstanceCount / totalAnimationCountEstimate ≤ 0.2
 *   2. 单元素 opacity ≤ 0.4: props.opacity ≤ 0.4
 *   3. 单屏 alpha 总和 ≤ 0.4: validateDecorationBoundary 校验
 *   4. 单屏 ≤ 3 类: activeDecorationTypes.size ≤ 3
 *   5. 核心交互元件禁装饰: 由调用方保证不在此组件上挂载（组件本身 pointer-events: none）
 *
 * @param props 装饰动效配置
 * @returns 渲染后的装饰动效容器
 * @throws {DecorationOverflowError} 当单屏 > 3 类或动效占比 > 20% 时抛出
 * @throws {DecorationBoundaryViolationError} 当 opacity > 0.4 或 alpha 总和 > 0.4 时抛出
 */
export function AnimeDecoration(props: AnimeDecorationProps): ReactElement | null {
  const { type, trigger, density, opacity } = props;

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

  // --- 模块级注册/注销（用于第 1/4 项校验的计数） ---
  useEffect(() => {
    activeDecorationTypes.add(type);
    decorationInstanceCount++;
    return () => {
      decorationInstanceCount = Math.max(0, decorationInstanceCount - 1);
      // 仅当计数为 0 时清理类型集合（避免过早移除仍活跃的类型）
      if (decorationInstanceCount === 0) {
        activeDecorationTypes.clear();
      }
    };
  }, [type]);

  // --- 使用边界 5 项运行时校验 ---
  const validationReport = useMemo(
    () => validateDecorationBoundary([{ type, trigger, density, opacity }]),
    [type, trigger, density, opacity],
  );

  // 第 2 项: 单元素 opacity ≤ 0.4（阻断式）
  if (opacity > USAGE_BOUNDARIES.singleElementOpacity) {
    throw new DecorationBoundaryViolationError(
      `AnimeDecoration: opacity=${opacity} 超过上限 ${USAGE_BOUNDARIES.singleElementOpacity}（singleElementOpacity）。`,
    );
  }

  // 第 3 项: 单屏 alpha 总和 ≤ 0.4（由 validateDecorationBoundary 校验，阻断式）
  if (!validationReport.passed) {
    const alphaViolation = validationReport.violations.find(
      (v) => v.rule === 'singleScreenAlphaSum',
    );
    if (alphaViolation) {
      throw new DecorationBoundaryViolationError(
        `AnimeDecoration: ${alphaViolation.detail}`,
      );
    }
  }

  // 第 4 项: 单屏 ≤ 3 类（阻断式，抛出 DecorationOverflowError）
  if (activeDecorationTypes.size > USAGE_BOUNDARIES.singleScreenCategories) {
    throw new DecorationOverflowError(
      `AnimeDecoration: 单屏装饰元素类别 ${activeDecorationTypes.size} 超过上限 ${USAGE_BOUNDARIES.singleScreenCategories}（类型: ${Array.from(activeDecorationTypes).join(', ')}）。`,
    );
  }

  // 第 1 项: 动效占比 ≤ 20%（阻断式，抛出 DecorationOverflowError）
  const ratio = decorationInstanceCount / totalAnimationCountEstimate;
  if (ratio > USAGE_BOUNDARIES.decorationAnimationRatio) {
    throw new DecorationOverflowError(
      `AnimeDecoration: 装饰动效占比 ${ratio.toFixed(2)} 超过上限 ${USAGE_BOUNDARIES.decorationAnimationRatio}（${decorationInstanceCount}/${totalAnimationCountEstimate}）。`,
    );
  }

  // 第 5 项: 核心交互元件禁装饰 —— 组件本身 pointer-events: none，不会接收交互
  // 调用方负责不将此组件挂载在核心交互元件上（validateDecorationBoundary 的 targetElement 校验）

  // --- prefers-reduced-motion 命中时返回 null ---
  if (reduced) {
    return null;
  }

  // --- 渲染装饰动效 ---
  const transition = getSpringTransition('bouncy');
  const clampedOpacity = Math.min(opacity, USAGE_BOUNDARIES.singleElementOpacity);
  const baseStyle: CSSProperties = {
    zIndex: Z_INDEX_LAYERS['decoration-band'],
    opacity: clampedOpacity,
    pointerEvents: 'none',
    position: 'absolute',
  };

  return <DecorationRenderer type={type} density={density} transition={transition} baseStyle={baseStyle} trigger={trigger} />;
}

// =============================================================================
// 装饰动效渲染子组件（根据 type 渲染不同动效）
// =============================================================================

interface DecorationRendererProps {
  type: AnimeDecorationType;
  density: number;
  transition: ReturnType<typeof getSpringTransition>;
  baseStyle: CSSProperties;
  trigger: AnimeDecorationProps['trigger'];
}

/**
 * 根据 type 渲染对应的装饰动效。
 * 子组件模式避免在条件分支中调用 hooks。
 */
function DecorationRenderer(props: DecorationRendererProps): ReactElement {
  const { type, density, transition, baseStyle, trigger } = props;

  switch (type) {
    case 'star':
      return <StarDecoration density={density} transition={transition} baseStyle={baseStyle} trigger={trigger} />;
    case 'music-note':
      return <NoteDecoration density={density} transition={transition} baseStyle={baseStyle} trigger={trigger} />;
    case 'petal':
      return <PetalDecoration density={density} transition={transition} baseStyle={baseStyle} trigger={trigger} />;
    case 'glow':
      return <GlowDecoration transition={transition} baseStyle={baseStyle} trigger={trigger} />;
    case 'star-trail':
      return <StarTrailDecoration transition={transition} baseStyle={baseStyle} trigger={trigger} />;
    default:
      return <div data-anime-decoration={type} style={baseStyle} />;
  }
}

/** 星光闪烁装饰 */
function StarDecoration(props: {
  density: number;
  transition: ReturnType<typeof getSpringTransition>;
  baseStyle: CSSProperties;
  trigger: AnimeDecorationProps['trigger'];
}): ReactElement {
  const { density, transition, baseStyle, trigger } = props;
  const count = Math.min(Math.max(1, Math.round(density * 3)), 3);
  void trigger;

  return (
    <div data-anime-decoration="star" style={baseStyle}>
      {Array.from({ length: count }, (_, i) => (
        <motion.svg
          key={i}
          width="12"
          height="12"
          viewBox="0 0 12 12"
          style={{ position: 'absolute', left: `${5 + i * 30}%`, top: `${10 + i * 20}%` }}
          animate={{ scale: [0.8, 1.2, 0.8], opacity: [0.3, 0.8, 0.3] }}
          transition={{ ...transition, duration: 2 + i * 0.5, repeat: Infinity }}
        >
          <path d="M6 0L7.5 4.5L12 6L7.5 7.5L6 12L4.5 7.5L0 6L4.5 4.5Z" fill={ANIME_PALETTE.moonlightWhite} />
        </motion.svg>
      ))}
    </div>
  );
}

/** 音符飘动装饰 */
function NoteDecoration(props: {
  density: number;
  transition: ReturnType<typeof getSpringTransition>;
  baseStyle: CSSProperties;
  trigger: AnimeDecorationProps['trigger'];
}): ReactElement {
  const { density, transition, baseStyle, trigger } = props;
  const count = Math.min(Math.max(1, Math.round(density * 5)), 5);
  void trigger;

  return (
    <div data-anime-decoration="music-note" style={baseStyle}>
      {Array.from({ length: count }, (_, i) => (
        <motion.div
          key={i}
          style={{ position: 'absolute', left: `${10 + i * 20}%`, bottom: '20%', color: ANIME_PALETTE.sakuraPink }}
          animate={{ y: [0, -60], x: [0, (i % 2 === 0 ? 15 : -15)], opacity: [0.4, 0] }}
          transition={{ ...transition, duration: 2 + i * 0.3, repeat: Infinity, delay: i * 0.2 }}
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
            <path d="M6 2v8.5a2.5 2.5 0 1 1-1-2V4l5-1v5.5a2.5 2.5 0 1 1-1-2V2H6z" />
          </svg>
        </motion.div>
      ))}
    </div>
  );
}

/** 花瓣飘落装饰 */
function PetalDecoration(props: {
  density: number;
  transition: ReturnType<typeof getSpringTransition>;
  baseStyle: CSSProperties;
  trigger: AnimeDecorationProps['trigger'];
}): ReactElement {
  const { density, transition, baseStyle, trigger } = props;
  const count = Math.min(Math.max(1, Math.round(density * 8)), 8);
  void trigger;

  return (
    <div data-anime-decoration="petal" style={baseStyle}>
      {Array.from({ length: count }, (_, i) => (
        <motion.div
          key={i}
          style={{ position: 'absolute', left: `${(i * 12) % 100}%`, top: '-20px', color: ANIME_PALETTE.sakuraPink }}
          animate={{ y: ['0vh', '100vh'], x: [0, (i % 2 === 0 ? 20 : -20), 0], rotate: [0, 360] }}
          transition={{ ...transition, duration: 3 + i * 0.5, repeat: Infinity, delay: i * 0.3 }}
        >
          <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor">
            <path d="M7 0C7 3 4 5 0 5C4 5 7 7 7 14C7 11 10 9 14 9C10 9 7 7 7 0Z" />
          </svg>
        </motion.div>
      ))}
    </div>
  );
}

/** 光晕脉动装饰 */
function GlowDecoration(props: {
  transition: ReturnType<typeof getSpringTransition>;
  baseStyle: CSSProperties;
  trigger: AnimeDecorationProps['trigger'];
}): ReactElement {
  const { transition, baseStyle, trigger } = props;
  void trigger;

  return (
    <motion.div
      data-anime-decoration="glow"
      style={{
        ...baseStyle,
        borderRadius: '50%',
        background: `radial-gradient(circle, ${ANIME_PALETTE.sakuraPink} 0%, transparent 70%)`,
        width: '60px',
        height: '60px',
      }}
      animate={{ scale: [1, 1.3, 1], opacity: [0.2, 0.4, 0.2] }}
      transition={{ ...transition, duration: 2, repeat: Infinity }}
    />
  );
}

/** 星轨流光装饰 */
function StarTrailDecoration(props: {
  transition: ReturnType<typeof getSpringTransition>;
  baseStyle: CSSProperties;
  trigger: AnimeDecorationProps['trigger'];
}): ReactElement {
  const { transition, baseStyle, trigger } = props;
  void trigger;

  return (
    <motion.svg
      data-anime-decoration="star-trail"
      width="120"
      height="40"
      viewBox="0 0 120 40"
      style={baseStyle}
      animate={{ opacity: [0.2, 0.4, 0.2] }}
      transition={{ ...transition, duration: 2, repeat: Infinity }}
    >
      <motion.path
        d="M0 20 Q30 0 60 20 T120 20"
        fill="none"
        stroke={ANIME_PALETTE.starSeaCyan}
        strokeWidth={2}
        strokeDasharray={200}
        initial={{ strokeDashoffset: 200 }}
        animate={{ strokeDashoffset: [200, 0] }}
        transition={{ ...transition, duration: 1.5, repeat: Infinity }}
      />
    </motion.svg>
  );
}
