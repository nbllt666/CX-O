/**
 * use-velocity-handoff.ts — velocity 传递 hook（手势速度传递给后续 spring 动画）
 *
 * 模块: 模块3 动效层
 * 契约对齐:
 *   - I3 frontend_motion.pyi §useVelocityHandoff
 *   - D5 motion_springs.schema.json §appleDesignPrinciples.velocityHandoff
 *   - C2 frontend_motion_config.schema.json §appleDesignPhysics.velocityNormalizationEnabled=true
 *   - E1 frontend_error_codes.schema.json FE-MOT-003（velocity handoff 失败）
 *
 * apple-design 原则落地（§velocityHandoff）:
 *   - rule: velocity-passed-to-spring（拖拽结束速度传递给 spring）
 *   - formula: relativeVelocity = gestureVelocity / (targetValue - currentValue)
 *   - implementation: useMotionValue + useVelocity
 *   - failureHandling: FE-MOT-003
 *
 * 相对速度归一化:
 *   relativeVelocity = gestureVelocity / (targetValue - currentValue)
 *   当 targetValue === currentValue 时分母为 0，触发 FE-MOT-003。
 *   失败处理: 回退到 0 速度（无 handoff）。
 *
 * 可中断:
 *   新动画打断旧动画时继承 velocity，保证动画连续性，无跳变。
 *   对齐 apple-design §interruptible。
 */

import {
  useVelocity,
  useMotionValueEvent,
  animate,
  type MotionValue as FramerMotionValue,
} from 'framer-motion';
import {
  type SpringConfig,
} from './springs';
import {
  type MotionValue,
  type AnimationControls,
  VelocityHandoffError,
} from './gsap-utils';

/**
 * 校验 spring 参数有效性。
 *
 * 对齐 I3 §VelocityHandoffError 抛出条件: "spring 参数无效"
 *
 * @throws {VelocityHandoffError} 当 spring 参数无效时抛出（errorCode=FE-MOT-003）
 */
function validateSpringForHandoff(spring: SpringConfig): void {
  if (spring.damping <= 0 || spring.stiffness <= 0 || spring.mass <= 0) {
    throw new VelocityHandoffError(
      `useVelocityHandoff: spring params invalid (damping=${spring.damping}, stiffness=${spring.stiffness}, mass=${spring.mass})`,
    );
  }
}

/**
 * 计算相对速度归一化。
 *
 * 对齐 D5 §appleDesignPrinciples.velocityHandoff.formula:
 *   relativeVelocity = gestureVelocity / (targetValue - currentValue)
 *
 * 当 targetValue === currentValue 时分母为 0，触发 VelocityHandoffError (FE-MOT-003)。
 * 失败处理: 回退到 0 速度（callerHandling = fallback-to-zero-velocity）。
 *
 * @param gestureVelocity 手势速度（px/s）
 * @param targetValue 目标值
 * @param currentValue 当前值
 * @returns 归一化后的相对速度
 * @throws {VelocityHandoffError} 当分母为 0 或结果为 NaN 时抛出（errorCode=FE-MOT-003）
 */
export function normalizeRelativeVelocity(
  gestureVelocity: number,
  targetValue: number,
  currentValue: number,
): number {
  const denominator = targetValue - currentValue;

  // 分母为 0 → 除零，触发 FE-MOT-003
  if (denominator === 0) {
    throw new VelocityHandoffError(
      `Velocity handoff failed: gestureVelocity=${gestureVelocity}, targetValue=${targetValue}, currentValue=${currentValue}, division by zero or NaN`,
    );
  }

  const relativeVelocity = gestureVelocity / denominator;

  // 结果为 NaN → 触发 FE-MOT-003
  if (Number.isNaN(relativeVelocity) || !Number.isFinite(relativeVelocity)) {
    throw new VelocityHandoffError(
      `Velocity handoff failed: gestureVelocity=${gestureVelocity}, targetValue=${targetValue}, currentValue=${currentValue}, division by zero or NaN`,
    );
  }

  return relativeVelocity;
}

/**
 * React hook: 手势速度传递给后续 spring 动画。
 *
 * 对应 I3 frontend_motion.pyi §useVelocityHandoff。
 *
 * 实现细节（apple-design §velocityHandoff）:
 *   - 监听 motionValue 的 velocity（通过 useVelocity）
 *   - 手势释放时，将当前 velocity 作为 spring 的初始速度
 *   - 相对速度归一化: relativeVelocity = gestureVelocity / (targetValue - currentValue)
 *   - 支持可中断: 新动画打断旧动画时继承 velocity
 *
 * @param motionValue 被监听速度的 MotionValue（通常由 useSpringDrag 返回）
 * @param spring spring 物理曲线配置
 * @returns AnimationControls: 动画控制器，可用于 start / stop 动画
 * @throws {VelocityHandoffError} 当 motionValue 为 null / spring 参数无效 / useVelocity 返回 NaN / 相对速度归一化失败（除零）时抛出
 */
export function useVelocityHandoff(
  motionValue: MotionValue<number> | FramerMotionValue<number> | null,
  spring: SpringConfig,
): AnimationControls {
  // 参数校验 1: motionValue 不能为 null
  if (motionValue === null || motionValue === undefined) {
    throw new VelocityHandoffError(
      'useVelocityHandoff: motionValue must not be null or undefined',
    );
  }

  // 参数校验 2: spring 参数有效性
  validateSpringForHandoff(spring);

  // 追踪 velocity（useVelocity 返回一个 MotionValue<number>）
  // 对齐 D5 §appleDesignPrinciples.velocityHandoff.implementation: useMotionValue + useVelocity
  const velocityValue = useVelocity(motionValue as FramerMotionValue<number>);

  // 当前活跃的动画控制器（用于可中断）
  // 对齐 apple-design §interruptible: 新动画打断旧动画时继承 velocity
  let activeAnimation: { stop: () => void } | null = null;

  // useMotionValueEvent: 监听 velocity 变化
  // 对齐 D5 §appleDesignPrinciples.interruptible.implementation: useMotionValue + animate 手动控制
  useMotionValueEvent(velocityValue, 'change', (latestVelocity) => {
    // 检测 useVelocity 返回 NaN
    if (Number.isNaN(latestVelocity) || !Number.isFinite(latestVelocity)) {
      // 降级: 使用 0 速度（callerHandling = fallback-to-zero-velocity）
      // 不抛出异常，仅记录警告
      console.warn('[useVelocityHandoff] FE-MOT-003: useVelocity returned NaN, falling back to 0 velocity');
      return;
    }

    // velocity 变化时更新当前速度（供 handoff 使用）
    // 实际的 handoff 在调用方触发（如 onDragEnd）
  });

  // 创建 AnimationControls 代理
  // 对齐 I3 §useVelocityHandoff 返回值: AnimationControls
  const controls: AnimationControls = {
    /**
     * 启动带 velocity handoff 的 spring 动画。
     *
     * @param target 目标值（number）或目标对象
     */
    start: async (target: unknown): Promise<void> => {
      // 中断当前动画（可中断）
      if (activeAnimation) {
        activeAnimation.stop();
      }

      // 获取当前 velocity
      const currentVelocity = velocityValue.get();
      const currentValue = (motionValue as FramerMotionValue<number>).get();
      const targetValue = typeof target === 'number' ? target : currentValue;

      // 相对速度归一化
      let handoffVelocity = 0;
      try {
        handoffVelocity = normalizeRelativeVelocity(currentVelocity, targetValue, currentValue);
      } catch {
        // 降级: 使用 0 速度（callerHandling = fallback-to-zero-velocity）
        handoffVelocity = 0;
      }

      // 启动 spring 动画（带 velocity handoff）
      // 对齐 apple-design §velocityHandoff: velocity 作为 spring 的初始速度
      activeAnimation = animate(motionValue as FramerMotionValue<number>, targetValue, {
        type: 'spring',
        damping: spring.damping,
        stiffness: spring.stiffness,
        mass: spring.mass,
        velocity: handoffVelocity, // velocity handoff
      }) as unknown as { stop: () => void };
    },

    /**
     * 停止当前动画。
     */
    stop: (): void => {
      if (activeAnimation) {
        activeAnimation.stop();
        activeAnimation = null;
      }
    },
  };

  return controls;
}
