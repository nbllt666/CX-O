/**
 * 头像驱动基础设施：类型层。
 *
 * 内容口径对齐 CX-O-Frontend：
 * - AvatarManifest 系列：components/business/avatar/avatar-manifest.ts 的纯类型部分
 *   （资产解析/表达式发现等运行逻辑归 Task 3 头像渲染系统，本层不引入）
 * - StageTransform：components/business/live2d/live2d-engine.ts
 * - WindParams / WindAffectedGroup：components/business/vrm/vrm-wind-field.ts
 * - EmotionType：components/business/vrm/vrm-expression.ts
 * - IAvatarDriver：components/business/avatar/avatar-driver.ts 的接口部分
 *   （Live2D/VRM 具体驱动实现归 Task 3，本层只冻结接口面）
 */

// ── Manifest 类型（avatar-manifest.ts 纯类型子集） ──

export type ExpressionId = string;

export type ExpressionLayer = {
  key: ExpressionId;
  weight: number;
};

type ExpressionFileBinding = {
  mode: 'file';
  file: string;
};

type ExpressionPresetBinding = {
  mode: 'preset';
  params: Record<string, number>;
};

export type ExpressionBinding = ExpressionFileBinding | ExpressionPresetBinding;

export type ExpressionKind = 'emotion' | 'pose' | 'prop' | 'effect' | 'custom';

export type AvatarExpression = {
  id: ExpressionId;
  label: string;
  kind: ExpressionKind;
  prompt: string;
  binding: ExpressionBinding;
  aliases?: string[];
};

export type ParameterId = string;

export type ParameterOverride = {
  id: ParameterId;
  value: number;
};

export type AvatarParameterControl = {
  id: ParameterId;
  label: string;
  prompt: string;
  min: number;
  max: number;
};

export type AvatarBoneControl = {
  id: string;
  label: string;
  rotationRange: {
    x: [number, number];
    y: [number, number];
    z: [number, number];
  };
  prompt: string;
};

export type MotionBinding = {
  file: string;
  group?: string;
};

export type WatermarkBinding = {
  enabledByDefault: boolean;
  bindings: ExpressionBinding[];
};

export type AvatarManifest = {
  id: string;
  name: string;
  summary: string;
  persona: {
    tone: string;
    traits: string[];
    styleRules: string[];
  };
  modelJson: string;
  scaleMultiplier: number;
  verticalOffset: number;
  modelTransform: {
    scale: number;
    offsetX: number;
    offsetY: number;
  };
  transformDefaults: {
    scale: number;
    offsetX: number;
    offsetY: number;
  };
  expressions: AvatarExpression[];
  parameterControls?: AvatarParameterControl[];
  boneControls?: AvatarBoneControl[];
  motions?: Record<string, MotionBinding>;
  watermark?: WatermarkBinding;
  avatarType: 'live2d' | 'vrm';
};

export type Live2DAvatarManifest = AvatarManifest & { avatarType: 'live2d' };
export type VRMAvatarManifest = AvatarManifest & { avatarType: 'vrm' };

// ── 舞台变换（live2d-engine.ts） ──

export type StageTransform = {
  scale: number;
  offsetX: number;
  offsetY: number;
};

// ── 风场参数（vrm-wind-field.ts） ──

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

// ── 情绪类型（vrm-expression.ts） ──

export type EmotionType = 'happy' | 'angry' | 'sad' | 'surprised' | 'relaxed' | 'neutral';

// ── 驱动接口（avatar-driver.ts 接口部分） ──

/**
 * 驱动场景模式：pet = 桌面宠物常驻模式，live = 直播演出模式。
 * 决定驱动在两种场景下的行为口径（表情强度、动作触发、交互风等）。
 */
export type SceneMode = 'pet' | 'live';

/**
 * 头像驱动统一接口：Live2D / VRM 双引擎在 Task 3 各自实现本接口。
 * 标签驱动管线（applyTags）只依赖本接口，不感知具体引擎。
 */
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
  /** 触发指定动作（VRM 动作动画）；crossFadeTime 为动作切换交叉淡入时长（秒），省略时用引擎默认值 0.3s */
  playAction(action: string, crossFadeTime?: number): void;
  /** 触发一次交互风（interaction wind）冲击，intensity 为冲击强度（0~1 归一化） */
  triggerInteractionWind(intensity: number): void;
  bindRuntime(runtime: unknown): void;
  update(dt: number): void;
  setBlendShapes(entries: Array<{ name: string; weight: number }>): void;
  setBoneRotations(
    entries: Array<{
      boneName: string;
      rotation: { x: number; y: number; z: number };
      speed?: number;
      /** 骨骼动作保持时长 ms；省略默认 3s 后自动归中，0 表示不自动归中 */
      holdMs?: number;
    }>,
  ): void;
  holdPose(durationMs?: number): void;
  releasePose(): void;
  setWind(params: Partial<WindParams>): void;
  /** 销毁驱动与底层引擎运行时（WebGL 上下文/定时器/订阅），切换头像类型或卸载时调用 */
  destroy(): void;
}
