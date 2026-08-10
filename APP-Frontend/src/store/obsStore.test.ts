/**
 * obsStore 单测（Task 9：OBS 采集桌宠支持）。
 * 覆盖：采集尺寸预设清单、尺寸合法化、头像自适应缩放决策（Electron/浏览器双路径）、
 * 循环切换推进/回卷，以及 store 默认态与动作行为。
 */
import { beforeEach, describe, expect, it } from 'vitest';

import {
  AVATAR_SCALE_FACTOR_MAX,
  AVATAR_SCALE_FACTOR_MIN,
  CAPTURE_MIN_HEIGHT,
  CAPTURE_MIN_WIDTH,
  CAPTURE_SIZE_PRESETS,
  DEFAULT_CAPTURE_SIZE,
  clampCaptureSize,
  computeAvatarScaleFactor,
  getNextCaptureSize,
  resolveAvatarScale,
  useObsStore,
} from './obsStore';

function resetStore() {
  useObsStore.setState({
    greenScreen: false,
    captureWidth: DEFAULT_CAPTURE_SIZE.width,
    captureHeight: DEFAULT_CAPTURE_SIZE.height,
  });
}

beforeEach(resetStore);

describe('采集尺寸预设清单', () => {
  it('默认档为 400x500，且包含 spec 点名的 400x500 / 550x700 档', () => {
    expect(DEFAULT_CAPTURE_SIZE).toEqual({ width: 400, height: 500 });
    const ids = CAPTURE_SIZE_PRESETS.map((p) => p.id);
    expect(ids).toContain('400x500');
    expect(ids).toContain('550x700');
  });

  it('全部预设不低于桌宠窗最小尺寸 300x400', () => {
    for (const p of CAPTURE_SIZE_PRESETS) {
      expect(p.width).toBeGreaterThanOrEqual(CAPTURE_MIN_WIDTH);
      expect(p.height).toBeGreaterThanOrEqual(CAPTURE_MIN_HEIGHT);
    }
  });
});

describe('clampCaptureSize（尺寸合法化）', () => {
  it('低于下限的尺寸被夹到 300x400', () => {
    expect(clampCaptureSize(200, 100)).toEqual({ width: 300, height: 400 });
  });

  it('小数尺寸取整', () => {
    expect(clampCaptureSize(550.6, 699.4)).toEqual({ width: 551, height: 699 });
  });

  it('非有限输入回落默认档', () => {
    expect(clampCaptureSize(NaN, Infinity)).toEqual(DEFAULT_CAPTURE_SIZE);
  });
});

describe('computeAvatarScaleFactor（头像缩放因子）', () => {
  it('默认尺寸因子为 1', () => {
    expect(computeAvatarScaleFactor(400, 500)).toBe(1);
  });

  it('小档按短边比例缩小（300x400 → 0.75）', () => {
    expect(computeAvatarScaleFactor(300, 400)).toBe(0.75);
  });

  it('大档按短边比例放大（550x700 → 1.375）', () => {
    expect(computeAvatarScaleFactor(550, 700)).toBeCloseTo(1.375);
  });

  it('极端尺寸被 clamp 到上下限', () => {
    expect(computeAvatarScaleFactor(100, 100)).toBe(AVATAR_SCALE_FACTOR_MIN);
    expect(computeAvatarScaleFactor(5000, 5000)).toBe(AVATAR_SCALE_FACTOR_MAX);
  });

  it('非法输入不缩放', () => {
    expect(computeAvatarScaleFactor(NaN, 500)).toBe(1);
    expect(computeAvatarScaleFactor(0, -10)).toBe(1);
  });
});

describe('resolveAvatarScale（头像自适应决策）', () => {
  it('窗口已缩放时（Electron）恒为 1，交由引擎随容器自适应', () => {
    expect(resolveAvatarScale(300, 400, true)).toBe(1);
    expect(resolveAvatarScale(400, 500, true)).toBe(1);
    expect(resolveAvatarScale(640, 800, true)).toBe(1);
  });

  it('浏览器降级路径按预设比例缩放头像', () => {
    expect(resolveAvatarScale(400, 500, false)).toBe(1);
    expect(resolveAvatarScale(300, 400, false)).toBe(0.75);
    expect(resolveAvatarScale(550, 700, false)).toBeCloseTo(1.375);
  });
});

describe('getNextCaptureSize（循环切换）', () => {
  it('按预设顺序逐档推进', () => {
    expect(getNextCaptureSize(300, 400)).toEqual({ width: 400, height: 500 });
    expect(getNextCaptureSize(400, 500)).toEqual({ width: 550, height: 700 });
    expect(getNextCaptureSize(550, 700)).toEqual({ width: 640, height: 800 });
  });

  it('末尾回卷到首档', () => {
    expect(getNextCaptureSize(640, 800)).toEqual({ width: 300, height: 400 });
  });

  it('未命中预设（自定义尺寸）回落默认档', () => {
    expect(getNextCaptureSize(512, 512)).toEqual(DEFAULT_CAPTURE_SIZE);
  });
});

describe('useObsStore', () => {
  it('默认状态：绿幕关闭、默认采集尺寸', () => {
    const s = useObsStore.getState();
    expect(s.greenScreen).toBe(false);
    expect(s.captureWidth).toBe(400);
    expect(s.captureHeight).toBe(500);
  });

  it('toggleGreenScreen / setGreenScreen 切换抠像背景模式', () => {
    useObsStore.getState().toggleGreenScreen();
    expect(useObsStore.getState().greenScreen).toBe(true);
    useObsStore.getState().toggleGreenScreen();
    expect(useObsStore.getState().greenScreen).toBe(false);
    useObsStore.getState().setGreenScreen(true);
    expect(useObsStore.getState().greenScreen).toBe(true);
  });

  it('setCaptureSize 经 clamp 后落库', () => {
    useObsStore.getState().setCaptureSize(200, 900.6);
    const s = useObsStore.getState();
    expect(s.captureWidth).toBe(300);
    expect(s.captureHeight).toBe(901);
  });

  it('cycleCaptureSize 逐档推进并在末尾回卷', () => {
    useObsStore.getState().cycleCaptureSize();
    expect(useObsStore.getState().captureWidth).toBe(550);
    useObsStore.getState().cycleCaptureSize();
    expect(useObsStore.getState().captureWidth).toBe(640);
    useObsStore.getState().cycleCaptureSize();
    expect(useObsStore.getState().captureWidth).toBe(300);
  });
});
