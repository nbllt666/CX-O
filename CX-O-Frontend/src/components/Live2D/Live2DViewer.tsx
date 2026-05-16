import { useEffect, useRef, useCallback, useState } from 'react';
import * as PIXI from 'pixi.js';
import { Live2DModel } from 'pixi-live2d-display';
import { AnimationSettings, DEFAULT_ANIMATION_SETTINGS } from '../../store/settingsStore';
import { Live2DLipSync } from './Live2DLipSync';
import { Live2DExpression } from './Live2DExpression';
import { Live2DMotion } from './Live2DMotion';

(window as unknown as { PIXI: typeof PIXI }).PIXI = PIXI;

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
}

export function Live2DViewer({
  modelPath,
  modelData,
  scale = 0.3,
  xOffset = 0,
  yOffset = 0,
  lipSyncEnabled = true,
  idleMotionEnabled = true,
  mouthOpenY = 0,
  onModelLoaded,
  onError,
  animationConfig,
}: Live2DViewerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const appRef = useRef<PIXI.Application | null>(null);
  const modelRef = useRef<Live2DModel | null>(null);
  const blobUrlRef = useRef<string | null>(null);
  const lipSyncRef = useRef<Live2DLipSync | null>(null);
  const expressionRef = useRef<Live2DExpression | null>(null);
  const motionRef = useRef<Live2DMotion | null>(null);
  const animationFrameRef = useRef<number | null>(null);
  const clockRef = useRef(0);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const effectiveAnim = useRef<Partial<AnimationSettings>>(animationConfig || {});
  if (animationConfig) effectiveAnim.current = animationConfig;
  const ac: AnimationSettings = { ...DEFAULT_ANIMATION_SETTINGS, ...effectiveAnim.current };

  const loadModel = useCallback(async () => {
    if (!canvasRef.current) return;

    let effectiveModelPath: string | null = null;
    let createdBlobUrl = false;

    if (modelData && modelData.byteLength > 0) {
      const blob = new Blob([modelData], { type: 'application/octet-stream' });
      effectiveModelPath = URL.createObjectURL(blob);
      createdBlobUrl = true;
    } else if (modelPath && modelPath.length > 0) {
      effectiveModelPath = modelPath;
    }

    if (!effectiveModelPath) {
      setLoadError('MODEL_NOT_CONFIGURED');
      setIsLoading(false);
      return;
    }

    if (blobUrlRef.current && blobUrlRef.current.startsWith('blob:')) {
      URL.revokeObjectURL(blobUrlRef.current);
    }
    if (createdBlobUrl) {
      blobUrlRef.current = effectiveModelPath;
    }

    try {
      setIsLoading(true);
      setLoadError(null);

      if (appRef.current) {
        try {
          appRef.current.destroy(true, { children: true });
        } catch (e) {
          console.warn('Live2D: Error destroying previous app:', e);
        }
        appRef.current = null;
      }

      const app = new PIXI.Application({
        view: canvasRef.current,
        width: canvasRef.current.clientWidth,
        height: canvasRef.current.clientHeight,
        backgroundAlpha: 0,
        resolution: window.devicePixelRatio || 1,
        autoDensity: true,
      });

      appRef.current = app;

      const model = await Live2DModel.from(effectiveModelPath, {
        autoInteract: true,
      });

      modelRef.current = model;

      model.scale.set(scale);
      model.x = app.screen.width / 2 + xOffset;
      model.y = app.screen.height / 2 + yOffset;

      app.stage.addChild(model as unknown as PIXI.Container);

      if (idleMotionEnabled && model.internalModel?.motionManager) {
        try {
          model.internalModel.motionManager.startRandomMotion('idle');
        } catch {
          console.log('Live2D: No idle motion available');
        }
      }

      // Initialize new systems
      lipSyncRef.current = new Live2DLipSync();
      lipSyncRef.current.bindModel(model);
      lipSyncRef.current.setSmoothing(ac.lipSyncSmoothing);

      expressionRef.current = new Live2DExpression();
      expressionRef.current.bindModel(model);
      expressionRef.current.setConfig({
        intensity: ac.emotionIntensity,
        duration: ac.emotionDuration,
        recoverSpeed: ac.emotionRecoverSpeed,
      });

      motionRef.current = new Live2DMotion();
      motionRef.current.bindModel(model);
      motionRef.current.setConfig({
        emotionMotionProbability: ac.motionTriggerProbability,
        speechMotionProbability: ac.motionTriggerProbability,
        focusSpeed: ac.focusSpeed,
      });

      // Start animation loop
      const animate = () => {
        const now = performance.now();
        const dt = (now - clockRef.current) / 1000;
        clockRef.current = now;

        if (lipSyncRef.current) lipSyncRef.current.update(dt);
        if (expressionRef.current) expressionRef.current.update(dt);
        if (motionRef.current) motionRef.current.update(dt);

        animationFrameRef.current = requestAnimationFrame(animate);
      };
      clockRef.current = performance.now();
      animate();

      setIsLoading(false);
      onModelLoaded?.();
    } catch (error) {
      console.error('Live2D: Failed to load model:', error);
      const errorMessage = error instanceof Error ? error.message : '';
      if (errorMessage.includes('<!doctype') || errorMessage.includes('Unexpected token')) {
        setLoadError('MODEL_FILE_NOT_FOUND');
      } else {
        setLoadError('LOAD_FAILED');
      }
      setIsLoading(false);
      onError?.(error instanceof Error ? error : new Error('Failed to load model'));
    }
  }, [modelPath, modelData, scale, xOffset, yOffset, idleMotionEnabled, onModelLoaded, onError, ac.lipSyncSmoothing, ac.emotionIntensity, ac.emotionDuration, ac.emotionRecoverSpeed, ac.motionTriggerProbability, ac.focusSpeed]);

  useEffect(() => {
    loadModel();

    return () => {
      if (animationFrameRef.current) cancelAnimationFrame(animationFrameRef.current);
      if (blobUrlRef.current && blobUrlRef.current.startsWith('blob:')) {
        URL.revokeObjectURL(blobUrlRef.current);
        blobUrlRef.current = null;
      }
      if (appRef.current) {
        try {
          if (typeof appRef.current.destroy === 'function') {
            appRef.current.destroy(true, { children: true });
          }
        } catch (e) {
          console.warn('Live2D: Error during cleanup:', e);
        }
        appRef.current = null;
      }
      modelRef.current = null;
    };
  }, [loadModel]);

  // Update animation config
  useEffect(() => {
    if (lipSyncRef.current) lipSyncRef.current.setSmoothing(ac.lipSyncSmoothing);
    if (expressionRef.current) {
      expressionRef.current.setConfig({
        intensity: ac.emotionIntensity,
        duration: ac.emotionDuration,
        recoverSpeed: ac.emotionRecoverSpeed,
      });
    }
    if (motionRef.current) {
      motionRef.current.setConfig({
        emotionMotionProbability: ac.motionTriggerProbability,
        speechMotionProbability: ac.motionTriggerProbability,
        focusSpeed: ac.focusSpeed,
      });
    }
  }, [ac.lipSyncSmoothing, ac.emotionIntensity, ac.emotionDuration, ac.emotionRecoverSpeed, ac.motionTriggerProbability, ac.focusSpeed]);

  // Vowel-based lip sync
  useEffect(() => {
    if (!lipSyncEnabled || !modelRef.current) return;

    // For now, distribute mouthOpenY across vowels
    const weights = {
      a: mouthOpenY * 0.8 * ac.vowelWeightA,
      i: mouthOpenY * 0.2 * ac.vowelWeightI,
      u: mouthOpenY * 0.3 * ac.vowelWeightU,
      e: mouthOpenY * 0.15 * ac.vowelWeightE,
      o: mouthOpenY * 0.25 * ac.vowelWeightO,
    };

    if (lipSyncRef.current) {
      lipSyncRef.current.updateWeights(weights);
    }
  }, [mouthOpenY, lipSyncEnabled, ac.vowelWeightA, ac.vowelWeightI, ac.vowelWeightU, ac.vowelWeightE, ac.vowelWeightO]);

  useEffect(() => {
    const handleResize = () => {
      if (appRef.current && canvasRef.current) {
        appRef.current.renderer.resize(
          canvasRef.current.clientWidth,
          canvasRef.current.clientHeight
        );
        if (modelRef.current) {
          modelRef.current.x = appRef.current.screen.width / 2 + xOffset;
          modelRef.current.y = appRef.current.screen.height / 2 + yOffset;
        }
      }
    };

    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [xOffset, yOffset]);

  useEffect(() => {
    if (modelRef.current) {
      modelRef.current.scale.set(scale);
    }
  }, [scale]);

  useEffect(() => {
    if (modelRef.current && appRef.current) {
      modelRef.current.x = appRef.current.screen.width / 2 + xOffset;
      modelRef.current.y = appRef.current.screen.height / 2 + yOffset;
    }
  }, [xOffset, yOffset]);

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
    <div className="relative w-full h-full">
      {isLoading && (
        <div className="absolute inset-0 flex items-center justify-center bg-[var(--color-bg-secondary)]">
          <div className="flex flex-col items-center">
            <div className="w-8 h-8 border-2 border-[var(--color-accent)] border-t-transparent rounded-full animate-spin" />
            <p className="text-sm text-[var(--color-text-secondary)] mt-2">加载模型...</p>
          </div>
        </div>
      )}
      <canvas
        ref={canvasRef}
        className="w-full h-full"
        style={{ opacity: isLoading ? 0 : 1 }}
      />
    </div>
  );
}
