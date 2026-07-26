import type { AvatarManifest, ExpressionLayer, ParameterOverride } from './avatar-manifest';
import type { StageTransform } from '../live2d/live2d-engine';
import type { EmotionType } from '../vrm/vrm-expression';
import type { VRMRuntimeState } from '../vrm/vrm-engine';
import {
  applyExpressionMix as vrmApplyExpressionMix,
  setParameterOverrides as vrmSetParameterOverrides,
  updateStageTransform as vrmUpdateStageTransform,
  destroyRuntime,
  setBlendShapes as vrmSetBlendShapes,
  setBoneRotations as vrmSetBoneRotations,
  holdPose as vrmHoldPose,
  releasePose as vrmReleasePose,
} from '../vrm/vrm-engine';
import { VRMWindField } from '../vrm/vrm-wind-field';
import type { WindParams } from '../vrm/vrm-wind-field';
import {
  applyExpressionMix as live2dApplyExpressionMix,
  setParameterOverrides as live2dSetParameterOverrides,
  setWatermarkVisibility as live2dSetWatermarkVisibility,
  destroyRuntime as live2dDestroyRuntime,
} from '../live2d/live2d-engine';
import { VRMExpression } from '../vrm/vrm-expression';
import { VRMMotionTrigger } from '../vrm/vrm-motion-trigger';
import { Live2DMotion } from '../live2d/live2d-motion';

export interface IAvatarDriver {
  readonly avatar: AvatarManifest;
  readonly expressionMix: ExpressionLayer[];
  readonly parameterOverrides: ParameterOverride[];
  readonly watermarkVisible: boolean;
  readonly transform: StageTransform;
  readonly mouthOpen: number;
  setExpressionMix(mix: ExpressionLayer[]): void;
  setParameterOverrides(overrides: ParameterOverride[]): void;
  setWatermarkVisibility(visible: boolean): void;
  setTransform(transform: StageTransform): void;
  setMouthOpen(value: number): void;
  subscribe(listener: () => void): () => void;
  getActiveExpressions(): ExpressionLayer[];
  setEmotion(emotion: string, weight: number): void;
  triggerEmotionMotion(emotion: EmotionType): void;
  triggerSpeechMotion(): void;
  bindRuntime(runtime: unknown): void;
  update(dt: number): void;
  setBlendShapes(entries: Array<{ name: string; weight: number }>): void;
  setBoneRotations(entries: Array<{ boneName: string; rotation: { x: number; y: number; z: number }; speed?: number }>): void;
  holdPose(durationMs?: number): void;
  releasePose(): void;
  setWind(params: Partial<WindParams>): void;
}

type DriverListener = () => void;

export class Live2DAvatarDriver implements IAvatarDriver {
  private runtime: unknown = null;
  private motion: Live2DMotion | null = null;
  private _avatar: AvatarManifest;
  private _expressionMix: ExpressionLayer[] = [];
  private _parameterOverrides: ParameterOverride[] = [];
  private _watermarkVisible = false;
  private _mouthOpen = 0;
  private _transform: StageTransform;
  private _listeners = new Set<DriverListener>();

  constructor(avatar: AvatarManifest) {
    this._avatar = avatar;
    this._transform = { ...avatar.transformDefaults };
  }

  get avatar() { return this._avatar; }
  get expressionMix() { return this._expressionMix; }
  get parameterOverrides() { return this._parameterOverrides; }
  get watermarkVisible() { return this._watermarkVisible; }
  get transform() { return this._transform; }
  get mouthOpen() { return this._mouthOpen; }

  bindRuntime(runtime: unknown): void {
    this.runtime = runtime;
    this.motion = new Live2DMotion();
    const rt = runtime as { model: unknown };
    this.motion.bindModel(rt.model as never);
  }

  setExpressionMix(mix: ExpressionLayer[]): void {
    this._expressionMix = mix;
    if (this.runtime) {
      live2dApplyExpressionMix(this.runtime as never, this._avatar, mix);
    }
    this._notify();
  }

  setParameterOverrides(overrides: ParameterOverride[]): void {
    this._parameterOverrides = overrides;
    if (this.runtime) {
      live2dSetParameterOverrides(this.runtime as never, this._avatar, overrides);
    }
    this._notify();
  }

  setWatermarkVisibility(visible: boolean): void {
    this._watermarkVisible = visible;
    if (this.runtime) {
      live2dSetWatermarkVisibility(this.runtime as never, this._avatar, visible);
    }
    this._notify();
  }

  setTransform(transform: StageTransform): void {
    this._transform = transform;
    this._notify();
  }

  setMouthOpen(value: number): void {
    this._mouthOpen = Math.min(Math.max(value, 0), 1);
    this._notify();
  }

  subscribe(listener: DriverListener): () => void {
    this._listeners.add(listener);
    return () => { this._listeners.delete(listener); };
  }

  getActiveExpressions(): ExpressionLayer[] {
    return this._expressionMix.filter((layer) => layer.weight > 0);
  }

  setEmotion(emotion: string, weight: number) {
    this.setExpressionMix([{ key: emotion, weight }]);
  }

  triggerEmotionMotion(emotion: EmotionType): void {
    if (this.motion) {
      this.motion.triggerEmotionMotion(emotion);
    }
  }

  triggerSpeechMotion(): void {
    if (this.motion) {
      this.motion.triggerNod();
    }
  }

  setBlendShapes(entries: Array<{ name: string; weight: number }>): void {
    const overrides = entries.map((entry) => ({ id: entry.name, value: entry.weight }));
    const newIds = new Set(overrides.map((o) => o.id));
    this._parameterOverrides = this._parameterOverrides.filter((o) => !newIds.has(o.id));
    this._parameterOverrides.push(...overrides);
    if (this.runtime) {
      live2dSetParameterOverrides(this.runtime as never, this._avatar, this._parameterOverrides);
    }
    this._notify();
  }

  setBoneRotations(_entries: Array<{ boneName: string; rotation: { x: number; y: number; z: number }; speed?: number }>): void {}

  holdPose(_durationMs?: number): void {}

  releasePose(): void {}

  setWind(_params: Partial<WindParams>): void {}

  update(dt: number): void {
    if (this.motion) this.motion.update(dt);
  }

  destroy(): void {
    if (this.runtime) {
      live2dDestroyRuntime(this.runtime as never);
      this.runtime = null;
    }
    this.motion = null;
    this._expressionMix = [];
    this._parameterOverrides = [];
  }

  private _notify() {
    for (const listener of this._listeners) { listener(); }
  }
}

export function createAvatarDriver(avatar: AvatarManifest): IAvatarDriver {
  if (avatar.avatarType === 'vrm') {
    return new VRMDriver(avatar);
  }
  return new Live2DAvatarDriver(avatar);
}

export class VRMDriver implements IAvatarDriver {
  private runtime: VRMRuntimeState | null = null;
  private expression: VRMExpression | null = null;
  private motionTrigger: VRMMotionTrigger | null = null;
  private windField: VRMWindField | null = null;
  private _avatar: AvatarManifest;
  private _expressionMix: ExpressionLayer[] = [];
  private _parameterOverrides: ParameterOverride[] = [];
  private _watermarkVisible = false;
  private _mouthOpen = 0;
  private _transform: StageTransform;
  private _listeners = new Set<DriverListener>();

  constructor(avatar: AvatarManifest) {
    this._avatar = avatar;
    this._transform = { ...avatar.transformDefaults };
  }

  get avatar() { return this._avatar; }
  get expressionMix() { return this._expressionMix; }
  get parameterOverrides() { return this._parameterOverrides; }
  get watermarkVisible() { return this._watermarkVisible; }
  get transform() { return this._transform; }
  get mouthOpen() { return this._mouthOpen; }

  bindRuntime(runtime: unknown): void {
    this.runtime = runtime as VRMRuntimeState;
    this.expression = new VRMExpression();
    this.expression.bindVRM(this.runtime.vrm);
    this.motionTrigger = new VRMMotionTrigger();
    this.motionTrigger.bindVRM(this.runtime.vrm);
    this.windField = new VRMWindField();
    this.windField.bindVRM(this.runtime.vrm);
  }

  setExpressionMix(mix: ExpressionLayer[]): void {
    this._expressionMix = mix;
    if (this.runtime) {
      vrmApplyExpressionMix(this.runtime, this._avatar, mix);
    }
    this._notify();
  }

  setParameterOverrides(overrides: ParameterOverride[]): void {
    this._parameterOverrides = overrides;
    if (this.runtime) {
      vrmSetParameterOverrides(this.runtime, this._avatar, overrides);
    }
    this._notify();
  }

  setWatermarkVisibility(visible: boolean): void {
    this._watermarkVisible = visible;
    this._notify();
  }

  setTransform(transform: StageTransform): void {
    this._transform = transform;
    if (this.runtime) {
      vrmUpdateStageTransform(this.runtime, transform);
    }
    this._notify();
  }

  setMouthOpen(value: number): void {
    this._mouthOpen = Math.min(Math.max(value, 0), 1);
    this._notify();
  }

  subscribe(listener: DriverListener): () => void {
    this._listeners.add(listener);
    return () => { this._listeners.delete(listener); };
  }

  getActiveExpressions(): ExpressionLayer[] {
    return this._expressionMix.filter((layer) => layer.weight > 0);
  }

  setEmotion(emotion: string, weight: number): void {
    if (this.expression) {
      this.expression.setEmotion(emotion, weight);
    }
  }

  triggerEmotionMotion(emotion: EmotionType): void {
    if (this.motionTrigger) {
      this.motionTrigger.triggerEmotionMotion(emotion);
    }
  }

  triggerSpeechMotion(): void {
    if (this.motionTrigger) {
      this.motionTrigger.triggerSpeechMotion();
    }
  }

  setBlendShapes(entries: Array<{ name: string; weight: number }>): void {
    if (this.runtime) {
      vrmSetBlendShapes(this.runtime, entries);
    }
  }

  setBoneRotations(entries: Array<{ boneName: string; rotation: { x: number; y: number; z: number }; speed?: number }>): void {
    if (this.runtime) {
      vrmSetBoneRotations(this.runtime, entries);
      this.motionTrigger?.interrupt();
    }
  }

  holdPose(durationMs?: number): void {
    if (this.runtime) {
      vrmHoldPose(this.runtime, durationMs);
      this.motionTrigger?.setPaused(true);
      this.runtime.animation.setBreathingAmplitude(0.3);
    }
  }

  releasePose(): void {
    if (this.runtime) {
      vrmReleasePose(this.runtime);
      this.motionTrigger?.setPaused(false);
      this.runtime.animation.setBreathingAmplitude(1.0);
    }
  }

  setWind(params: Partial<WindParams>): void {
    this.windField?.setWindParams(params);
  }

  update(dt: number): void {
    if (this.expression) this.expression.update(dt);
    if (this.motionTrigger) this.motionTrigger.update(dt);
    if (this.windField) this.windField.update(dt);
  }

  destroy(): void {
    if (this.runtime) {
      destroyRuntime(this.runtime);
      this.runtime = null;
    }
    this.expression = null;
    this.motionTrigger = null;
    this.windField?.reset();
    this.windField = null;
    this._expressionMix = [];
    this._parameterOverrides = [];
  }

  private _notify() {
    for (const listener of this._listeners) { listener(); }
  }
}
