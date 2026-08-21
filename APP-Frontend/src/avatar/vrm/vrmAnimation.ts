/**
 * VRM 空闲动画：呼吸 / 眨眼 / 摇摆 / 头部跟随（含空闲漂移）。
 * 行为口径对齐 CX-O-Frontend components/business/vrm/vrm-animation.ts。
 */
import { VRM } from '@pixiv/three-vrm';
import * as THREE from 'three';

export interface IdleConfig {
  breathFrequency: number;
  breathAmplitude: number;
  breathIrregularity: number;
  blinkInterval: number;
  blinkDuration: number;
  swayAmplitude: number;
  swayFrequency: number;
  swayIrregularity: number;
  headFollowSpeed: number;
  bodyFollowDelay: number;
  headIdleRange: number;
  headTrackingLimit: number;
}

class SimpleNoise {
  private perm: number[] = [];

  constructor(seed: number = 42) {
    for (let i = 0; i < 256; i++) this.perm[i] = i;
    let s = seed;
    for (let i = 255; i > 0; i--) {
      s = (s * 16807) % 2147483647;
      const j = s % (i + 1);
      [this.perm[i], this.perm[j]] = [this.perm[j], this.perm[i]];
    }
    for (let i = 0; i < 256; i++) this.perm[256 + i] = this.perm[i];
  }

  noise(x: number): number {
    const xi = Math.floor(x) & 255;
    const xf = x - Math.floor(x);
    const u = xf * xf * (3 - 2 * xf);
    const a = this.perm[xi] / 255;
    const b = this.perm[xi + 1] / 255;
    return a * (1 - u) + b * u;
  }
}

export class VRMAnimation {
  private vrm: VRM | null = null;
  private enabled = true;
  private time = 0;
  private blinkTimer = 0;
  private isBlinking = false;
  private blinkPhase = 0;
  private headTarget = new THREE.Vector3(0, 0, 10);
  private currentHeadRot = new THREE.Euler(0, 0, 0);
  private targetHeadRot = new THREE.Euler(0, 0, 0);
  private bodyRot = new THREE.Euler(0, 0, 0);
  private breathingAmplitude = 1.0;

  private swayNoise = new SimpleNoise(42);
  private breathNoise = new SimpleNoise(137);
  private headIdleNoiseX = new SimpleNoise(73);
  private headIdleNoiseY = new SimpleNoise(91);
  private swayRandomWalk = 0;
  private breathFreqJitter = 0;
  private breathFreqJitterTimer = 0;
  private headIdleTimer = 0;

  private config: IdleConfig = {
    breathFrequency: 0.3,
    breathAmplitude: 0.02,
    breathIrregularity: 0.2,
    blinkInterval: 3.0,
    blinkDuration: 0.15,
    swayAmplitude: 0.01,
    swayFrequency: 0.5,
    swayIrregularity: 0.3,
    headFollowSpeed: 2.0,
    bodyFollowDelay: 0.3,
    headIdleRange: 0.03,
    headTrackingLimit: 0.5,
  };

  bindVRM(vrm: VRM): void {
    this.vrm = vrm;
  }

  /**
   * 启停空闲动画。从 true 切到 false 时复位关键骨骼到中立姿态，
   * 避免角色冻结在禁用前最后一帧。
   */
  setEnabled(enabled: boolean): void {
    this.enabled = enabled;
    if (enabled) {
      return;
    }
    if (!this.vrm) return;
    const humanoid = this.vrm.humanoid;
    if (!humanoid) return;

    const chest = humanoid.getNormalizedBoneNode('chest');
    if (chest) {
      chest.scale.setScalar(1);
    }

    for (const name of ['spine', 'neck', 'head', 'hips'] as const) {
      const bone = humanoid.getNormalizedBoneNode(name);
      if (bone) {
        bone.rotation.set(0, 0, 0);
      }
    }
  }

  setConfig(config: Partial<IdleConfig>): void {
    this.config = { ...this.config, ...config };
  }

  setHeadTarget(x: number, y: number, z: number): void {
    this.headTarget.set(x, y, z);
  }

  getHeadRotation(): { x: number; y: number } {
    return { x: this.currentHeadRot.x, y: this.currentHeadRot.y };
  }

  setBreathingAmplitude(factor: number): void {
    this.breathingAmplitude = Math.min(Math.max(factor, 0), 1);
  }

  update(deltaTime: number): void {
    if (!this.vrm) return;
    if (!this.enabled) return;
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

    // 呼吸频率微随机变化（每 3-5 秒更新一次）
    this.breathFreqJitterTimer -= _deltaTime;
    if (this.breathFreqJitterTimer <= 0) {
      this.breathFreqJitterTimer = 3 + Math.random() * 2;
      this.breathFreqJitter = (Math.random() - 0.5) * this.config.breathIrregularity * 0.1;
    }

    const effectiveFreq = this.config.breathFrequency + this.breathFreqJitter;
    const breathPhase = this.time * effectiveFreq * Math.PI * 2;

    const breath = Math.sin(breathPhase);
    const amplitudeNoise =
      1 + (this.breathNoise.noise(this.time * 0.3) - 0.5) * this.config.breathIrregularity * 0.4;
    const effectiveAmplitude = this.config.breathAmplitude * this.breathingAmplitude * amplitudeNoise;
    const scale = 1 + breath * effectiveAmplitude;

    // 呼吸收敛为胸腔深度（Z）方向的轻微起伏：仅前后厚度变化，不在 XYZ 整体膨胀、
    // 不带动脊柱前倾、不带动肩膀，避免"整个模型晃动"的观感。
    const chest = humanoid.getNormalizedBoneNode('chest');
    if (chest) {
      chest.scale.set(1, 1, scale);
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

    const em = this.vrm.expressionManager;
    if (em) {
      let blinkWeight = 0;
      if (this.isBlinking) {
        blinkWeight = Math.sin(this.blinkPhase * Math.PI);
      }
      em.setValue('blink', blinkWeight);
    }
  }

  private updateSway(_deltaTime: number): void {
    if (!this.vrm) return;
    const humanoid = this.vrm.humanoid;
    if (!humanoid) return;

    const slowSway = Math.sin(this.time * this.config.swayFrequency * Math.PI * 2);
    const fastSway = Math.sin(this.time * this.config.swayFrequency * Math.PI * 2 * 2.3) * 0.2;

    const noiseVal = this.swayNoise.noise(this.time * 0.5) - 0.5;
    this.swayRandomWalk += noiseVal * _deltaTime * this.config.swayIrregularity * 0.5;
    this.swayRandomWalk *= 0.95;
    this.swayRandomWalk = Math.max(-1, Math.min(1, this.swayRandomWalk));

    const irregularityFactor = 1 + this.swayRandomWalk * this.config.swayIrregularity;
    const sway = (slowSway + fastSway) * this.config.swayAmplitude * irregularityFactor;

    const hips = humanoid.getNormalizedBoneNode('hips');
    if (hips) {
      hips.rotation.z = sway * 0.3;
      hips.rotation.x = slowSway * this.config.swayAmplitude * 0.15;
    }

    const spine = humanoid.getNormalizedBoneNode('spine');
    if (spine) {
      spine.rotation.z = sway * 0.5;
    }

    const chest = humanoid.getNormalizedBoneNode('chest');
    if (chest) {
      chest.rotation.z = sway * 0.2;
    }

    const head = humanoid.getNormalizedBoneNode('head');
    if (head) {
      head.rotation.z = sway * 0.1;
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

    const hasMouseInteraction = this.headTarget.lengthSq() > 0.01;

    if (hasMouseInteraction) {
      const headPos = new THREE.Vector3();
      head.getWorldPosition(headPos);
      const direction = new THREE.Vector3().subVectors(this.headTarget, headPos).normalize();
      const targetYaw = Math.atan2(direction.x, direction.z);
      const targetPitch = Math.asin(direction.y);

      const limit = this.config.headTrackingLimit;
      const yawLimit = limit * 1.6;
      const clampedYaw = Math.max(-yawLimit, Math.min(yawLimit, targetYaw));
      const clampedPitch = Math.max(-limit, Math.min(limit, targetPitch));

      this.targetHeadRot.y = clampedYaw;
      this.targetHeadRot.x = clampedPitch;
    } else {
      this.headIdleTimer += deltaTime;
      const idleNoiseX = (this.headIdleNoiseX.noise(this.headIdleTimer * 0.3) - 0.5) * 2;
      const idleNoiseY = (this.headIdleNoiseY.noise(this.headIdleTimer * 0.2) - 0.5) * 2;

      this.targetHeadRot.y = idleNoiseX * this.config.headIdleRange;
      this.targetHeadRot.x = idleNoiseY * this.config.headIdleRange * 0.6;
    }

    const speed = this.config.headFollowSpeed * deltaTime;
    this.currentHeadRot.y += (this.targetHeadRot.y - this.currentHeadRot.y) * speed;
    this.currentHeadRot.x += (this.targetHeadRot.x - this.currentHeadRot.x) * speed;

    head.rotation.y = this.currentHeadRot.y;
    head.rotation.x = this.currentHeadRot.x;

    if (neck) {
      neck.rotation.y = this.currentHeadRot.y * 0.3;
      neck.rotation.x = this.currentHeadRot.x * 0.3;
    }

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
    this.swayRandomWalk = 0;
    this.breathFreqJitter = 0;
    this.breathFreqJitterTimer = 0;
    this.headIdleTimer = 0;
  }
}
