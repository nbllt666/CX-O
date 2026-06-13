import * as THREE from 'three';
import { VRM, VRMExpressionPresetName } from '@pixiv/three-vrm';
import type {
  AvatarManifest,
  AvatarExpression,
  ExpressionBinding,
  ExpressionLayer,
  ParameterOverride,
} from '../Avatar/avatarManifest';
import { VRMAnimation } from './VRMAnimation';
import { VRMLipSync } from './VRMLipSync';

export type StageTransform = {
  scale: number;
  offsetX: number;
  offsetY: number;
};

type ResolvedBinding =
  | { mode: 'preset'; params: Record<string, number> }
  | {
      mode: 'file';
      params: Array<{
        name: string;
        value: number;
        blend: 'Add' | 'Multiply' | 'Overwrite';
      }>;
    };

type BlendShapeFilePayload = {
  BlendShapes?: Array<{
    Name?: string;
    Value?: number;
    Blend?: string;
  }>;
};

export type VRMRuntimeState = {
  vrm: VRM;
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  renderer: THREE.WebGLRenderer;
  activeExpressionMix: ExpressionLayer[];
  parameterOverrides: ParameterOverride[];
  overlayCurrentValues: Map<string, number>;
  overlayTargetValues: Map<string, number>;
  baselineValues: Map<string, number>;
  trackedBlendShapeNames: Set<string>;
  animation: VRMAnimation;
  lipSync: VRMLipSync;
  currentTransform: StageTransform;
  avatar: AvatarManifest;
  clock: THREE.Timer;
  canvas: HTMLCanvasElement;
  resolvedBindingCache: Map<string, ResolvedBinding>;
  animationFrameId: number;
  modelHeight: number;
  modelWidth: number;
  directBlendShapes: Map<string, number>;
  heldBones: Map<string, { x: number; y: number; z: number }>;
  poseHoldTimer: number;
  boneTransitionSpeeds: Map<string, number>;
  boneCurrentRotations: Map<string, { x: number; y: number; z: number }>;
  boneTargetRotations: Map<string, { x: number; y: number; z: number }>;
};

function easeTowards(current: number, target: number, factor: number): number {
  if (Math.abs(target - current) <= 0.0005) {
    return target;
  }
  return current + (target - current) * factor;
}

function getOverlayFactor(blendShapeName: string, hasExplicitTarget: boolean): number {
  if (/^(Aa|Ih|Ou|Ee|Oh)$/.test(blendShapeName)) {
    return hasExplicitTarget ? 0.22 : 0.14;
  }
  if (/^Blink/.test(blendShapeName)) {
    return hasExplicitTarget ? 0.24 : 0.16;
  }
  if (/^Look/.test(blendShapeName)) {
    return hasExplicitTarget ? 0.24 : 0.16;
  }
  if (/^(Happy|Angry|Sad|Surprised|Relaxed|Neutral)$/.test(blendShapeName)) {
    return hasExplicitTarget ? 0.18 : 0.12;
  }
  return hasExplicitTarget ? 0.16 : 0.1;
}

function ensureTrackedBaseline(runtime: VRMRuntimeState, blendShapeName: string): void {
  if (runtime.trackedBlendShapeNames.has(blendShapeName)) {
    return;
  }
  runtime.trackedBlendShapeNames.add(blendShapeName);
  const em = runtime.vrm.expressionManager;
  if (em) {
    const value = em.getValue(blendShapeName as keyof typeof VRMExpressionPresetName);
    runtime.baselineValues.set(blendShapeName, typeof value === 'number' ? value : 0);
  } else {
    runtime.baselineValues.set(blendShapeName, 0);
  }
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

async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Failed to fetch ${url}`);
  }
  return (await response.json()) as T;
}

async function resolveBinding(
  runtime: VRMRuntimeState,
  binding: ExpressionBinding,
): Promise<ResolvedBinding> {
  if (binding.mode === 'preset') {
    return { mode: 'preset', params: binding.params };
  }
  const cached = runtime.resolvedBindingCache.get(binding.file);
  if (cached) {
    return cached;
  }
  const payload = await fetchJson<BlendShapeFilePayload>(binding.file);
  const resolved: ResolvedBinding = {
    mode: 'file',
    params: (payload.BlendShapes ?? [])
      .filter((bs) => bs.Name && typeof bs.Value === 'number')
      .map((bs) => ({
        name: bs.Name!,
        value: bs.Value!,
        blend: normalizeBlend(bs.Blend),
      })),
  };
  runtime.resolvedBindingCache.set(binding.file, resolved);
  return resolved;
}

async function mergeBindingIntoBlendShapes(
  runtime: VRMRuntimeState,
  nextValues: Map<string, number>,
  binding: ExpressionBinding,
  weight: number,
): Promise<void> {
  const resolved = await resolveBinding(runtime, binding);
  const normalizedWeight = clampLayerWeight(weight);

  if (resolved.mode === 'preset') {
    for (const [name, value] of Object.entries(resolved.params)) {
      ensureTrackedBaseline(runtime, name);
      const baseline = runtime.baselineValues.get(name) ?? 0;
      const current = nextValues.get(name) ?? baseline;
      nextValues.set(name, mixOverwrite(current, value, normalizedWeight));
    }
    return;
  }

  for (const param of resolved.params) {
    ensureTrackedBaseline(runtime, param.name);
    const baseline = runtime.baselineValues.get(param.name) ?? 0;
    const current = nextValues.get(param.name) ?? baseline;
    if (param.blend === 'Overwrite') {
      nextValues.set(param.name, mixOverwrite(current, param.value, normalizedWeight));
    } else if (param.blend === 'Multiply') {
      nextValues.set(param.name, mixMultiply(current, param.value, normalizedWeight));
    } else {
      nextValues.set(param.name, current + param.value * normalizedWeight);
    }
  }
}

async function buildMixedBlendShapes(
  runtime: VRMRuntimeState,
  avatar: AvatarManifest,
  expressionMix: ExpressionLayer[],
  parameterOverrides: ParameterOverride[],
): Promise<Map<string, number>> {
  const nextValues = new Map<string, number>();
  const expressionMap = new Map<string, AvatarExpression>(
    avatar.expressions.map((expr) => [expr.id, expr]),
  );

  for (const layer of expressionMix) {
    const expr = expressionMap.get(layer.key);
    if (!expr) continue;
    await mergeBindingIntoBlendShapes(runtime, nextValues, expr.binding, layer.weight);
  }

  for (const override of parameterOverrides) {
    ensureTrackedBaseline(runtime, override.id);
    nextValues.set(override.id, override.value);
  }

  return nextValues;
}

function fitVRMModel(runtime: VRMRuntimeState, transform?: StageTransform): void {
  const { vrm, avatar, camera, renderer, canvas } = runtime;
  const width = canvas.clientWidth || 300;
  const height = canvas.clientHeight || 400;
  const nextTransform = transform ?? runtime.currentTransform;

  renderer.setSize(width, height, false);
  camera.aspect = width / height;
  camera.updateProjectionMatrix();

  const scale = avatar.scaleMultiplier * avatar.modelTransform.scale * nextTransform.scale;
  vrm.scene.scale.setScalar(scale);

  const box = new THREE.Box3().setFromObject(vrm.scene);
  const size = box.getSize(new THREE.Vector3());
  const modelHeight = Math.max(size.y, 0.1);
  const modelWidth = Math.max(size.x, 0.1);

  vrm.scene.position.set(
    avatar.modelTransform.offsetX + nextTransform.offsetX,
    -box.min.y + avatar.modelTransform.offsetY + nextTransform.offsetY,
    0,
  );

  camera.position.set(0, modelHeight * 0.7, Math.max(modelWidth * 2.5, 2));
  camera.lookAt(0, modelHeight * 0.5, 0);

  runtime.modelHeight = modelHeight;
  runtime.modelWidth = modelWidth;
  runtime.currentTransform = nextTransform;
}

export function createVRMRuntime(
  canvas: HTMLCanvasElement,
  avatar: AvatarManifest,
  vrm: VRM,
): VRMRuntimeState {
  const width = canvas.clientWidth || 300;
  const height = canvas.clientHeight || 400;

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(30, width / height, 0.1, 20);

  const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
  renderer.setPixelRatio(window.devicePixelRatio);
  renderer.setSize(width, height, false);
  renderer.outputColorSpace = THREE.SRGBColorSpace;

  const dirLight = new THREE.DirectionalLight(0xffffff, 1.0);
  dirLight.position.set(1, 1.5, 1);
  scene.add(dirLight);
  scene.add(new THREE.AmbientLight(0xffffff, 0.6));
  const pointLight = new THREE.PointLight(0xffffff, 0.5, 10);
  pointLight.position.set(-1, 1, 1);
  scene.add(pointLight);

  const animation = new VRMAnimation();
  animation.bindVRM(vrm);

  const lipSync = new VRMLipSync();
  lipSync.bindVRM(vrm);

  const clock = new THREE.Timer();

  scene.add(vrm.scene);

  const box = new THREE.Box3().setFromObject(vrm.scene);
  const size = box.getSize(new THREE.Vector3());

  const runtime: VRMRuntimeState = {
    vrm,
    scene,
    camera,
    renderer,
    activeExpressionMix: [],
    parameterOverrides: [],
    overlayCurrentValues: new Map(),
    overlayTargetValues: new Map(),
    baselineValues: new Map(),
    trackedBlendShapeNames: new Set(),
    animation,
    lipSync,
    currentTransform: avatar.transformDefaults,
    avatar,
    clock,
    canvas,
    resolvedBindingCache: new Map(),
    animationFrameId: 0,
    modelHeight: Math.max(size.y, 0.1),
    modelWidth: Math.max(size.x, 0.1),
    directBlendShapes: new Map(),
    heldBones: new Map(),
    poseHoldTimer: 0,
    boneTransitionSpeeds: new Map(),
    boneCurrentRotations: new Map(),
    boneTargetRotations: new Map(),
  };

  fitVRMModel(runtime);

  const animate = () => {
    const dt = runtime.clock.getDelta();

    runtime.animation.update(dt);
    runtime.lipSync.update(dt);

    const em = runtime.vrm.expressionManager;
    if (runtime.trackedBlendShapeNames.size > 0 && em) {
      for (const name of runtime.trackedBlendShapeNames) {
        const baseline = runtime.baselineValues.get(name) ?? 0;
        const hasExplicitTarget = runtime.overlayTargetValues.has(name);
        const target = runtime.overlayTargetValues.get(name) ?? baseline;
        const current = runtime.overlayCurrentValues.get(name) ?? baseline;
        const next = easeTowards(current, target, getOverlayFactor(name, hasExplicitTarget));
        runtime.overlayCurrentValues.set(name, next);
        em.setValue(name as keyof typeof VRMExpressionPresetName, next);
      }
    }

    if (runtime.directBlendShapes.size > 0) {
      const em = runtime.vrm.expressionManager;
      if (em) {
        for (const [name, weight] of runtime.directBlendShapes) {
          em.setValue(name as keyof typeof VRMExpressionPresetName, weight);
        }
      }
    }

    if (runtime.poseHoldTimer > 0) {
      runtime.poseHoldTimer -= dt;
      if (runtime.poseHoldTimer <= 0) {
        runtime.poseHoldTimer = 0;
        releasePose(runtime);
      }
    }

    if (runtime.boneTargetRotations.size > 0) {
      const humanoid = runtime.vrm.humanoid;
      if (humanoid) {
        for (const [boneName, target] of runtime.boneTargetRotations) {
          const bone = humanoid.getNormalizedBoneNode(boneName as never);
          if (!bone) continue;

          const speed = runtime.boneTransitionSpeeds.get(boneName) ?? 1.0;
          const current = runtime.boneCurrentRotations.get(boneName) ?? { x: bone.rotation.x, y: bone.rotation.y, z: bone.rotation.z };

          const factor = Math.min(1, speed * dt * 5);
          const next = {
            x: current.x + (target.x - current.x) * factor,
            y: current.y + (target.y - current.y) * factor,
            z: current.z + (target.z - current.z) * factor,
          };

          runtime.boneCurrentRotations.set(boneName, next);
          bone.rotation.x = next.x;
          bone.rotation.y = next.y;
          bone.rotation.z = next.z;
        }
      }
    }

    runtime.vrm.update(dt);
    runtime.renderer.render(runtime.scene, runtime.camera);
    runtime.animationFrameId = requestAnimationFrame(animate);
  };

  runtime.animationFrameId = requestAnimationFrame(animate);
  return runtime;
}

export function setBlendShapes(runtime: VRMRuntimeState, entries: Array<{ name: string; weight: number }>): void {
  for (const entry of entries) {
    runtime.directBlendShapes.set(entry.name, Math.min(Math.max(entry.weight, 0), 1));
  }
}

export function setBoneRotations(runtime: VRMRuntimeState, entries: Array<{ boneName: string; rotation: { x: number; y: number; z: number }; speed?: number }>): void {
  for (const entry of entries) {
    runtime.boneTargetRotations.set(entry.boneName, entry.rotation);
    runtime.boneTransitionSpeeds.set(entry.boneName, entry.speed ?? 1.0);
    if (!runtime.boneCurrentRotations.has(entry.boneName)) {
      const humanoid = runtime.vrm.humanoid;
      if (humanoid) {
        const bone = humanoid.getNormalizedBoneNode(entry.boneName as never);
        if (bone) {
          runtime.boneCurrentRotations.set(entry.boneName, { x: bone.rotation.x, y: bone.rotation.y, z: bone.rotation.z });
          continue;
        }
      }
      runtime.boneCurrentRotations.set(entry.boneName, { x: 0, y: 0, z: 0 });
    }
  }
}

export function holdPose(runtime: VRMRuntimeState, durationMs?: number): void {
  for (const [boneName, target] of runtime.boneTargetRotations) {
    runtime.heldBones.set(boneName, { ...target });
  }
  runtime.poseHoldTimer = (durationMs ?? 3000) / 1000;
}

export function releasePose(runtime: VRMRuntimeState): void {
  runtime.heldBones.clear();
  runtime.poseHoldTimer = 0;
  runtime.directBlendShapes.clear();
  for (const boneName of runtime.boneTargetRotations.keys()) {
    runtime.boneTargetRotations.set(boneName, { x: 0, y: 0, z: 0 });
    runtime.boneTransitionSpeeds.set(boneName, 3.3);
  }
}

export async function applyExpressionMix(
  runtime: VRMRuntimeState,
  avatar: AvatarManifest,
  expressionMix: ExpressionLayer[],
): Promise<void> {
  runtime.activeExpressionMix = expressionMix;
  await applyRuntimeState(runtime, avatar);
}

export async function setParameterOverrides(
  runtime: VRMRuntimeState,
  avatar: AvatarManifest,
  parameterOverrides: ParameterOverride[],
): Promise<void> {
  runtime.parameterOverrides = parameterOverrides;
  await applyRuntimeState(runtime, avatar);
}

async function applyRuntimeState(runtime: VRMRuntimeState, avatar: AvatarManifest): Promise<void> {
  if (runtime.activeExpressionMix.length === 0 && runtime.parameterOverrides.length === 0) {
    runtime.overlayTargetValues = new Map();
    return;
  }

  const mixedValues = await buildMixedBlendShapes(
    runtime,
    avatar,
    runtime.activeExpressionMix,
    runtime.parameterOverrides,
  );

  if (mixedValues.size === 0) {
    runtime.overlayTargetValues = new Map();
    return;
  }

  runtime.overlayTargetValues = mixedValues;
}

export function resizeRuntime(runtime: VRMRuntimeState, canvas: HTMLCanvasElement): void {
  runtime.canvas = canvas;
  fitVRMModel(runtime);
}

export function updateStageTransform(runtime: VRMRuntimeState, transform: StageTransform): void {
  fitVRMModel(runtime, transform);
}

export function destroyRuntime(runtime: VRMRuntimeState): void {
  cancelAnimationFrame(runtime.animationFrameId);
  runtime.scene.remove(runtime.vrm.scene);

  const vrmWithDispose = runtime.vrm as unknown as { dispose?: () => void };
  if (typeof vrmWithDispose.dispose === 'function') {
    vrmWithDispose.dispose();
  } else {
    runtime.vrm.scene.traverse((o) => {
      const mesh = o as THREE.Mesh;
      if (mesh.geometry) mesh.geometry.dispose();
      const mat = mesh.material;
      if (mat) {
        if (Array.isArray(mat)) {
          mat.forEach((m) => m.dispose());
        } else {
          mat.dispose();
        }
      }
    });
  }

  runtime.renderer.dispose();
  runtime.animation.reset();
  runtime.lipSync.reset();
  runtime.trackedBlendShapeNames.clear();
  runtime.overlayCurrentValues.clear();
  runtime.overlayTargetValues.clear();
  runtime.baselineValues.clear();
  runtime.resolvedBindingCache.clear();
  runtime.directBlendShapes.clear();
  runtime.heldBones.clear();
  runtime.boneTransitionSpeeds.clear();
  runtime.boneCurrentRotations.clear();
  runtime.boneTargetRotations.clear();
  runtime.activeExpressionMix = [];
  runtime.parameterOverrides = [];
}
