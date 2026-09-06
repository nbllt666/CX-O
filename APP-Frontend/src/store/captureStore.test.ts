/**
 * captureStore 单测（Task 4 / Task 6 共享契约）。
 * 覆盖：默认态、视频叙事开关 videoModeEnabled 的 setter 与持久化、
 * 帧筛选开关 frameFilterEnabled 的 setter 与持久化（spec add-vlm-frame-filter-face-match Task 5）、
 * 自适应占空比 frameDutyCycle 的默认值 / setter 钳制 / 持久化 / merge 回填（spec enhance-frame-adaptive-duty-cycle Task 1）、
 * 旧持久化未知 frameMode 的安全回退，以及既有字段默认值回归。
 */
import { beforeEach, describe, expect, it } from 'vitest';

import { CAPTURE_STORE_NAME, useCaptureStore } from './captureStore';

function resetStore() {
  useCaptureStore.setState({
    screenActive: false,
    cameraActive: false,
    visionEnabled: false,
    videoModeEnabled: false,
    frameFilterEnabled: false,
    frameMode: 'interval',
    frameIntervalSec: 5,
    frameDutyCycle: 50,
  });
}

/** 读取底层持久化内容（zustand persist 打包为 { state, version }） */
function readPersistedState(): Record<string, unknown> {
  const raw = localStorage.getItem(CAPTURE_STORE_NAME);
  expect(raw).not.toBeNull();
  const parsed = JSON.parse(raw!) as { state: Record<string, unknown> };
  return parsed.state;
}

beforeEach(() => {
  resetStore();
  localStorage.clear();
});

describe('useCaptureStore 默认态', () => {
  it('默认 videoModeEnabled === false', () => {
    expect(useCaptureStore.getState().videoModeEnabled).toBe(false);
  });

  it('既有默认值保持不变（回归）', () => {
    const s = useCaptureStore.getState();
    expect(s.screenActive).toBe(false);
    expect(s.cameraActive).toBe(false);
    expect(s.visionEnabled).toBe(false);
    expect(s.frameMode).toBe('interval');
    expect(s.frameIntervalSec).toBe(5);
  });
});

describe('videoModeEnabled（视频叙事开关）', () => {
  it('setVideoModeEnabled(true) 后值变更', () => {
    useCaptureStore.getState().setVideoModeEnabled(true);
    expect(useCaptureStore.getState().videoModeEnabled).toBe(true);
    useCaptureStore.getState().setVideoModeEnabled(false);
    expect(useCaptureStore.getState().videoModeEnabled).toBe(false);
  });

  it('持久化 partialize 纳入 videoModeEnabled', () => {
    useCaptureStore.getState().setVideoModeEnabled(true);
    expect(readPersistedState().videoModeEnabled).toBe(true);
  });
});

describe('frameFilterEnabled（帧筛选开关，Task 5）', () => {
  it('默认 frameFilterEnabled === false（关闭=现状直通）', () => {
    expect(useCaptureStore.getState().frameFilterEnabled).toBe(false);
  });

  it('setFrameFilterEnabled(true) 后值变更', () => {
    useCaptureStore.getState().setFrameFilterEnabled(true);
    expect(useCaptureStore.getState().frameFilterEnabled).toBe(true);
    useCaptureStore.getState().setFrameFilterEnabled(false);
    expect(useCaptureStore.getState().frameFilterEnabled).toBe(false);
  });

  it('持久化 partialize 纳入 frameFilterEnabled', () => {
    useCaptureStore.getState().setFrameFilterEnabled(true);
    expect(readPersistedState().frameFilterEnabled).toBe(true);
  });
});

describe('persist merge（旧持久化兼容）', () => {
  it('未知 frameMode 安全回退 interval', async () => {
    localStorage.setItem(
      CAPTURE_STORE_NAME,
      JSON.stringify({ state: { frameMode: 'bogus-mode', frameIntervalSec: 9 }, version: 0 }),
    );
    await useCaptureStore.persist.rehydrate();
    expect(useCaptureStore.getState().frameMode).toBe('interval');
  });

  it('merge 纳入 videoModeEnabled（持久化 true 覆盖默认 false）', async () => {
    const s = useCaptureStore.getState();
    s.setVideoModeEnabled(false);
    localStorage.setItem(
      CAPTURE_STORE_NAME,
      JSON.stringify({ state: { videoModeEnabled: true }, version: 0 }),
    );
    await useCaptureStore.persist.rehydrate();
    expect(useCaptureStore.getState().videoModeEnabled).toBe(true);
  });

  it('merge 纳入 frameFilterEnabled（持久化 true 覆盖默认 false，Task 5）', async () => {
    useCaptureStore.getState().setFrameFilterEnabled(false);
    localStorage.setItem(
      CAPTURE_STORE_NAME,
      JSON.stringify({ state: { frameFilterEnabled: true }, version: 0 }),
    );
    await useCaptureStore.persist.rehydrate();
    expect(useCaptureStore.getState().frameFilterEnabled).toBe(true);
  });

  it('merge 对缺失 frameFilterEnabled 的旧持久化回退默认 false', async () => {
    localStorage.setItem(
      CAPTURE_STORE_NAME,
      JSON.stringify({ state: { visionEnabled: true }, version: 0 }),
    );
    await useCaptureStore.persist.rehydrate();
    expect(useCaptureStore.getState().frameFilterEnabled).toBe(false);
  });

  it('合法 adaptive 档经 merge 保留', async () => {
    localStorage.setItem(
      CAPTURE_STORE_NAME,
      JSON.stringify({ state: { frameMode: 'adaptive', frameIntervalSec: 12 }, version: 0 }),
    );
    await useCaptureStore.persist.rehydrate();
    expect(useCaptureStore.getState().frameMode).toBe('adaptive');
  });
});

describe('frameDutyCycle（自适应占空比，spec enhance-frame-adaptive-duty-cycle Task 1）', () => {
  it('默认 frameDutyCycle === 50（与历史行为一致）', () => {
    expect(useCaptureStore.getState().frameDutyCycle).toBe(50);
  });

  it('setFrameDutyCycle 钳制取整：5→10、95→90、50.7→51', () => {
    useCaptureStore.getState().setFrameDutyCycle(5);
    expect(useCaptureStore.getState().frameDutyCycle).toBe(10);
    useCaptureStore.getState().setFrameDutyCycle(95);
    expect(useCaptureStore.getState().frameDutyCycle).toBe(90);
    useCaptureStore.getState().setFrameDutyCycle(50.7);
    expect(useCaptureStore.getState().frameDutyCycle).toBe(51);
  });

  it('持久化 partialize 纳入 frameDutyCycle', () => {
    useCaptureStore.getState().setFrameDutyCycle(80);
    expect(readPersistedState().frameDutyCycle).toBe(80);
  });
});

describe('persist merge（frameDutyCycle 旧档兼容）', () => {
  it('merge 纳入 frameDutyCycle（持久化 80 覆盖默认 50）', async () => {
    localStorage.setItem(
      CAPTURE_STORE_NAME,
      JSON.stringify({ state: { frameDutyCycle: 80 }, version: 0 }),
    );
    await useCaptureStore.persist.rehydrate();
    expect(useCaptureStore.getState().frameDutyCycle).toBe(80);
  });

  it('merge 对缺失 frameDutyCycle 的旧持久化回填默认 50', async () => {
    localStorage.setItem(
      CAPTURE_STORE_NAME,
      JSON.stringify({ state: { visionEnabled: true }, version: 0 }),
    );
    await useCaptureStore.persist.rehydrate();
    expect(useCaptureStore.getState().frameDutyCycle).toBe(50);
  });
});