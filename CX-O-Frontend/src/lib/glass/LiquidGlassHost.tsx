/**
 * LiquidGlassHost.tsx — Liquid Glass 全局挂载组件（React 包装）
 * ============================================================================
 * 用途: 在 main.tsx 全局挂载，实例化 LiquidGlassRenderer 并运行渲染循环
 *
 * 核心职责:
 *   1. 创建 fixed 全屏 canvas（z-index=2，pointer-events=none）
 *   2. 实例化 LiquidGlassRenderer（失败则 console.warn + return null，CSS 兜底接管）
 *   3. rAF 渲染循环：DOM 扫描 [data-glass] 元素 + 上传 uniform + render
 *   4. resize 监听 + DPR 适配
 *   5. webglcontextlost 事件 → dispose + return null
 *   6. prefers-reduced-motion 命中时 uIntensity=0
 *   7. 主题变化时通过 CSS 变量获取 uTint（粉紫青）
 *
 * 与原 GlassRendererHost.tsx（250 LOC）的差异:
 *   - ✅ 简化的 DOM 扫描（仅 getBoundingClientRect，无 OffscreenCanvas）
 *   - ✅ rAF 节流（非 200ms 定时器）
 *   - ✅ 失败时添加/移除 webgl-active class 控制 CSS 切换
 * ============================================================================
 */

import { useEffect, useRef, useState, type ReactElement } from 'react';
import { LiquidGlassRenderer, GPUContextLossError, GLSLCompileError, type GlassElementRect, type GlassUniforms } from './liquid-glass-renderer';

/** DOM 扫描节流间隔（ms） */
const DOM_SCAN_THROTTLE_MS = 100;

/** 指针位置 30fps 节流间隔（ms） */
const POINTER_THROTTLE_MS = 1000 / 30;

/** 最大玻璃元素数量 */
const MAX_GLASS_ELEMENTS = 8;

/**
 * 扫描 DOM 中的 [data-glass] 元素，转换为 NDC 坐标。
 */
function scanGlassElements(): GlassElementRect[] {
  if (typeof document === 'undefined') return [];

  const elements = document.querySelectorAll<HTMLElement>('[data-glass="true"]');
  const rects: GlassElementRect[] = [];

  const viewportWidth = window.innerWidth;
  const viewportHeight = window.innerHeight;

  elements.forEach((el) => {
    if (rects.length >= MAX_GLASS_ELEMENTS) return;

    // 跳过不可见元素
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return;

    // 转换为 NDC 坐标 [-1, 1]
    const centerX = rect.left + rect.width / 2;
    const centerY = rect.top + rect.height / 2;

    const ndcX = (centerX / viewportWidth) * 2 - 1;
    const ndcY = -((centerY / viewportHeight) * 2 - 1); // Y 轴翻转

    const ndcW = (rect.width / viewportWidth) * 2;
    const ndcH = (rect.height / viewportHeight) * 2;

    rects.push({ x: ndcX, y: ndcY, w: ndcW, h: ndcH });
  });

  return rects;
}

/**
 * 从 CSS 变量获取主题着色 RGB。
 */
function getThemeTint(): [number, number, number] {
  if (typeof window === 'undefined') return [1.0, 0.72, 0.88]; // 默认樱花粉

  const root = document.documentElement;
  const r = parseFloat(getComputedStyle(root).getPropertyValue('--glass-tint-r')) || 255;
  const g = parseFloat(getComputedStyle(root).getPropertyValue('--glass-tint-g')) || 183;
  const b = parseFloat(getComputedStyle(root).getPropertyValue('--glass-tint-b')) || 225;

  return [r / 255, g / 255, b / 255];
}

/**
 * 检测 prefers-reduced-motion。
 */
function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || !window.matchMedia) return false;
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/**
 * LiquidGlassHost 组件。
 */
export function LiquidGlassHost(): ReactElement | null {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rendererRef = useRef<LiquidGlassRenderer | null>(null);
  const animationFrameRef = useRef<number | null>(null);
  const lastScanTimeRef = useRef(0);
  const elementsRef = useRef<GlassElementRect[]>([]);
  const pointerPositionRef = useRef<[number, number]>([0.5, 0.5]);
  const lastPointerUpdateRef = useRef(0);
  const scrollVelocityRef = useRef<[number, number]>([0, 0]);
  const lastScrollYRef = useRef(0);
  const lastScrollXRef = useRef(0);
  const [webglAvailable, setWebglAvailable] = useState(true);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    // 将 canvas 移到 body 层级，脱离 React #root 的 stacking context
    // 否则 z-index: -1 会跑到 #root 后面被背景色盖住
    if (canvas.parentElement !== document.body) {
      document.body.appendChild(canvas);
    }

    // 设置 canvas 全屏样式
    // v2.1: WebGL canvas 降级为装饰增强层（流动光带、指针光斑）
    // CSS backdrop-filter 是玻璃主体，永远生效；WebGL 仅作锦上添花
    canvas.style.position = 'fixed';
    canvas.style.top = '0';
    canvas.style.left = '0';
    canvas.style.width = '100vw';
    canvas.style.height = '100vh';
    canvas.style.pointerEvents = 'none';
    canvas.style.zIndex = '0'; // 在 body 层级，0 即在所有内容之下（内容区 z-index >= 1）
    canvas.style.mixBlendMode = 'normal'; // 不再用 screen，避免稀释效果
    canvas.style.opacity = '0.6'; // 装饰层半透明，不喧宾夺主

    // 设置 canvas 实际像素尺寸（DPR 适配）
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.floor(window.innerWidth * dpr);
    canvas.height = Math.floor(window.innerHeight * dpr);

    // 实例化渲染器
    try {
      const renderer = new LiquidGlassRenderer(canvas);
      rendererRef.current = renderer;

      // 标记 WebGL 可用（CSS 隐藏 backdrop-filter）
      document.documentElement.classList.add('webgl-active');

      console.info(
        `[LiquidGlassHost] WebGL 初始化成功 (webgl2=${renderer.isUsingWebGL2()}, tier=WebGL 主体)`,
      );
    } catch (e) {
      if (e instanceof GPUContextLossError) {
        console.warn('[LiquidGlassHost] WebGL 不可用，降级到 CSS backdrop-filter:', e.message);
      } else if (e instanceof GLSLCompileError) {
        console.warn('[LiquidGlassHost] Shader 编译失败，降级到 CSS backdrop-filter:', e.message);
      } else {
        console.warn('[LiquidGlassHost] 初始化失败，降级到 CSS:', e);
      }

      // 移除 webgl-active class（CSS backdrop-filter 接管）
      document.documentElement.classList.remove('webgl-active');
      setWebglAvailable(false);
      return;
    }

    // 监听窗口 resize
    const handleResize = () => {
      const renderer = rendererRef.current;
      if (!renderer) return;
      renderer.resize(window.innerWidth, window.innerHeight);
    };
    window.addEventListener('resize', handleResize, { passive: true });

    // 监听鼠标移动（30fps 节流）
    const handleMouseMove = (e: MouseEvent) => {
      const now = performance.now();
      if (now - lastPointerUpdateRef.current < POINTER_THROTTLE_MS) return;
      lastPointerUpdateRef.current = now;
      const x = e.clientX / window.innerWidth;
      const y = 1.0 - (e.clientY / window.innerHeight);
      pointerPositionRef.current = [x, y];
    };
    window.addEventListener('mousemove', handleMouseMove, { passive: true });

    // 监听滚动（计算滚动速度）
    const handleScroll = () => {
      const scrollY = window.scrollY;
      const scrollX = window.scrollX;
      const dy = scrollY - lastScrollYRef.current;
      const dx = scrollX - lastScrollXRef.current;
      lastScrollYRef.current = scrollY;
      lastScrollXRef.current = scrollX;

      // 归一化并衰减
      scrollVelocityRef.current = [
        Math.max(-1, Math.min(1, dx / 100)),
        Math.max(-1, Math.min(1, dy / 100)),
      ];
    };
    window.addEventListener('scroll', handleScroll, { passive: true });

    // 监听 WebGL 上下文丢失
    const handleContextLost = (e: Event) => {
      e.preventDefault();
      console.warn('[LiquidGlassHost] WebGL 上下文丢失，降级到 CSS backdrop-filter');
      document.documentElement.classList.remove('webgl-active');
      setWebglAvailable(false);

      if (rendererRef.current) {
        rendererRef.current.dispose();
        rendererRef.current = null;
      }
    };
    canvas.addEventListener('webglcontextlost', handleContextLost);

    // 渲染循环
    const renderLoop = (timestamp: number) => {
      const renderer = rendererRef.current;
      if (!renderer) return;

      // DOM 扫描（节流）
      if (timestamp - lastScanTimeRef.current > DOM_SCAN_THROTTLE_MS) {
        lastScanTimeRef.current = timestamp;
        elementsRef.current = scanGlassElements();
      }

      // 衰减滚动速度
      scrollVelocityRef.current[0] *= 0.9;
      scrollVelocityRef.current[1] *= 0.9;

      // 获取主题着色
      const tint = getThemeTint();

      // reduced-motion 时强度为 0
      const intensity = prefersReducedMotion() ? 0 : 1;

      const uniforms: GlassUniforms = {
        uTime: timestamp / 1000,
        uPointer: pointerPositionRef.current,
        uScrollVelocity: scrollVelocityRef.current,
        uTint: tint,
        uIntensity: intensity,
      };

      try {
        renderer.render(elementsRef.current, uniforms);
      } catch (e) {
        if (e instanceof GPUContextLossError) {
          console.warn('[LiquidGlassHost] 渲染过程中上下文丢失，降级到 CSS:', e.message);
          document.documentElement.classList.remove('webgl-active');
          setWebglAvailable(false);
          return;
        }
        console.error('[LiquidGlassHost] 渲染错误:', e);
      }

      animationFrameRef.current = requestAnimationFrame(renderLoop);
    };

    animationFrameRef.current = requestAnimationFrame(renderLoop);

    // 清理
    return () => {
      window.removeEventListener('resize', handleResize);
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('scroll', handleScroll);
      canvas.removeEventListener('webglcontextlost', handleContextLost);

      if (animationFrameRef.current !== null) {
        cancelAnimationFrame(animationFrameRef.current);
        animationFrameRef.current = null;
      }

      if (rendererRef.current) {
        rendererRef.current.dispose();
        rendererRef.current = null;
      }

      // 移除 webgl-active class
      document.documentElement.classList.remove('webgl-active');
    };
  }, []);

  // WebGL 不可用时不渲染 canvas
  if (!webglAvailable) return null;

  return (
    <canvas
      ref={canvasRef}
      data-glass-host="true"
      aria-hidden="true"
      style={{ display: 'block' }}
    />
  );
}
