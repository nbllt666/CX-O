import { useEffect, useRef, useState, useCallback } from 'react';
import * as THREE from 'three';
import { VRM, VRMLoaderPlugin, VRMExpressionPresetName } from '@pixiv/three-vrm';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMTweakConfig, DEFAULT_VRM_TWEAK, AnimationSettings, DEFAULT_ANIMATION_SETTINGS, VRMWindConfig } from '../../store/settingsStore';
import { VRMLipSync } from './VRMLipSync';
import { VRMExpression } from './VRMExpression';
import { VRMAnimation } from './VRMAnimation';
import { VRMMotionTrigger } from './VRMMotionTrigger';
import { VRMWindField } from './VRMWindField';
import { VowelAnalyzer } from './VowelAnalyzer';
import { createVRMRuntime, destroyRuntime, resizeRuntime, applyExpressionMix, setParameterOverrides, type VRMRuntimeState } from './VRMEngine';
import type { IAvatarDriver } from '../Avatar/AvatarDriver';
import { VRMDriver } from '../Avatar/AvatarDriver';
import type { ExpressionLayer, ParameterOverride, AvatarManifest } from '../Avatar/avatarManifest';
import { resolveAvatarManifest } from '../Avatar/avatarManifest';

export type { VRMTweakConfig };
export { DEFAULT_VRM_TWEAK as DEFAULT_TWEAK_CONFIG };

interface VRMViewerProps {
  modelPath: string;
  modelDataRef: React.RefObject<ArrayBuffer | undefined>;
  dataVersion: number;
  scale?: number;
  position?: [number, number, number];
  lipSyncEnabled?: boolean;
  lookAtMouse?: boolean;
  mouthOpenY?: number;
  onModelLoaded?: () => void;
  onError?: (error: Error) => void;
  tweakConfig?: Partial<VRMTweakConfig>;
  animationConfig?: Partial<AnimationSettings>;
  renderScale?: number;
  devicePixelRatio?: number | 'auto';
  idleAnimation?: boolean;
  windConfig?: VRMWindConfig;
  driver?: IAvatarDriver;
  expressionMix?: ExpressionLayer[];
  parameterOverrides?: ParameterOverride[];
  avatar?: AvatarManifest;
}

export function VRMViewer({
  modelPath,
  modelDataRef,
  dataVersion,
  scale = 1.0,
  position = [0, 0, 0],
  lipSyncEnabled = true,
  lookAtMouse = true,
  mouthOpenY = 0,
  onModelLoaded,
  onError,
  tweakConfig,
  animationConfig,
  renderScale = 1.0,
  devicePixelRatio = 'auto',
  idleAnimation = true,
  windConfig,
  driver,
  expressionMix,
  parameterOverrides,
  avatar,
}: VRMViewerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const runtimeRef = useRef<VRMRuntimeState | null>(null);
  const vrmRef = useRef<VRM | null>(null);
  const clockRef = useRef(new THREE.Timer());
  const smoothLookAtRef = useRef(new THREE.Vector3(0, 1.5, 1.5));
  const mouseTargetRef = useRef(new THREE.Vector3(0, 1.5, 1.5));
  const lookAtMouseRef = useRef(lookAtMouse);
  lookAtMouseRef.current = lookAtMouse;
  const lipSyncRef = useRef<VRMLipSync | null>(null);
  const expressionRef = useRef<VRMExpression | null>(null);
  const animationRef = useRef<VRMAnimation | null>(null);
  const motionTriggerRef = useRef<VRMMotionTrigger | null>(null);
  const windFieldRef = useRef<VRMWindField | null>(null);
  const vowelAnalyzerRef = useRef<VowelAnalyzer | null>(null);
  const animationFrameRef = useRef<number | null>(null);

  const dirLightRef = useRef<THREE.DirectionalLight | null>(null);
  const ambLightRef = useRef<THREE.AmbientLight | null>(null);
  const pntLightRef = useRef<THREE.PointLight | null>(null);

  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const propsRef = useRef({ scale, position, onModelLoaded, onError, renderScale, devicePixelRatio });
  // 直接在渲染时更新 ref，确保 loadModel 和动画循环能获取最新值
  propsRef.current.scale = scale;
  propsRef.current.position = position;
  propsRef.current.renderScale = renderScale;
  propsRef.current.devicePixelRatio = devicePixelRatio;
  const idleAnimRef = useRef(idleAnimation);
  useEffect(() => { idleAnimRef.current = idleAnimation; }, [idleAnimation]);
  const lastVersionRef = useRef(-1);
  const renderIdRef = useRef(0);

  const effectiveTweak = useRef<Partial<VRMTweakConfig>>(tweakConfig || {});
  effectiveTweak.current = tweakConfig || {};
  const tc: VRMTweakConfig = { ...DEFAULT_VRM_TWEAK, ...tweakConfig };
  const tcRef = useRef<VRMTweakConfig>(tc);
  tcRef.current = tc;

  const ac: AnimationSettings = { ...DEFAULT_ANIMATION_SETTINGS, ...animationConfig };
  const acRef = useRef<AnimationSettings>(ac);
  // 直接在渲染时更新 ref，确保 loadModel 能获取最新值
  acRef.current = ac;

  useEffect(() => {
    if (dataVersion === lastVersionRef.current) return;
    lastVersionRef.current = dataVersion;
    const myRenderId = ++renderIdRef.current;

    const loadModel = async () => {
      const data = modelDataRef?.current;
      const useBuf = data && data.byteLength > 0;
      const usePath = !useBuf && modelPath?.length;

      if (!useBuf && !usePath) { setLoadError('MODEL_NOT_CONFIGURED'); setIsLoading(false); return; }

      let url: string | null = null;
      let blobUrl: string | null = null;

      if (useBuf) {
        url = URL.createObjectURL(new Blob([data], { type: 'application/octet-stream' }));
        blobUrl = url;
      } else if (usePath) {
        // 使用 fetch 加载模型，绕过 MIME 类型问题
        try {
          const response = await fetch(modelPath);
          if (!response.ok) throw new Error(`Failed to fetch model: ${response.status}`);
          const arrayBuffer = await response.arrayBuffer();
          url = URL.createObjectURL(new Blob([arrayBuffer], { type: 'application/octet-stream' }));
          blobUrl = url;
        } catch (fetchError) {
          setLoadError(`MODEL_FETCH_FAILED: ${fetchError}`);
          setIsLoading(false);
          return;
        }
      }

      if (!url) return;

      try {
        setIsLoading(true); setLoadError(null);

        if (runtimeRef.current) {
          destroyRuntime(runtimeRef.current);
          runtimeRef.current = null;
        }

        const canvas = await waitForCanvas();

        const loader = new GLTFLoader(); loader.register((p) => new VRMLoaderPlugin(p));
        const gltf = await loader.loadAsync(url);

        if (renderIdRef.current !== myRenderId) return;

        const vrm = gltf.userData.vrm as VRM;
        if (!vrm) throw new Error('Not a VRM model');

        vrmRef.current = vrm;
        // 统一通过 applyTransform 设置 scale/position/rotation（在模型加载完成后由 useEffect 触发）
        const tcLatest = tcRef.current;
        vrm.scene.rotation.x = tcLatest.modelRotationX; vrm.scene.rotation.y = tcLatest.modelRotationY; vrm.scene.rotation.z = tcLatest.modelRotationZ;

        const humanoid = vrm.humanoid;
        if (humanoid) {
          const setRot = (name: string, x: number, y: number, z: number) => {
            const bone = humanoid.getNormalizedBoneNode(name as never);
            if (bone) bone.rotation.set(x, y, z);
          };
          setRot('leftUpperArm', 0, 0, 1.2);
          setRot('rightUpperArm', 0, 0, -1.2);
          setRot('leftLowerArm', 0, -0.2, 0.1);
          setRot('rightLowerArm', 0, 0.2, -0.1);
          setRot('leftUpperLeg', 0.05, 0, 0.05);
          setRot('rightUpperLeg', 0.05, 0, -0.05);
          setRot('leftLowerLeg', -0.05, 0, 0);
          setRot('rightLowerLeg', -0.05, 0, 0);
          setRot('spine', 0, 0, 0);
          setRot('chest', 0, 0, 0);
        }

        let resolvedAvatar = avatar;
        if (!resolvedAvatar) {
          const availableBlendShapes = vrm.expressionManager
            ? Object.values(VRMExpressionPresetName).filter(
                (name) => (vrm.expressionManager!.getValue(name as keyof typeof VRMExpressionPresetName)) !== undefined
              )
            : [];
          const availableBones = humanoid
            ? Array.from({ length: 100 }, (_, i) => {
                try {
                  const boneNames = ['hips', 'spine', 'chest', 'upperChest', 'neck', 'head',
                    'leftShoulder', 'rightShoulder', 'leftUpperArm', 'rightUpperArm',
                    'leftLowerArm', 'rightLowerArm', 'leftHand', 'rightHand',
                    'leftUpperLeg', 'rightUpperLeg', 'leftLowerLeg', 'rightLowerLeg'];
                  return boneNames[i] ?? '';
                } catch { return ''; }
              }).filter(Boolean)
            : [];

          resolvedAvatar = {
            id: 'vrm-dynamic',
            name: 'VRM Model',
            summary: 'Dynamically loaded VRM model',
            persona: { tone: '', traits: [], styleRules: [] },
            modelJson: '',
            scaleMultiplier: 1,
            verticalOffset: 0,
            modelTransform: { scale: scale, offsetX: position[0], offsetY: position[1] },
            transformDefaults: { scale: 1, offsetX: 0, offsetY: 0 },
            expressions: [],
            parameterControls: [],
            avatarType: 'vrm',
          };

          try {
            resolvedAvatar = await resolveAvatarManifest(resolvedAvatar, {
              blendShapes: availableBlendShapes,
              bones: availableBones,
            });
          } catch { /* resolution optional */ }
        }

        if (driver && resolvedAvatar) {
          const runtime = createVRMRuntime(canvas, resolvedAvatar, vrm);
          runtimeRef.current = runtime;
          (driver as VRMDriver).bindRuntime(runtime);
        } else {
          const runtime = createVRMRuntime(canvas, resolvedAvatar!, vrm);
          runtimeRef.current = runtime;
        }

        // fitVRMModel 已在 createVRMRuntime 中调用，基准位置由 applyTransform 重新计算
        const scene = runtimeRef.current!.scene;
        const cam = runtimeRef.current!.camera;
        const renderer = runtimeRef.current!.renderer;

        dirLightRef.current = scene.children.find((c): c is THREE.DirectionalLight => c instanceof THREE.DirectionalLight) ?? null;
        ambLightRef.current = scene.children.find((c): c is THREE.AmbientLight => c instanceof THREE.AmbientLight) ?? null;
        pntLightRef.current = scene.children.find((c): c is THREE.PointLight => c instanceof THREE.PointLight) ?? null;

        // 立即应用光照 tweak（修复：初始挂载时 L483 useEffect 在 ref 赋值前执行，导致 tweak 不生效）
        // 使用 tcRef.current 获取最新 tweak 值（避免闭包捕获旧值）
        const initTweak = tcRef.current;
        if (dirLightRef.current) dirLightRef.current.intensity = initTweak.light.directionalIntensity;
        if (ambLightRef.current) ambLightRef.current.intensity = initTweak.light.ambientIntensity;
        if (pntLightRef.current) pntLightRef.current.intensity = initTweak.light.pointIntensity;

        lipSyncRef.current = runtimeRef.current!.lipSync;
        const acLatest = acRef.current;
        lipSyncRef.current.setSmoothing(acLatest.lipSyncSmoothing);

        expressionRef.current = new VRMExpression();
        expressionRef.current.bindVRM(vrm);
        expressionRef.current.setConfig({
          intensity: acLatest.emotionIntensity,
          duration: acLatest.emotionDuration,
          recoverSpeed: acLatest.emotionRecoverSpeed,
          idleExpressionIntensity: acLatest.idleExpressionIntensity,
        });

        animationRef.current = runtimeRef.current!.animation;
        animationRef.current.setConfig({
          breathFrequency: acLatest.breathFrequency,
          breathAmplitude: acLatest.breathAmplitude,
          breathIrregularity: acLatest.breathIrregularity,
          blinkInterval: acLatest.blinkInterval,
          blinkDuration: acLatest.blinkDuration,
          swayAmplitude: acLatest.swayAmplitude,
          swayFrequency: acLatest.swayFrequency,
          swayIrregularity: acLatest.swayIrregularity,
          headFollowSpeed: acLatest.headFollowSpeed,
          bodyFollowDelay: acLatest.bodyFollowDelay,
          headIdleRange: acLatest.headIdleRange,
          headTrackingLimit: acLatest.headTrackingLimit,
        });

        if (vrm.lookAt) {
          // 禁用 VRM 的自动 lookAt target 跟踪，改为手动设置 yaw/pitch
          // 避免 target 系统在中线附近的不连续性（表情/骨骼切换导致跳变）
          vrm.lookAt.autoUpdate = false;
          if (!vrm.lookAt.target) {
            const lookAtTarget = new THREE.Object3D();
            lookAtTarget.position.set(0, 1.5, 1.5);
            runtimeRef.current!.scene.add(lookAtTarget);
            vrm.lookAt.target = lookAtTarget;
          }
        }

        windFieldRef.current = new VRMWindField();
        windFieldRef.current.bindVRM(vrm);
        if (windConfig) {
          windFieldRef.current.setWindParams(windConfig);
        }

        motionTriggerRef.current = new VRMMotionTrigger();
        motionTriggerRef.current.bindVRM(vrm);
        motionTriggerRef.current.setConfig({
          probability: acLatest.motionTriggerProbability,
          speechRhythmInterval: 1.5,
          transitionSpeed: acLatest.focusSpeed,
        });

        setIsLoading(false);
        propsRef.current.onModelLoaded?.();

        if (runtimeRef.current) {
          cancelAnimationFrame(runtimeRef.current.animationFrameId);
        }

        const animate = () => {
          if (renderIdRef.current !== myRenderId) return;
          clockRef.current.update();
          const rawDt = clockRef.current.getDelta();
          // 限制 dt 上限，防止窗口最小化后恢复导致动画异常（过大 dt 会让旋转插值瞬间完成）
          const dt = Math.min(rawDt, 0.1);

          // 头部追踪与眼球跟踪为两个正交独立开关：
          // - lookAtMouse（头部追踪）：控制头部跟随鼠标转动
          // - eyeTrackingEnabled（眼球跟踪）：控制眼球 yaw/pitch 跟随鼠标
          // 两者各自独立判断，关闭任一不影响另一个
          const mouseActive = lookAtMouseRef.current || acRef.current.eyeTrackingEnabled;
          if (mouseActive) {
            smoothLookAtRef.current.copy(mouseTargetRef.current);
            // 眼球跟踪分支：独立于头部追踪
            if (acRef.current.eyeTrackingEnabled && vrmRef.current?.lookAt) {
              const nx = smoothLookAtRef.current.x / 2;
              const ny = (smoothLookAtRef.current.y - 1.5) / 1.0;
              const maxYaw = 45;
              const maxPitch = 45;
              const targetYaw = Math.sign(nx) * Math.min(Math.abs(nx) ** 0.8, 1) * maxYaw;
              const targetPitch = -Math.sign(ny) * Math.min(Math.abs(ny) ** 0.8, 1) * maxPitch;
              const headRot = animationRef.current?.getHeadRotation();
              const headYawDeg = headRot ? headRot.y * (180 / Math.PI) : 0;
              const headPitchDeg = headRot ? headRot.x * (180 / Math.PI) : 0;
              vrmRef.current.lookAt.yaw = targetYaw + headYawDeg;
              vrmRef.current.lookAt.pitch = targetPitch + headPitchDeg;
            }
            // 头部追踪分支：独立于眼球跟踪
            if (lookAtMouseRef.current && animationRef.current) {
              animationRef.current.setHeadTarget(
                smoothLookAtRef.current.x,
                smoothLookAtRef.current.y,
                smoothLookAtRef.current.z
              );
            }
          }

          if (driver) (driver as VRMDriver).update(dt);
          if (lipSyncRef.current) lipSyncRef.current.update(dt);
          if (!driver && expressionRef.current) expressionRef.current.update(dt);
          if (idleAnimRef.current !== false && animationRef.current) animationRef.current.update(dt);
          if (!driver && motionTriggerRef.current) motionTriggerRef.current.update(dt);
          if (windFieldRef.current) windFieldRef.current.update(dt);

          if (vrmRef.current) vrmRef.current.update(dt);
          if (renderer && scene && cam) renderer.render(scene, cam);
          animationFrameRef.current = requestAnimationFrame(animate);
        };
        animate();
      } catch (err) {
        if (renderIdRef.current !== myRenderId) return;
        const msg = err instanceof Error ? err.message : '';
        if (msg.includes('<!doctype') || msg.includes('Unexpected token')) setLoadError('MODEL_FILE_NOT_FOUND');
        else setLoadError('LOAD_FAILED');
        setIsLoading(false);
        propsRef.current.onError?.(err instanceof Error ? err : new Error(String(err)));
      } finally { if (url.startsWith('blob:')) URL.revokeObjectURL(url); }
    };

    const waitForCanvas = (): Promise<HTMLCanvasElement> =>
      new Promise((resolve) => {
        let n = 0;
        const check = () => {
          const c = canvasRef.current;
          if (c && c.clientWidth > 0 && c.clientHeight > 0) resolve(c);
          else if (++n >= 200) resolve(c || document.createElement('canvas'));
          else requestAnimationFrame(check);
        };
        check();
      });

    loadModel();

    return () => {
      if (animationFrameRef.current) cancelAnimationFrame(animationFrameRef.current);
      if (windFieldRef.current) { windFieldRef.current.reset(); windFieldRef.current = null; }
      if (runtimeRef.current) {
        destroyRuntime(runtimeRef.current);
        runtimeRef.current = null;
      }
      if (vowelAnalyzerRef.current) { vowelAnalyzerRef.current.stop(); vowelAnalyzerRef.current = null; }
    };
  }, [dataVersion, modelPath]);

  // 当 animationConfig 变化时应用配置（模型加载后 animationRef.current 才存在）
  useEffect(() => {
    if (animationRef.current) {
      animationRef.current.setConfig({
        breathFrequency: ac.breathFrequency,
        breathAmplitude: ac.breathAmplitude,
        breathIrregularity: ac.breathIrregularity,
        blinkInterval: ac.blinkInterval,
        blinkDuration: ac.blinkDuration,
        swayAmplitude: ac.swayAmplitude,
        swayFrequency: ac.swayFrequency,
        swayIrregularity: ac.swayIrregularity,
        headFollowSpeed: ac.headFollowSpeed,
        bodyFollowDelay: ac.bodyFollowDelay,
        headIdleRange: ac.headIdleRange,
        headTrackingLimit: ac.headTrackingLimit,
      });
    }
    if (expressionRef.current) {
      expressionRef.current.setConfig({
        intensity: ac.emotionIntensity,
        duration: ac.emotionDuration,
        recoverSpeed: ac.emotionRecoverSpeed,
        idleExpressionIntensity: ac.idleExpressionIntensity,
      });
    }
    if (lipSyncRef.current) {
      lipSyncRef.current.setSmoothing(ac.lipSyncSmoothing);
    }
    if (motionTriggerRef.current) {
      motionTriggerRef.current.setConfig({
        probability: ac.motionTriggerProbability,
        speechRhythmInterval: 1.5,
        transitionSpeed: ac.focusSpeed,
      });
    }
  }, [animationConfig]);

  // 统一的变换应用函数：设置 scale/rotation/position，并根据 tc.camera 调整相机（不随 canvas 尺寸缩放）
  const applyTransform = useCallback(() => {
    if (!vrmRef.current || !runtimeRef.current) return;
    const vrm = vrmRef.current;
    const cam = runtimeRef.current.camera;
    const pos = propsRef.current.position;
    const tcLatest = tcRef.current;

    // 1. 先重置 position 到原点，确保包围盒计算不受历史 position 残留影响（避免位置/角度跳变）
    vrm.scene.position.set(0, 0, 0);
    // 2. 设置用户 scale 和 rotation
    vrm.scene.scale.setScalar(propsRef.current.scale);
    vrm.scene.rotation.x = tcLatest.modelRotationX;
    vrm.scene.rotation.y = tcLatest.modelRotationY;
    vrm.scene.rotation.z = tcLatest.modelRotationZ;
    vrm.scene.updateMatrixWorld(true);

    // 3. 重新计算包围盒（scale/rotation 变化后包围盒也变化）
    const box = new THREE.Box3().setFromObject(vrm.scene);
    const size = box.getSize(new THREE.Vector3());
    const modelHeight = Math.max(size.y, 0.1);

    // 4. 设置位置：X/Z 用用户偏移，Y 让脚部对齐地面 + 用户偏移
    vrm.scene.position.set(pos[0], -box.min.y + pos[1], pos[2]);
    vrm.scene.updateMatrixWorld(true);

    // 5. 使用固定相机距离（基于模型高度 + tc.camera.offsetZ），不随 canvas 尺寸缩放
    const camZ = Math.max(modelHeight * 2, tcLatest.camera.offsetZ);
    cam.position.set(
      tcLatest.camera.offsetX,
      modelHeight * 0.7 + tcLatest.camera.offsetY,
      camZ,
    );
    cam.lookAt(0, modelHeight * tcLatest.camera.lookAtY, 0);
  }, []);

  // 当 scale/position/rotation/camera 变化或模型加载完成时应用
  useEffect(() => {
    if (vrmRef.current) applyTransform();
  }, [scale, position, isLoading, tc.modelRotationX, tc.modelRotationY, tc.modelRotationZ,
      tc.camera.offsetX, tc.camera.offsetY, tc.camera.offsetZ, tc.camera.lookAtY, applyTransform]);

  useEffect(() => {
    if (windFieldRef.current && windConfig) {
      windFieldRef.current.setWindParams(windConfig);
    }
  }, [windConfig, isLoading]);

  useEffect(() => {
    if (idleAnimation === false && vrmRef.current && animationRef.current) {
      animationRef.current.reset();
      const humanoid = vrmRef.current.humanoid;
      if (humanoid) {
        const chest = humanoid.getNormalizedBoneNode('chest');
        if (chest) chest.scale.setScalar(1);
        const hips = humanoid.getNormalizedBoneNode('hips');
        if (hips) hips.rotation.z = 0;
        const head = humanoid.getNormalizedBoneNode('head');
        if (head) { head.rotation.x = 0; head.rotation.y = 0; }
        const neck = humanoid.getNormalizedBoneNode('neck');
        if (neck) { neck.rotation.x = 0; neck.rotation.y = 0; }
        const spine = humanoid.getNormalizedBoneNode('spine');
        if (spine) spine.rotation.y = 0;
      }
      const em = vrmRef.current.expressionManager;
      if (em) em.setValue('blink', 0);
    }
  }, [idleAnimation]);

  useEffect(() => {
    if (dirLightRef.current) dirLightRef.current.intensity = tc.light.directionalIntensity;
    if (ambLightRef.current) ambLightRef.current.intensity = tc.light.ambientIntensity;
    if (pntLightRef.current) pntLightRef.current.intensity = tc.light.pointIntensity;
  }, [tc.light.directionalIntensity, tc.light.ambientIntensity, tc.light.pointIntensity]);

  // rotation 和 camera 由 applyTransform 统一处理，删除重复的 useEffect

  useEffect(() => {
    if (!lipSyncEnabled || !vrmRef.current) return;
    const em = vrmRef.current.expressionManager;
    if (em) {
      em.setValue(VRMExpressionPresetName.Aa, mouthOpenY * 0.8 * ac.vowelWeightA);
      em.setValue(VRMExpressionPresetName.Ih, mouthOpenY * 0.2 * ac.vowelWeightI);
      em.setValue(VRMExpressionPresetName.Ou, mouthOpenY * 0.3 * ac.vowelWeightU);
      em.setValue(VRMExpressionPresetName.Ee, mouthOpenY * 0.15 * ac.vowelWeightE);
      em.setValue(VRMExpressionPresetName.Oh, mouthOpenY * 0.25 * ac.vowelWeightO);
    }
  }, [mouthOpenY, lipSyncEnabled, ac.vowelWeightA, ac.vowelWeightI, ac.vowelWeightU, ac.vowelWeightE, ac.vowelWeightO]);

  useEffect(() => {
    // 任一开关开启时都需注册鼠标监听，保证眼球跟踪独立于头部追踪拿到输入
    if (!lookAtMouse && !ac.eyeTrackingEnabled) {
      if (animationRef.current) animationRef.current.setHeadTarget(0, 0, 0);
      return;
    }
    const h = (e: MouseEvent) => {
      if (!canvasRef.current) return;
      const r = canvasRef.current.getBoundingClientRect();
      const rawX = ((e.clientX - r.left) / r.width) * 2 - 1;
      const rawY = -((e.clientY - r.top) / r.height) * 2 + 1;
      // Clamp 到合理范围
      const x = Math.max(-1, Math.min(1, rawX));
      const y = Math.max(-1, Math.min(1, rawY));
      // target 位置：鼠标在中心时 target 在头部正前方 (0, 1.5, 1.5)
      mouseTargetRef.current.set(x * 2, 1.5 + y * 1.0, 1.5);
    };
    window.addEventListener('mousemove', h);
    return () => window.removeEventListener('mousemove', h);
  }, [lookAtMouse, ac.eyeTrackingEnabled]);

  useEffect(() => {
    if (!ac.eyeTrackingEnabled && vrmRef.current?.lookAt) {
      // 眼球归位：看向正前方（yaw=0, pitch=0）
      vrmRef.current.lookAt.yaw = 0;
      vrmRef.current.lookAt.pitch = 0;
    }
  }, [ac.eyeTrackingEnabled]);

  useEffect(() => {
    const h = () => {
      if (!canvasRef.current || !runtimeRef.current) return;
      resizeRuntime(runtimeRef.current, canvasRef.current);
      const dpr = propsRef.current.devicePixelRatio === 'auto' ? window.devicePixelRatio : propsRef.current.devicePixelRatio;
      runtimeRef.current.renderer.setPixelRatio(dpr * propsRef.current.renderScale);
      // resize 后重新应用用户变换（包括根据 canvas 宽高比调整相机距离）
      applyTransform();
    };
    window.addEventListener('resize', h);
    let ro: ResizeObserver | null = null;
    if (canvasRef.current?.parentElement && typeof ResizeObserver !== 'undefined') {
      ro = new ResizeObserver(() => h());
      ro.observe(canvasRef.current.parentElement);
      h();
    }
    return () => {
      window.removeEventListener('resize', h);
      if (ro) ro.disconnect();
    };
  }, [applyTransform]);

  useEffect(() => {
    if (!expressionMix || !runtimeRef.current || !avatar) return;
    if (driver) {
      driver.setExpressionMix(expressionMix);
    } else {
      applyExpressionMix(runtimeRef.current, avatar, expressionMix);
    }
  }, [expressionMix, driver, avatar]);

  useEffect(() => {
    if (!parameterOverrides || !runtimeRef.current || !avatar) return;
    if (driver) {
      driver.setParameterOverrides(parameterOverrides);
    } else {
      setParameterOverrides(runtimeRef.current, avatar, parameterOverrides);
    }
  }, [parameterOverrides, driver, avatar]);

  if (loadError) {
    const m: Record<string, string> = { MODEL_NOT_CONFIGURED: '模型未配置', MODEL_FILE_NOT_FOUND: '模型文件不存在', LOAD_FAILED: '模型加载失败' };
    return (
      <div className="flex flex-col items-center justify-center h-full text-center p-4">
        <svg className="w-16 h-16 mx-auto text-[var(--color-text-tertiary)]" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" /></svg>
        <p className="text-sm text-[var(--color-text-secondary)] mt-3">{m[loadError] ?? '?'}</p>
        <p className="text-xs text-[var(--color-text-tertiary)] mt-1">请上传模型或刷新页面</p>
      </div>
    );
  }

  return (
    <div className="relative w-full h-full">
      {isLoading && <div className="absolute inset-0 flex items-center justify-center bg-[var(--color-bg-secondary)]"><div className="flex flex-col items-center"><div className="w-8 h-8 border-2 border-[var(--color-accent)] border-t-transparent rounded-full animate-spin" /><p className="text-sm text-[var(--color-text-secondary)] mt-2">加载中...</p></div></div>}
      <canvas ref={canvasRef} className="w-full h-full block" style={{ opacity: isLoading ? 0 : 1, minWidth: '100%', minHeight: '100%' }} />
    </div>
  );
}
