/**
 * VRM 动作控制器：基于 THREE.AnimationMixer 播放动作片段，支持动作间交叉淡入。
 * 行为口径对齐 CX-O-Frontend components/business/vrm/vrm-action-controller.ts。
 *
 * - bind：绑定模型根节点与动画片段（gltf.animations）
 * - playAction：匹配片段 → 新动作与当前动作 crossFadeTo 交叉淡入
 * - update：由驱动每帧驱动 mixer 推进
 */
import * as THREE from 'three';
import type { AnimationClip, AnimationAction, AnimationMixer } from 'three';

export class VRMActionController {
  private mixer: AnimationMixer | null = null;
  private clips: AnimationClip[] = [];
  private currentAction: AnimationAction | null = null;

  bind(root: THREE.Object3D, clips: AnimationClip[]): void {
    this.clips = clips;
    this.mixer = new THREE.AnimationMixer(root);
  }

  hasAction(name: string): boolean {
    return this.findClip(name) !== null;
  }

  playAction(name: string, fadeIn = 0.3): boolean {
    const clip = this.findClip(name);
    if (!clip || !this.mixer) return false;

    const newAction = this.mixer.clipAction(clip);
    if (this.currentAction) {
      newAction.reset().play();
      this.currentAction.crossFadeTo(newAction, fadeIn, true);
    } else {
      newAction.fadeIn(fadeIn).play();
    }
    this.currentAction = newAction;
    return true;
  }

  update(dt: number): void {
    this.mixer?.update(dt);
  }

  reset(): void {
    this.currentAction?.fadeOut(0.3);
    this.currentAction = null;
    this.mixer?.stopAllAction();
  }

  /** 在片段列表中匹配名称（等于 name 或包含 name，大小写不敏感） */
  private findClip(name: string): AnimationClip | null {
    const lower = name.toLowerCase();
    return (
      this.clips.find(
        (clip) =>
          clip.name.toLowerCase() === lower || clip.name.toLowerCase().includes(lower),
      ) ?? null
    );
  }
}
