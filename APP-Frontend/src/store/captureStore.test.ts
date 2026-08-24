/**
 * captureStore 单测（Task 4 / Task 6 共享契约）。
 * 覆盖：默认态、视频叙事开关 videoModeEnabled 的 setter 与持久化、
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
    frameMode: 'interval',
    frameIntervalSec: 5,
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

  it('合法 adaptive 档经 merge 保留', async () => {
    localStorage.setItem(
      CAPTURE_STORE_NAME,
      JSON.stringify({ state: { frameMode: 'adaptive', frameIntervalSec: 12 }, version: 0 }),
    );
    await useCaptureStore.persist.rehydrate();
    expect(useCaptureStore.getState().frameMode).toBe('adaptive');
  });
});