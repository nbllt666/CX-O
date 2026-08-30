/**
 * Live2D 查看器（桌宠窗）：createLive2DRuntime + 驱动绑定 + 口型接线。
 *
 * 与 CX-O-Frontend live2d-viewer 的差异：
 * - 模型只从本地 URL（public/models）加载，无 blob 路径
 * - 口型不经 parameterOverrides（避免与驱动的 blend 覆盖互踩），
 *   而在 PIXI ticker 末尾按帧直写 ParamMouthOpenY（引擎 overlay 之后执行，帧级生效）
 * - driver.update（动作触发）挂在同一 ticker 上
 */
import { useEffect, useRef, useState } from 'react';
import type { MutableRefObject } from 'react';
import { useTranslation } from 'react-i18next';
import type { AvatarManifest, IAvatarDriver } from '../../avatar/types';
import {
  createLive2DRuntime,
  destroyRuntime,
  resizeRuntime,
  setIdleAnimationConfig,
  setIdleAnimationEnabled,
  updateStageTransform,
  type Live2DRuntimeState,
} from '../../avatar/live2d/live2dEngine';
import type { AnimationSettings } from '../../store/settingsStore';

interface Live2DViewerProps {
  modelPath: string;
  avatar: AvatarManifest;
  driver: IAvatarDriver | null;
  /**
   * 用户舞台变换（实时热更新，不并入 manifest——避免拖缩放/偏移滑杆时整模型重建重载）。
   * scale 与 obsScale 采集自适应因子合成后传入；xOffset/yOffset 为设置原值（内部 /400 归一化）。
   * 取值口径与旧 manifest 内嵌方式等价（fitModel：scale 相乘、offset 相加）。
   */
  scale?: number;
  xOffset?: number;
  yOffset?: number;
  idleMotionEnabled?: boolean;
  animationConfig?: Partial<AnimationSettings>;
  /** 口型：实时音量 ref（0~1，渲染循环直读） */
  volumeRef?: MutableRefObject<number>;
  onModelLoaded?: () => void;
  onError?: (error: Error) => void;
}

export function Live2DViewer({
  modelPath,
  avatar,
  driver,
  scale = 1,
  xOffset = 0,
  yOffset = 0,
  idleMotionEnabled = true,
  animationConfig,
  volumeRef,
  onModelLoaded,
  onError,
}: Live2DViewerProps) {
  const { t } = useTranslation();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const runtimeRef = useRef<Live2DRuntimeState | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const onModelLoadedRef = useRef(onModelLoaded);
  const onErrorRef = useRef(onError);
  onModelLoadedRef.current = onModelLoaded;
  onErrorRef.current = onError;
  const volumeRefProxy = useRef(volumeRef);
  volumeRefProxy.current = volumeRef;
  const sensitivityRef = useRef(1);
  sensitivityRef.current = animationConfig?.lipSyncSensitivity ?? 1;

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    if (!modelPath) {
      setLoadError('MODEL_NOT_CONFIGURED');
      setIsLoading(false);
      return;
    }

    let cancelled = false;
    setIsLoading(true);
    setLoadError(null);

    createLive2DRuntime(container, avatar)
      .then((runtime) => {
        if (cancelled) {
          destroyRuntime(runtime);
          return;
        }
        runtimeRef.current = runtime;

        if (driver) {
          driver.bindRuntime(runtime);
        }
        if (animationConfig) {
          setIdleAnimationConfig(runtime, animationConfig);
        }
        setIdleAnimationEnabled(runtime, idleMotionEnabled);

        // 口型 + 驱动动作更新：挂在 ticker 末尾（引擎 overlay 之后执行）
        runtime.app.ticker.add(() => {
          const dt = runtime.app.ticker.deltaMS / 1000;
          driver?.update(dt);

          try {
            const coreModel = runtime.model.internalModel.coreModel as {
              setParameterValueById(id: string, value: number): void;
            };
            const volume = (volumeRefProxy.current?.current ?? 0) * sensitivityRef.current;
            coreModel.setParameterValueById(
              'ParamMouthOpenY',
              Math.min(Math.max(volume, 0), 1),
            );
          } catch {
            // 模型无该参数时跳过
          }
        });

        setIsLoading(false);
        onModelLoadedRef.current?.();
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        console.error('Live2D: Failed to load model:', error);
        const msg = error instanceof Error ? error.message : '';
        if (msg.includes('<!doctype') || msg.includes('Unexpected token')) {
          setLoadError('MODEL_FILE_NOT_FOUND');
        } else {
          setLoadError('LOAD_FAILED');
        }
        setIsLoading(false);
        onErrorRef.current?.(error instanceof Error ? error : new Error(String(error)));
      });

    const observer = new ResizeObserver(() => {
      if (runtimeRef.current && containerRef.current) {
        resizeRuntime(runtimeRef.current, containerRef.current);
      }
    });
    observer.observe(container);

    return () => {
      cancelled = true;
      observer.disconnect();
      if (runtimeRef.current) {
        destroyRuntime(runtimeRef.current);
        runtimeRef.current = null;
      }
    };
  }, [modelPath, avatar, driver, animationConfig, idleMotionEnabled]);

  // 用户舞台变换（scale/xOffset/yOffset）变化时热应用（B3）：经引擎 updateStageTransform
  // 改写 runtime.currentTransform 并重算取景，不重建模型——对齐 VRMViewer 的
  // scale/position prop 热更新方案。xOffset/yOffset /400 归一化口径与旧 manifest
  // 内嵌方式（createSyntheticLive2DManifest）一致；isLoading 依赖确保加载完成、
  // runtimeRef 就位后补首次应用。
  useEffect(() => {
    const runtime = runtimeRef.current;
    const container = containerRef.current;
    if (!runtime || !container || isLoading) return;
    updateStageTransform(runtime, container, {
      scale,
      offsetX: xOffset / 400,
      offsetY: yOffset / 400,
    });
  }, [scale, xOffset, yOffset, isLoading]);

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
      <div ref={containerRef} className="h-full w-full" style={{ opacity: isLoading ? 0 : 1 }} />
    </div>
  );
}
