/**
 * Live2D 运行时引擎：PIXI Application + Live2DModel 加载 + 参数混合。
 *
 * 行为口径对齐 CX-O-Frontend components/business/live2d/live2d-engine.ts：
 * - 表情混合（expressionMix / parameterOverrides / watermark）经 overlay 层平滑过渡
 * - 空闲动画（呼吸/双频摇摆/眨眼）由 app.ticker 驱动
 * - 模型自适应取景（包围盒 + transform）
 *
 * 运行时依赖 window.Live2DCubismCore（index.html 引入本地 cubism core）。
 */
import * as PIXI from 'pixi.js';
import { Live2DModel } from 'pixi-live2d-display/cubism4';
import type {
  AvatarManifest,
  AvatarExpression,
  ExpressionBinding,
  ExpressionLayer,
  ParameterOverride,
  StageTransform,
} from '../types';
import type { AnimationSettings } from '../../store/settingsStore';

declare global {
  interface Window {
    PIXI: typeof PIXI;
    Live2DCubismCore?: object;
  }
}

type IdleAnimationState = {
  enabled: boolean;
  config: Partial<AnimationSettings>;
  time: number;
  blinkTimer: number;
  isBlinking: boolean;
  blinkPhase: number;
  swayRandomWalk: number;
  breathFreqJitter: number;
  breathFreqJitterTimer: number;
};

export type Live2DRuntimeState = {
  model: Live2DModel;
  activeParams: Map<string, number> | null;
  overlayCurrentParams: Map<string, number>;
  overlayTargetParams: Map<string, number>;
  baselineParams: Map<string, number>;
  trackedParamIds: Set<string>;
  app: PIXI.Application;
  avatar: AvatarManifest;
  modelBaseWidth: number;
  modelBaseHeight: number;
  currentTransform: StageTransform;
  resolvedBindingCache: Map<string, ResolvedBinding>;
  expressionMix: ExpressionLayer[];
  parameterOverrides: ParameterOverride[];
  watermarkVisible: boolean;
  idle: IdleAnimationState;
};

type CubismCoreModel = {
  getParameterValueById(parameterId: string): number;
  setParameterValueById(parameterId: string, value: number, weight?: number): void;
};

type FocusControllerLike = {
  focus(x: number, y: number, instant?: boolean): void;
};

/**
 * pixi-live2d-display 类型声明面向 pixi v6/v7，与项目内 pixi v8 的
 * Container/DisplayObject 类型不兼容（运行时能力齐全，仅类型断层）。
 * 本接口显式声明引擎用到的显示对象面，调用处经 asDisplay 收敛断言。
 */
type Live2DDisplayLike = {
  scale: { set(x: number, y?: number): void };
  anchor: { set(x: number, y: number): void };
  x: number;
  y: number;
  getLocalBounds(): { width: number; height: number };
};

function asDisplay(model: Live2DModel): Live2DDisplayLike {
  return model as unknown as Live2DDisplayLike;
}

type ExpressionFilePayload = {
  Parameters?: Array<{
    Id?: string;
    Value?: number;
    Blend?: 'Add' | 'Multiply' | 'Overwrite' | string;
  }>;
};

type ResolvedBinding =
  | { mode: 'preset'; params: Record<string, number> }
  | {
      mode: 'file';
      params: Array<{
        id: string;
        value: number;
        blend: 'Add' | 'Multiply' | 'Overwrite';
      }>;
    };

function getCoreModel(runtime: Live2DRuntimeState): CubismCoreModel {
  return runtime.model.internalModel.coreModel as CubismCoreModel;
}

async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Failed to fetch ${url}`);
  }
  return (await response.json()) as T;
}

function toRelativeAssetPath(modelJson: string, assetPath: string): string {
  const modelDirectory = modelJson.slice(0, modelJson.lastIndexOf('/') + 1);
  return assetPath.replace(modelDirectory, '');
}

function createAugmentedSettings(
  settings: Record<string, unknown>,
  avatar: AvatarManifest,
): Record<string, unknown> {
  const fileReferences = {
    ...(settings.FileReferences as Record<string, unknown> | undefined),
  };

  const expressions = avatar.expressions
    .filter((expressionItem) => expressionItem.binding.mode === 'file')
    .map((expressionItem) => ({
      Name: expressionItem.id,
      File: toRelativeAssetPath(avatar.modelJson, (expressionItem.binding as { file: string }).file),
    }));

  if (expressions.length > 0) {
    fileReferences.Expressions = expressions;
  }

  if (avatar.motions && Object.keys(avatar.motions).length > 0) {
    fileReferences.Motions = {
      TapBody: Object.values(avatar.motions).map((motion) => ({
        File: toRelativeAssetPath(avatar.modelJson, motion.file),
      })),
    };
  }

  return {
    url: avatar.modelJson,
    ...settings,
    FileReferences: fileReferences,
  };
}

function easeTowards(current: number, target: number, factor: number): number {
  if (Math.abs(target - current) <= 0.0005) {
    return target;
  }
  return current + (target - current) * factor;
}

function getOverlayFactor(paramId: string, hasExplicitTarget: boolean): number {
  if (/^ParamEyeBall[XY]$/i.test(paramId)) {
    return hasExplicitTarget ? 0.24 : 0.16;
  }
  if (/^(ParamAngle|ParamBodyAngle)/i.test(paramId)) {
    return hasExplicitTarget ? 0.14 : 0.09;
  }
  if (/^Param(Brow|Cheek)/i.test(paramId)) {
    return hasExplicitTarget ? 0.18 : 0.12;
  }
  if (/^ParamMouthOpenY$/i.test(paramId)) {
    return hasExplicitTarget ? 0.22 : 0.14;
  }
  if (/^ParamMouthForm$/i.test(paramId)) {
    return hasExplicitTarget ? 0.18 : 0.12;
  }
  return hasExplicitTarget ? 0.16 : 0.1;
}

function ensureTrackedBaseline(runtime: Live2DRuntimeState, paramId: string): void {
  if (runtime.trackedParamIds.has(paramId)) {
    return;
  }
  const coreModel = getCoreModel(runtime);
  runtime.trackedParamIds.add(paramId);
  runtime.baselineParams.set(paramId, coreModel.getParameterValueById(paramId));
}

function clampLayerWeight(weight: number): number {
  return Math.min(Math.max(weight, 0), 1);
}

function normalizeBlend(value: string | undefined): 'Add' | 'Multiply' | 'Overwrite' {
  if (value === 'Multiply' || value === 'Overwrite') {
    return value;
  }
  return 'Add';
}

function mixOverwrite(base: number, target: number, weight: number): number {
  return base + (target - base) * weight;
}

function mixMultiply(base: number, value: number, weight: number): number {
  return base * (1 + (value - 1) * weight);
}

async function resolveBinding(
  runtime: Live2DRuntimeState,
  binding: ExpressionBinding,
): Promise<ResolvedBinding> {
  if (binding.mode === 'preset') {
    return { mode: 'preset', params: binding.params };
  }
  const cached = runtime.resolvedBindingCache.get(binding.file);
  if (cached) {
    return cached;
  }
  const payload = await fetchJson<ExpressionFilePayload>(binding.file);
  const resolved: ResolvedBinding = {
    mode: 'file',
    params: (payload.Parameters ?? [])
      .filter((parameter) => parameter.Id && typeof parameter.Value === 'number')
      .map((parameter) => ({
        id: parameter.Id!,
        value: parameter.Value!,
        blend: normalizeBlend(parameter.Blend),
      })),
  };
  runtime.resolvedBindingCache.set(binding.file, resolved);
  return resolved;
}

async function mergeBindingIntoParameters(
  runtime: Live2DRuntimeState,
  nextParams: Map<string, number>,
  binding: ExpressionBinding,
  weight: number,
): Promise<void> {
  const resolved = await resolveBinding(runtime, binding);
  const normalizedWeight = clampLayerWeight(weight);

  if (resolved.mode === 'preset') {
    for (const [paramId, value] of Object.entries(resolved.params)) {
      ensureTrackedBaseline(runtime, paramId);
      const baseline = runtime.baselineParams.get(paramId) ?? 0;
      const current = nextParams.get(paramId) ?? baseline;
      nextParams.set(paramId, mixOverwrite(current, value, normalizedWeight));
    }
    return;
  }

  for (const param of resolved.params) {
    ensureTrackedBaseline(runtime, param.id);
    const baseline = runtime.baselineParams.get(param.id) ?? 0;
    const current = nextParams.get(param.id) ?? baseline;
    if (param.blend === 'Overwrite') {
      nextParams.set(param.id, mixOverwrite(current, param.value, normalizedWeight));
    } else if (param.blend === 'Multiply') {
      nextParams.set(param.id, mixMultiply(current, param.value, normalizedWeight));
    } else {
      nextParams.set(param.id, current + param.value * normalizedWeight);
    }
  }
}

async function buildMixedParameters(
  runtime: Live2DRuntimeState,
  avatar: AvatarManifest,
  expressionMix: ExpressionLayer[],
  parameterOverrides: ParameterOverride[],
  watermarkVisible: boolean,
): Promise<Map<string, number>> {
  const nextParams = new Map<string, number>();
  const expressionMap = new Map<string, AvatarExpression>(
    avatar.expressions.map((expressionItem) => [expressionItem.id, expressionItem]),
  );

  for (const layer of expressionMix) {
    const expressionItem = expressionMap.get(layer.key);
    if (!expressionItem) {
      continue;
    }
    await mergeBindingIntoParameters(runtime, nextParams, expressionItem.binding, layer.weight);
  }

  if (watermarkVisible && avatar.watermark) {
    for (const binding of avatar.watermark.bindings) {
      await mergeBindingIntoParameters(runtime, nextParams, binding, 1);
    }
  }

  for (const parameterOverride of parameterOverrides) {
    ensureTrackedBaseline(runtime, parameterOverride.id);
    nextParams.set(parameterOverride.id, parameterOverride.value);
  }

  return nextParams;
}

function fitModel(
  runtime: Live2DRuntimeState,
  container: HTMLElement,
  transform?: StageTransform,
): void {
  const { model, avatar, app } = runtime;
  const width = container.clientWidth || 800;
  const height = container.clientHeight || 800;
  const nextTransform = transform ?? runtime.currentTransform;

  app.renderer.resize(width, height);

  const baseScale = Math.min(width / runtime.modelBaseWidth, height / runtime.modelBaseHeight);
  const scale =
    baseScale * avatar.scaleMultiplier * avatar.modelTransform.scale * nextTransform.scale;

  const display = asDisplay(model);
  display.scale.set(scale);
  display.anchor.set(0.5, 1);
  display.x = width * (0.5 + avatar.modelTransform.offsetX + nextTransform.offsetX);
  display.y =
    height * (1 - avatar.verticalOffset + avatar.modelTransform.offsetY + nextTransform.offsetY);
  runtime.currentTransform = nextTransform;
}

function getFocusController(runtime: Live2DRuntimeState): FocusControllerLike {
  return runtime.model.internalModel.focusController as FocusControllerLike;
}

export async function createLive2DRuntime(
  container: HTMLElement,
  avatar: AvatarManifest,
): Promise<Live2DRuntimeState> {
  if (!window.Live2DCubismCore) {
    throw new Error('live2dcubismcore.min.js is not loaded.');
  }

  window.PIXI = PIXI;

  // PIXI v8：Application.init() 异步初始化
  const app = new PIXI.Application();
  await app.init({
    autoStart: true,
    resizeTo: container,
    backgroundAlpha: 0,
    antialias: true,
  });

  container.replaceChildren(app.canvas as HTMLCanvasElement);

  const rawSettings = await fetchJson<Record<string, unknown>>(avatar.modelJson);
  const settings = createAugmentedSettings(rawSettings, avatar);
  const model = await Live2DModel.from(settings, {
    autoInteract: false,
  });

  app.stage.addChild(model as unknown as PIXI.ContainerChild);
  const display = asDisplay(model);
  display.scale.set(1);

  const localBounds = display.getLocalBounds();
  const modelBaseWidth = Math.max(localBounds.width, 1);
  const modelBaseHeight = Math.max(localBounds.height, 1);

  const runtime: Live2DRuntimeState = {
    model,
    activeParams: null,
    overlayCurrentParams: new Map(),
    overlayTargetParams: new Map(),
    baselineParams: new Map(),
    trackedParamIds: new Set(),
    app,
    avatar,
    modelBaseWidth,
    modelBaseHeight,
    currentTransform: avatar.transformDefaults,
    resolvedBindingCache: new Map(),
    expressionMix: [],
    parameterOverrides: [],
    watermarkVisible: avatar.watermark?.enabledByDefault ?? false,
    idle: {
      enabled: true,
      config: {},
      time: 0,
      blinkTimer: 3,
      isBlinking: false,
      blinkPhase: 0,
      swayRandomWalk: 0,
      breathFreqJitter: 0,
      breathFreqJitterTimer: 0,
    },
  };

  app.ticker.add(() => {
    const coreModel = getCoreModel(runtime);
    const dt = app.ticker.deltaMS / 1000;

    if (runtime.trackedParamIds.size > 0) {
      for (const paramId of runtime.trackedParamIds) {
        const baseline = runtime.baselineParams.get(paramId) ?? 0;
        const hasExplicitTarget = runtime.overlayTargetParams.has(paramId);
        const target = runtime.overlayTargetParams.get(paramId) ?? baseline;
        const current = runtime.overlayCurrentParams.get(paramId) ?? baseline;
        const next = easeTowards(current, target, getOverlayFactor(paramId, hasExplicitTarget));

        runtime.overlayCurrentParams.set(paramId, next);
        coreModel.setParameterValueById(paramId, next);
      }
    }

    if (runtime.idle.enabled) {
      updateIdleAnimation(runtime, coreModel, dt);
    }
  });

  fitModel(runtime, container);
  getFocusController(runtime).focus(0, 0, true);
  return runtime;
}

function updateIdleAnimation(
  runtime: Live2DRuntimeState,
  coreModel: CubismCoreModel,
  dt: number,
): void {
  const idle = runtime.idle;
  const config = idle.config;
  idle.time += dt;

  const breathFrequency = config.breathFrequency ?? 0.3;
  const breathAmplitude = config.breathAmplitude ?? 0.03;
  const breathIrregularity = config.breathIrregularity ?? 0.2;
  const swayAmplitude = config.swayAmplitude ?? 0.04;
  const swayFrequency = config.swayFrequency ?? 0.5;
  const swayIrregularity = config.swayIrregularity ?? 0.3;
  const blinkInterval = config.blinkInterval ?? 3.0;
  const blinkDuration = config.blinkDuration ?? 0.15;

  // 呼吸频率微随机变化
  idle.breathFreqJitterTimer -= dt;
  if (idle.breathFreqJitterTimer <= 0) {
    idle.breathFreqJitterTimer = 3 + Math.random() * 2;
    idle.breathFreqJitter = (Math.random() - 0.5) * breathIrregularity * 0.1;
  }

  const effectiveBreathFreq = breathFrequency + idle.breathFreqJitter;
  const breath = Math.sin(idle.time * effectiveBreathFreq * Math.PI * 2);
  const breathValue = 0.5 + breath * 0.5 * (1 + breathAmplitude * 10);
  trySetParam(coreModel, 'ParamBreath', breathValue);

  // 双频率摇摆
  const slowSway = Math.sin(idle.time * swayFrequency * Math.PI * 2);
  const fastSway = Math.sin(idle.time * swayFrequency * Math.PI * 2 * 2.3) * 0.2;
  const swayNoiseVal = (Math.random() - 0.5) * swayIrregularity * 0.5;
  idle.swayRandomWalk += swayNoiseVal * dt;
  idle.swayRandomWalk *= 0.95;
  idle.swayRandomWalk = Math.max(-1, Math.min(1, idle.swayRandomWalk));

  const irregularityFactor = 1 + idle.swayRandomWalk * swayIrregularity;
  const sway = (slowSway + fastSway) * swayAmplitude * irregularityFactor;
  // Live2D ParamBodyAngle 范围约 -30~30 度，将弧度转为度数
  trySetParam(coreModel, 'ParamBodyAngleX', sway * 30);
  trySetParam(coreModel, 'ParamBodyAngleZ', sway * 15);

  // 眨眼
  if (idle.isBlinking) {
    idle.blinkPhase += dt / blinkDuration;
    if (idle.blinkPhase >= 1) {
      idle.isBlinking = false;
      idle.blinkPhase = 0;
      idle.blinkTimer = Math.random() * blinkInterval + blinkInterval * 0.5;
    }
  } else {
    idle.blinkTimer -= dt;
    if (idle.blinkTimer <= 0) {
      idle.isBlinking = true;
      idle.blinkPhase = 0;
    }
  }

  let eyeOpen = 1;
  if (idle.isBlinking) {
    eyeOpen = 1 - Math.sin(idle.blinkPhase * Math.PI);
  }
  trySetParam(coreModel, 'ParamEyeLOpen', eyeOpen);
  trySetParam(coreModel, 'ParamEyeROpen', eyeOpen);
}

function trySetParam(coreModel: CubismCoreModel, paramId: string, value: number): void {
  try {
    const current = coreModel.getParameterValueById(paramId);
    if (current !== 0 || value !== 0) {
      coreModel.setParameterValueById(paramId, value);
    }
  } catch {
    // 参数不存在则跳过
  }
}

export async function applyExpressionMix(
  runtime: Live2DRuntimeState,
  avatar: AvatarManifest,
  expressionMix: ExpressionLayer[],
): Promise<void> {
  runtime.expressionMix = expressionMix;
  await applyRuntimeState(runtime, avatar);
}

export function setIdleAnimationConfig(
  runtime: Live2DRuntimeState,
  config: Partial<AnimationSettings>,
): void {
  runtime.idle.config = config;
}

export function setIdleAnimationEnabled(runtime: Live2DRuntimeState, enabled: boolean): void {
  runtime.idle.enabled = enabled;
}

export async function setWatermarkVisibility(
  runtime: Live2DRuntimeState,
  avatar: AvatarManifest,
  watermarkVisible: boolean,
): Promise<void> {
  runtime.watermarkVisible = watermarkVisible;
  await applyRuntimeState(runtime, avatar);
}

export async function setParameterOverrides(
  runtime: Live2DRuntimeState,
  avatar: AvatarManifest,
  parameterOverrides: ParameterOverride[],
): Promise<void> {
  runtime.parameterOverrides = parameterOverrides;
  await applyRuntimeState(runtime, avatar);
}

async function applyRuntimeState(
  runtime: Live2DRuntimeState,
  avatar: AvatarManifest,
): Promise<void> {
  runtime.model.internalModel.motionManager.expressionManager?.resetExpression();

  if (
    runtime.expressionMix.length === 0 &&
    runtime.parameterOverrides.length === 0 &&
    !(runtime.watermarkVisible && avatar.watermark)
  ) {
    runtime.activeParams = null;
    runtime.overlayTargetParams = new Map();
    return;
  }

  const mixedParams = await buildMixedParameters(
    runtime,
    avatar,
    runtime.expressionMix,
    runtime.parameterOverrides,
    runtime.watermarkVisible,
  );

  if (mixedParams.size === 0) {
    runtime.activeParams = null;
    runtime.overlayTargetParams = new Map();
    return;
  }

  runtime.activeParams = mixedParams;
  runtime.overlayTargetParams = mixedParams;
}

export function resizeRuntime(runtime: Live2DRuntimeState, container: HTMLElement): void {
  fitModel(runtime, container);
}

export function updateStageTransform(
  runtime: Live2DRuntimeState,
  container: HTMLElement,
  transform: StageTransform,
): void {
  fitModel(runtime, container, transform);
}

export function focusRuntime(
  runtime: Live2DRuntimeState,
  container: HTMLElement,
  clientX: number,
  clientY: number,
): void {
  const rect = container.getBoundingClientRect();
  const x = clientX - rect.left;
  const y = clientY - rect.top;
  runtime.model.focus(x, y);
}

export function resetRuntimeFocus(runtime: Live2DRuntimeState): void {
  getFocusController(runtime).focus(0, 0);
}

export function destroyRuntime(runtime: Live2DRuntimeState): void {
  runtime.overlayCurrentParams.clear();
  runtime.overlayTargetParams.clear();
  runtime.baselineParams.clear();
  runtime.trackedParamIds.clear();
  runtime.resolvedBindingCache.clear();
  runtime.expressionMix.length = 0;
  runtime.parameterOverrides.length = 0;
  runtime.activeParams = null;
  runtime.app.destroy(true, { children: true, texture: true, textureSource: true });
}
