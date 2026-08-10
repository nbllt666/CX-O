import { describe, expect, it } from 'vitest';

import { isDuplicateFrame, pickActiveFrameSource, shouldSendByInterval } from './frameThrottle';
import type { FrameSource } from './frameThrottle';

function makeSource(kind: 'screen' | 'camera', active: boolean): FrameSource {
  return { kind, active, captureFrame: () => `data:image/jpeg;base64,${kind}` };
}

describe('pickActiveFrameSource', () => {
  it('空列表返回 null', () => {
    expect(pickActiveFrameSource([])).toBeNull();
  });

  it('全部未激活返回 null', () => {
    expect(pickActiveFrameSource([makeSource('screen', false), makeSource('camera', false)])).toBeNull();
  });

  it('取第一个激活源（屏幕优先）', () => {
    const picked = pickActiveFrameSource([makeSource('screen', true), makeSource('camera', true)]);
    expect(picked?.kind).toBe('screen');
  });

  it('屏幕未激活时落到摄像头', () => {
    const picked = pickActiveFrameSource([makeSource('screen', false), makeSource('camera', true)]);
    expect(picked?.kind).toBe('camera');
  });
});

describe('shouldSendByInterval', () => {
  it('从未发送过立即放行首帧', () => {
    expect(shouldSendByInterval(1000, null, 5)).toBe(true);
  });

  it('未满间隔不放行', () => {
    expect(shouldSendByInterval(4000, 1000, 5)).toBe(false);
  });

  it('恰好满间隔放行', () => {
    expect(shouldSendByInterval(6000, 1000, 5)).toBe(true);
  });

  it('超过间隔放行', () => {
    expect(shouldSendByInterval(60000, 1000, 5)).toBe(true);
  });

  it('非正间隔按 0 处理（每次放行）', () => {
    expect(shouldSendByInterval(1001, 1000, 0)).toBe(true);
    expect(shouldSendByInterval(1001, 1000, -3)).toBe(true);
  });
});

describe('isDuplicateFrame', () => {
  it('首帧不算重复', () => {
    expect(isDuplicateFrame('data:a', null)).toBe(false);
  });

  it('与上次发送一致判重复', () => {
    expect(isDuplicateFrame('data:a', 'data:a')).toBe(true);
  });

  it('画面变化不算重复', () => {
    expect(isDuplicateFrame('data:b', 'data:a')).toBe(false);
  });
});
