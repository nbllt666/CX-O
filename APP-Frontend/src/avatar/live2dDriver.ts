/**
 * Live2D 头像驱动：IAvatarDriver 的 Live2D 实现。
 *
 * 行为口径对齐 CX-O-Frontend avatar-driver.ts 的 Live2DAvatarDriver：
 * - 情绪经表达式混合（setExpressionMix）作用于参数层
 * - 直接 BlendShape（标签 [blend:]）合并进 parameterOverrides
 * - 骨骼旋转 / 姿态保持 / 风场为 VRM 专属能力，Live2D 侧为空实现
 */
import type {
  AvatarManifest,
  EmotionType,
  ExpressionLayer,
  IAvatarDriver,
  ParameterOverride,
  StageTransform,
  WindParams,
} from './types';
import type { Live2DRuntimeState } from './live2d/live2dEngine';
import {
  applyExpressionMix as engineApplyExpressionMix,
  setParameterOverrides as engineSetParameterOverrides,
  setWatermarkVisibility as engineSetWatermarkVisibility,
  destroyRuntime as engineDestroyRuntime,
} from './live2d/live2dEngine';
import { Live2DMotion } from './live2d/live2dMotion';

type DriverListener = () => void;

export class Live2DDriver implements IAvatarDriver {
  private runtime: Live2DRuntimeState | null = null;
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

  bindRuntime(runtime: unknown): void {
    this.runtime = runtime as Live2DRuntimeState;
    this.motion = new Live2DMotion();
    this.motion.bindModel(this.runtime.model);
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
    if (this.runtime) {
      void engineSetWatermarkVisibility(this.runtime, this._avatar, visible);
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
    return () => {
      this._listeners.delete(listener);
    };
  }

  getActiveExpressions(): ExpressionLayer[] {
    return this._expressionMix.filter((layer) => layer.weight > 0);
  }

  setEmotion(emotion: string, weight: number): void {
    this.setExpressionMix([{ key: emotion, weight }]);
  }

  triggerEmotionMotion(emotion: EmotionType): void {
    this.motion?.triggerEmotionMotion(emotion);
  }

  triggerSpeechMotion(): void {
    this.motion?.triggerNod();
  }

  setBlendShapes(entries: Array<{ name: string; weight: number }>): void {
    const overrides = entries.map((entry) => ({ id: entry.name, value: entry.weight }));
    const newIds = new Set(overrides.map((o) => o.id));
    this._parameterOverrides = this._parameterOverrides.filter((o) => !newIds.has(o.id));
    this._parameterOverrides.push(...overrides);
    if (this.runtime) {
      void engineSetParameterOverrides(this.runtime, this._avatar, this._parameterOverrides);
    }
    this._notify();
  }

  /** Live2D 无骨骼概念：骨骼旋转为 VRM 专属，空实现 */
  setBoneRotations(
    _entries: Array<{
      boneName: string;
      rotation: { x: number; y: number; z: number };
      speed?: number;
    }>,
  ): void {}

  /** 姿态保持为 VRM 专属，空实现 */
  holdPose(_durationMs?: number): void {}

  releasePose(): void {}

  /** 风场为 VRM 弹簧骨专属，空实现 */
  setWind(_params: Partial<WindParams>): void {}

  setSpeaking(speaking: boolean): void {
    this.motion?.setSpeaking(speaking);
  }

  update(dt: number): void {
    this.motion?.update(dt);
  }

  destroy(): void {
    if (this.runtime) {
      engineDestroyRuntime(this.runtime);
      this.runtime = null;
    }
    this.motion?.reset();
    this.motion = null;
    this._expressionMix = [];
    this._parameterOverrides = [];
  }

  private _notify(): void {
    for (const listener of this._listeners) {
      listener();
    }
  }
}
