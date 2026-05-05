import { useEffect, useRef, useCallback, useState } from 'react';
import * as PIXI from 'pixi.js';
import { Live2DModel } from 'pixi-live2d-display';

(window as unknown as { PIXI: typeof PIXI }).PIXI = PIXI;

interface Live2DViewerProps {
  modelPath: string;
  scale?: number;
  xOffset?: number;
  yOffset?: number;
  lipSyncEnabled?: boolean;
  idleMotionEnabled?: boolean;
  mouthOpenY?: number;
  onModelLoaded?: () => void;
  onError?: (error: Error) => void;
}

export function Live2DViewer({
  modelPath,
  scale = 0.3,
  xOffset = 0,
  yOffset = 0,
  lipSyncEnabled = true,
  idleMotionEnabled = true,
  mouthOpenY = 0,
  onModelLoaded,
  onError,
}: Live2DViewerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const appRef = useRef<PIXI.Application | null>(null);
  const modelRef = useRef<Live2DModel | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const loadModel = useCallback(async () => {
    if (!canvasRef.current) return;

    try {
      setIsLoading(true);
      setLoadError(null);

      if (appRef.current) {
        appRef.current.destroy(true, { children: true });
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

      const model = await Live2DModel.from(modelPath, {
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

      setIsLoading(false);
      onModelLoaded?.();
    } catch (error) {
      console.error('Live2D: Failed to load model:', error);
      const errorMessage = error instanceof Error ? error.message : 'Unknown error';
      setLoadError(errorMessage);
      setIsLoading(false);
      onError?.(error instanceof Error ? error : new Error(errorMessage));
    }
  }, [modelPath, scale, xOffset, yOffset, idleMotionEnabled, onModelLoaded, onError]);

  useEffect(() => {
    loadModel();

    return () => {
      if (appRef.current) {
        appRef.current.destroy(true, { children: true });
        appRef.current = null;
      }
      modelRef.current = null;
    };
  }, [loadModel]);

  useEffect(() => {
    if (lipSyncEnabled && modelRef.current && mouthOpenY !== undefined) {
      try {
        const coreModel = modelRef.current.internalModel?.coreModel as Record<string, unknown> | undefined;
        if (coreModel) {
          if (typeof coreModel.setParameterValueById === 'function') {
            (coreModel.setParameterValueById as (id: string, value: number) => void)('ParamMouthOpenY', mouthOpenY);
          } else if (typeof coreModel.setParameterValue === 'function') {
            const getParameterIndex = coreModel.getParameterIndex as ((name: string) => number) | undefined;
            const paramIndex = getParameterIndex?.('ParamMouthOpenY');
            if (paramIndex !== undefined && paramIndex >= 0) {
              (coreModel.setParameterValue as (index: number, value: number) => void)(paramIndex, mouthOpenY);
            }
          }
        }
      } catch (error) {
        console.warn('Live2D: Failed to set mouth parameter:', error);
      }
    }
  }, [mouthOpenY, lipSyncEnabled]);

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
    return (
      <div className="flex flex-col items-center justify-center h-full text-center p-4">
        <div className="text-red-500 mb-2">
          <svg className="w-12 h-12 mx-auto" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
        </div>
        <p className="text-sm text-[var(--color-text-secondary)]">模型加载失败</p>
        <p className="text-xs text-[var(--color-text-tertiary)] mt-1">{loadError}</p>
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
