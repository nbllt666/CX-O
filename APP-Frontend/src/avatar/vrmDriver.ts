/**
 * VRM 头像驱动：IAvatarDriver 的 VRM 实现。
 *
 * 行为口径对齐 CX-O-Frontend avatar-driver.ts 的 VRMDriver：
 * - setEmotion 走 VRMExpression（情绪 BlendShape 过渡）
 * - 姿态保持期间动作触发暂停、呼吸幅度压低
 * - 风场参数经 VRMWindField 作用于弹簧骨
 */
import * as THREE from 'three';
import type {
  AvatarManifest,
  EmotionType,
  ExpressionLayer,
  IAvatarDriver,
  ParameterOverride,
  StageTransform,
  WindParams,
} from './types';
import type { VRMRuntimeState } from './vrm/vrmEngine';
import {
  applyExpressionMix as engineApplyExpressionMix,
  setParameterOverrides as engineSetParameterOverrides,
  updateStageTransform as engineUpdateStageTransform,
  destroyRuntime as engineDestroyRuntime,
  setBlendShapes as engineSetBlendShapes,
  setBoneRotations as engineSetBoneRotations,
  holdPose as engineHoldPose,
  releasePose as engineReleasePose,
} from './vrm/vrmEngine';
import { VRMActionController } from './vrm/vrmActionController';
import { VRMExpression } from './vrm/vrmExpression';
import { VRMMotionTrigger } from './vrm/vrmMotionTrigger';
import { VRMWindField } from './vrm/vrmWindField';

type DriverListener = () => void;

/** 动作名 → 情绪动作回退映射：无匹配动画片段时降级触发情绪动作 */
const ACTION_EMOTION_FALLBACK: Record<string, EmotionType> = {
  wave: 'happy',
  hi: 'happy',
  hello: 'happy',
  bye: 'happy',
  greet: 'happy',
  handwave: 'happy',
};

export class VRMDriver implements IAvatarDriver {
  private runtime: VRMRuntimeState | null = null;
  private expression: VRMExpression | null = null;
  private motionTrigger: VRMMotionTrigger | null = null;
  private windField: VRMWindField | null = null;
  private actionController: VRMActionController | null = null;
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

  get avatar() {
    return this._avatar;
  }
  get expressionMix() {
    return this._expressionMix;
  }
  get parameterOverrides() {
    return this._parameterOverrides;
  }
  get watermarkVisible() {
    return this._watermarkVisible;
  }
  get transform() {
    return this._transform;
  }
  get mouthOpen() {
    return this._mouthOpen;
  }

  bindRuntime(runtime: unknown, animations?: THREE.AnimationClip[]): void {
    this.runtime = runtime as VRMRuntimeState;
    this.expression = new VRMExpression();
    this.expression.bindVRM(this.runtime.vrm);
    this.motionTrigger = new VRMMotionTrigger();
    this.motionTrigger.bindVRM(this.runtime.vrm);
    this.windField = new VRMWindField();
    this.windField.bindVRM(this.runtime.vrm);
    // 动作控制器：绑定模型根节点与动画片段（动作交叉淡入）
    if (this.runtime.vrm.scene) {
      this.actionController = new VRMActionController();
      this.actionController.bind(this.runtime.vrm.scene, animations ?? []);
    }
  }

  setExpressionMix(mix: ExpressionLayer[]): void {
    this._expressionMix = mix;
    if (this.runtime) {
      void engineApplyExpressionMix(this.runtime, this._avatar, mix);
    }
    this._notify();
  }

  setParameterOverrides(overrides: ParameterOverride[]): void {
    this._parameterOverrides = overrides;
    if (this.runtime) {
      void engineSetParameterOverrides(this.runtime, this._avatar, overrides);
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
      engineUpdateStageTransform(this.runtime, transform);
    }
    this._notify();
  }

  setMouthOpen(value: number): void {
    this._mouthOpen = Math.min(Math.max(value, 0), 1);
    this._notify();
  }

  subscribe(listener: DriverListener): () => void {
    this._listeners.add(listener);
    return () => {
      this._listeners.delete(listener);
    };
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
      engineSetBlendShapes(this.runtime, entries);
    }
  }

  setBoneRotations(
    entries: Array<{
      boneName: string;
      rotation: { x: number; y: number; z: number };
      speed?: number;
      /** 骨骼动作保持时长 ms；省略默认 3s 后自动归中，0 表示不自动归中 */
      holdMs?: number;
    }>,
  ): void {
    if (this.runtime) {
      engineSetBoneRotations(this.runtime, entries);
      this.motionTrigger?.interrupt();
    }
  }

  holdPose(durationMs?: number): void {
    if (this.runtime) {
      engineHoldPose(this.runtime, durationMs);
      this.motionTrigger?.setPaused(true);
      this.runtime.animation.setBreathingAmplitude(0.3);
    }
  }

  releasePose(): void {
    if (this.runtime) {
      engineReleasePose(this.runtime);
      this.motionTrigger?.setPaused(false);
      this.runtime.animation.setBreathingAmplitude(1.0);
    }
  }

  setWind(params: Partial<WindParams>): void {
    this.windField?.setWindParams(params);
  }

  /** 设置默认（环境）风场参数，与标签触发的瞬时风场叠加 */
  setDefaultWind(params: Partial<WindParams>): void {
    this.windField?.setDefaultParams(params);
  }

  setSpeaking(speaking: boolean): void {
    this.motionTrigger?.setSpeaking(speaking);
  }

  /** 触发指定动作：优先播放匹配动画片段（交叉淡入），无匹配片段时降级触发情绪动作，均不抛错 */
  playAction(action: string, crossFadeTime?: number): void {
    if (this.actionController?.hasAction(action)) {
      this.actionController.playAction(action, crossFadeTime ?? 0.3);
      return;
    }
    const emotion = ACTION_EMOTION_FALLBACK[action.toLowerCase()];
    if (emotion) {
      this.triggerEmotionMotion(emotion);
    }
  }

  /** 触发一次交互风冲击（作用于弹簧骨） */
  triggerInteractionWind(intensity: number): void {
    this.windField?.triggerInteractionWind(intensity);
  }

  update(dt: number): void {
    if (this.expression) this.expression.update(dt);
    if (this.motionTrigger) this.motionTrigger.update(dt);
    if (this.windField) this.windField.update(dt);
    this.actionController?.update(dt);
  }

  destroy(): void {
    if (this.runtime) {
      engineDestroyRuntime(this.runtime);
      this.runtime = null;
    }
    this.expression = null;
    this.motionTrigger = null;
    this.windField?.reset();
    this.windField = null;
    this.actionController?.reset();
    this.actionController = null;
    this._expressionMix = [];
    this._parameterOverrides = [];
  }

  private _notify(): void {
    for (const listener of this._listeners) {
      listener();
    }
  }
}
