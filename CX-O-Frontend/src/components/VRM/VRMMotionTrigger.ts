import { VRM } from '@pixiv/three-vrm';
import * as THREE from 'three';
import type { ExpressionKind } from '../Avatar/avatarManifest';
import type { EmotionType } from './VRMExpression';

export type { EmotionType } from './VRMExpression';

export type MotionTriggerConfig = {
  probability: number;
  speechRhythmInterval: number;
  transitionSpeed: number;
};

type BoneRotation = {
  x: number;
  y: number;
  z: number;
};

type MotionDefinition = {
  boneTargets: Record<string, BoneRotation>;
  duration: number;
  kind: ExpressionKind;
};

type ActiveMotion = {
  definition: MotionDefinition;
  elapsed: number;
  fromRotations: Record<string, BoneRotation>;
};

const IDLE_ROTATION: BoneRotation = { x: 0, y: 0, z: 0 };

const EMOTION_MOTIONS: Record<EmotionType, MotionDefinition> = {
  happy: {
    boneTargets: {
      rightUpperArm: { x: 0, y: 0, z: -1.0 },
      rightLowerArm: { x: 0, y: -0.3, z: -0.8 },
      rightHand: { x: 0, y: 0, z: -0.3 },
    },
    duration: 1.2,
    kind: 'emotion',
  },
  angry: {
    boneTargets: {
      spine: { x: 0.15, y: 0, z: 0 },
      chest: { x: 0.1, y: 0, z: 0 },
      upperChest: { x: 0.05, y: 0, z: 0 },
    },
    duration: 0.8,
    kind: 'emotion',
  },
  sad: {
    boneTargets: {
      head: { x: 0.3, y: 0, z: 0 },
      neck: { x: 0.15, y: 0, z: 0 },
      leftShoulder: { x: 0.1, y: 0, z: 0.05 },
      rightShoulder: { x: 0.1, y: 0, z: -0.05 },
    },
    duration: 1.5,
    kind: 'emotion',
  },
  surprised: {
    boneTargets: {
      spine: { x: -0.1, y: 0, z: 0 },
      head: { x: -0.1, y: 0, z: 0 },
      upperChest: { x: -0.05, y: 0, z: 0 },
      leftUpperArm: { x: 0, y: 0, z: 0.15 },
      rightUpperArm: { x: 0, y: 0, z: -0.15 },
    },
    duration: 0.6,
    kind: 'emotion',
  },
  relaxed: {
    boneTargets: {
      leftUpperArm: { x: 0, y: 0, z: 0.05 },
      rightUpperArm: { x: 0, y: 0, z: -0.05 },
    },
    duration: 2.0,
    kind: 'emotion',
  },
  neutral: {
    boneTargets: {},
    duration: 0,
    kind: 'emotion',
  },
};

const SPEECH_NOD_MOTION: MotionDefinition = {
  boneTargets: {
    head: { x: 0.2, y: 0, z: 0 },
    neck: { x: 0.1, y: 0, z: 0 },
  },
  duration: 0.6,
  kind: 'pose',
};

function easeInOut(t: number): number {
  return t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
}

function lerpRotation(from: BoneRotation, to: BoneRotation, t: number): BoneRotation {
  return {
    x: THREE.MathUtils.lerp(from.x, to.x, t),
    y: THREE.MathUtils.lerp(from.y, to.y, t),
    z: THREE.MathUtils.lerp(from.z, to.z, t),
  };
}

export class VRMMotionTrigger {
  private vrm: VRM | null = null;
  private config: MotionTriggerConfig = {
    probability: 0.7,
    speechRhythmInterval: 1.5,
    transitionSpeed: 1.0,
  };
  private activeMotion: ActiveMotion | null = null;
  private speechTimer = 0;
  private isSpeaking = false;
  private _paused = false;
  get paused(): boolean { return this._paused; }

  bindVRM(vrm: VRM): void {
    this.vrm = vrm;
  }

  setConfig(config: Partial<MotionTriggerConfig>): void {
    this.config = { ...this.config, ...config };
  }

  triggerEmotionMotion(emotion: EmotionType): void {
    if (emotion === 'neutral') return;
    if (Math.random() > this.config.probability) return;
    const definition = EMOTION_MOTIONS[emotion];
    if (!definition || definition.duration <= 0) return;
    this.startMotion(definition);
  }

  triggerSpeechMotion(): void {
    this.startMotion(SPEECH_NOD_MOTION);
  }

  setSpeaking(speaking: boolean): void {
    this.isSpeaking = speaking;
    if (!speaking) {
      this.speechTimer = 0;
    }
  }

  interrupt(): void {
    if (this.activeMotion) {
      this.restoreIdleBones(this.activeMotion);
      this.activeMotion = null;
    }
  }

  setPaused(paused: boolean): void {
    this._paused = paused;
    if (paused) {
      this.interrupt();
    }
  }

  update(deltaTime: number): void {
    if (!this.vrm) return;
    if (this._paused) return;

    if (this.isSpeaking) {
      this.speechTimer += deltaTime;
      if (this.speechTimer >= this.config.speechRhythmInterval) {
        this.speechTimer = 0;
        if (!this.activeMotion) {
          this.triggerSpeechMotion();
        }
      }
    }

    if (this.activeMotion) {
      this.activeMotion.elapsed += deltaTime * this.config.transitionSpeed;
      const progress = THREE.MathUtils.clamp(
        this.activeMotion.elapsed / this.activeMotion.definition.duration,
        0,
        1,
      );

      if (progress >= 1) {
        this.restoreIdleBones(this.activeMotion);
        this.activeMotion = null;
      } else {
        this.applyMotionProgress(progress);
      }
    }
  }

  reset(): void {
    if (this.activeMotion) {
      this.restoreIdleBones(this.activeMotion);
    }
    this.activeMotion = null;
    this.speechTimer = 0;
    this.isSpeaking = false;
  }

  private startMotion(definition: MotionDefinition): void {
    const fromRotations: Record<string, BoneRotation> = {};
    const mergedTargets: Record<string, BoneRotation> = { ...definition.boneTargets };

    if (this.activeMotion) {
      const currentProgress = THREE.MathUtils.clamp(
        this.activeMotion.elapsed / this.activeMotion.definition.duration,
        0,
        1,
      );

      for (const boneName of Object.keys(this.activeMotion.definition.boneTargets)) {
        fromRotations[boneName] = this.computeBoneRotation(
          this.activeMotion,
          boneName,
          currentProgress,
        );
        if (!(boneName in mergedTargets)) {
          mergedTargets[boneName] = IDLE_ROTATION;
        }
      }
    }

    for (const boneName of Object.keys(definition.boneTargets)) {
      if (!(boneName in fromRotations)) {
        fromRotations[boneName] = this.getCurrentBoneRotation(boneName);
      }
    }

    this.activeMotion = {
      definition: { ...definition, boneTargets: mergedTargets },
      elapsed: 0,
      fromRotations,
    };
  }

  private computeBoneRotation(
    motion: ActiveMotion,
    boneName: string,
    progress: number,
  ): BoneRotation {
    const from = motion.fromRotations[boneName] ?? IDLE_ROTATION;
    const target = motion.definition.boneTargets[boneName] ?? IDLE_ROTATION;

    const transitionInEnd = 0.3;

    if (progress < transitionInEnd) {
      const localT = easeInOut(progress / transitionInEnd);
      return lerpRotation(from, target, localT);
    }
    const localT = easeInOut((progress - transitionInEnd) / (1 - transitionInEnd));
    return lerpRotation(target, IDLE_ROTATION, localT);
  }

  private applyMotionProgress(progress: number): void {
    if (!this.vrm || !this.activeMotion) return;
    const humanoid = this.vrm.humanoid;
    if (!humanoid) return;

    const allBoneNames = Object.keys({
      ...this.activeMotion.definition.boneTargets,
      ...this.activeMotion.fromRotations,
    });

    for (const boneName of allBoneNames) {
      const bone = humanoid.getNormalizedBoneNode(boneName as never);
      if (!bone) continue;
      const rotation = this.computeBoneRotation(this.activeMotion, boneName, progress);
      bone.rotation.x = rotation.x;
      bone.rotation.y = rotation.y;
      bone.rotation.z = rotation.z;
    }
  }

  private restoreIdleBones(motion: ActiveMotion): void {
    if (!this.vrm) return;
    const humanoid = this.vrm.humanoid;
    if (!humanoid) return;

    const allBoneNames = Object.keys({
      ...motion.definition.boneTargets,
      ...motion.fromRotations,
    });

    for (const boneName of allBoneNames) {
      const bone = humanoid.getNormalizedBoneNode(boneName as never);
      if (!bone) continue;
      bone.rotation.x = 0;
      bone.rotation.y = 0;
      bone.rotation.z = 0;
    }
  }

  private getCurrentBoneRotation(boneName: string): BoneRotation {
    if (!this.vrm) return IDLE_ROTATION;
    const humanoid = this.vrm.humanoid;
    if (!humanoid) return IDLE_ROTATION;
    const bone = humanoid.getNormalizedBoneNode(boneName as never);
    if (!bone) return IDLE_ROTATION;
    return { x: bone.rotation.x, y: bone.rotation.y, z: bone.rotation.z };
  }
}
