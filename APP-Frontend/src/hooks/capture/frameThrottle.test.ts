import { describe, expect, it } from 'vitest';

import {
  computeAdaptiveIntervalSec,
  computeChangeMagnitude,
  isDuplicateFrame,
  magnitudeFromGrays,
  pickActiveFrameSource,
  shouldSendByInterval,
} from './frameThrottle';
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

describe('computeChangeMagnitude', () => {
  it('无前帧（prevDataUrl=null）→ 0', async () => {
    await expect(computeChangeMagnitude('data:image/jpeg;base64,AA==', null)).resolves.toBe(0);
  });

  it('两帧 dataURL 完全一致 → 0（快速路径）', async () => {
    await expect(computeChangeMagnitude('data:img,a', 'data:img,a')).resolves.toBe(0);
  });

  it('无 canvas 环境（node/jsdom）降级为 0 且不抛错', async () => {
    await expect(computeChangeMagnitude('data:img,a', 'data:img,b')).resolves.toBe(0);
  });
});

describe('magnitudeFromGrays（像素差异纯函数路径）', () => {
  it('全同 → 0', () => {
    expect(magnitudeFromGrays([0, 0, 0], [0, 0, 0])).toBe(0);
  });

  it('全异 → 接近 1', () => {
    expect(magnitudeFromGrays([0, 0, 0], [255, 255, 255])).toBeCloseTo(1, 5);
  });

  it('长度不一致 → 0（无从比较）', () => {
    expect(magnitudeFromGrays([0], [0, 0])).toBe(0);
  });
});

describe('computeAdaptiveIntervalSec', () => {
  it('magnitude 高 → 趋近 minSec（发送更频繁）', () => {
    expect(computeAdaptiveIntervalSec({ baseIntervalSec: 5, magnitude: 1 })).toBe(1);
    expect(computeAdaptiveIntervalSec({ baseIntervalSec: 5, magnitude: 0.9 })).toBeLessThan(5);
  });

  it('magnitude 低 → 趋近 maxSec（间隔更松）', () => {
    expect(computeAdaptiveIntervalSec({ baseIntervalSec: 5, magnitude: 0 })).toBe(60);
    expect(computeAdaptiveIntervalSec({ baseIntervalSec: 5, magnitude: 0.1 })).toBeGreaterThan(5);
  });

  it('magnitude 0.5 → 收敛到 baseIntervalSec', () => {
    expect(computeAdaptiveIntervalSec({ baseIntervalSec: 8, magnitude: 0.5 })).toBe(8);
  });

  it('单调：magnitude 递增则 interval 递减', () => {
    const vals = [0, 0.25, 0.5, 0.75, 1].map((m) =>
      computeAdaptiveIntervalSec({ baseIntervalSec: 10, magnitude: m }),
    );
    for (let i = 1; i < vals.length; i++) {
      expect(vals[i]).toBeLessThanOrEqual(vals[i - 1]);
    }
  });

  it('边界钳制：magnitude 越界与 min/max 校验', () => {
    expect(computeAdaptiveIntervalSec({ baseIntervalSec: 5, magnitude: -1 })).toBe(60);
    expect(computeAdaptiveIntervalSec({ baseIntervalSec: 5, magnitude: 2 })).toBe(1);
    // 自定义区间边界
    expect(computeAdaptiveIntervalSec({ baseIntervalSec: 5, magnitude: 0, minSec: 2, maxSec: 10 })).toBe(10);
    expect(computeAdaptiveIntervalSec({ baseIntervalSec: 5, magnitude: 1, minSec: 2, maxSec: 10 })).toBe(2);
  });
});
