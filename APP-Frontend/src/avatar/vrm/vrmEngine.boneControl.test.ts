/**
 * setBoneRotations 的过滤与限幅单测。
 *
 * 用假 runtime 隔离真实 VRM/WebGL 依赖，仅验证白名单过滤与 rotationRange 限幅逻辑。
 * boneTargetRotations.get(key) 以 entry.boneName 原样为 key（见实现），
 * 故大小写用例断言需对应用例传入的原始 boneName。
 */
import { describe, expect, it } from 'vitest';
import { DEFAULT_BONE_CONTROLS } from './boneControlCatalog';
import { setBoneRotations } from './vrmEngine';

function makeRuntime() {
  return {
    avatar: { boneControls: DEFAULT_BONE_CONTROLS },
    boneTargetRotations: new Map(),
    boneTransitionSpeeds: new Map(),
    boneCurrentRotations: new Map(),
    boneHoldTimers: new Map(),
    vrm: { humanoid: null },
  } as any;
}

describe('setBoneRotations', () => {
  it('A. 白名单外骨骼被跳过，boneTargetRotations 为空', () => {
    const runtime = makeRuntime();
    setBoneRotations(runtime, [{ boneName: 'leftPinky', rotation: { x: 0, y: 0, z: 0 } }]);
    expect(runtime.boneTargetRotations.size).toBe(0);
  });

  it('B. 白名单内骨骼超限被限幅：head 的 x 钳制到范围上限 0.6', () => {
    const runtime = makeRuntime();
    setBoneRotations(runtime, [
      { boneName: 'head', rotation: { x: 3.0, y: 0, z: 0 }, speed: 1.0 },
    ]);
    expect(runtime.boneTargetRotations.get('head').x).toBe(0.6);
  });

  it('C. 白名单内正常骨骼按原值直通', () => {
    const runtime = makeRuntime();
    setBoneRotations(runtime, [
      { boneName: 'neck', rotation: { x: 0.1, y: 0.2, z: 0.3 } },
    ]);
    const target = runtime.boneTargetRotations.get('neck');
    expect(target).toBeDefined();
    expect(target.x).toBe(0.1);
    expect(target.y).toBe(0.2);
    expect(target.z).toBe(0.3);
  });

  it('D. 大小写不敏感入白名单：HEAD 被接受并限幅', () => {
    const runtime = makeRuntime();
    setBoneRotations(runtime, [
      { boneName: 'HEAD', rotation: { x: 3.0, y: 0, z: 0 }, speed: 1.0 },
    ]);
    // head 范围 x 上限 0.6，key 为传入的原始 boneName 'HEAD'
    expect(runtime.boneTargetRotations.get('HEAD').x).toBe(0.6);
  });

  it('E. 省略 holdMs 时设置默认 3s 自动归中计时器', () => {
    const runtime = makeRuntime();
    setBoneRotations(runtime, [{ boneName: 'head', rotation: { x: 0.3, y: 0, z: 0 } }]);
    expect(runtime.boneHoldTimers.get('head')).toBeCloseTo(3.0, 5);
  });

  it('F. 显式 holdMs 转换秒数入计时器', () => {
    const runtime = makeRuntime();
    setBoneRotations(runtime, [
      { boneName: 'neck', rotation: { x: 0.1, y: 0, z: 0 }, holdMs: 1500 },
    ]);
    expect(runtime.boneHoldTimers.get('neck')).toBeCloseTo(1.5, 5);
  });

  it('G. holdMs=0 表示不自动归中（清除计时器）', () => {
    const runtime = makeRuntime();
    setBoneRotations(runtime, [
      { boneName: 'head', rotation: { x: 0.3, y: 0, z: 0 }, holdMs: 0 },
    ]);
    expect(runtime.boneHoldTimers.has('head')).toBe(false);
  });
});