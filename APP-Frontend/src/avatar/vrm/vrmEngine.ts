/**
 * VRM 运行时引擎：Three.js 场景/相机/渲染器 + 渲染循环。
 *
 * 行为口径对齐 CX-O-Frontend components/business/vrm/vrm-engine.ts：
 * - 表情混合（expressionMix / parameterOverrides）经 overlay 层平滑过渡到 BlendShape
 * - 直接 BlendShape（标签 [blend:]）与骨骼旋转（标签 [bone:]）逐帧插值
 * - 姿态保持（holdPose/releasePose）计时管理
 * - 模型自适应取景（包围盒 + transform）
 *
 * 与参考实现的差异：渲染循环不在 createVRMRuntime 内启动，
 * 由 startRuntimeLoop 显式启动并接受 onFrame 回调（查看器注入驱动/视线/口型更新），
 * 避免参考实现中"先启动再取消再替换"的双重循环竞争。
 */
import * as THREE from 'three';
import { VRM, VRMExpressionPresetName } from '@pixiv/three-vrm';
import type {
  AvatarManifest,
  AvatarExpression,
  ExpressionBinding,
  ExpressionLayer,
  ParameterOverride,
  StageTransform,
} from '../types';
import { VRMAnimation } from './vrmAnimation';
import { VRMLipSync } from './vrmLipSync';
import { BlendShapeInterpolator } from './vrmBlendShapeInterpolator';

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
  canvas: HTMLCanvasElement;
  resolvedBindingCache: Map<string, ResolvedBinding>;
  animationFrameId: number;
  modelHeight: number;
  modelWidth: number;
  baseModelHeight: number;
  baseModelWidth: number;
  blendInterpolator: BlendShapeInterpolator;
  springBoneEveryOtherFrame: boolean;
  heldBones: Map<string, { x: number; y: number; z: number }>;
  poseHoldTimer: number;
  boneTransitionSpeeds: Map<string, number>;
  boneCurrentRotations: Map<string, { x: number; y: number; z: number }>;
  boneTargetRotations: Map<string, { x: number; y: number; z: number }>;
  /** 骨骼自动归中计时器：boneName → 剩余保持秒；<=0 时对应该骨骼目标归零回待机 */
  boneHoldTimers: Map<string, number>;
  /**
   * 刘海骨骼（短前发链）引用。springbone 物理会把刘海推到前倾翻起，
   * 渲染循环在物理解算后对这批骨骼的 rotation.x 完全锁死为 0，
   * 禁止前后翻起、仅保留侧向（y/z）摆动。
   */
  bangBones: THREE.Object3D[];
  /** 刘海 rotation.x 钳制上限（弧度），默认 0（完全锁死） */
  bangXClamp?: number;
  cameraTweak?: {
    offsetX: number;
    offsetY: number;
    offsetZ: number;
    lookAtY: number;
  };
};

type BlendShapeName = keyof typeof VRMExpressionPresetName;

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
    const value = em.getValue(blendShapeName as BlendShapeName);
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

  // 取景：高度优先，窄画布按宽度兜底，下限 0.5 防极小模型贴脸。
  // 模型始终"填满视口"（距离完全跟随缩放后尺寸）→ 任何缩放都不会裁切。
  // 缩放对屏幕大小的影响由调用方负责：随 scale 同步放大桌宠窗，窗口变大→模型
  // 更大且完整可见；若窗口固定而仅改场景 scale，会因本取景把模型重新配平到视口，
  // 导致屏幕大小不变（见 PetPage 的窗口随 scale 缩放逻辑）。
  const halfFovTan = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
  const distForHeight = (modelHeight / 2 / halfFovTan) * 1.12;
  const distForWidth = (modelWidth / 2 / (halfFovTan * camera.aspect)) * 1.12;
  const dist = Math.max(distForHeight, distForWidth, 0.5);

  const cameraTweak = runtime.cameraTweak;
  camera.position.set(
    cameraTweak?.offsetX ?? 0,
    modelHeight * 0.5 + (cameraTweak?.offsetY ?? 0),
    dist + (cameraTweak?.offsetZ ?? 0),
  );
  camera.lookAt(
    0,
    modelHeight * 0.5 + (cameraTweak?.lookAtY ?? 0),
    0,
  );

  runtime.modelHeight = modelHeight;
  runtime.modelWidth = modelWidth;
  runtime.currentTransform = nextTransform;
}

export function createVRMRuntime(
  canvas: HTMLCanvasElement,
  avatar: AvatarManifest,
  vrm: VRM,
  cameraTweak?: VRMRuntimeState['cameraTweak'],
): VRMRuntimeState {
  const width = canvas.clientWidth || 300;
  const height = canvas.clientHeight || 400;

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(28, width / height, 0.1, 20);

  const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
  renderer.setPixelRatio(window.devicePixelRatio);
  renderer.setSize(width, height, false);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  // VRM MToon 材质对 ACESFilmic 会压暗暗部并压扁二次元色阶；改用 LinearToneMapping + 适度曝光
  renderer.toneMapping = THREE.LinearToneMapping;
  renderer.toneMappingExposure = 1.25;

  // 光照：通透二次元动漫光照（主光纯白 + 充裕半球漫射 + 暖点光）
  const dirLight = new THREE.DirectionalLight(0xffffff, 1.6);
  dirLight.position.set(1.5, 2.5, 2);
  scene.add(dirLight);
  scene.add(new THREE.HemisphereLight(0xffffff, 0xc0c0c0, 1.2));
  const pointLight = new THREE.PointLight(0xffecd9, 0.6, 10);
  pointLight.position.set(-1.5, 1.2, 2);
  scene.add(pointLight);

  const animation = new VRMAnimation();
  animation.bindVRM(vrm);

  const lipSync = new VRMLipSync();
  lipSync.bindVRM(vrm);

  scene.add(vrm.scene);

  const box = new THREE.Box3().setFromObject(vrm.scene);
  const size = box.getSize(new THREE.Vector3());

  // 刘海（短前发链）处理：CX.vrm/avatar.vrm 的刘海骨骼 J_Sec_Hair1_* 挂在 head 下，
  // springbone 物理会把刘海推到前倾翻起（模型本身绑定姿态并不翻起）。
  // 根治方案：把刘海 joint 从 springbone 物理中移除（deleteJoint），物理不再作用于刘海，
  // 刘海保持模型绑定姿态；渲染循环再对 bangBones 做 rotation.x 锁轴双重保障。
  const bangBones: THREE.Object3D[] = [];
  const manager = vrm.springBoneManager;
  if (manager) {
    const rawJoints = (manager as unknown as { joints?: unknown }).joints
      ?? (manager as unknown as { _joints?: unknown })._joints;
    const joints: Array<{ bone: THREE.Object3D; settings?: unknown }> = Array.isArray(rawJoints)
      ? rawJoints
      : rawJoints instanceof Set
        ? Array.from(rawJoints)
        : [];
    const seen = new Set<THREE.Object3D>();
    for (const joint of joints) {
      const name = joint.bone?.name ?? '';
      if (/hair1/i.test(name)) {
        if (!seen.has(joint.bone)) {
          seen.add(joint.bone);
          bangBones.push(joint.bone);
        }
        // 从 springbone 物理移除刘海 joint：物理不再推翻刘海，保持绑定姿态。
        try {
          if (typeof manager.deleteJoint === 'function') {
            manager.deleteJoint(joint as never);
          } else if (rawJoints instanceof Set) {
            rawJoints.delete(joint as never);
          }
        } catch {
          // 忽略删除失败（不影响主流程）
        }
      }
    }
  }

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
    canvas,
    resolvedBindingCache: new Map(),
    animationFrameId: 0,
    modelHeight: Math.max(size.y, 0.1),
    modelWidth: Math.max(size.x, 0.1),
    baseModelHeight: Math.max(size.y, 0.1),
    baseModelWidth: Math.max(size.x, 0.1),
    blendInterpolator: new BlendShapeInterpolator(),
    springBoneEveryOtherFrame: false,
    heldBones: new Map(),
    poseHoldTimer: 0,
    boneTransitionSpeeds: new Map(),
    boneCurrentRotations: new Map(),
    boneTargetRotations: new Map(),
    boneHoldTimers: new Map(),
    bangBones,
    cameraTweak,
  };

  fitVRMModel(runtime);
  return runtime;
}

/**
 * 启动渲染循环。onFrame 在每帧引擎更新前调用（查看器注入驱动/视线/口型更新）。
 * dt 上限钳制 0.1s，防止窗口最小化恢复后动画跳变。
 */
export function startRuntimeLoop(
  runtime: VRMRuntimeState,
  onFrame?: (dt: number) => void,
): void {
  // 幂等守卫：重入时先取消旧 RAF 循环再启动，避免双循环并行
  //（destroy 只取消最后一条 animationFrameId，旧循环会泄漏并持续渲染）
  if (runtime.animationFrameId !== 0) {
    cancelAnimationFrame(runtime.animationFrameId);
    runtime.animationFrameId = 0;
  }
  const clock = new THREE.Timer();
  let frameCount = 0;

  const animate = () => {
    clock.update();
    const rawDt = clock.getDelta();
    const dt = Math.min(rawDt, 0.1);

    // ============ 分层管线 L0→L3 ============
    // L0 物理：spring bone / 骨骼物理解算须在一切骨骼/BlendShape 写入之前执行，
    //          保证后续各层写入建立在最新物理姿态之上。render 仍保留在循环末尾。
    if (runtime.springBoneEveryOtherFrame) {
      frameCount += 1;
      if (frameCount % 2 === 1) {
        runtime.vrm.update(dt);
      }
    } else {
      runtime.vrm.update(dt);
    }

    // 刘海锁轴：springbone 物理解算后会重写刘海骨骼 rotation，这里把 rotation.x
    // （前后俯仰）完全锁死为 0，彻底禁止刘海向上翻起；y/z（侧向摆动）保留自由。
    // 刘海定义见 createVRMRuntime 的 bangBones 收集（J_Sec_Hair1_* 短前发链）。
    if (runtime.bangBones.length > 0) {
      const clampX = runtime.bangXClamp ?? 0;
      for (const bone of runtime.bangBones) {
        if (bone.rotation.x > clampX) bone.rotation.x = clampX;
        else if (bone.rotation.x < -clampX) bone.rotation.x = -clampX;
      }
    }

    // L1 程序化：骨骼动画 + 口型同步（程序化动画源，与用户指令解耦）
    runtime.animation.update(dt);
    runtime.lipSync.update(dt);

    // L2 指令：查看器注入的 driver.update（视线/驱动/口型指令，写入 target 值）
    onFrame?.(dt);

    // L3 平滑：把各写入源（overlay 表情 + 直接 BlendShape 插值器 + 姿态保持 + 骨骼插值）
    //          指数平滑收敛到表情/骨骼，避免指令瞬时跳变。
    const em = runtime.vrm.expressionManager;
    if (runtime.trackedBlendShapeNames.size > 0 && em) {
      for (const name of runtime.trackedBlendShapeNames) {
        const baseline = runtime.baselineValues.get(name) ?? 0;
        const hasExplicitTarget = runtime.overlayTargetValues.has(name);
        const target = runtime.overlayTargetValues.get(name) ?? baseline;
        const current = runtime.overlayCurrentValues.get(name) ?? baseline;
        const next = easeTowards(current, target, getOverlayFactor(name, hasExplicitTarget));
        runtime.overlayCurrentValues.set(name, next);
        em.setValue(name as BlendShapeName, next);
      }
    }

    // 直接 BlendShape（驱动指令经 setExpression 写入）走插值器平滑
    runtime.blendInterpolator.update(dt, runtime.vrm);

    if (runtime.poseHoldTimer > 0) {
      runtime.poseHoldTimer -= dt;
      if (runtime.poseHoldTimer <= 0) {
        runtime.poseHoldTimer = 0;
        releasePose(runtime);
      }
    }

    if (runtime.boneHoldTimers.size > 0) {
      for (const [boneName, remain] of runtime.boneHoldTimers) {
        const next = remain - dt;
        if (next <= 0) {
          // 保持到期 → 该骨骼目标归零，让插值器平滑回到待机；并移除计时器
          runtime.boneHoldTimers.delete(boneName);
          runtime.boneTargetRotations.set(boneName, { x: 0, y: 0, z: 0 });
          runtime.boneTransitionSpeeds.set(boneName, 3.3);
        } else {
          runtime.boneHoldTimers.set(boneName, next);
        }
      }
    }

    if (runtime.boneTargetRotations.size > 0) {
      const humanoid = runtime.vrm.humanoid;
      if (humanoid) {
        for (const [boneName, target] of runtime.boneTargetRotations) {
          const bone = humanoid.getNormalizedBoneNode(boneName as never);
          if (!bone) continue;

          const speed = runtime.boneTransitionSpeeds.get(boneName) ?? 1.0;
          const current = runtime.boneCurrentRotations.get(boneName) ?? {
            x: bone.rotation.x,
            y: bone.rotation.y,
            z: bone.rotation.z,
          };

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

    // render 始终在最后（L0 已负责 vrm.update 物理解算）
    runtime.renderer.render(runtime.scene, runtime.camera);
    runtime.animationFrameId = requestAnimationFrame(animate);
  };

  runtime.animationFrameId = requestAnimationFrame(animate);
}

export function setBlendShapes(
  runtime: VRMRuntimeState,
  entries: Array<{ name: string; weight: number }>,
): void {
  // entries 视为"当前活跃直接表情集"：先逐条写入目标权重，再调用
  // fadeOutUnusedExpressions 把不在当次批次的旧直接表情目标置 0，
  // 由插值器的后续 update 平滑归零，避免切换表情时残留上一批次的权重。
  for (const entry of entries) {
    runtime.blendInterpolator.setExpression(entry.name, entry.weight);
  }
  runtime.blendInterpolator.fadeOutUnusedExpressions(entries.map((e) => e.name));
}

export function setBoneRotations(
  runtime: VRMRuntimeState,
  entries: Array<{
    boneName: string;
    rotation: { x: number; y: number; z: number };
    speed?: number;
    /** 保持时长 ms；省略用引擎默认（3s）后自动归中；0 表示不自动归中 */
    holdMs?: number;
  }>,
): void {
  // 骨骼自动归中默认保持时长（秒）
  const DEFAULT_BONE_HOLD_SEC = 3;

  // 真相源 = manifest 填充的运行时副本，勿直读 catalog 常量。
  const controls = runtime.avatar.boneControls ?? [];
  const controlsByName = new Map(controls.map((c) => [c.id.toLowerCase(), c]));

  for (const entry of entries) {
    const control = controlsByName.get(entry.boneName.toLowerCase());
    // 白名单过滤：目录中找不到大小写不敏感匹配的骨骼直接跳过
    if (!control) {
      continue;
    }

    // 按骨骼限幅：rotationRange 缺失时保持原值
    let rotation = entry.rotation;
    const range = control.rotationRange;
    if (range) {
      rotation = {
        x: Math.min(range.x[1], Math.max(range.x[0], entry.rotation.x)),
        y: Math.min(range.y[1], Math.max(range.y[0], entry.rotation.y)),
        z: Math.min(range.z[1], Math.max(range.z[0], entry.rotation.z)),
      };
    }

    runtime.boneTargetRotations.set(entry.boneName, rotation);
    runtime.boneTransitionSpeeds.set(entry.boneName, entry.speed ?? 1.0);
    // 自动归中：holdMs>0 → 设保持计时；holdMs=0 → 清除计时（保持不归中）；
    // holdMs 省略 → 用默认 3s。
    if (entry.holdMs === 0) {
      runtime.boneHoldTimers.delete(entry.boneName);
    } else {
      runtime.boneHoldTimers.set(
        entry.boneName,
        (entry.holdMs ?? DEFAULT_BONE_HOLD_SEC * 1000) / 1000,
      );
    }
    if (!runtime.boneCurrentRotations.has(entry.boneName)) {
      const humanoid = runtime.vrm.humanoid;
      if (humanoid) {
        const bone = humanoid.getNormalizedBoneNode(entry.boneName as never);
        if (bone) {
          runtime.boneCurrentRotations.set(entry.boneName, {
            x: bone.rotation.x,
            y: bone.rotation.y,
            z: bone.rotation.z,
          });
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
  runtime.boneHoldTimers.clear();
  runtime.blendInterpolator.reset();
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
  runtime.blendInterpolator.reset();
  runtime.heldBones.clear();
  runtime.boneHoldTimers.clear();
  runtime.boneTransitionSpeeds.clear();
  runtime.boneCurrentRotations.clear();
  runtime.boneTargetRotations.clear();
  runtime.activeExpressionMix = [];
  runtime.parameterOverrides = [];
}
