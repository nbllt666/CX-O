import { useEffect, useRef, useState, useMemo } from 'react';
import { buildGlassDataAttributes, isValidGlassTier } from '@/components/ui-v2';
import type { AvatarManifest, ExpressionLayer, ParameterOverride } from '../avatar/avatar-manifest';
import type { IAvatarDriver } from '../avatar/avatar-driver';
import { Live2DAvatarDriver } from '../avatar/avatar-driver';
import type { StageTransform } from './live2d-engine';
import {
  applyExpressionMix,
  createLive2DRuntime,
  destroyRuntime,
  resizeRuntime,
  setParameterOverrides,
  setIdleAnimationConfig,
  updateStageTransform,
} from './live2d-engine';
import type { AnimationSettings } from '@/store/settingsStore';

// Liquid Glass: data-glass 属性构建（查看器容器注入）
const glassTier = 'tier-2';
const validTier = isValidGlassTier(glassTier) ? glassTier : undefined;
const glassAttributes = buildGlassDataAttributes(true, validTier);

interface Live2DViewerProps {
  modelPath: string;
  modelData?: ArrayBuffer;
  scale?: number;
  xOffset?: number;
  yOffset?: number;
  lipSyncEnabled?: boolean;
  idleMotionEnabled?: boolean;
  mouthOpenY?: number;
  onModelLoaded?: () => void;
  onError?: (error: Error) => void;
  animationConfig?: Partial<AnimationSettings>;
  expressionMix?: ExpressionLayer[];
  parameterOverrides?: ParameterOverride[];
  driver?: IAvatarDriver;
}

function createSyntheticManifest(
  modelJson: string,
  scale: number,
  xOffset: number,
  yOffset: number,
): AvatarManifest {
  return {
    id: 'synthetic',
    name: 'Model',
    summary: '',
    persona: { tone: '', traits: [], styleRules: [] },
    modelJson,
    scaleMultiplier: scale,
    verticalOffset: 0.08,
    modelTransform: {
      scale: 8,
      offsetX: xOffset / 400,
      offsetY: yOffset / 400 + 1.3,
    },
    transformDefaults: {
      scale: 1,
      offsetX: 0,
      offsetY: 0,
    },
    expressions: [],
    parameterControls: [],
    avatarType: 'live2d',
  };
}

export function Live2DViewer({
  modelPath,
  modelData,
  scale = 0.3,
  xOffset = 0,
  yOffset = 0,
  lipSyncEnabled = true,
  mouthOpenY = 0,
  onModelLoaded,
  onError,
  animationConfig,
  expressionMix,
  parameterOverrides: externalOverrides,
  driver,
}: Live2DViewerProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const runtimeRef = useRef<Awaited<ReturnType<typeof createLive2DRuntime>> | null>(null);
  const blobUrlRef = useRef<string | null>(null);
  const onModelLoadedRef = useRef(onModelLoaded);
  const onErrorRef = useRef(onError);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const transformRef = useRef<StageTransform>({
    scale: 1,
    offsetX: 0,
    offsetY: 0,
  });
  const allOverridesRef = useRef<ParameterOverride[]>([]);
  const effectiveExpressionMixRef = useRef<ExpressionLayer[]>([]);

  onModelLoadedRef.current = onModelLoaded;
  onErrorRef.current = onError;

  const effectiveModelPath = useMemo(() => {
    if (modelData && modelData.byteLength > 0) {
      if (blobUrlRef.current && blobUrlRef.current.startsWith('blob:')) {
        URL.revokeObjectURL(blobUrlRef.current);
      }
      const blob = new Blob([modelData], { type: 'application/octet-stream' });
      const url = URL.createObjectURL(blob);
      blobUrlRef.current = url;
      return url;
    }
    return modelPath;
  }, [modelData, modelPath]);

  useEffect(() => {
    return () => {
      if (blobUrlRef.current && blobUrlRef.current.startsWith('blob:')) {
        URL.revokeObjectURL(blobUrlRef.current);
        blobUrlRef.current = null;
      }
    };
  }, []);

  const avatar = useMemo(
    () => createSyntheticManifest(effectiveModelPath, scale, xOffset, yOffset),
    [effectiveModelPath, scale, xOffset, yOffset],
  );

  const lipSyncOverrides = useMemo<ParameterOverride[]>(() => {
    if (!lipSyncEnabled) return [];
    return [{ id: 'ParamMouthOpenY', value: mouthOpenY }];
  }, [lipSyncEnabled, mouthOpenY]);

  const allOverrides = useMemo<ParameterOverride[]>(() => {
    return [...lipSyncOverrides, ...(externalOverrides ?? [])];
  }, [lipSyncOverrides, externalOverrides]);

  const effectiveExpressionMix = useMemo<ExpressionLayer[]>(() => {
    return expressionMix ?? [];
  }, [expressionMix]);

  allOverridesRef.current = allOverrides;
  effectiveExpressionMixRef.current = effectiveExpressionMix;

  useEffect(() => {
    const container = containerRef.current;
    if (!container || !effectiveModelPath) {
      if (!effectiveModelPath) {
        setLoadError('MODEL_NOT_CONFIGURED');
        setIsLoading(false);
      }
      return;
    }

    let cancelled = false;
    setIsLoading(true);
    setLoadError(null);

    const initialMix = effectiveExpressionMixRef.current.length > 0 ? effectiveExpressionMixRef.current : [{ key: 'neutral', weight: 1 }];

    void createLive2DRuntime(container, avatar)
      .then(async (runtime) => {
        if (cancelled) {
          destroyRuntime(runtime);
          return;
        }

        runtimeRef.current = runtime;
        if (driver) {
          (driver as Live2DAvatarDriver).bindRuntime(runtime);
        }
        if (animationConfig) {
          setIdleAnimationConfig(runtime, animationConfig);
        }
        await applyExpressionMix(runtime, avatar, initialMix);
        await setParameterOverrides(runtime, avatar, allOverridesRef.current);
        updateStageTransform(runtime, container, transformRef.current);
        setIsLoading(false);
        onModelLoadedRef.current?.();
      })
      .catch((error) => {
        if (cancelled) return;
        console.error('Live2D: Failed to load model:', error);
        const errorMessage = error instanceof Error ? error.message : '';
        if (errorMessage.includes('<!doctype') || errorMessage.includes('Unexpected token')) {
          setLoadError('MODEL_FILE_NOT_FOUND');
        } else {
          setLoadError('LOAD_FAILED');
        }
        setIsLoading(false);
        onErrorRef.current?.(error instanceof Error ? error : new Error('Failed to load model'));
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
  }, [avatar, effectiveModelPath]);

  useEffect(() => {
    if (!runtimeRef.current) return;
    const mix = effectiveExpressionMix.length > 0 ? effectiveExpressionMix : [{ key: 'neutral', weight: 1 }];
    void applyExpressionMix(runtimeRef.current, avatar, mix).catch(console.error);
  }, [avatar, effectiveExpressionMix]);

  useEffect(() => {
    if (!runtimeRef.current) return;
    void setParameterOverrides(runtimeRef.current, avatar, allOverrides).catch(console.error);
  }, [avatar, allOverrides]);

  useEffect(() => {
    if (!runtimeRef.current || !animationConfig) return;
    setIdleAnimationConfig(runtimeRef.current, animationConfig);
  }, [animationConfig]);

  useEffect(() => {
    if (!runtimeRef.current || !containerRef.current) return;
    updateStageTransform(runtimeRef.current, containerRef.current, transformRef.current);
  }, [transformRef]);

  if (loadError) {
    const isNotConfigured = loadError === 'MODEL_NOT_CONFIGURED';
    const isFileNotFound = loadError === 'MODEL_FILE_NOT_FOUND';
    return (
      <div className="flex flex-col items-center justify-center h-full text-center p-4">
        <div className="text-[var(--color-text-tertiary)] mb-3">
          <svg className="w-16 h-16 mx-auto" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
          </svg>
        </div>
        <p className="text-sm text-[var(--color-text-secondary)]">
          {isNotConfigured ? '模型未配置' : isFileNotFound ? '模型文件不存在' : '模型加载失败'}
        </p>
        <p className="text-xs text-[var(--color-text-tertiary)] mt-1">
          {isNotConfigured || isFileNotFound ? '请上传模型或检查模型路径' : '请检查模型文件是否存在且格式正确'}
        </p>
      </div>
    );
  }

  return (
    <div
      className="relative w-full h-full"
      data-glass={glassAttributes['data-glass'] ?? undefined}
      data-glass-tier={glassAttributes['data-glass-tier'] ?? undefined}
    >
      {isLoading && (
        <div className="absolute inset-0 flex items-center justify-center bg-[var(--color-bg-secondary)]">
          <div className="flex flex-col items-center">
            <div className="w-8 h-8 border-2 border-[var(--color-accent)] border-t-transparent rounded-full animate-spin" />
            <p className="text-sm text-[var(--color-text-secondary)] mt-2">加载模型...</p>
          </div>
        </div>
      )}
      <div
        ref={containerRef}
        className="w-full h-full"
        style={{ opacity: isLoading ? 0 : 1 }}
      />
    </div>
  );
}
