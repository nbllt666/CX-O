/**
 * VRM 查看器（桌宠窗）：模型加载 → createVRMRuntime → startRuntimeLoop。
 *
 * 与 CX-O-Frontend vrm-viewer 的差异：
 * - 渲染循环由引擎层 startRuntimeLoop 托管，onFrame 注入驱动更新/视线追踪/口型权重
 * - 模型只从本地 URL（public/models）加载，无 IndexedDB/blob 路径
 * - 口型经 VRMLipSync.updateWeights 按帧写入（元音权重 × 音量门控）
 */
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import type { MutableRefObject } from 'react';
import * as THREE from 'three';
import { VRM, VRMLoaderPlugin } from '@pixiv/three-vrm';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { useTranslation } from 'react-i18next';
import type { AvatarManifest, IAvatarDriver, SceneMode } from '../../avatar/types';
import type { VRMDriver } from '../../avatar/vrmDriver';
import {
  createVRMRuntime,
  startRuntimeLoop,
  destroyRuntime,
  resizeRuntime,
  updateStageTransform,
  type VRMRuntimeState,
} from '../../avatar/vrm/vrmEngine';
import {
  createLookAtStrategy,
  LiveCameraStrategy,
  type LookAtStrategy,
} from '../../avatar/vrm/vrmLookAtStrategy';
import { PerformanceMonitor } from '../../avatar/vrm/vrmPerformanceMonitor';
import type { VowelWeights } from '../../hooks/useAudioAnalyzer';
import type { AnimationSettings, VRMTweakConfig } from '../../store/settingsStore';
import { DEFAULT_ANIMATION_SETTINGS, DEFAULT_VRM_TWEAK } from '../../store/settingsStore';
import { resolveVrmModelUrl } from '../../lib/vrmModelSource';

interface VRMViewerProps {
  modelPath: string;
  avatar: AvatarManifest;
  driver: IAvatarDriver | null;
  scale?: number;
  position?: [number, number, number];
  lookAtMouse?: boolean;
  /** 场景模式：'live' 时启用直播视线策略（镜头/弹幕），默认 'pet'（鼠标跟随） */
  sceneMode?: SceneMode;
  animationConfig?: Partial<AnimationSettings>;
  tweakConfig?: Partial<VRMTweakConfig>;
  /** 口型：实时音量（0~1）与元音权重的 ref（渲染循环直读，不走 React state） */
  volumeRef?: MutableRefObject<number>;
  vowelWeightsRef?: MutableRefObject<VowelWeights>;
  onModelLoaded?: () => void;
  onError?: (error: Error) => void;
}

/** VRMViewer 命令式句柄（供上层触发直播读弹幕视线） */
export interface VRMViewerHandle {
  /** 触发读弹幕视线（仅直播模式生效）；state 省略或 true 时开始读弹幕，2s 后自动复位 */
  setReadingDanmaku: (state?: boolean) => void;
}

export const VRMViewer = forwardRef<VRMViewerHandle, VRMViewerProps>(function VRMViewer(
  {
    modelPath,
    avatar,
    driver,
    scale = 1.0,
    position = [0, 0, 0],
    lookAtMouse = true,
    sceneMode = 'pet',
    animationConfig,
    tweakConfig,
    volumeRef,
    vowelWeightsRef,
    onModelLoaded,
    onError,
  },
  ref,
) {
  const { t } = useTranslation();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const runtimeRef = useRef<VRMRuntimeState | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const onModelLoadedRef = useRef(onModelLoaded);
  const onErrorRef = useRef(onError);
  onModelLoadedRef.current = onModelLoaded;
  onErrorRef.current = onError;

  const lookAtMouseRef = useRef(lookAtMouse);
  lookAtMouseRef.current = lookAtMouse;
  const volumeRefProxy = useRef(volumeRef);
  volumeRefProxy.current = volumeRef;
  const vowelWeightsRefProxy = useRef(vowelWeightsRef);
  vowelWeightsRefProxy.current = vowelWeightsRef;

  const ac: AnimationSettings = { ...DEFAULT_ANIMATION_SETTINGS, ...animationConfig };
  const acRef = useRef(ac);
  acRef.current = ac;
  const tc: VRMTweakConfig = { ...DEFAULT_VRM_TWEAK, ...tweakConfig };
  const tcRef = useRef(tc);
  tcRef.current = tc;

  const mousePosRef = useRef<{ x: number; y: number }>({ x: 0, y: 0 });
  // 直播模式弹幕区锚点（归一化屏幕坐标；pet 模式不使用，LiveCameraStrategy 内部有缺省值）
  const danmakuAreaRef = useRef<{ x: number; y: number } | undefined>(undefined);

  // 场景模式：渲染循环直读 ref（sceneMode 变更时重建策略但不重建模型）
  const sceneModeRef = useRef<SceneMode>(sceneMode);
  sceneModeRef.current = sceneMode;
  const lookAtStrategyRef = useRef<LookAtStrategy>(createLookAtStrategy(sceneMode));
  useEffect(() => {
    lookAtStrategyRef.current = createLookAtStrategy(sceneMode);
  }, [sceneMode]);

  // 读弹幕视线自动复位计时器（直播模式）
  const readingDanmakuTimerRef = useRef<number | null>(null);
  useEffect(() => {
    return () => {
      if (readingDanmakuTimerRef.current !== null) {
        window.clearTimeout(readingDanmakuTimerRef.current);
        readingDanmakuTimerRef.current = null;
      }
    };
  }, []);

  // 模型加载 + 渲染循环（modelPath / avatar 变更 → 全量重建）
  useEffect(() => {
    if (!modelPath) {
      setLoadError('MODEL_NOT_CONFIGURED');
      setIsLoading(false);
      return;
    }

    let cancelled = false;
    // 性能监控订阅退订函数（loadModel 内赋值，effect 清理时调用）
    let unsubPerformance: (() => void) | null = null;
    // 本地模型读取生成的 blob URL 释放函数（loadModel 内赋值，effect 清理时 revoke）
    let blobRevoke: (() => void) | null = null;
    setIsLoading(true);
    setLoadError(null);

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

    const loadModel = async () => {
      const canvas = await waitForCanvas();
      if (cancelled) return;

      const loader = new GLTFLoader();
      loader.register((p) => new VRMLoaderPlugin(p));
      // 解析模型加载源：打包内资源直接走 URL；本地路径经 IPC 读为 blob URL（卸载时 revoke）
      const source = await resolveVrmModelUrl(modelPath);
      blobRevoke = source.revoke;
      const gltf = await loader.loadAsync(source.url);
      if (cancelled) return;

      const vrm = gltf.userData.vrm as VRM | undefined;
      if (!vrm) throw new Error('Not a VRM model');

      // 初始姿态：手臂自然下垂（对齐参考实现的骨骼预置）
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
      }

      const tcLatest = tcRef.current;
      vrm.scene.rotation.set(tcLatest.modelRotationX, tcLatest.modelRotationY, tcLatest.modelRotationZ);

      const runtime = createVRMRuntime(canvas, avatar, vrm, {
        offsetX: tcLatest.camera.offsetX,
        offsetY: tcLatest.camera.offsetY,
        offsetZ: tcLatest.camera.offsetZ,
        lookAtY: tcLatest.camera.lookAtY,
      });
      runtimeRef.current = runtime;
      (window as unknown as { __vrmRuntime?: unknown }).__vrmRuntime = runtime;

      // 性能监控：FPS 降级 → 关闭空闲动画 + 跳帧 SpringBone（springBoneEveryOtherFrame 由 Task 5 在 VRMRuntimeState 上新增）
      const performanceMonitor = new PerformanceMonitor();
      unsubPerformance = performanceMonitor.subscribe((degraded) => {
        runtime.animation.setEnabled(!degraded);
        runtime.springBoneEveryOtherFrame = degraded;
      });

      // 光照 tweak
      const dirLight = runtime.scene.children.find(
        (c): c is THREE.DirectionalLight => c instanceof THREE.DirectionalLight,
      );
      const ambLight = runtime.scene.children.find(
        (c): c is THREE.HemisphereLight => c instanceof THREE.HemisphereLight,
      );
      const pntLight = runtime.scene.children.find(
        (c): c is THREE.PointLight => c instanceof THREE.PointLight,
      );
      if (dirLight) dirLight.intensity = tcLatest.light.directionalIntensity;
      if (ambLight) ambLight.intensity = tcLatest.light.ambientIntensity;
      if (pntLight) pntLight.intensity = tcLatest.light.pointIntensity;

      // 动画/口型配置
      const acLatest = acRef.current;
      runtime.animation.setConfig({
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
      runtime.lipSync.setSmoothing(acLatest.lipSyncSmoothing);

      // 视线：禁用自动 target 跟踪，改手动 yaw/pitch（对齐参考实现）
      if (vrm.lookAt) {
        vrm.lookAt.autoUpdate = false;
        if (!vrm.lookAt.target) {
          const target = new THREE.Object3D();
          target.position.set(0, 1.5, 1.5);
          runtime.scene.add(target);
          vrm.lookAt.target = target;
        }
      }

      // 驱动绑定（表情/动作/风场子系统在 bindRuntime 内创建；动作交叉淡入传入 gltf 动画片段）
      if (driver) {
        (driver as VRMDriver).bindRuntime(runtime, gltf.animations);
      }

      // 渲染循环：onFrame 注入性能监控 / 驱动更新 / 视线策略 / 口型权重
      startRuntimeLoop(runtime, (dt) => {
        // 性能监控：FPS 结算并触发降级/恢复（降级时经 subscribe 关闭动画 + 跳帧 SpringBone）
        performanceMonitor.update(dt);

        // 口型：元音权重 × 音量门控（音量低时权重归零 → 闭嘴）
        const volume = volumeRefProxy.current?.current ?? 0;
        const vowels = vowelWeightsRefProxy.current?.current;
        const sensitivity = acRef.current.lipSyncSensitivity;
        if (vowels && volume > 0.02) {
          runtime.lipSync.updateWeights({
            a: vowels.a * volume * acRef.current.vowelWeightA * sensitivity,
            i: vowels.i * volume * acRef.current.vowelWeightI * sensitivity,
            u: vowels.u * volume * acRef.current.vowelWeightU * sensitivity,
            e: vowels.e * volume * acRef.current.vowelWeightE * sensitivity,
            o: vowels.o * volume * acRef.current.vowelWeightO * sensitivity,
          });
        } else {
          runtime.lipSync.updateWeights({ a: 0, i: 0, u: 0, e: 0, o: 0 });
        }

        // 视线策略：按场景模式计算目标点（pet=鼠标跟随 / live=镜头/弹幕）
        const targetPos = lookAtStrategyRef.current.getTargetPosition(
          runtime.camera,
          mousePosRef.current,
          danmakuAreaRef.current,
        );

        // 眼球追踪（正交独立，保留 eyeTrackingEnabled 逻辑）
        if (acRef.current.eyeTrackingEnabled && vrm.lookAt) {
          const nx = targetPos.x / 3.2;
          const ny = (targetPos.y - 1.5) / 1.6;
          const targetYaw = Math.sign(nx) * Math.min(Math.abs(nx) ** 0.8, 1) * 24;
          const targetPitch = -Math.sign(ny) * Math.min(Math.abs(ny) ** 0.8, 1) * 24;
          const headRot = runtime.animation.getHeadRotation();
          vrm.lookAt.yaw = targetYaw + headRot.y * (180 / Math.PI);
          vrm.lookAt.pitch = targetPitch + headRot.x * (180 / Math.PI);
        }
        // 头部跟随：pet 模式由 lookAtMouse 开关决定，live 模式始终驱动（镜头/弹幕策略）
        if (lookAtMouseRef.current || sceneModeRef.current === 'live') {
          runtime.animation.setHeadTarget(targetPos.x, targetPos.y, targetPos.z);
        }

        // 驱动子系统（表情/动作触发/风场）
        (driver as VRMDriver | null)?.update(dt);
      });

      setIsLoading(false);
      onModelLoadedRef.current?.();
    };

    loadModel().catch((error: unknown) => {
      if (cancelled) return;
      console.error('VRM: Failed to load model:', error);
      const msg = error instanceof Error ? error.message : '';
      if (
        msg.includes('<!doctype') ||
        msg.includes('Unexpected token') ||
        msg.startsWith('MODEL_READ_FAILED') ||
        msg.startsWith('LOCAL_MODEL_UNSUPPORTED')
      ) {
        setLoadError('MODEL_FILE_NOT_FOUND');
      } else {
        setLoadError('LOAD_FAILED');
      }
      setIsLoading(false);
      onErrorRef.current?.(error instanceof Error ? error : new Error(String(error)));
    });

    return () => {
      cancelled = true;
      unsubPerformance?.();
      blobRevoke?.();
      if (runtimeRef.current) {
        destroyRuntime(runtimeRef.current);
        runtimeRef.current = null;
      }
    };
    // driver 变更（头像类型切换）需要重建运行时绑定
  }, [modelPath, avatar, driver]);

  // 鼠标位置监听（视线策略输入）：归一化坐标（-1..1，y 向上）存 ref，由策略消费
  useEffect(() => {
    if (!lookAtMouse && !ac.eyeTrackingEnabled) return;
    const handler = (e: MouseEvent) => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const rect = canvas.getBoundingClientRect();
      const rawX = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      const rawY = -((e.clientY - rect.top) / rect.height) * 2 + 1;
      mousePosRef.current = {
        x: Math.max(-1, Math.min(1, rawX)),
        y: Math.max(-1, Math.min(1, rawY)),
      };
    };
    window.addEventListener('mousemove', handler);
    return () => window.removeEventListener('mousemove', handler);
  }, [lookAtMouse, ac.eyeTrackingEnabled]);

  // 命令式句柄：直播模式收到新弹幕时触发读弹幕视线，2s 后自动复位
  useImperativeHandle(
    ref,
    () => ({
      setReadingDanmaku: (state?: boolean) => {
        const strategy = lookAtStrategyRef.current;
        if (!(strategy instanceof LiveCameraStrategy)) return;
        if (readingDanmakuTimerRef.current !== null) {
          window.clearTimeout(readingDanmakuTimerRef.current);
          readingDanmakuTimerRef.current = null;
        }
        if (state === false) {
          strategy.setReadingDanmaku(false);
          return;
        }
        strategy.setReadingDanmaku(true);
        readingDanmakuTimerRef.current = window.setTimeout(() => {
          readingDanmakuTimerRef.current = null;
          strategy.setReadingDanmaku(false);
        }, 2000);
      },
    }),
    [],
  );

  // 尺寸自适应
  useEffect(() => {
    const handler = () => {
      const canvas = canvasRef.current;
      if (!canvas || !runtimeRef.current) return;
      resizeRuntime(runtimeRef.current, canvas);
    };
    window.addEventListener('resize', handler);
    let observer: ResizeObserver | null = null;
    if (canvasRef.current?.parentElement && typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver(() => handler());
      observer.observe(canvasRef.current.parentElement);
    }
    return () => {
      window.removeEventListener('resize', handler);
      observer?.disconnect();
    };
  }, []);

  // 用户变换（scale/position）变化时实时应用（经 updateStageTransform，不重建模型）
  useEffect(() => {
    const runtime = runtimeRef.current;
    if (!runtime || isLoading) return;
    updateStageTransform(runtime, {
      scale,
      offsetX: position[0],
      offsetY: position[1],
    });
  }, [scale, position, isLoading]);

  if (loadError) {
    return (
      <div className="flex h-full flex-col items-center justify-center p-4 text-center">
        <p className="text-sm text-muted-foreground">
          {loadError === 'MODEL_NOT_CONFIGURED'
            ? t('pet.avatar.notConfigured')
            : loadError === 'MODEL_FILE_NOT_FOUND'
              ? t('pet.avatar.fileNotFound')
              : t('pet.avatar.loadFailed')}
        </p>
      </div>
    );
  }

  return (
    <div className="relative h-full w-full">
      {isLoading && (
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        </div>
      )}
      <canvas
        ref={canvasRef}
        className="block h-full w-full"
        style={{ opacity: isLoading ? 0 : 1 }}
      />
    </div>
  );
});
