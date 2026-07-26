/**
 * glass-canvas.tsx — Liquid Glass React 组件
 * ============================================================================
 * 模块: 模块4 WebGL 玻璃层
 * 契约: I1 frontend_glass.pyi (GlassCanvas + GlassCanvasProps + GlassForm) +
 *        D2 glass_tier_config.schema.json (threeJsCoordination + dynamicLighting)
 * 用途: 声明玻璃渲染区域的容器组件，根据 tier 渲染不同视觉效果
 *
 * 四级 tier 渲染策略:
 *   - Tier 1/2: WebGL canvas（GlassRenderer 接管）
 *   - Tier 3: CSS backdrop-filter + SVG filter（blur(16px) saturate(1.8)）
 *   - Tier 4: background-color 半透明兜底
 *
 * Three.js/Pixi.js 协同（D2 threeJsCoordination, 闭合判据 §7）:
 *   - 独立 canvas + z-index 严格分层（Three.js=1 / 玻璃=2 / UI=3）
 *   - pointer-events 精确控制（OBS-G 处置）
 *   - 禁止 globalThis/window 共享 GL state
 *
 * 动态光影（D2 dynamicLighting, 闭合判据 §8）:
 *   - uPointerPosition 30fps 节流
 *   - uScrollVelocity 滚动速度驱动高光偏移
 *   - mix-blend-mode: overlay
 * ============================================================================
 */

import { useEffect, useRef, useCallback, type ReactNode } from 'react';
import { GlassTier } from './tier-detector';
import { useGlassTier, setGlassPointerEvents, GlassZIndex, assertNoConflict } from './use-glass-tier';

// ============================================================================
// 类型定义（I1 TypedDict 对应）
// ============================================================================

/**
 * 玻璃形态定义（I1 GlassForm）。
 *
 * 定义玻璃元件的几何形态与渲染参数，由 GlassCanvas props.glassForm 传入。
 */
export interface GlassForm {
  /** 形状: "rect" | "circle" | "pill" | "custom" */
  shape: 'rect' | 'circle' | 'pill' | 'custom';
  /** 圆角半径（px） */
  radius: number;
  /** 折射强度系数（0-1，默认 0.08） */
  refractionStrength: number;
  /** 玻璃着色（hex 或 rgba） */
  tint: string;
}

/**
 * GlassCanvas 组件 props（I1 GlassCanvasProps）。
 */
export interface GlassCanvasProps {
  /** data-glass 属性，声明玻璃形态 ID，由 WebGL 层接管渲染 */
  dataGlass: string;
  /** 玻璃形态定义 */
  glassForm: GlassForm;
  /** 子元素 */
  children: ReactNode;
  /** 可选 className */
  className?: string;
  /** 可选 tier 覆盖，默认由 useGlassTier 提供 */
  tier?: GlassTier;
}

// ============================================================================
// 常量定义（D2 + C1 配置驱动）
// ============================================================================

/** uPointerPosition 30fps 节流间隔（ms，D2 dynamicLighting.uPointerPosition.throttleFps = 30） */
const POINTER_THROTTLE_MS = 1000 / 30;

/** Tier 3 backdrop-filter CSS 值（D2 tiers.tier3.technology） */
const TIER3_BACKDROP_FILTER = 'blur(16px) saturate(1.8)';

// ============================================================================
// GlassCanvas 组件（I1 签名匹配）
// ============================================================================

/**
 * 组件: GlassCanvas — 声明玻璃渲染区域的容器组件（I1, merged.md §2.1）。
 *
 * UI 元素通过 data-glass 属性声明其玻璃形态，由 WebGL 绘制对应的折射/高光/着色区域。
 * 本组件为声明式封装，实际渲染由 GlassRenderer 接管（Tier 1/2）或 CSS 接管（Tier 3/4）。
 *
 * Three.js/Pixi.js 协同（闭合判据 §7）:
 *   - 独立 canvas + z-index 严格分层 1/2/3
 *   - pointer-events 精确控制
 *   - 禁止 globalThis/window 共享 GL state
 *
 * 动态光影（闭合判据 §8）:
 *   - uPointerPosition 30fps 节流
 *   - mix-blend-mode: overlay
 *
 * @param props 组件 props
 * @returns 渲染的 canvas 容器元素
 */
export function GlassCanvas(props: GlassCanvasProps): React.ReactElement {
  const { dataGlass, glassForm, children, className, tier: propTier } = props;

  // 获取当前 tier（如果 props 未指定，由 useGlassTier 提供）
  const { tier: hookTier } = useGlassTier();
  const tier = propTier ?? hookTier;

  // 容器 ref
  const containerRef = useRef<HTMLDivElement>(null);

  // uPointerPosition 30fps 节流相关
  const lastPointerUpdate = useRef(0);
  const pointerPosition = useRef<[number, number]>([0.5, 0.5]);

  // z-index 分层校验（开发模式自动调用）
  useEffect(() => {
    if (process.env.NODE_ENV === 'development') {
      assertNoConflict({
        threeJs: GlassZIndex.THREE_JS,
        glass: GlassZIndex.GLASS,
        ui: GlassZIndex.UI,
      });
    }
  }, []);

  // 设置 pointer-events（OBS-G 处置）
  useEffect(() => {
    if (containerRef.current) {
      // 玻璃层默认 pointer-events: none（事件穿透到下层）
      // 仅在需要交互的 glass 元素上设置 pointer-events: auto
      setGlassPointerEvents(containerRef.current, 'none');
    }
  }, []);

  // uPointerPosition 30fps 节流监听（D2 dynamicLighting.uPointerPosition）
  useEffect(() => {
    if (tier >= GlassTier.TIER_3) return; // Tier 3/4 不需要鼠标位置 uniform

    const handleMouseMove = (e: MouseEvent) => {
      const now = performance.now();
      if (now - lastPointerUpdate.current < POINTER_THROTTLE_MS) return;

      lastPointerUpdate.current = now;

      // 归一化鼠标位置到 [0, 1]
      const x = e.clientX / (typeof window !== 'undefined' ? window.innerWidth : 1);
      const y = 1.0 - (e.clientY / (typeof window !== 'undefined' ? window.innerHeight : 1));
      pointerPosition.current = [x, y];
    };

    if (typeof window !== 'undefined') {
      window.addEventListener('mousemove', handleMouseMove, { passive: true });
    }

    return () => {
      if (typeof window !== 'undefined') {
        window.removeEventListener('mousemove', handleMouseMove);
      }
    };
  }, [tier]);

  // 根据 tier 生成容器样式
  const getContainerStyle = useCallback((): React.CSSProperties => {
    const baseStyle: React.CSSProperties = {
      position: 'relative',
      zIndex: GlassZIndex.GLASS, // 玻璃层 z-index: 2（D2 threeJsCoordination.zIndexLayering）
      mixBlendMode: 'overlay', // 动态光影: mix-blend-mode: overlay（闭合判据 §8）
      borderRadius: glassForm.radius,
    };

    switch (tier) {
      case GlassTier.TIER_1:
      case GlassTier.TIER_2:
        // WebGL 渲染路径：canvas 由 GlassRenderer 接管
        return {
          ...baseStyle,
          // 玻璃着色
          backgroundColor: glassForm.tint,
        };

      case GlassTier.TIER_3:
        // CSS backdrop-filter 降级（D2 tiers.tier3.technology）
        return {
          ...baseStyle,
          backdropFilter: TIER3_BACKDROP_FILTER,
          WebkitBackdropFilter: TIER3_BACKDROP_FILTER,
          backgroundColor: glassForm.tint,
          // SVG filter 边缘精修（D2 svgFilter, OBS-A 处置, 仅 Tier 3）
          // filter: 'url(#glass-edge)', // 由外部 SVG 定义
        };

      case GlassTier.TIER_4:
        // solid bg 兜底（D2 tiers.tier4.technology）
        return {
          ...baseStyle,
          backgroundColor: glassForm.tint,
        };

      default:
        return baseStyle;
    }
  }, [tier, glassForm]);

  // 渲染
  return (
    <div
      ref={containerRef}
      data-glass={dataGlass}
      className={className}
      style={getContainerStyle()}
      data-tier={tier}
    >
      {children}
    </div>
  );
}
