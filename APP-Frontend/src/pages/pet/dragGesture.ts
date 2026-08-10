export interface DragGestureState {
  originX: number;
  originY: number;
  lastX: number;
  lastY: number;
  dragging: boolean;
}

export function createDragGestureState(x: number, y: number): DragGestureState {
  return { originX: x, originY: y, lastX: x, lastY: y, dragging: false };
}

export function advanceDragGesture(
  state: DragGestureState,
  x: number,
  y: number,
  threshold = 6,
): { dx: number; dy: number; moved: boolean } {
  if (!state.dragging && Math.hypot(x - state.originX, y - state.originY) < threshold) {
    return { dx: 0, dy: 0, moved: false };
  }
  state.dragging = true;
  const dx = Math.round(x - state.lastX);
  const dy = Math.round(y - state.lastY);
  if (dx !== 0 || dy !== 0) {
    state.lastX = x;
    state.lastY = y;
  }
  return { dx, dy, moved: dx !== 0 || dy !== 0 };
}

export function isDragGestureClick(state: DragGestureState | null): boolean {
  return !!state && !state.dragging;
}
