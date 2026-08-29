/**
 * VRM 风场：对弹簧骨（头发/裙摆/飘带等）施加方向性风力与阵风。
 * 行为口径对齐 CX-O-Frontend components/business/vrm/vrm-wind-field.ts。
 *
 * 风力通过叠加到 springBone joint 的 gravityDir 实现，不影响骨骼动画本体；
 * strength/gustStrength 均为 0 时恢复原始重力方向。
 */
import * as THREE from 'three';
import type { VRM } from '@pixiv/three-vrm';
import type { VRMSpringBoneJoint } from '@pixiv/three-vrm-springbone';
import type { WindParams, WindAffectedGroup } from '../types';

const WIND_AFFECTED_KEYWORDS = [
  'hair',
  'jacket',
  'skirt',
  'ribbon',
  'mantle',
  'scarf',
  'cape',
  'coat',
  'dress',
  'ponytail',
  'twintail',
  'sleeve',
  'apron',
  'tail',
  'ear',
  'antenna',
  'wing',
];

const WIND_SCALE_FACTOR = 0.5;

const ZERO_WIND: WindParams = {
  direction: 0,
  strength: 0,
  gustStrength: 0,
  gustFrequency: 0,
  gustDuration: 0,
};

export class VRMWindField {
  private vrm: VRM | null = null;
  private params: WindParams = { ...ZERO_WIND };
  private defaultParams: WindParams = { ...ZERO_WIND };
  private affectedJoints: Set<VRMSpringBoneJoint> = new Set();
  private originalGravities: Map<VRMSpringBoneJoint, THREE.Vector3> = new Map();
  private gustTimer = 0;
  private gustActive = false;
  private gustRemainingDuration = 0;
  private interactionStrength = 0;
  private customGroups: WindAffectedGroup[] = [];

  bindVRM(vrm: VRM): void {
    this.reset();
    this.vrm = vrm;

    const manager = vrm.springBoneManager;
    if (!manager) return;

    // three-vrm 3.x 新版弹簧骨集合为 `_joints`（Set），旧版为数组 `joints`；兼容两者。
    const rawJoints = manager.joints ?? (manager as unknown as { _joints?: unknown })._joints;
    const joints: VRMSpringBoneJoint[] = Array.isArray(rawJoints)
      ? rawJoints
      : rawJoints instanceof Set
        ? Array.from(rawJoints)
        : [];

    for (const joint of joints) {
      const boneName = joint.bone.name.toLowerCase();
      const matchesKeyword = WIND_AFFECTED_KEYWORDS.some((kw) => boneName.includes(kw));
      if (matchesKeyword) {
        this.affectedJoints.add(joint);
        this.originalGravities.set(joint, joint.settings.gravityDir.clone());
      }
    }

    this.applyCustomGroups();
  }

  setWindParams(params: Partial<WindParams>): void {
    this.params = { ...this.params, ...params };
  }

  setDefaultParams(params: Partial<WindParams>): void {
    this.defaultParams = { ...this.defaultParams, ...params };
  }

  setCustomGroups(groups: WindAffectedGroup[]): void {
    this.customGroups = groups;
    if (this.vrm) {
      this.applyCustomGroups();
    }
  }

  triggerInteractionWind(intensity: number): void {
    this.interactionStrength = Math.max(this.interactionStrength, intensity);
  }

  update(dt: number): void {
    if (!this.vrm || this.affectedJoints.size === 0) return;

    const effectiveDirection = this.params.direction ?? this.defaultParams.direction;
    const effectiveStrength = this.params.strength ?? this.defaultParams.strength;
    const effectiveGustStrength = this.params.gustStrength ?? this.defaultParams.gustStrength;
    const effectiveGustFrequency = this.params.gustFrequency ?? this.defaultParams.gustFrequency;
    const effectiveGustDuration = this.params.gustDuration ?? this.defaultParams.gustDuration;

    // 交互风力每帧衰减（峰值保持由 triggerInteractionWind 的 Math.max 保证）
    this.interactionStrength *= 0.95;

    if (effectiveStrength + this.interactionStrength <= 0 && effectiveGustStrength <= 0) {
      for (const joint of this.affectedJoints) {
        const original = this.originalGravities.get(joint);
        if (original) {
          joint.settings.gravityDir.copy(original);
        }
      }
      return;
    }

    const rad = (effectiveDirection * Math.PI) / 180;
    const windForce = new THREE.Vector3(
      Math.sin(rad) * (effectiveStrength + this.interactionStrength),
      0,
      -Math.cos(rad) * (effectiveStrength + this.interactionStrength),
    );

    this.gustTimer += dt;

    if (effectiveGustFrequency > 0 && !this.gustActive) {
      const interval = 1 / effectiveGustFrequency;
      if (this.gustTimer >= interval) {
        this.gustActive = true;
        this.gustRemainingDuration = this.parseGustDuration(effectiveGustDuration);
        this.gustTimer = 0;
      }
    }

    if (this.gustActive) {
      this.gustRemainingDuration -= dt;
      if (this.gustRemainingDuration <= 0) {
        this.gustActive = false;
        this.gustRemainingDuration = 0;
      } else {
        const variation = 0.7 + Math.random() * 0.6;
        const gustForce = new THREE.Vector3(
          Math.sin(rad) * effectiveGustStrength * variation,
          0,
          -Math.cos(rad) * effectiveGustStrength * variation,
        );
        windForce.add(gustForce);
      }
    }

    for (const joint of this.affectedJoints) {
      const original = this.originalGravities.get(joint);
      if (!original) continue;
      joint.settings.gravityDir.copy(original).addScaledVector(windForce, WIND_SCALE_FACTOR);
    }
  }

  reset(): void {
    for (const joint of this.affectedJoints) {
      const original = this.originalGravities.get(joint);
      if (original) {
        joint.settings.gravityDir.copy(original);
      }
    }

    this.affectedJoints.clear();
    this.originalGravities.clear();
    this.vrm = null;
    this.gustTimer = 0;
    this.gustActive = false;
    this.gustRemainingDuration = 0;
    this.interactionStrength = 0;
    this.params = { ...ZERO_WIND };
  }

  private parseGustDuration(duration: number | string): number {
    if (typeof duration === 'number') {
      return Math.max(0, duration);
    }
    const parts = duration.split('-').map(Number);
    if (parts.length === 2 && !Number.isNaN(parts[0]) && !Number.isNaN(parts[1])) {
      const min = Math.min(parts[0], parts[1]);
      const max = Math.max(parts[0], parts[1]);
      return min + Math.random() * (max - min);
    }
    const parsed = parseFloat(duration);
    return Number.isNaN(parsed) ? 0 : Math.max(0, parsed);
  }

  private applyCustomGroups(): void {
    if (this.customGroups.length === 0) return;

    const manager = this.vrm?.springBoneManager;
    if (!manager) return;

    // three-vrm 3.x 新版弹簧骨集合为 `_joints`（Set），旧版为数组 `joints`；兼容两者
    // （与 bindVRM 的双形态提取一致），否则 3.x 下 manager.joints 为 undefined 会 TypeError。
    const rawJoints = manager.joints ?? (manager as unknown as { _joints?: unknown })._joints;
    const joints: VRMSpringBoneJoint[] = Array.isArray(rawJoints)
      ? rawJoints
      : rawJoints instanceof Set
        ? Array.from(rawJoints)
        : [];

    for (const group of this.customGroups) {
      for (const joint of joints) {
        const boneName = joint.bone.name;
        const matchesGroup = group.boneNames.some(
          (name) =>
            boneName.toLowerCase() === name.toLowerCase() ||
            boneName.toLowerCase().includes(name.toLowerCase()),
        );
        if (matchesGroup) {
          if (group.enabled) {
            if (!this.affectedJoints.has(joint)) {
              this.affectedJoints.add(joint);
              this.originalGravities.set(joint, joint.settings.gravityDir.clone());
            }
          } else {
            const original = this.originalGravities.get(joint);
            if (original) {
              joint.settings.gravityDir.copy(original);
            }
            this.affectedJoints.delete(joint);
            this.originalGravities.delete(joint);
          }
        }
      }
    }
  }
}
