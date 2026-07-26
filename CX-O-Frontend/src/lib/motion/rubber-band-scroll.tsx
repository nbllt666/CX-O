/**
 * rubber-band-scroll.tsx — 橡皮筋滚动组件（iOS 风格边界回弹）
 *
 * 模块: 模块3 动效层
 * 契约对齐:
 *   - I3 frontend_motion.pyi §RubberBandScroll
 *   - D5 motion_springs.schema.json §appleDesignPrinciples.rubberBand
 *   - C2 frontend_motion_config.schema.json §appleDesignPhysics（rubberBandDamping=20 / rubberBandStiffness=180）
 *   - E1 frontend_error_codes.schema.json FE-MOT-004（rubber-band 失败）
 *
 * apple-design 原则落地（§rubberBand）:
 *   - rule: boundary-bounce（边界回弹）
 *   - component: RubberBandScroll（自建组件）
 *   - damping: 20（默认）
 *   - stiffness: 180（默认）
 *   - scope: ios-native-scroll-only（仅在 iOS 原生滚动容器启用，避免与 React 滚动容器冲突）
 *
 * 实现方式:
 *   基于 Framer Motion motion.div 的 drag + dragConstraints + dragElastic + dragTransition。
 *   dragTransition.bounceStiffness / bounceDamping 控制 rubber-band 回弹的 spring 参数。
 *
 * 异常处理:
 *   - children 不是单个 React 元素 → RubberBandError (FE-MOT-004)
 *   - bounds 参数无效（top > bottom / left > right）→ RubberBandError (FE-MOT-004)
 *   - damping / stiffness 参数无效（≤ 0）→ RubberBandError (FE-MOT-004)
 *   - useDrag 初始化失败（Pointer Events 不支持）→ RubberBandError (FE-MOT-004)
 */

import { type ReactNode, type CSSProperties, Children, isValidElement } from 'react';
import { motion } from 'framer-motion';
import {
  type Bounds,
  RubberBandError,
} from './gsap-utils';

/**
 * RubberBandScroll 组件 props。
 *
 * 对应 I3 frontend_motion.pyi §RubberBandScroll 签名:
 *   RubberBandScroll(children, className, bounds, *, damping=20, stiffness=180)
 *
 * TypeScript 转换: 使用 props 对象（React 惯例）。
 */
export interface RubberBandScrollProps {
  /** 子元素（必须是单个 React 元素） */
  readonly children: ReactNode;
  /** 容器 CSS 类名 */
  readonly className?: string;
  /** 回弹边界 */
  readonly bounds: Bounds;
  /** 阻尼系数，默认 20（对齐 D5 §rubberBand.damping） */
  readonly damping?: number;
  /** 刚度系数，默认 180（对齐 D5 §rubberBand.stiffness） */
  readonly stiffness?: number;
  /** 拖拽轴向，默认 'y'（垂直滚动） */
  readonly axis?: 'x' | 'y' | 'both';
  /** 弹性系数（0-1，超出边界后的阻力，默认 0.2） */
  readonly elastic?: number;
  /** 自定义内联样式 */
  readonly style?: CSSProperties;
}

/**
 * 校验 children 是否为单个 React 元素。
 *
 * 对齐 I3 §RubberBandError 抛出条件: "children 不是单个 React 元素（React.Children.count !== 1）"
 *
 * @throws {RubberBandError} 当 children 不是单个 React 元素时抛出（errorCode=FE-MOT-004）
 */
function validateChildren(children: ReactNode): void {
  const count = Children.count(children);
  if (count !== 1) {
    throw new RubberBandError(
      `RubberBandScroll: children must be a single React element, got ${count} elements`,
    );
  }

  if (!isValidElement(children)) {
    throw new RubberBandError(
      'RubberBandScroll: children must be a valid React element',
    );
  }
}

/**
 * 校验 bounds 参数有效性。
 *
 * 对齐 I3 §RubberBandError 抛出条件: "bounds 参数无效（top > bottom / left > right）"
 *
 * @throws {RubberBandError} 当 bounds 参数无效时抛出（errorCode=FE-MOT-004）
 */
function validateBoundsForRubberBand(bounds: Bounds): void {
  if (bounds.top > bounds.bottom) {
    throw new RubberBandError(
      `RubberBandScroll: bounds invalid (top=${bounds.top} > bottom=${bounds.bottom})`,
    );
  }
  if (bounds.left > bounds.right) {
    throw new RubberBandError(
      `RubberBandScroll: bounds invalid (left=${bounds.left} > right=${bounds.right})`,
    );
  }
}

/**
 * 校验 damping / stiffness 参数有效性。
 *
 * 对齐 I3 §RubberBandError 抛出条件: "damping / stiffness 参数无效（≤ 0）"
 *
 * @throws {RubberBandError} 当 damping 或 stiffness ≤ 0 时抛出（errorCode=FE-MOT-004）
 */
function validateRubberBandParams(damping: number, stiffness: number): void {
  if (damping <= 0) {
    throw new RubberBandError(
      `RubberBandScroll: damping=${damping} must be > 0`,
    );
  }
  if (stiffness <= 0) {
    throw new RubberBandError(
      `RubberBandScroll: stiffness=${stiffness} must be > 0`,
    );
  }
}

/**
 * 检测浏览器是否支持 Pointer Events。
 *
 * 对齐 I3 §RubberBandError 抛出条件: "useDrag 初始化失败"
 * Framer Motion 的 drag 依赖 Pointer Events。如果不支持，降级为原生滚动。
 *
 * @returns 是否支持 Pointer Events
 */
function supportsPointerEvents(): boolean {
  if (typeof window === 'undefined') return false;
  return (
    typeof window.PointerEvent === 'function' ||
    typeof window.PointerEvent === 'object' ||
    'ontouchstart' in window
  );
}

/**
 * React 组件: 可滚动容器边界回弹（rubber-band）。
 *
 * 对应 I3 frontend_motion.pyi §RubberBandScroll。
 *
 * 实现细节（apple-design §rubberBand）:
 *   - 基于 Framer Motion motion.div 的 drag + dragConstraints + dragElastic + dragTransition
 *   - damping=20 / stiffness=180（Apple 风格 rubber-band，对齐 D5 §rubberBand）
 *   - 拖拽超出 bounds 时产生回弹动效
 *   - iOS 原生滚动容器启用，避免与 React 滚动容器冲突
 *
 * 降级策略:
 *   - Pointer Events 不支持时降级为原生滚动（overflow: auto），丧失 rubber-band 效果但保持可用性
 *   - 对齐 I3 §RubberBandError callerHandling: "降级为原生滚动（overflow: auto）"
 *
 * @param props 组件 props（children / className / bounds / damping / stiffness / axis / elastic / style）
 * @returns 渲染后的滚动容器
 * @throws {RubberBandError} 当 children 不是单个 React 元素 / bounds 参数无效 / damping 或 stiffness 参数无效（≤ 0）时抛出
 */
export function RubberBandScroll(props: RubberBandScrollProps): ReactNode {
  const {
    children,
    className,
    bounds,
    damping = 20,
    stiffness = 180,
    axis = 'y',
    elastic = 0.2,
    style,
  } = props;

  // 参数校验
  validateChildren(children);
  validateBoundsForRubberBand(bounds);
  validateRubberBandParams(damping, stiffness);

  // 检测 Pointer Events 支持
  if (!supportsPointerEvents()) {
    // 降级: 原生滚动（无 rubber-band 效果）
    // 对齐 I3 §RubberBandError callerHandling: "降级为原生滚动（overflow: auto）"
    return (
      <div
        className={className}
        style={{
          overflow: 'auto',
          ...style,
        }}
      >
        {children}
      </div>
    );
  }

  // rubber-band 滚动容器
  // 对齐 apple-design §rubberBand:
  //   damping=20 / stiffness=180 / scope=ios-native-scroll-only
  // dragTransition.bounceStiffness / bounceDamping 控制 rubber-band 回弹 spring 参数
  return (
    <motion.div
      className={className}
      drag={axis === 'both' ? true : axis}
      dragConstraints={{
        top: bounds.top,
        left: bounds.left,
        right: bounds.right,
        bottom: bounds.bottom,
      }}
      dragElastic={elastic}
      dragTransition={{
        bounceStiffness: stiffness,
        bounceDamping: damping,
      }}
      style={{
        overflow: 'auto',
        ...style,
      }}
    >
      {children}
    </motion.div>
  );
}
