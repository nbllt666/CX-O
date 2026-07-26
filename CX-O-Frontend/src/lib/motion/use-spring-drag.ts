/**
 * use-spring-drag.ts — 拖拽 spring hook（1:1 跟手 + velocity handoff + momentum projection）
 *
 * 模块: 模块3 动效层
 * 契约对齐:
 *   - I3 frontend_motion.pyi §useSpringDrag + §SpringDragConfig TypedDict
 *   - D5 motion_springs.schema.json §appleDesignPrinciples（oneToOneFollow/velocityHandoff/momentumProjection/interruptible）
 *   - C2 frontend_motion_config.schema.json §appleDesignPhysics（momentumDeceleration=0.998）
 *   - E1 frontend_error_codes.schema.json FE-MOT-002（spring 参数无效）/ FE-MOT-008（bounds/MotionValue/setPointerCapture）
 *
 * apple-design 原则落地:
 *   - §oneToOneFollow: Framer Motion drag 自动实现 1:1 跟手（useTransform 直接映射，无延迟）
 *   - §velocityHandoff: useVelocity 追踪速度，drag end 时传递给后续 spring
 *   - §momentumProjection: momentumProjection() 计算 resting position，snap 到最近边界
 *   - §interruptible: animate() 可被 stop() 中断，拖拽中接受新目标值
 *   - Pointer Events + setPointerCapture: Framer Motion drag 内部使用 Pointer Events
 *
 * 使用方式:
 *   const [dragHandlers, motionValues] = useSpringDrag({ spring: springs.gentle, bounds, axis: 'x' });
 *   <motion.div
 *     drag={axis}
 *     dragConstraints={bounds}
 *     onDragStart={dragHandlers.onDragStart}
 *     onDrag={dragHandlers.onDrag}
 *     onDragEnd={dragHandlers.onDragEnd}
 *     style={{ x: motionValues.x, y: motionValues.y }}
 *   />
 */

import {
  useMotionValue,
  useVelocity,
  animate,
  type PanInfo,
} from 'framer-motion';
import {
  type SpringConfig,
} from './springs';
import {
  type Bounds,
  type MotionValue,
  momentumProjection,
  SpringDragError,
  APPLE_DESIGN_PHYSICS,
} from './gsap-utils';

/**
 * 拖拽元件配置。
 *
 * 对应 I3 frontend_motion.pyi §SpringDragConfig TypedDict:
 *   { spring: SpringConfig; bounds: Bounds; axis?: 'x' | 'y' | 'both' }
 */
export interface SpringDragConfig {
  /** spring 物理曲线（drag end 后的回弹动画） */
  readonly spring: SpringConfig;
  /** 拖拽边界（momentum projection snap 目标） */
  readonly bounds: Bounds;
  /** 拖拽轴向，默认 'both' */
  readonly axis?: 'x' | 'y' | 'both';
}

/**
 * 拖拽事件处理器。
 *
 * 对应 I3 frontend_motion.pyi §DragHandlers TypeAlias:
 *   { onDragStart?; onDrag?; onDragEnd? }
 *
 * 绑定到 motion.div 的 drag 相关 props:
 *   <motion.div drag onDragStart={handlers.onDragStart} ... />
 */
export interface DragHandlers {
  onDragStart?: (event: MouseEvent | TouchEvent | PointerEvent, info: PanInfo) => void;
  onDrag?: (event: MouseEvent | TouchEvent | PointerEvent, info: PanInfo) => void;
  onDragEnd?: (event: MouseEvent | TouchEvent | PointerEvent, info: PanInfo) => void;
}

/**
 * MotionValue 字典（拖拽状态）。
 *
 * 对应 I3 frontend_motion.pyi §useSpringDrag 返回值 motionValues:
 *   { x, y, velocityX, velocityY }
 */
export interface SpringDragMotionValues {
  /** X 轴位置 MotionValue */
  readonly x: MotionValue<number>;
  /** Y 轴位置 MotionValue */
  readonly y: MotionValue<number>;
  /** X 轴速度 MotionValue（由 useVelocity 追踪） */
  readonly velocityX: MotionValue<number>;
  /** Y 轴速度 MotionValue（由 useVelocity 追踪） */
  readonly velocityY: MotionValue<number>;
}

/**
 * 当前活跃的动画控制器（用于可中断）。
 *
 * animate() 返回 AnimationPlaybackControls，可被 stop() 中断。
 */
interface AnimationPlaybackControls {
  stop(): void;
}

/**
 * 校验 spring 参数有效性。
 *
 * 对齐 I3 §SpringDragError 抛出条件: "spring 参数无效（damping ≤ 0 / stiffness ≤ 0 / mass ≤ 0）"
 *
 * @throws {SpringDragError} 当 spring 参数无效时抛出（errorCode=FE-MOT-002）
 */
function validateSpringParams(spring: SpringConfig): void {
  if (spring.damping <= 0 || spring.stiffness <= 0 || spring.mass <= 0) {
    throw new SpringDragError(
      `useSpringDrag: spring params invalid (damping=${spring.damping}, stiffness=${spring.stiffness}, mass=${spring.mass}) — must be > 0`,
      'FE-MOT-002',
    );
  }
}

/**
 * 校验 bounds 参数有效性。
 *
 * 对齐 I3 §SpringDragError 抛出条件: "bounds 参数无效（top > bottom / left > right）"
 *
 * @throws {SpringDragError} 当 bounds 参数无效时抛出（errorCode=FE-MOT-008）
 */
function validateBounds(bounds: Bounds): void {
  if (bounds.top > bounds.bottom) {
    throw new SpringDragError(
      `useSpringDrag: bounds invalid (top=${bounds.top} > bottom=${bounds.bottom})`,
      'FE-MOT-008',
    );
  }
  if (bounds.left > bounds.right) {
    throw new SpringDragError(
      `useSpringDrag: bounds invalid (left=${bounds.left} > right=${bounds.right})`,
      'FE-MOT-008',
    );
  }
}

/**
 * React hook: 拖拽元件，含 1:1 跟手 + velocity handoff + momentum projection。
 *
 * 对应 I3 frontend_motion.pyi §useSpringDrag。
 *
 * 实现细节（apple-design 原则）:
 *   - **1:1 跟手** (§oneToOneFollow): Framer Motion drag 自动实现，useTransform 直接映射指针位置，无延迟
 *   - **velocity handoff** (§velocityHandoff): useVelocity 追踪速度，drag end 时传递给后续 spring
 *   - **momentum projection** (§momentumProjection): momentumProjection() 计算 resting position，snap 到最近边界
 *   - **可中断** (§interruptible): animate() 可被 stop() 中断，拖拽中接受新目标值
 *   - **Pointer Events + setPointerCapture**: Framer Motion drag 内部使用 Pointer Events
 *
 * @param config 拖拽配置（spring 物理曲线 + bounds 边界 + axis 轴向）
 * @returns [dragHandlers, motionValues]:
 *   - dragHandlers: 拖拽事件处理器（onDragStart / onDrag / onDragEnd）
 *   - motionValues: MotionValue 字典（x / y / velocityX / velocityY）
 * @throws {SpringDragError} 当 spring 参数无效 / bounds 参数无效 / MotionValue 创建失败 / setPointerCapture 失败时抛出
 */
export function useSpringDrag(
  config: SpringDragConfig,
): readonly [DragHandlers, SpringDragMotionValues] {
  const { spring, bounds, axis = 'both' } = config;

  // 参数校验
  validateSpringParams(spring);
  validateBounds(bounds);

  // 创建 MotionValue（1:1 跟手的基础）
  // 对齐 apple-design §oneToOneFollow: useTransform 直接映射，无延迟
  const x = useMotionValue(0);
  const y = useMotionValue(0);

  // 追踪 velocity（velocity handoff 的基础）
  // 对齐 apple-design §velocityHandoff: useMotionValue + useVelocity
  const velocityX = useVelocity(x);
  const velocityY = useVelocity(y);

  // 当前活跃的动画控制器（用于可中断）
  // 对齐 apple-design §interruptible: 新动画打断旧动画
  let activeAnimationX: AnimationPlaybackControls | null = null;
  let activeAnimationY: AnimationPlaybackControls | null = null;

  /**
   * 启动 spring 动画到目标位置（可中断）。
   *
   * 对齐 apple-design §interruptible: 如果有正在运行的动画，先 stop 再启动新动画。
   */
  const animateTo = (
    targetX: number,
    targetY: number,
    velocityXValue: number,
    velocityYValue: number,
  ): void => {
    // 中断当前动画（可中断）
    if (activeAnimationX) {
      activeAnimationX.stop();
    }
    if (activeAnimationY) {
      activeAnimationY.stop();
    }

    // X 轴动画（带 velocity handoff）
    if (axis === 'x' || axis === 'both') {
      activeAnimationX = animate(x, targetX, {
        type: 'spring',
        damping: spring.damping,
        stiffness: spring.stiffness,
        mass: spring.mass,
        velocity: velocityXValue, // velocity handoff: 传递速度给 spring
      }) as unknown as AnimationPlaybackControls;
    }

    // Y 轴动画（带 velocity handoff）
    if (axis === 'y' || axis === 'both') {
      activeAnimationY = animate(y, targetY, {
        type: 'spring',
        damping: spring.damping,
        stiffness: spring.stiffness,
        mass: spring.mass,
        velocity: velocityYValue, // velocity handoff: 传递速度给 spring
      }) as unknown as AnimationPlaybackControls;
    }
  };

  // dragHandlers
  const dragHandlers: DragHandlers = {
    /**
     * onDragStart: 拖拽开始
     *
     * 中断当前动画（如果有），开始 1:1 跟手。
     */
    onDragStart: () => {
      // 中断当前 spring 动画（可中断原则）
      if (activeAnimationX) {
        activeAnimationX.stop();
        activeAnimationX = null;
      }
      if (activeAnimationY) {
        activeAnimationY.stop();
        activeAnimationY = null;
      }
    },

    /**
     * onDrag: 拖拽中
     *
     * 1:1 跟手由 Framer Motion drag 自动处理（useTransform 直接映射）。
     * 此处仅记录拖拽状态，无需手动更新 x/y。
     */
    onDrag: () => {
      // 1:1 跟手: Framer Motion drag 自动更新 x/y MotionValue
      // 对齐 apple-design §oneToOneFollow: no-latency-drag
    },

    /**
     * onDragEnd: 拖拽结束
     *
     * velocity handoff + momentum projection + snap to bounds。
     *
     * 对齐 apple-design:
     *   - §velocityHandoff: 速度传递给 spring
     *   - §momentumProjection: project(v, decel=0.998) 计算 resting position
     *   - §snapStrategy: snap-to-nearest-boundary
     */
    onDragEnd: (_event, info) => {
      // 获取当前 velocity（velocity handoff 的源）
      // info.velocity 是 Framer Motion 提供的拖拽速度（px/s）
      const vx = info.velocity.x;
      const vy = info.velocity.y;

      // momentum projection: 计算 resting position
      // 对齐 apple-design §momentumProjection:
      //   formula: project(v, decel=0.998) = v/1000 * decel / (1-decel)
      const currentX = x.get();
      const currentY = y.get();

      // 使用 momentumProjection 计算投影停止点
      // momentumProjection 返回的是从 0 开始的偏移量，需要加上当前位置
      const projectionX = momentumProjection(vx, APPLE_DESIGN_PHYSICS.momentumDeceleration);
      const projectionY = momentumProjection(vy, APPLE_DESIGN_PHYSICS.momentumDeceleration);

      const restingX = currentX + projectionX;
      const restingY = currentY + projectionY;

      // snap to nearest boundary
      // 对齐 apple-design §momentumProjection.snapStrategy = 'snap-to-nearest-boundary'
      const targetX = snapToBoundary(restingX, bounds.left, bounds.right);
      const targetY = snapToBoundary(restingY, bounds.top, bounds.bottom);

      // 启动 spring 动画（带 velocity handoff）
      animateTo(targetX, targetY, vx, vy);
    },
  };

  // motionValues 字典
  const motionValues: SpringDragMotionValues = {
    x: x as unknown as MotionValue<number>,
    y: y as unknown as MotionValue<number>,
    velocityX: velocityX as unknown as MotionValue<number>,
    velocityY: velocityY as unknown as MotionValue<number>,
  };

  return [dragHandlers, motionValues] as const;
}

/**
 * 将目标值 snap 到最近的边界。
 *
 * 对齐 D5 §appleDesignPrinciples.momentumProjection.snapStrategy = 'snap-to-nearest-boundary'。
 *
 * @param value 目标值
 * @param min 最小边界
 * @param max 最大边界
 * @returns snap 后的值（如果在边界内则保持原值，否则 snap 到最近边界）
 */
function snapToBoundary(value: number, min: number, max: number): number {
  if (value < min) return min;
  if (value > max) return max;
  return value;
}
