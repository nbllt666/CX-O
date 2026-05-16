import { VRM } from '@pixiv/three-vrm';
import * as THREE from 'three';

export interface IdleConfig {
  breathFrequency: number;
  breathAmplitude: number;
  blinkInterval: number;
  blinkDuration: number;
  swayAmplitude: number;
  swayFrequency: number;
  headFollowSpeed: number;
  bodyFollowDelay: number;
}

export class VRMAnimation {
  private vrm: VRM | null = null;
  private time = 0;
  private blinkTimer = 0;
  private isBlinking = false;
  private blinkPhase = 0;
  private headTarget = new THREE.Vector3(0, 0, 10);
  private currentHeadRot = new THREE.Euler(0, 0, 0);
  private targetHeadRot = new THREE.Euler(0, 0, 0);
  private bodyRot = new THREE.Euler(0, 0, 0);

  private config: IdleConfig = {
    breathFrequency: 0.3,
    breathAmplitude: 0.02,
    blinkInterval: 3.0,
    blinkDuration: 0.15,
    swayAmplitude: 0.01,
    swayFrequency: 0.5,
    headFollowSpeed: 2.0,
    bodyFollowDelay: 0.3,
  };

  bindVRM(vrm: VRM): void {
    this.vrm = vrm;
  }

  setConfig(config: Partial<IdleConfig>): void {
    this.config = { ...this.config, ...config };
  }

  setHeadTarget(x: number, y: number, z: number): void {
    this.headTarget.set(x, y, z);
  }

  update(deltaTime: number): void {
    if (!this.vrm) return;
    this.time += deltaTime;

    this.updateBreathing(deltaTime);
    this.updateBlinking(deltaTime);
    this.updateSway(deltaTime);
    this.updateHeadFollow(deltaTime);
  }

  private updateBreathing(_deltaTime: number): void {
    if (!this.vrm) return;
    const humanoid = this.vrm.humanoid;
    if (!humanoid) return;

    const breath = Math.sin(this.time * this.config.breathFrequency * Math.PI * 2);
    const scale = 1 + breath * this.config.breathAmplitude;

    // Chest breathing
    const chest = humanoid.getNormalizedBoneNode('chest');
    if (chest) {
      chest.scale.setScalar(scale);
    }

    // Shoulder micro movement
    const leftShoulder = humanoid.getNormalizedBoneNode('leftShoulder');
    const rightShoulder = humanoid.getNormalizedBoneNode('rightShoulder');
    if (leftShoulder) {
      leftShoulder.rotation.z = Math.sin(this.time * this.config.breathFrequency * Math.PI * 2) * 0.02;
    }
    if (rightShoulder) {
      rightShoulder.rotation.z = -Math.sin(this.time * this.config.breathFrequency * Math.PI * 2) * 0.02;
    }
  }

  private updateBlinking(deltaTime: number): void {
    if (!this.vrm) return;

    if (this.isBlinking) {
      this.blinkPhase += deltaTime / this.config.blinkDuration;
      if (this.blinkPhase >= 1) {
        this.isBlinking = false;
        this.blinkPhase = 0;
        this.blinkTimer = Math.random() * this.config.blinkInterval + this.config.blinkInterval * 0.5;
      }
    } else {
      this.blinkTimer -= deltaTime;
      if (this.blinkTimer <= 0) {
        this.isBlinking = true;
        this.blinkPhase = 0;
      }
    }

    // Apply blink to blend shapes
    const em = this.vrm.expressionManager;
    if (em) {
      let blinkWeight = 0;
      if (this.isBlinking) {
        // Parabolic blink curve
        blinkWeight = Math.sin(this.blinkPhase * Math.PI);
      }
      em.setValue('blink' as any, blinkWeight);
    }
  }

  private updateSway(_deltaTime: number): void {
    if (!this.vrm) return;
    const humanoid = this.vrm.humanoid;
    if (!humanoid) return;

    const sway = Math.sin(this.time * this.config.swayFrequency * Math.PI * 2) * this.config.swayAmplitude;

    // Subtle hip sway
    const hips = humanoid.getNormalizedBoneNode('hips');
    if (hips) {
      hips.rotation.z = sway;
    }
  }

  private updateHeadFollow(deltaTime: number): void {
    if (!this.vrm) return;
    const humanoid = this.vrm.humanoid;
    if (!humanoid) return;

    const head = humanoid.getNormalizedBoneNode('head');
    const neck = humanoid.getNormalizedBoneNode('neck');
    const spine = humanoid.getNormalizedBoneNode('spine');

    if (!head) return;

    // Calculate target rotation from lookAt target
    const headPos = new THREE.Vector3();
    head.getWorldPosition(headPos);
    const direction = new THREE.Vector3().subVectors(this.headTarget, headPos).normalize();
    const targetYaw = Math.atan2(direction.x, direction.z);
    const targetPitch = -Math.asin(direction.y);

    // Clamp angles
    const clampedYaw = Math.max(-0.8, Math.min(0.8, targetYaw));
    const clampedPitch = Math.max(-0.5, Math.min(0.5, targetPitch));

    this.targetHeadRot.y = clampedYaw;
    this.targetHeadRot.x = clampedPitch;

    // Smooth head rotation
    const speed = this.config.headFollowSpeed * deltaTime;
    this.currentHeadRot.y += (this.targetHeadRot.y - this.currentHeadRot.y) * speed;
    this.currentHeadRot.x += (this.targetHeadRot.x - this.currentHeadRot.x) * speed;

    head.rotation.y = this.currentHeadRot.y;
    head.rotation.x = this.currentHeadRot.x;

    // Neck follows head with slight delay
    if (neck) {
      neck.rotation.y = this.currentHeadRot.y * 0.3;
      neck.rotation.x = this.currentHeadRot.x * 0.3;
    }

    // Body follows with more delay
    if (spine) {
      const bodyYaw = this.currentHeadRot.y * this.config.bodyFollowDelay;
      this.bodyRot.y += (bodyYaw - this.bodyRot.y) * deltaTime * 2;
      spine.rotation.y = this.bodyRot.y;
    }
  }

  reset(): void {
    this.time = 0;
    this.blinkTimer = 0;
    this.isBlinking = false;
    this.blinkPhase = 0;
    this.currentHeadRot.set(0, 0, 0);
    this.targetHeadRot.set(0, 0, 0);
    this.bodyRot.set(0, 0, 0);
  }
}
