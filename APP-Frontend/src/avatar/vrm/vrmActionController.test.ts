/**
 * VRMActionController 单测。
 *
 * 覆盖：
 * - hasAction 命中与大小写不敏感匹配
 * - playAction 首次播放与 crossFadeTo 交叉淡入
 * - update 与 reset 状态清理
 */
import { describe, expect, it } from 'vitest';
import * as THREE from 'three';
import { VRMActionController } from './vrmActionController';

describe('VRMActionController', () => {
  it('未 bind 时 hasAction 返回 false，playAction 返回 false', () => {
    const controller = new VRMActionController();
    expect(controller.hasAction('wave')).toBe(false);
    expect(controller.playAction('wave')).toBe(false);
  });

  it('bind 后可大小写不敏感匹配动作片段并触发播放', () => {
    const controller = new VRMActionController();
    const root = new THREE.Object3D();
    const clip1 = new THREE.AnimationClip('Action_Wave', 1.0, []);
    const clip2 = new THREE.AnimationClip('greet_nod', 0.8, []);
    controller.bind(root, [clip1, clip2]);

    expect(controller.hasAction('wave')).toBe(true);
    expect(controller.hasAction('GREET_NOD')).toBe(true);
    expect(controller.hasAction('jump')).toBe(false);

    expect(controller.playAction('wave')).toBe(true);
    // 再次触发另一个动作走 crossFadeTo
    expect(controller.playAction('greet_nod', 0.2)).toBe(true);
  });

  it('update 与 reset 正常执行不抛错', () => {
    const controller = new VRMActionController();
    const root = new THREE.Object3D();
    const clip = new THREE.AnimationClip('wave', 1.0, []);
    controller.bind(root, [clip]);

    controller.playAction('wave');
    expect(() => controller.update(0.016)).not.toThrow();
    expect(() => controller.reset()).not.toThrow();
  });
});
