/**
 * 鼠标穿透命中几何：纯逻辑层（无 DOM/React 依赖，可单测）。
 *
 * 策略与 CX-O-Frontend usePetMousePassthrough 同口径：
 * 头像区域用「归一化椭圆」近似模型包围区，命中即拦截鼠标；
 * 额外的交互矩形（聊天气泡/输入框/右键菜单）命中同样拦截；
 * 其余区域穿透到桌面。
 */

/** 归一化椭圆（相对画布宽高，0~1）：圆心 + 半径 */
export type HitEllipse = {
  cx: number;
  cy: number;
  rx: number;
  ry: number;
};

/** 客户端坐标系矩形（px） */
export type ClientRect = {
  x: number;
  y: number;
  width: number;
  height: number;
};

/** 默认头像命中区：略偏上的椭圆（对齐参考实现 [0.5, 0.45, 0.3, 0.4]） */
export const DEFAULT_HIT_ELLIPSE: HitEllipse = { cx: 0.5, cy: 0.45, rx: 0.3, ry: 0.4 };

/** 点（客户端坐标）是否落在画布内的归一化椭圆区域中 */
export function pointInEllipse(
  px: number,
  py: number,
  canvasRect: ClientRect,
  ellipse: HitEllipse,
): boolean {
  const { x, y, width, height } = canvasRect;
  if (width <= 0 || height <= 0) return false;
  if (px < x || px > x + width || py < y || py > y + height) return false;
  const nx = (px - x) / width;
  const ny = (py - y) / height;
  const dx = (nx - ellipse.cx) / ellipse.rx;
  const dy = (ny - ellipse.cy) / ellipse.ry;
  return dx * dx + dy * dy <= 1;
}

/** 点（客户端坐标）是否落在矩形内（边界含等号） */
export function pointInRect(px: number, py: number, rect: ClientRect): boolean {
  return (
    rect.width > 0 &&
    rect.height > 0 &&
    px >= rect.x &&
    px <= rect.x + rect.width &&
    py >= rect.y &&
    py <= rect.y + rect.height
  );
}

/**
 * 是否应穿透（setIgnoreMouseEvents 的入参）。
 * 命中头像椭圆或任一附加交互矩形 → 不穿透（false）；其余 → 穿透（true）。
 */
export function shouldIgnoreMouse(
  px: number,
  py: number,
  canvasRect: ClientRect | null,
  ellipse: HitEllipse,
  extraRects: ClientRect[],
): boolean {
  if (canvasRect && pointInEllipse(px, py, canvasRect, ellipse)) {
    return false;
  }
  for (const rect of extraRects) {
    if (pointInRect(px, py, rect)) {
      return false;
    }
  }
  return true;
}
