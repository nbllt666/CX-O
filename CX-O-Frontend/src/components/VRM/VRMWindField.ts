import * as THREE from 'three';
import type { VRM } from '@pixiv/three-vrm';
import type { VRMSpringBoneJoint } from '@pixiv/three-vrm-springbone';

export type WindParams = {
  direction: number;
  strength: number;
  gustStrength: number;
  gustFrequency: number;
  gustDuration: number | string;
};

export type WindAffectedGroup = {
  boneNames: string[];
  enabled: boolean;
};

const WIND_AFFECTED_KEYWORDS = [
  'hair', 'jacket', 'skirt', 'ribbon', 'mantle', 'scarf', 'cape', 'coat',
  'dress', 'ponytail', 'twintail', 'sleeve', 'apron', 'tail', 'ear',
  'antenna', 'wing',
];

const WIND_SCALE_FACTOR = 0.5;

export class VRMWindField {
  private vrm: VRM | null = null;
  private params: WindParams = {
    direction: 0,
    strength: 0,
    gustStrength: 0,
    gustFrequency: 0,
    gustDuration: 0,
  };
  private defaultParams: WindParams = {
    direction: 0,
    strength: 0,
    gustStrength: 0,
    gustFrequency: 0,
    gustDuration: 0,
  };
  private affectedJoints: Set<VRMSpringBoneJoint> = new Set();
  private originalGravities: Map<VRMSpringBoneJoint, THREE.Vector3> = new Map();
  private gustTimer = 0;
  private gustActive = false;
  private gustRemainingDuration = 0;
  private customGroups: WindAffectedGroup[] = [];

  bindVRM(vrm: VRM): void {
    this.reset();
    this.vrm = vrm;

    const manager = vrm.springBoneManager;
    if (!manager) return;

    for (const joint of manager.joints) {
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

  update(dt: number): void {
    if (!this.vrm || this.affectedJoints.size === 0) return;

    const effectiveDirection = this.params.direction ?? this.defaultParams.direction;
    const effectiveStrength = this.params.strength ?? this.defaultParams.strength;
    const effectiveGustStrength = this.params.gustStrength ?? this.defaultParams.gustStrength;
    const effectiveGustFrequency = this.params.gustFrequency ?? this.defaultParams.gustFrequency;
    const effectiveGustDuration = this.params.gustDuration ?? this.defaultParams.gustDuration;

    if (effectiveStrength <= 0 && effectiveGustStrength <= 0) {
      for (const joint of this.affectedJoints) {
        const original = this.originalGravities.get(joint);
        if (original) {
          joint.settings.gravityDir.copy(original);
        }
      }
      return;
    }

    const rad = effectiveDirection * Math.PI / 180;
    const windForce = new THREE.Vector3(
      Math.sin(rad) * effectiveStrength,
      0,
      -Math.cos(rad) * effectiveStrength,
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
      joint.settings.gravityDir
        .copy(original)
        .addScaledVector(windForce, WIND_SCALE_FACTOR);
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
    this.params = {
      direction: 0,
      strength: 0,
      gustStrength: 0,
      gustFrequency: 0,
      gustDuration: 0,
    };
  }

  private parseGustDuration(duration: number | string): number {
    if (typeof duration === 'number') {
      return Math.max(0, duration);
    }
    const parts = duration.split('-').map(Number);
    if (parts.length === 2 && !isNaN(parts[0]) && !isNaN(parts[1])) {
      const min = Math.min(parts[0], parts[1]);
      const max = Math.max(parts[0], parts[1]);
      return min + Math.random() * (max - min);
    }
    const parsed = parseFloat(duration);
    return isNaN(parsed) ? 0 : Math.max(0, parsed);
  }

  private applyCustomGroups(): void {
    if (this.customGroups.length === 0) return;

    const manager = this.vrm?.springBoneManager;
    if (!manager) return;

    for (const group of this.customGroups) {
      for (const joint of manager.joints) {
        const boneName = joint.bone.name;
        const matchesGroup = group.boneNames.some(
          (name) => boneName.toLowerCase() === name.toLowerCase()
            || boneName.toLowerCase().includes(name.toLowerCase()),
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
