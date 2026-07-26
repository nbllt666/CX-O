/**
 * @file touch-adapter.tsx
 * @module 模块9b/移动端降级层
 *
 * 触摸适配组件。提供 tap/hover/press 手势映射，消费 D6 touchAdaptation + C3 touchAdaptation 配置。
 *
 * 契约对齐：
 * - 数据契约 D6 responsive_breakpoints.schema.json §touchAdaptation：
 *   - minTapTarget: 44×44px（Apple HIG）
 *   - hoverDegradeOnCoarsePointer: hover 态在 pointer: coarse 降级为 active
 *   - longPressContextMenu: 长按手势替代右键菜单
 *   - rubberBandScope: rubber-band 仅 iOS 原生滚动容器
 * - 配置契约 C3 frontend_responsive_config.schema.json §touchAdaptation（4 项参数，配置驱动）
 * - 错误码契约 E1 frontend_error_codes.schema.json FE-RES-003（触摸适配冲突复用此错误码）
 *
 * 手势映射（对齐 D6 touchAdaptation）：
 * - tap: 单击（pointerup 在 300ms 内且未移动 > 10px）
 * - hover: 鼠标设备展示 hover 态；coarse pointer（触摸屏）降级为 active 态
 * - press: 长按（pointerdown 后 500ms 未释放且未移动），替代右键菜单
 *
 * 跨模块约束（AGENTS.md §4.3）：
 * - 仅 import 模块9a（useMobileDetect）+ 模块9b（degradation-rules 触摸适配配置类型）
 * - 不 import 模块1/2/3/5/6/7/8 任何内部实现
 *
 * @example 基础用法
 * ```tsx
 * import { TouchAdapter } from '@/lib/responsive/touch-adapter';
 *
 * function Button({ children, onSelect, onLongPress }) {
 *   return (
 *     <TouchAdapter onTap={onSelect} onPress={onLongPress}>
 *       <button>{children}</button>
 *     </TouchAdapter>
 *   );
 * }
 * ```
 *
 * @example hover 降级
 * ```tsx
 * // 触摸设备：hover 自动降级为 active 态
 * <TouchAdapter onHover={() => showTooltip()} onTap={() => select()}>
 *   <Card>悬停或点击</Card>
 * </TouchAdapter>
 * ```
 */

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from 'react';

// 模块9a：移动端检测
import { useMobileDetect } from './use-mobile-detect';

// 模块9b：触摸适配配置类型 + 错误码
import {
  DEFAULT_TOUCH_ADAPTATION_CONFIG,
  type TouchAdaptationConfig,
} from './degradation-rules';
import { MOBILE_DEGRADE_ERROR_CODES, MobileDegradeError } from './mobile-degradation';

// ============================================================================
// 一、常量
// ============================================================================

/** tap 判定时间阈值（ms）。pointerup 在 300ms 内判定为 tap。 */
const TAP_TIMEOUT_MS = 300;

/** press 长按时间阈值（ms）。pointerdown 后 500ms 未释放判定为 press。 */
const PRESS_TIMEOUT_MS = 500;

/** tap/press 移动容差（px）。移动距离 > 10px 取消手势判定。 */
const MOVE_TOLERANCE_PX = 10;

// ============================================================================
// 二、手势状态类型
// ============================================================================

/** 手势状态枚举。 */
export type GestureState = 'idle' | 'tap' | 'hover' | 'press';

/**
 * useTouchAdapter hook 返回值。
 */
export interface UseTouchAdapterResult {
  /** 当前手势状态 */
  gesture: GestureState;
  /** 是否处于 active 态（tap/press 触发时为 true） */
  isActive: boolean;
  /** 是否处于 hover 态（仅 fine pointer 设备） */
  isHovering: boolean;
  /** 是否已触发 press（长按） */
  isPressed: boolean;
  /** 注入到目标元素的事件处理器 */
  handlers: {
    onPointerDown: (e: ReactPointerEvent) => void;
    onPointerMove: (e: ReactPointerEvent) => void;
    onPointerUp: (e: ReactPointerEvent) => void;
    onPointerCancel: (e: ReactPointerEvent) => void;
    onPointerEnter: (e: ReactPointerEvent) => void;
    onPointerLeave: (e: ReactPointerEvent) => void;
  };
}

/**
 * useTouchAdapter hook 选项。
 */
export interface UseTouchAdapterOptions {
  /** 触摸适配配置（对齐 C3 touchAdaptation，配置驱动） */
  config?: Partial<TouchAdaptationConfig>;
  /** tap 回调 */
  onTap?: (e: ReactPointerEvent) => void;
  /** hover 回调（coarse pointer 降级为 active 时改触发 onTap） */
  onHover?: (e: ReactPointerEvent) => void;
  /** press（长按）回调 */
  onPress?: (e: ReactPointerEvent) => void;
}

// ============================================================================
// 三、useTouchAdapter hook
// ============================================================================

/**
 * 触摸适配 hook。提供 tap/hover/press 手势映射。
 *
 * 手势判定逻辑：
 * - pointerdown: 记录起始时间 + 位置，启动 press 长按定时器（500ms）
 * - pointermove: 移动距离 > 10px 取消 tap/press 判定
 * - pointerup:
 *   - 500ms 内 + 未移动 → tap
 *   - 500ms 后（press 定时器已触发）→ 不触发 tap
 * - pointerenter/leave:
 *   - fine pointer（鼠标）→ hover 态
 *   - coarse pointer（触摸）→ 降级为 active 态（D6 hoverDegradeOnCoarsePointer）
 *
 * 配置驱动（rules-3 §三）：
 * - minTouchTargetSize / hoverToActiveOnCoarsePointer / longPressForContextMenu 从 config 读取
 * - 缺失字段以 DEFAULT_TOUCH_ADAPTATION_CONFIG 补齐
 *
 * @param options - hook 选项
 * @returns 手势状态 + 事件处理器
 */
export function useTouchAdapter(options?: UseTouchAdapterOptions): UseTouchAdapterResult {
  const { config: partialConfig, onTap, onHover, onPress } = options ?? {};

  // 合并配置（对齐 C3 touchAdaptation default）
  const config: TouchAdaptationConfig = {
    ...DEFAULT_TOUCH_ADAPTATION_CONFIG,
    ...partialConfig,
  };

  // 移动端检测（coarse pointer 判定）
  const { isCoarsePointer, hasHover } = useMobileDetect();

  // 手势状态
  const [gesture, setGesture] = useState<GestureState>('idle');
  const [isActive, setIsActive] = useState(false);
  const [isHovering, setIsHovering] = useState(false);
  const [isPressed, setIsPressed] = useState(false);

  // ref 保存手势上下文（避免 re-render）
  const pointerDownRef = useRef<{
    timeStamp: number;
    x: number;
    y: number;
    pressTimer: ReturnType<typeof setTimeout> | null;
    pressTriggered: boolean;
    moved: boolean;
  } | null>(null);

  // ref 保存最新回调
  const onTapRef = useRef(onTap);
  onTapRef.current = onTap;
  const onHoverRef = useRef(onHover);
  onHoverRef.current = onHover;
  const onPressRef = useRef(onPress);
  onPressRef.current = onPress;

  // 清理 press 定时器
  const clearPressTimer = useCallback(() => {
    if (pointerDownRef.current?.pressTimer) {
      clearTimeout(pointerDownRef.current.pressTimer);
      pointerDownRef.current.pressTimer = null;
    }
  }, []);

  // 组件卸载时清理
  useEffect(() => {
    return () => clearPressTimer();
  }, [clearPressTimer]);

  const handlePointerDown = useCallback(
    (e: ReactPointerEvent) => {
      // 仅处理主键（左键 / 触摸 / 触控笔）
      if (e.button !== 0 && e.pointerType === 'mouse') return;

      setIsActive(true);
      setGesture('tap');

      const pressTimer =
        config.longPressForContextMenu && onPressRef.current
          ? setTimeout(() => {
              // 长按触发
              if (pointerDownRef.current && !pointerDownRef.current.moved) {
                pointerDownRef.current.pressTriggered = true;
                setIsPressed(true);
                setGesture('press');
                onPressRef.current?.(e);
              }
            }, PRESS_TIMEOUT_MS)
          : null;

      pointerDownRef.current = {
        timeStamp: e.timeStamp,
        x: e.clientX,
        y: e.clientY,
        pressTimer,
        pressTriggered: false,
        moved: false,
      };
    },
    [config.longPressForContextMenu],
  );

  const handlePointerMove = useCallback((e: ReactPointerEvent) => {
    if (!pointerDownRef.current) return;

    const dx = e.clientX - pointerDownRef.current.x;
    const dy = e.clientY - pointerDownRef.current.y;
    const distance = Math.sqrt(dx * dx + dy * dy);

    if (distance > MOVE_TOLERANCE_PX) {
      pointerDownRef.current.moved = true;
      clearPressTimer();
      // 移动超过容差，取消 tap/press 判定
      setGesture('idle');
      setIsActive(false);
    }
  }, [clearPressTimer]);

  const handlePointerUp = useCallback((e: ReactPointerEvent) => {
    if (!pointerDownRef.current) return;

    clearPressTimer();
    setIsActive(false);

    const elapsed = e.timeStamp - pointerDownRef.current.timeStamp;
    const moved = pointerDownRef.current.moved;
    const pressTriggered = pointerDownRef.current.pressTriggered;

    if (!moved && !pressTriggered && elapsed < TAP_TIMEOUT_MS) {
      // tap 判定成功
      setGesture('tap');
      onTapRef.current?.(e);
    } else if (!moved && pressTriggered) {
      // press 已触发，不再触发 tap（正常路径）
      setGesture('idle');
    } else if (moved) {
      // 移动了，取消手势
      setGesture('idle');
    }

    pointerDownRef.current = null;
    setIsPressed(false);
  }, [clearPressTimer]);

  const handlePointerCancel = useCallback(() => {
    clearPressTimer();
    setGesture('idle');
    setIsActive(false);
    setIsPressed(false);
    pointerDownRef.current = null;
  }, [clearPressTimer]);

  const handlePointerEnter = useCallback(
    (e: ReactPointerEvent) => {
      // hover 态：仅 fine pointer 设备（鼠标/触控笔）
      // coarse pointer（触摸屏）降级为 active 态（D6 hoverDegradeOnCoarsePointer）
      if (config.hoverToActiveOnCoarsePointer && isCoarsePointer) {
        // 触摸设备：不触发 hover，降级为 active（在 pointerdown 时处理）
        return;
      }

      if (hasHover) {
        setIsHovering(true);
        setGesture('hover');
        onHoverRef.current?.(e);
      }
    },
    [config.hoverToActiveOnCoarsePointer, isCoarsePointer, hasHover],
  );

  const handlePointerLeave = useCallback(() => {
    setIsHovering(false);
    if (gesture === 'hover') {
      setGesture('idle');
    }
  }, [gesture]);

  // 手势冲突检测：如果 tap 和 press 同时绑定，press 触发后 pointerup 不应再触发 tap
  // （已在 handlePointerUp 中通过 pressTriggered 标志处理）
  // 额外检测：如果 onTap 和 onPress 都未绑定，但配置启用了 longPressForContextMenu
  useEffect(() => {
    if (config.longPressForContextMenu && !onPressRef.current && !onTapRef.current) {
      // 无回调但启用长按，记录警告（不抛异常，可能仅用于状态展示）
      console.warn(
        '[touch-adapter] longPressForContextMenu enabled but no onTap/onPress callback provided.'
      );
    }
  }, [config.longPressForContextMenu]);

  return {
    gesture,
    isActive,
    isHovering,
    isPressed,
    handlers: {
      onPointerDown: handlePointerDown,
      onPointerMove: handlePointerMove,
      onPointerUp: handlePointerUp,
      onPointerCancel: handlePointerCancel,
      onPointerEnter: handlePointerEnter,
      onPointerLeave: handlePointerLeave,
    },
  };
}

// ============================================================================
// 四、TouchAdapter 组件
// ============================================================================

/**
 * TouchAdapter 组件 props。
 */
export interface TouchAdapterProps {
  /** 子元素 */
  children: ReactNode;
  /** 触摸适配配置（对齐 C3 touchAdaptation，配置驱动） */
  config?: Partial<TouchAdaptationConfig>;
  /** tap 回调 */
  onTap?: (e: ReactPointerEvent) => void;
  /** hover 回调（coarse pointer 降级为 active） */
  onHover?: (e: ReactPointerEvent) => void;
  /** press（长按）回调 */
  onPress?: (e: ReactPointerEvent) => void;
  /** 自定义 className */
  className?: string;
  /** 自定义内联样式 */
  style?: CSSProperties;
  /** 是否禁用触摸适配（仅渲染子元素，不注入手势） */
  disabled?: boolean;
}

/**
 * TouchAdapter 触摸适配组件。
 *
 * 包装子元素，注入 tap/hover/press 手势处理器，并保证最小点击区域（Apple HIG 44×44px）。
 *
 * 特性：
 * - tap/hover/press 手势映射（对齐 D6 touchAdaptation）
 * - hover 在 coarse pointer 设备降级为 active 态
 * - 长按手势替代右键菜单（对齐 D6 longPressContextMenu）
 * - 最小点击区域 44×44px（对齐 D6 minTapTarget，配置驱动）
 * - 手势冲突检测（FE-RES-003 触摸适配冲突）
 *
 * @example
 * ```tsx
 * <TouchAdapter
 *   onTap={(e) => console.log('tap', e)}
 *   onPress={(e) => console.log('long press', e)}
 *   config={{ minTouchTargetSize: 48 }}
 * >
 *   <button>触摸目标</button>
 * </TouchAdapter>
 * ```
 */
export function TouchAdapter({
  children,
  config,
  onTap,
  onHover,
  onPress,
  className,
  style,
  disabled = false,
}: TouchAdapterProps): JSX.Element {
  const { gesture, isActive, isHovering, handlers } = useTouchAdapter({
    config,
    onTap,
    onHover,
    onPress,
  });

  // 合并配置（用于 minTouchTargetSize 样式）
  const mergedConfig: TouchAdaptationConfig = {
    ...DEFAULT_TOUCH_ADAPTATION_CONFIG,
    ...config,
  };

  // 最小点击区域样式（对齐 D6 minTapTarget 44×44px）
  const touchStyle: CSSProperties = {
    minWidth: `${mergedConfig.minTouchTargetSize}px`,
    minHeight: `${mergedConfig.minTouchTargetSize}px`,
    // 触摸设备去除 tap 高亮（对齐 D6 touchAdaptation -webkit-tap-highlight-color）
    WebkitTapHighlightColor: 'transparent',
    // 触摸设备去除长按选中
    WebkitTouchCallout: 'none',
    // user-select 触摸设备禁用
    userSelect: 'none',
    // active 态视觉反馈
    ...(isActive && {
      transform: 'scale(0.97)',
      transition: 'transform 100ms ease-out',
    }),
    ...style,
  };

  if (disabled) {
    return (
      <div className={className} style={style}>
        {children}
      </div>
    );
  }

  return (
    <div
      className={className}
      style={touchStyle}
      data-gesture={gesture}
      data-active={isActive}
      data-hovering={isHovering}
      {...handlers}
    >
      {children}
    </div>
  );
}

// ============================================================================
// 五、便捷 hook：useMinTouchTarget
// ============================================================================

/**
 * useMinTouchTarget 返回值类型。
 */
export interface UseMinTouchTargetResult {
  /** 最小点击区域样式（minWidth/minHeight + 触摸优化） */
  style: CSSProperties;
  /** 最小点击区域尺寸（px） */
  minTouchTargetSize: number;
}

/**
 * 最小点击区域便捷 hook。
 *
 * 返回最小点击区域样式（对齐 D6 touchAdaptation.minTapTarget 44×44px），
 * 供业务组件直接注入到 style 属性。
 *
 * @param config - 触摸适配配置（部分）
 * @returns 最小点击区域样式 + 尺寸
 *
 * @example
 * ```tsx
 * import { useMinTouchTarget } from '@/lib/responsive/touch-adapter';
 *
 * function IconButton() {
 *   const { style } = useMinTouchTarget();
 *   return <button style={style}>×</button>;
 * }
 * ```
 */
export function useMinTouchTarget(
  config?: Partial<TouchAdaptationConfig>,
): UseMinTouchTargetResult {
  const mergedConfig: TouchAdaptationConfig = {
    ...DEFAULT_TOUCH_ADAPTATION_CONFIG,
    ...config,
  };

  const style: CSSProperties = {
    minWidth: `${mergedConfig.minTouchTargetSize}px`,
    minHeight: `${mergedConfig.minTouchTargetSize}px`,
    WebkitTapHighlightColor: 'transparent',
    WebkitTouchCallout: 'none',
    userSelect: 'none',
  };

  return {
    style,
    minTouchTargetSize: mergedConfig.minTouchTargetSize,
  };
}

// ============================================================================
// 六、手势冲突检测（FE-RES-003 触摸适配冲突）
// ============================================================================

/**
 * 手势冲突检测选项。
 */
export interface GestureConflictCheckOptions {
  /** 是否绑定 tap 回调 */
  hasTap: boolean;
  /** 是否绑定 press 回调 */
  hasPress: boolean;
  /** 是否绑定 hover 回调 */
  hasHover: boolean;
  /** 触摸适配配置 */
  config: TouchAdaptationConfig;
}

/**
 * 检测手势配置冲突。
 *
 * 触摸适配冲突场景（对齐 E1 FE-RES-003 触摸适配冲突）：
 * - longPressForContextMenu=false 但绑定了 onPress（配置与回调矛盾）
 * - hoverToActiveOnCoarsePointer=false 但设备为 coarse pointer 且绑定了 onHover（hover 无法降级）
 * - tap 与 press 同时绑定但 longPressForContextMenu 未启用（press 无法触发）
 *
 * 检测到冲突时抛出 MobileDegradeError（FE-RES-003），调用方应捕获并上报。
 *
 * @param options - 冲突检测选项
 * @throws MobileDegradeError 检测到冲突时抛出（failureType='apply-failed'）
 *
 * @example
 * ```ts
 * import { detectGestureConflict } from '@/lib/responsive/touch-adapter';
 *
 * try {
 *   detectGestureConflict({
 *     hasTap: true,
 *     hasPress: true,
 *     hasHover: false,
 *     config: { minTouchTargetSize: 44, hoverToActiveOnCoarsePointer: true, longPressForContextMenu: false, rubberBandOnlyIOS: true },
 *   });
 * } catch (e) {
 *   console.error('Gesture conflict:', e);
 * }
 * ```
 */
export function detectGestureConflict(options: GestureConflictCheckOptions): void {
  const { hasTap, hasPress, hasHover, config } = options;

  // 冲突 1：longPressForContextMenu=false 但绑定了 onPress
  if (!config.longPressForContextMenu && hasPress) {
    throw new MobileDegradeError(
      `[${MOBILE_DEGRADE_ERROR_CODES.MOBILE_DEGRADE_FAILED}] Touch adapter gesture conflict: ` +
        `onPress bound but longPressForContextMenu=false. Press gesture will never trigger.`,
      { failureType: 'apply-failed' },
    );
  }

  // 冲突 2：tap 与 press 同时绑定但 longPressForContextMenu 未启用
  if (hasTap && hasPress && !config.longPressForContextMenu) {
    throw new MobileDegradeError(
      `[${MOBILE_DEGRADE_ERROR_CODES.MOBILE_DEGRADE_FAILED}] Touch adapter gesture conflict: ` +
        `onTap and onPress both bound but longPressForContextMenu=false. ` +
        `Press requires longPressForContextMenu=true to distinguish from tap.`,
      { failureType: 'apply-failed' },
    );
  }

  // 冲突 3：hover 回调绑定但 hoverToActiveOnCoarsePointer=false
  // （此场景下 coarse pointer 设备的 hover 不会降级，可能导致 hover 态无法触发）
  if (hasHover && !config.hoverToActiveOnCoarsePointer) {
    throw new MobileDegradeError(
      `[${MOBILE_DEGRADE_ERROR_CODES.MOBILE_DEGRADE_FAILED}] Touch adapter gesture conflict: ` +
        `onHover bound but hoverToActiveOnCoarsePointer=false. ` +
        `Hover will not degrade to active on coarse pointer devices.`,
      { failureType: 'apply-failed' },
    );
  }
}
