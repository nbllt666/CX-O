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

describe('computeAdaptiveIntervalSec（占空比 dutyCycle）', () => {
  /** 旧实现参考（固定 0.5 锚点）：内联对照基准，防实现漂移（spec 回归承诺的逐点对照） */
  function legacyAdaptiveInterval(opts: {
    baseIntervalSec: number;
    magnitude: number;
    minSec?: number;
    maxSec?: number;
  }): number {
    const minSec = opts.minSec ?? 1;
    const maxSec = opts.maxSec ?? 60;
    const floor = Math.min(minSec, maxSec);
    const ceil = Math.max(minSec, maxSec);
    const m = Math.min(1, Math.max(0, Number.isFinite(opts.magnitude) ? opts.magnitude : 0));
    const base = Number.isFinite(opts.baseIntervalSec)
      ? Math.min(ceil, Math.max(floor, opts.baseIntervalSec))
      : ceil;
    if (m <= 0.5) {
      return ceil - (ceil - base) * (m / 0.5);
    }
    return base - (base - floor) * ((m - 0.5) / 0.5);
  }

  it('回归：不传 dutyCycle 与传 50 的输出均与旧公式逐点一致', () => {
    const cases: Array<{
      baseIntervalSec: number;
      magnitude: number;
      minSec?: number;
      maxSec?: number;
    }> = [
      { baseIntervalSec: 5, magnitude: 0 },
      { baseIntervalSec: 5, magnitude: 0.25 },
      { baseIntervalSec: 8, magnitude: 0.5 },
      { baseIntervalSec: 5, magnitude: 0.75 },
      { baseIntervalSec: 5, magnitude: 1 },
      { baseIntervalSec: 10, magnitude: 0.3, minSec: 2, maxSec: 10 },
      { baseIntervalSec: 10, magnitude: 0.5, minSec: 2, maxSec: 10 },
      { baseIntervalSec: 10, magnitude: 0.6, minSec: 2, maxSec: 10 },
      { baseIntervalSec: 3, magnitude: 0.2, minSec: 20, maxSec: 4 }, // min/max 乱序
      { baseIntervalSec: 5, magnitude: -1 }, // magnitude 越界钳制
      { baseIntervalSec: 5, magnitude: 2 },
      { baseIntervalSec: Number.NaN, magnitude: 0.7 }, // 非法 base 保守处理
    ];
    for (const c of cases) {
      expect(computeAdaptiveIntervalSec(c)).toBe(legacyAdaptiveInterval(c));
      expect(computeAdaptiveIntervalSec({ ...c, dutyCycle: 50 })).toBe(legacyAdaptiveInterval(c));
    }
  });

  it('方向：duty 越大越积极——duty=80 输出 < duty=20 输出，且 duty=20 时低变化度间隔 > base', () => {
    const active = computeAdaptiveIntervalSec({
      baseIntervalSec: 10,
      magnitude: 0.3,
      maxSec: 60,
      dutyCycle: 80,
    });
    const quiet = computeAdaptiveIntervalSec({
      baseIntervalSec: 10,
      magnitude: 0.3,
      maxSec: 60,
      dutyCycle: 20,
    });
    expect(active).toBeLessThan(quiet);
    expect(quiet).toBeGreaterThan(10);
  });

  it('单调：固定 duty=70，magnitude 0→1（步进 0.1）输出单调不增', () => {
    const vals = Array.from({ length: 11 }, (_, i) => i / 10).map((m) =>
      computeAdaptiveIntervalSec({ baseIntervalSec: 10, magnitude: m, dutyCycle: 70 }),
    );
    for (let i = 1; i < vals.length; i++) {
      expect(vals[i]).toBeLessThanOrEqual(vals[i - 1]);
    }
  });

  it('端点：m=0 → maxSec、m=1 → minSec、m=t（duty=70 → t=0.3）→ base', () => {
    expect(computeAdaptiveIntervalSec({ baseIntervalSec: 10, magnitude: 0, dutyCycle: 70, maxSec: 60 })).toBe(60);
    expect(computeAdaptiveIntervalSec({ baseIntervalSec: 10, magnitude: 1, dutyCycle: 70, minSec: 2 })).toBe(2);
    // t=1-70/100 存在浮点表示误差，锚点收敛用 closeTo 断言
    expect(
      computeAdaptiveIntervalSec({ baseIntervalSec: 10, magnitude: 0.3, dutyCycle: 70, maxSec: 60 }),
    ).toBeCloseTo(10, 9);
  });

  it('钳制：duty=5 与 duty=95 分别等价于 duty=10 与 duty=90', () => {
    const opts = { baseIntervalSec: 10, magnitude: 0.4, maxSec: 60 } as const;
    expect(computeAdaptiveIntervalSec({ ...opts, dutyCycle: 5 })).toBe(
      computeAdaptiveIntervalSec({ ...opts, dutyCycle: 10 }),
    );
    expect(computeAdaptiveIntervalSec({ ...opts, dutyCycle: 95 })).toBe(
      computeAdaptiveIntervalSec({ ...opts, dutyCycle: 90 }),
    );
  });

  it('兜底：非有限数 duty（NaN/Infinity）按缺省 50 处理，输出与不传 dutyCycle 一致', () => {
    const opts = { baseIntervalSec: 10, magnitude: 0.6, maxSec: 60 } as const;
    const baseline = computeAdaptiveIntervalSec(opts);
    expect(computeAdaptiveIntervalSec({ ...opts, dutyCycle: Number.NaN })).toBe(baseline);
    expect(computeAdaptiveIntervalSec({ ...opts, dutyCycle: Number.POSITIVE_INFINITY })).toBe(baseline);
  });
});
