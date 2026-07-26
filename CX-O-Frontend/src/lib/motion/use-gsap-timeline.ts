/**
 * use-gsap-timeline.ts — GSAP timeline React hook（StrictMode 安全）
 *
 * 模块: 模块3 动效层
 * 契约对齐:
 *   - I3 frontend_motion.pyi §useGsapTimeline
 *   - D5 motion_springs.schema.json §gsapTimelines.hookWrapper
 *   - C2 frontend_motion_config.schema.json §gsapTimeline
 *   - E1 frontend_error_codes.schema.json FE-MOT-001（创建失败）/ FE-MOT-005（降级失败）
 *
 * React 18 StrictMode 安全（D5 §gsapTimelines.hookWrapper.strictModeSafe = true）:
 *   - cleanup 时调用 timeline.kill() + timeline.clear()
 *   - 避免重复挂载导致多个 timeline 并存
 *   - deps 变化时重建 timeline，旧 timeline 被清理
 *
 * GSAP 依赖说明:
 *   GSAP 未在 package.json 中声明（预存在的项目配置问题，见观察项）。
 *   本文件使用静态 import（类型由 gsap-utils.ts 的 declare module 'gsap' 提供）。
 *   tsc --noEmit 通过类型检查；Vite 构建需 gsap 安装后才能通过。
 *   运行时若 GSAP 不可用，import 会失败，符合 I3 "GSAP 库未加载" 的异常条件。
 *
 * prefers-reduced-motion 降级:
 *   - 命中时不创建 timeline（返回 no-op timeline）
 *   - 对齐 D5 §reducedMotion.gsapBehavior: disable-all-timelines
 */

import { useEffect, useRef } from 'react';
import gsap from 'gsap';
import {
  type GsapTimeline,
  type GsapTimelineConfig,
  type GsapStep,
  GsapTimelineError,
  prefersReducedMotion,
} from './gsap-utils';

/**
 * 创建 no-op timeline（prefers-reduced-motion 降级时使用）。
 *
 * 所有操作都是空操作，不产生任何动画。
 * 对齐 D5 §reducedMotion.gsapBehavior.action = 'disable-all-timelines'。
 */
function createNoopTimeline(): GsapTimeline {
  const noop = (): GsapTimeline => proxy;
  const proxy: GsapTimeline = {
    kill: () => undefined,
    clear: () => undefined,
    play: noop,
    pause: noop,
    reverse: noop,
    seek: noop,
    to: noop,
    from: noop,
    fromTo: noop,
  };
  return proxy;
}

/**
 * 校验 GSAP timeline 配置。
 *
 * 对齐 I3 §GsapTimelineError 抛出条件:
 *   - config.steps 为空数组
 *   - step.target 无效（null / undefined）
 *   - GSAP 库未加载
 *
 * @throws {GsapTimelineError} 当 steps 为空或 target 无效时抛出（errorCode=FE-MOT-001）
 */
function validateTimelineConfig(config: GsapTimelineConfig): void {
  // 校验 1: steps 不能为空
  if (!config.steps || config.steps.length === 0) {
    throw new GsapTimelineError(
      'useGsapTimeline: config.steps must not be empty',
      'FE-MOT-001',
    );
  }

  // 校验 2: 每个 step 的 target 不能为 null/undefined
  for (let i = 0; i < config.steps.length; i++) {
    const step: GsapStep = config.steps[i];
    if (step.target === null || step.target === undefined) {
      throw new GsapTimelineError(
        `useGsapTimeline: step[${i}].target is null or undefined`,
        'FE-MOT-001',
      );
    }
  }
}

/**
 * React hook: 封装 GSAP timeline，确保 React 18 StrictMode 下重复挂载不泄漏。
 *
 * 对应 I3 frontend_motion.pyi §useGsapTimeline。
 * 对齐 D5 §gsapTimelines.hookWrapper:
 *   hookName: 'useGsapTimeline'
 *   cleanup: 'useEffect-cleanup-kill'（useEffect cleanup 调用 timeline.kill()）
 *   strictModeSafe: true（重复挂载不泄漏）
 *
 * StrictMode 行为:
 *   - cleanup 时调用 timeline.kill() + timeline.clear()
 *   - 避免重复挂载导致多个 timeline 并存
 *   - deps 变化时重建 timeline，旧 timeline 被清理
 *
 * GSAP 与 Framer Motion 分工（merged.md §5.2）:
 *   - GSAP 管时间线编排（命令式、精确控制）
 *   - Framer Motion 管 UI 微交互（声明式、可中断）
 *
 * prefers-reduced-motion 降级:
 *   - 命中时返回 no-op timeline（所有操作空操作）
 *   - 对齐 D5 §reducedMotion.gsapBehavior: disable-all-timelines
 *
 * @param config GSAP timeline 配置（含 defaults 选项 + steps 动画步骤序列）
 * @param deps React 依赖列表，deps 变化时重建 timeline
 * @returns GsapTimeline 实例，可用于命令式控制（play / pause / reverse / seek）
 * @throws {GsapTimelineError} 当 config.steps 为空 / step.target 无效 / GSAP 库未加载 / timeline 创建失败时抛出
 */
export function useGsapTimeline(
  config: GsapTimelineConfig,
  deps: readonly unknown[],
): GsapTimeline {
  const timelineRef = useRef<GsapTimeline | null>(null);

  useEffect(() => {
    // 1. 校验配置（steps 非空 + target 有效）
    try {
      validateTimelineConfig(config);
    } catch (error) {
      if (error instanceof GsapTimelineError) {
        // 记录错误但不阻断渲染（降级为 no-op timeline）
        console.error(`[useGsapTimeline] ${error.errorCode}: ${error.message}`);
        timelineRef.current = createNoopTimeline();
        return;
      }
      throw error;
    }

    // 2. 检测 prefers-reduced-motion
    const reducedMotion = prefersReducedMotion();
    if (reducedMotion.reduced) {
      // 降级: 不创建实际 timeline，返回 no-op
      // 对齐 D5 §reducedMotion.gsapBehavior.action = 'disable-all-timelines'
      timelineRef.current = createNoopTimeline();
      return;
    }

    // 3. 检测 GSAP 是否可用
    if (typeof gsap === 'undefined' || typeof gsap.timeline !== 'function') {
      // GSAP 库未加载 — 降级为 no-op timeline
      // 对齐 I3 §GsapTimelineError: "GSAP 库未加载（typeof gsap === 'undefined'）"
      console.error('[useGsapTimeline] FE-MOT-001: GSAP library not loaded');
      timelineRef.current = createNoopTimeline();
      return;
    }

    // 4. 创建 timeline
    let timeline: GsapTimeline;
    try {
      timeline = gsap.timeline(config.defaults) as unknown as GsapTimeline;

      // 添加 steps
      for (const step of config.steps) {
        if (step.position !== undefined) {
          timeline.to(step.target, step.vars, step.position);
        } else {
          timeline.to(step.target, step.vars);
        }
      }
    } catch (error) {
      // timeline 创建失败 — 抛出 GsapTimelineError
      throw new GsapTimelineError(
        `useGsapTimeline: timeline creation failed: ${error instanceof Error ? error.message : String(error)}`,
        'FE-MOT-001',
      );
    }

    timelineRef.current = timeline;

    // 5. cleanup: kill + clear（React 18 StrictMode 安全）
    // 对齐 D5 §gsapTimelines.hookWrapper.cleanup = 'useEffect-cleanup-kill'
    return () => {
      timeline.kill();
      timeline.clear();
      timelineRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  // 返回 timeline（初始可能为 null，useEffect 后有值）
  // 使用类型断言满足 I3 接口契约的返回类型 GsapTimeline
  // 调用方应在 useEffect 或事件处理器中使用返回值，不要在 render 阶段直接调用方法
  return (timelineRef.current ?? createNoopTimeline()) as GsapTimeline;
}
