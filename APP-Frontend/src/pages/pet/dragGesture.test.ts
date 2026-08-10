import { describe, expect, it } from 'vitest';
import { advanceDragGesture, createDragGestureState, isDragGestureClick } from './dragGesture';

describe('dragGesture', () => {
  it('低于 6px 阈值保持点击状态', () => {
    const state = createDragGestureState(100, 100);
    expect(advanceDragGesture(state, 104, 103)).toEqual({ dx: 0, dy: 0, moved: false });
    expect(isDragGestureClick(state)).toBe(true);
  });

  it('达到 6px 阈值进入拖动态并返回增量', () => {
    const state = createDragGestureState(100, 100);
    expect(advanceDragGesture(state, 106, 100)).toEqual({ dx: 6, dy: 0, moved: true });
    expect(isDragGestureClick(state)).toBe(false);
  });

  it('连续拖动按上次坐标返回增量', () => {
    const state = createDragGestureState(100, 100);
    advanceDragGesture(state, 108, 100);
    expect(advanceDragGesture(state, 111, 104)).toEqual({ dx: 3, dy: 4, moved: true });
  });

  it('空状态不判定为点击', () => {
    expect(isDragGestureClick(null)).toBe(false);
  });
});
