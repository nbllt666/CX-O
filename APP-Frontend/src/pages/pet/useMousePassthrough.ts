/**
 * useMousePassthrough — 桌宠窗鼠标穿透钩子。
 *
 * 行为口径对齐 CX-O-Frontend usePetMousePassthrough（几何椭圆命中），
 * 扩展点：附加交互区域（聊天气泡/输入框/右键菜单）以 ref 注册，
 * 命中任一区域即恢复拦截，其余区域经 IPC 穿透到桌面。
 *
 * 命中几何纯逻辑见 ./hitGeometry.ts（可单测）。
 */
import { useCallback, useEffect, useRef } from 'react';
import type { RefObject } from 'react';
import {
  shouldIgnoreMouse,
  DEFAULT_HIT_ELLIPSE,
  type HitEllipse,
  type ClientRect,
} from './hitGeometry';

export interface UseMousePassthroughOptions {
  /** 头像容器（内部查找 canvas 作为椭圆命中基准） */
  avatarContainerRef: RefObject<HTMLElement | null>;
  /** 附加交互区域（聊天气泡、输入框、右键菜单等） */
  interactiveRefs?: Array<RefObject<HTMLElement | null>>;
  /** 自定义命中椭圆（默认 DEFAULT_HIT_ELLIPSE） */
  hitEllipse?: HitEllipse;
  /** 总开关（浏览器模式无 electronAPI 时自动空转） */
  enabled?: boolean;
}

function toClientRect(rect: DOMRect): ClientRect {
  return { x: rect.left, y: rect.top, width: rect.width, height: rect.height };
}

export function useMousePassthrough({
  avatarContainerRef,
  interactiveRefs = [],
  hitEllipse = DEFAULT_HIT_ELLIPSE,
  enabled = true,
}: UseMousePassthroughOptions): void {
  const lastStateRef = useRef<boolean | null>(null);
  const hitEllipseRef = useRef(hitEllipse);
  hitEllipseRef.current = hitEllipse;
  const interactiveRefsRef = useRef(interactiveRefs);
  interactiveRefsRef.current = interactiveRefs;

  const setIgnore = useCallback((ignore: boolean) => {
    if (lastStateRef.current === ignore) return;
    lastStateRef.current = ignore;
    void window.electronAPI?.setIgnoreMouseEvents(ignore);
  }, []);

  useEffect(() => {
    if (!enabled) return;
    if (!window.electronAPI?.setIgnoreMouseEvents) return;

    const handleMouseMove = (e: MouseEvent) => {
      const container = avatarContainerRef.current;
      const canvas = container?.querySelector('canvas') ?? null;
      const canvasRect = canvas ? toClientRect(canvas.getBoundingClientRect()) : null;

      const extraRects: ClientRect[] = [];
      for (const ref of interactiveRefsRef.current) {
        const el = ref.current;
        if (!el) continue;
        // 隐藏元素（display:none / 空闲收起的菜单）不参与命中
        if (el.offsetWidth === 0 && el.offsetHeight === 0) continue;
        extraRects.push(toClientRect(el.getBoundingClientRect()));
      }

      setIgnore(shouldIgnoreMouse(e.clientX, e.clientY, canvasRect, hitEllipseRef.current, extraRects));
    };

    const handleMouseLeave = () => {
      setIgnore(true);
    };

    // 自愈兜底：主进程 window:set-ignore-mouse-events 在 ignore=true 时不带 forward，
    // 穿透期间渲染进程收不到任何鼠标事件（单行道陷阱）。
    // 但穿透点击落到桌面/他窗时本窗失焦，blur 是焦点事件不受 ignore 影响，
    // 借此恢复拦截，使下一次悬停可重新参与命中判定，窗口永不永久卡死。
    const handleWindowBlur = () => {
      lastStateRef.current = null;
      setIgnore(false);
    };

    window.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseleave', handleMouseLeave);
    window.addEventListener('blur', handleWindowBlur);

    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseleave', handleMouseLeave);
      window.removeEventListener('blur', handleWindowBlur);
    };
  }, [enabled, avatarContainerRef, setIgnore]);

  // 卸载或停用时恢复拦截，避免窗口残留穿透状态无法交互
  useEffect(() => {
    if (!enabled) {
      lastStateRef.current = null;
      void window.electronAPI?.setIgnoreMouseEvents(false);
    }
  }, [enabled]);
}
