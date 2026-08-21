/**
 * VRM 视线策略层（VRM 驱动分层升级 Spec Task 4）。
 *
 * 按场景模式选择视线目标计算策略，供 VRMViewer 渲染循环直读：
 * - MouseFollowStrategy（pet）：鼠标归一化坐标 → 世界坐标目标点（对齐原 VRMViewer 口径）
 * - LiveCameraStrategy（live）：直播常态直视镜头方向 + 读弹幕态转向弹幕区锚点
 *
 * 坐标约定：mousePos / danmakuArea 均为归一化屏幕坐标（-1..1，y 向上）。
 */
import * as THREE from 'three';
import type { SceneMode } from '../types';

export interface LookAtStrategy {
  getTargetPosition(
    camera: THREE.PerspectiveCamera,
    mousePos?: { x: number; y: number },
    danmakuArea?: { x: number; y: number },
  ): THREE.Vector3;
}

/** 鼠标跟随策略：鼠标归一化坐标 → 世界坐标目标点（x∈[-1,1]→x*2；y∈[-1,1]→1.5+y*1.0；z 固定 1.5） */
export class MouseFollowStrategy implements LookAtStrategy {
  getTargetPosition(
    _camera: THREE.PerspectiveCamera,
    mousePos?: { x: number; y: number },
  ): THREE.Vector3 {
    const x = mousePos?.x ?? 0;
    const y = mousePos?.y ?? 0;
    // 以头部位置 (0, 1.5, 0) 为基准：水平角钳制 ±15°、垂直角钳制 ±10°
    const dz = 1.5;
    const maxX = Math.tan(THREE.MathUtils.degToRad(15)) * dz;
    const maxY = Math.tan(THREE.MathUtils.degToRad(10)) * Math.hypot(dz, maxX);
    const cx = THREE.MathUtils.clamp(x * 2, -maxX, maxX);
    const cy = THREE.MathUtils.clamp(y * 1.0, -maxY, maxY);
    return new THREE.Vector3(cx, 1.5 + cy, dz);
  }
}

/** 直播相机策略：常态直视镜头方向（带极小噪声游离），读弹幕态转向弹幕区锚点 */
export class LiveCameraStrategy implements LookAtStrategy {
  private readingDanmaku = false;

  /** 设置读弹幕状态（读弹幕 2s 后由调用方复位） */
  setReadingDanmaku(state: boolean): void {
    this.readingDanmaku = state;
  }

  getTargetPosition(
    camera: THREE.PerspectiveCamera,
    _mousePos?: { x: number; y: number },
    danmakuArea?: { x: number; y: number },
  ): THREE.Vector3 {
    // 读弹幕态：弹幕区锚点归一化坐标 → 世界坐标（缺省取右侧偏上锚点）
    if (this.readingDanmaku) {
      const area = danmakuArea ?? { x: 0.5, y: 0.2 };
      return new THREE.Vector3(area.x * 2, 1.5 + area.y * 1.0, 1.5);
    }
    // 常态：直视镜头方向 + 极小噪声游离（幅度 ≤0.05），时间基保证跨帧连续
    const now = performance.now() * 0.001;
    const target = camera.position.clone();
    target.x += (Math.sin(now * 0.7) + Math.sin(now * 1.3 + 1.7) * 0.5) * 0.04;
    target.y += (Math.cos(now * 0.5 + 0.4) + Math.sin(now * 1.1 + 2.3) * 0.5) * 0.03;
    return target;
  }
}

/** 工厂：按场景模式创建视线策略（'pet'→鼠标跟随，'live'→直播相机） */
export function createLookAtStrategy(mode: SceneMode): LookAtStrategy {
  return mode === 'live' ? new LiveCameraStrategy() : new MouseFollowStrategy();
}
