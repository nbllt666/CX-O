/**
 * VRMWindField 单测：交互风（triggerInteractionWind）作用于弹簧骨 gravityDir。
 *
 * 用假 VRM（springBoneManager.joints 单关节 hair_front）观察 gravityDir：
 * 交互风注入风力 → 逐帧衰减 → reset 后恢复原始重力方向。
 */
import { describe, it, expect } from 'vitest';
import type { VRM } from '@pixiv/three-vrm';

import { VRMWindField } from './vrmWindField';

type Vec3Like = { x: number; y: number; z: number };

/** 迷你 Vector3：模拟 copy/clone/addScaledVector 的运算语义，便于断言 */
function createFakeVector3(x = 0, y = 0, z = 0) {
  return {
    x,
    y,
    z,
    copy(v: Vec3Like) {
      this.x = v.x;
      this.y = v.y;
      this.z = v.z;
      return this;
    },
    clone() {
      return createFakeVector3(this.x, this.y, this.z);
    },
    addScaledVector(v: Vec3Like, s: number) {
      this.x += v.x * s;
      this.y += v.y * s;
      this.z += v.z * s;
      return this;
    },
  };
}

function createFakeVRM() {
  const originalGravity = createFakeVector3(0, -1, 0);
  const gravityDir = createFakeVector3(0, -1, 0);
  const joint = {
    bone: { name: 'hair_front' }, // 命中 WIND_AFFECTED_KEYWORDS 的 'hair'
    settings: { gravityDir },
  };
  const vrm = {
    springBoneManager: { joints: [joint] },
  } as unknown as VRM;
  return { vrm, gravityDir, originalGravity };
}

describe('VRMWindField 交互风', () => {
  it('triggerInteractionWind(0.8) 后 update 一帧，gravityDir 含交互分量', () => {
    const { vrm, gravityDir } = createFakeVRM();
    const wind = new VRMWindField();
    wind.bindVRM(vrm);
    wind.triggerInteractionWind(0.8);
    wind.update(1 / 60);

    // 方向 0° 时风力沿 -Z：z 从 0 变为负值，x/y 保持原始重力方向
    expect(gravityDir.x).toBe(0);
    expect(gravityDir.y).toBe(-1);
    expect(gravityDir.z).toBeLessThan(0);
  });

  it('交互风力逐帧衰减：长时间 update 后每帧增量趋近 0', () => {
    const { vrm, gravityDir } = createFakeVRM();
    const wind = new VRMWindField();
    wind.bindVRM(vrm);
    wind.triggerInteractionWind(0.8);

    wind.update(1 / 60);
    const z1 = gravityDir.z;
    wind.update(1 / 60);
    const z2 = gravityDir.z;
    // 初期风力明显：单帧增量显著
    expect(Math.abs(z2 - z1)).toBeGreaterThan(0.01);

    // 大量帧后交互强度衰减殆尽，每帧增量趋近 0
    for (let i = 0; i < 200; i += 1) wind.update(1 / 60);
    const zA = gravityDir.z;
    wind.update(1 / 60);
    const zB = gravityDir.z;
    expect(Math.abs(zB - zA)).toBeLessThan(0.0001);
  });

  it('reset 清空后 update 恢复原始 gravityDir', () => {
    const { vrm, gravityDir, originalGravity } = createFakeVRM();
    const wind = new VRMWindField();
    wind.bindVRM(vrm);
    wind.triggerInteractionWind(0.8);
    wind.update(1 / 60);
    expect(gravityDir.z).not.toBe(originalGravity.z);

    wind.reset();
    // reset 已恢复原始重力方向；随后 update 因无绑定 VRM 不再改写
    wind.update(1 / 60);
    expect(gravityDir.x).toBe(originalGravity.x);
    expect(gravityDir.y).toBe(originalGravity.y);
    expect(gravityDir.z).toBe(originalGravity.z);
  });
});
