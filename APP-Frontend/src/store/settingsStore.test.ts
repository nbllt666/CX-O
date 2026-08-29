/**
 * settingsStore 单测（第九轮 G5）。
 * 覆盖：persist merge 对持久化还原的 vrm.modelPath 以 `blob:` 开头时的消毒回退——
 * 浏览器模式上传的 VRM 模型为临时 blob URL，仅当次会话有效，还原出死链时必须
 * 回退 store 内 vrm 初始 state 的默认模型路径，避免桌宠窗加载失效 URL。
 * 测试风格对齐 src/store/captureStore.test.ts。
 */
import { beforeEach, describe, expect, it } from 'vitest';

import { SETTINGS_STORE_NAME, useSettingsStore } from './settingsStore';

/** 初始 state 快照（字段值；setter 引用不在用例中变更，无需复位） */
const initialState = useSettingsStore.getState();

beforeEach(() => {
  useSettingsStore.setState({
    avatarType: initialState.avatarType,
    live2d: initialState.live2d,
    vrm: initialState.vrm,
    layout: initialState.layout,
    autoSave: initialState.autoSave,
    limits: initialState.limits,
  });
  localStorage.clear();
});

describe('persist merge（blob: modelPath 消毒）', () => {
  it('持久化还原 blob: 前缀 modelPath 时回退默认模型路径', async () => {
    localStorage.setItem(
      SETTINGS_STORE_NAME,
      JSON.stringify({
        state: { vrm: { modelPath: 'blob:https://cxo.local/dead-url' } },
        version: 0,
      }),
    );
    await useSettingsStore.persist.rehydrate();
    expect(useSettingsStore.getState().vrm.modelPath).toBe(initialState.vrm.modelPath);
  });

  it('持久化还原本地绝对路径 modelPath 时保持不变', async () => {
    localStorage.setItem(
      SETTINGS_STORE_NAME,
      JSON.stringify({
        state: { vrm: { modelPath: 'C:\\models\\custom.vrm' } },
        version: 0,
      }),
    );
    await useSettingsStore.persist.rehydrate();
    expect(useSettingsStore.getState().vrm.modelPath).toBe('C:\\models\\custom.vrm');
  });

  it('消毒只影响 modelPath，其余持久化字段（如 scale）正常合并', async () => {
    localStorage.setItem(
      SETTINGS_STORE_NAME,
      JSON.stringify({
        state: { vrm: { modelPath: 'blob:https://cxo.local/dead-url', scale: 1.5 } },
        version: 0,
      }),
    );
    await useSettingsStore.persist.rehydrate();
    const vrm = useSettingsStore.getState().vrm;
    expect(vrm.modelPath).toBe(initialState.vrm.modelPath);
    expect(vrm.scale).toBe(1.5);
  });
});
