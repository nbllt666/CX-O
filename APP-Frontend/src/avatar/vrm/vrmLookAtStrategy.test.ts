/**
 * VRM 视线策略单测。
 *
 * 覆盖：
 * - MouseFollowStrategy: 坐标钳制在 ±15° / ±10° 锥角内
 * - LiveCameraStrategy: 常态直视镜头+游离、读弹幕转向锚点
 * - createLookAtStrategy 工厂分发
 */
import { describe, expect, it } from 'vitest';
import * as THREE from 'three';
import {
  createLookAtStrategy,
  LiveCameraStrategy,
  MouseFollowStrategy,
} from './vrmLookAtStrategy';

describe('MouseFollowStrategy', () => {
  it('中立鼠标坐标 (0, 0) 返回正前方基准位置', () => {
    const strategy = new MouseFollowStrategy();
    const camera = new THREE.PerspectiveCamera(28, 1, 0.1, 20);
    const pos = strategy.getTargetPosition(camera, { x: 0, y: 0 });
    expect(pos.x).toBeCloseTo(0, 4);
    expect(pos.y).toBeCloseTo(1.5, 4);
    expect(pos.z).toBeCloseTo(1.5, 4);
  });

  it('极端鼠标输入应被水平 ±15° 与垂直 ±10° 锥角严格钳制', () => {
    const strategy = new MouseFollowStrategy();
    const camera = new THREE.PerspectiveCamera(28, 1, 0.1, 20);
    const dz = 1.5;
    const maxX = Math.tan(THREE.MathUtils.degToRad(15)) * dz;
    const maxY = Math.tan(THREE.MathUtils.degToRad(10)) * Math.hypot(dz, maxX);

    const posRight = strategy.getTargetPosition(camera, { x: 10, y: 10 });
    expect(posRight.x).toBeCloseTo(maxX, 4);
    expect(posRight.y - 1.5).toBeCloseTo(maxY, 4);

    const posLeft = strategy.getTargetPosition(camera, { x: -10, y: -10 });
    expect(posLeft.x).toBeCloseTo(-maxX, 4);
    expect(posLeft.y - 1.5).toBeCloseTo(-maxY, 4);
  });
});

describe('LiveCameraStrategy', () => {
  it('常态视线指向相机位置附近并带微游离', () => {
    const strategy = new LiveCameraStrategy();
    const camera = new THREE.PerspectiveCamera(28, 1, 0.1, 20);
    camera.position.set(0, 1.2, 3);
    const pos = strategy.getTargetPosition(camera);
    expect(Math.abs(pos.x - camera.position.x)).toBeLessThanOrEqual(0.08);
    expect(Math.abs(pos.y - camera.position.y)).toBeLessThanOrEqual(0.08);
    expect(pos.z).toBeCloseTo(3, 4);
  });

  it('读弹幕状态下视线转向指定弹幕区锚点', () => {
    const strategy = new LiveCameraStrategy();
    const camera = new THREE.PerspectiveCamera(28, 1, 0.1, 20);
    strategy.setReadingDanmaku(true);
    const pos = strategy.getTargetPosition(camera, undefined, { x: 0.6, y: -0.2 });
    expect(pos.x).toBeCloseTo(0.6 * 2, 4);
    expect(pos.y).toBeCloseTo(1.5 - 0.2 * 1.0, 4);
    expect(pos.z).toBeCloseTo(1.5, 4);
  });
});

describe('createLookAtStrategy', () => {
  it('按 sceneMode 正确分发对应策略实例', () => {
    expect(createLookAtStrategy('pet')).toBeInstanceOf(MouseFollowStrategy);
    expect(createLookAtStrategy('live')).toBeInstanceOf(LiveCameraStrategy);
  });
});
