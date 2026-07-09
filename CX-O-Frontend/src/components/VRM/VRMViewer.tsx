import { useEffect, useRef, useState } from 'react';
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
  const [modelSize, setModelSize] = useState<{ height: number; width: number }>({ height: 1.6, width: 0.8 });

  const propsRef = useRef({ scale, position, onModelLoaded, onError, renderScale, devicePixelRatio });
  useEffect(() => {
    propsRef.current.renderScale = renderScale;
    propsRef.current.devicePixelRatio = devicePixelRatio;
  }, [renderScale, devicePixelRatio]);
  const idleAnimRef = useRef(idleAnimation);
  useEffect(() => { idleAnimRef.current = idleAnimation; }, [idleAnimation]);
  const lastVersionRef = useRef(-1);
  const renderIdRef = useRef(0);

  const effectiveTweak = useRef<Partial<VRMTweakConfig>>(tweakConfig || {});
  useEffect(() => { effectiveTweak.current = tweakConfig || {}; }, [tweakConfig]);
  const tc: VRMTweakConfig = { ...DEFAULT_VRM_TWEAK, ...tweakConfig };
  const tcRef = useRef<VRMTweakConfig>(tc);
  useEffect(() => { tcRef.current = tc; }, [tc]);

  const ac: AnimationSettings = { ...DEFAULT_ANIMATION_SETTINGS, ...animationConfig };
  const acRef = useRef<AnimationSettings>(ac);
  useEffect(() => { acRef.current = ac; }, [ac]);

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
      if (useBuf) url = URL.createObjectURL(new Blob([data], { type: 'application/octet-stream' }));
      else url = modelPath;
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
        vrm.scene.scale.setScalar(propsRef.current.scale);
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

        const scene = runtimeRef.current!.scene;
        const cam = runtimeRef.current!.camera;
        const renderer = runtimeRef.current!.renderer;

        dirLightRef.current = scene.children.find((c): c is THREE.DirectionalLight => c instanceof THREE.DirectionalLight) ?? null;
        ambLightRef.current = scene.children.find((c): c is THREE.AmbientLight => c instanceof THREE.AmbientLight) ?? null;
        pntLightRef.current = scene.children.find((c): c is THREE.PointLight => c instanceof THREE.PointLight) ?? null;

        const box = new THREE.Box3().setFromObject(vrm.scene);
        const size = box.getSize(new THREE.Vector3());
        const height = Math.max(size.y, 0.1), width = Math.max(size.x, 0.1);
        setModelSize({ height, width });

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

        if (vrm.lookAt && !vrm.lookAt.target) {
          const lookAtTarget = new THREE.Object3D();
          lookAtTarget.position.set(0, 1.5, 1.5);
          runtimeRef.current!.scene.add(lookAtTarget);
          vrm.lookAt.target = lookAtTarget;
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
          const dt = clockRef.current.getDelta();

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
  }, [ac.breathFrequency, ac.breathAmplitude, ac.breathIrregularity,
      ac.blinkInterval, ac.blinkDuration,
      ac.swayAmplitude, ac.swayFrequency, ac.swayIrregularity,
      ac.headFollowSpeed, ac.bodyFollowDelay, ac.headIdleRange,
      ac.headTrackingLimit,
      ac.emotionIntensity, ac.emotionDuration,
      ac.emotionRecoverSpeed, ac.idleExpressionIntensity,
      ac.lipSyncSmoothing, ac.motionTriggerProbability, ac.focusSpeed]);

  useEffect(() => {
    if (windFieldRef.current && windConfig) {
      windFieldRef.current.setWindParams(windConfig);
    }
  }, [windConfig]);

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

  useEffect(() => {
    if (vrmRef.current) {
      vrmRef.current.scene.rotation.x = tc.modelRotationX;
      vrmRef.current.scene.rotation.y = tc.modelRotationY;
      vrmRef.current.scene.rotation.z = tc.modelRotationZ;
    }
  }, [tc.modelRotationX, tc.modelRotationY, tc.modelRotationZ]);

  useEffect(() => {
    const cam = runtimeRef.current?.camera;
    if (!cam) return;
    const { height } = modelSize;
    cam.position.set(tc.camera.offsetX, height * 0.7 + tc.camera.offsetY, Math.max(modelSize.width * 2.5, tc.camera.offsetZ));
    cam.lookAt(0, height * tc.camera.lookAtY, 0);
  }, [tc.camera.offsetX, tc.camera.offsetY, tc.camera.offsetZ, tc.camera.lookAtY, modelSize]);

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
    if (!lookAtMouse) {
      if (animationRef.current) animationRef.current.setHeadTarget(0, 0, 0);
      return;
    }
    const h = (e: MouseEvent) => {
      if (!vrmRef.current || !canvasRef.current) return;
      const r = canvasRef.current.getBoundingClientRect();
      const x = ((e.clientX - r.left) / r.width) * 2 - 1;
      const y = -((e.clientY - r.top) / r.height) * 2 + 1;
      if (acRef.current.eyeTrackingEnabled) {
        const la = vrmRef.current.lookAt;
        if (la?.target) la.target.position.set(x * 2, y * 1.5 + 1, 1.5);
      }
      if (animationRef.current) {
        animationRef.current.setHeadTarget(x * 2, y * 1.5 + 1, 1.5);
      }
    };
    window.addEventListener('mousemove', h);
    return () => window.removeEventListener('mousemove', h);
  }, [lookAtMouse]);

  useEffect(() => {
    if (!ac.eyeTrackingEnabled && vrmRef.current?.lookAt?.target) {
      vrmRef.current.lookAt.target.position.set(0, 1.5, 1.5);
    }
  }, [ac.eyeTrackingEnabled]);

  useEffect(() => {
    const h = () => {
      if (!canvasRef.current || !runtimeRef.current) return;
      resizeRuntime(runtimeRef.current, canvasRef.current);
      const dpr = propsRef.current.devicePixelRatio === 'auto' ? window.devicePixelRatio : propsRef.current.devicePixelRatio;
      runtimeRef.current.renderer.setPixelRatio(dpr * propsRef.current.renderScale);
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
  }, []);

  useEffect(() => { if (vrmRef.current) vrmRef.current.scene.scale.setScalar(scale); }, [scale]);
  useEffect(() => { if (vrmRef.current) vrmRef.current.scene.position.set(position[0], position[1], position[2]); }, [position]);

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
