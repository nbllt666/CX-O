import { useState, useCallback, useRef, useEffect, useSyncExternalStore, useMemo } from 'react';
import { Live2DViewer } from './live2d-viewer';
import { Live2DStage } from './live2d-stage';
import { buildGlassDataAttributes, isValidGlassTier } from '@/components/ui-v2';
import type { IAvatarDriver } from '../avatar/avatar-driver';
import type { ParameterOverride } from '../avatar/avatar-manifest';
import type { StageTransform } from './live2d-engine';
import { useSettingsStore } from '@/store/settingsStore';
import { getAvatar } from '@/services/avatarStorage';
import { useAudioAnalyzer } from '@/hooks/useAudioAnalyzer';

// Liquid Glass: data-glass 属性构建（面板容器注入）
const glassTier = 'tier-2';
const validTier = isValidGlassTier(glassTier) ? glassTier : undefined;
const glassAttributes = buildGlassDataAttributes(true, validTier);

interface Live2DPanelProps {
  audioElement: HTMLAudioElement | null;
  isPlaying: boolean;
  driver?: IAvatarDriver;
}

interface DriverSnapshot {
  avatar: IAvatarDriver['avatar'];
  mouthOpen: number;
  expressionMix: IAvatarDriver['expressionMix'];
  parameterOverrides: IAvatarDriver['parameterOverrides'];
  watermarkVisible: boolean;
  transform: IAvatarDriver['transform'];
}

function useDriverState(driver: IAvatarDriver) {
  const prevSnapshotRef = useRef<DriverSnapshot | null>(null);
  const getSnapshot = useCallback(() => {
    const newSnapshot: DriverSnapshot = {
      avatar: driver.avatar,
      mouthOpen: driver.mouthOpen,
      expressionMix: driver.expressionMix,
      parameterOverrides: driver.parameterOverrides,
      watermarkVisible: driver.watermarkVisible,
      transform: driver.transform,
    };
    if (prevSnapshotRef.current) {
      const prev = prevSnapshotRef.current;
      if (
        prev.avatar === newSnapshot.avatar &&
        prev.mouthOpen === newSnapshot.mouthOpen &&
        prev.expressionMix === newSnapshot.expressionMix &&
        prev.parameterOverrides === newSnapshot.parameterOverrides &&
        prev.watermarkVisible === newSnapshot.watermarkVisible &&
        prev.transform === newSnapshot.transform
      ) {
        return prev;
      }
    }
    prevSnapshotRef.current = newSnapshot;
    return newSnapshot;
  }, [driver]);
  const subscribe = useCallback((listener: () => void) => driver.subscribe(listener), [driver]);
  return useSyncExternalStore(subscribe, getSnapshot);
}

function ExpressionInfo({ driver }: { driver: IAvatarDriver }) {
  const state = useDriverState(driver);
  const activeExpressions = state.expressionMix.filter((layer) => layer.weight > 0);

  if (activeExpressions.length === 0) {
    return (
      <div className="px-2 py-1 text-xs text-[var(--color-text-tertiary)] border-t border-[var(--color-border)]">
        表情: 默认
      </div>
    );
  }

  return (
    <div className="px-2 py-1 text-xs text-[var(--color-text-tertiary)] border-t border-[var(--color-border)] flex flex-wrap gap-1 items-center">
      <span>表情:</span>
      {activeExpressions.map((layer) => {
        const expressionItem = driver.avatar.expressions.find((e) => e.id === layer.key);
        const label = expressionItem?.label ?? layer.key;
        return (
          <span
            key={layer.key}
            className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded bg-[var(--color-bg-tertiary)] text-[var(--color-text-secondary)]"
          >
            {label}
            <span className="text-[10px] opacity-60">{Math.round(layer.weight * 100)}%</span>
          </span>
        );
      })}
    </div>
  );
}

export function Live2DPanel({ audioElement, isPlaying, driver }: Live2DPanelProps) {
  const { live2d, layout, toggleLive2DCollapsed, setLive2DWidth, setLive2DSettings } = useSettingsStore();
  const [isResizing, setIsResizing] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);
  const startXRef = useRef(0);
  const startWidthRef = useRef(0);
  const [modelData, setModelData] = useState<ArrayBuffer | undefined>(undefined);

  const { volume: mouthOpenY } = useAudioAnalyzer({
    audioElement,
    isPlaying,
    enabled: live2d.lipSync,
  });

  useEffect(() => {
    if (live2d.modelId) {
      getAvatar(live2d.modelId).then((avatar) => {
        if (avatar?.data) {
          avatar.data.arrayBuffer().then(setModelData);
        }
      });
    } else {
      setModelData(undefined);
    }
  }, [live2d.modelId]);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setIsResizing(true);
    startXRef.current = e.clientX;
    startWidthRef.current = layout.live2dWidth;
  }, [layout.live2dWidth]);

  useEffect(() => {
    if (!isResizing) return;

    const handleMouseMove = (e: MouseEvent) => {
      const deltaX = live2d.position === 'left' ? e.clientX - startXRef.current : startXRef.current - e.clientX;
      const newWidth = Math.max(live2d.minWidth, Math.min(live2d.maxWidth, startWidthRef.current + deltaX));
      setLive2DWidth(newWidth);
    };

    const handleMouseUp = () => {
      setIsResizing(false);
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isResizing, live2d.position, live2d.minWidth, live2d.maxWidth, setLive2DWidth]);

  if (!live2d.enabled) {
    return null;
  }

  if (layout.live2dCollapsed) {
    return (
      <div className={`flex flex-col items-center py-2 bg-[var(--color-bg-secondary)] ${live2d.position === 'left' ? 'border-r' : 'border-l'} border-[var(--color-border)]`}>
        <button
          onClick={toggleLive2DCollapsed}
          className="p-2 rounded hover:bg-[var(--color-bg-hover)] transition-colors"
          title="展开 Live2D"
        >
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
          </svg>
        </button>
        <span className="text-xs text-[var(--color-text-tertiary)] mt-1 writing-mode-vertical" style={{ writingMode: 'vertical-rl' }}>
          Live2D
        </span>
      </div>
    );
  }

  const stageContent = driver ? (
    <DriverStageContent driver={driver} lipSyncEnabled={live2d.lipSync} mouthOpenY={mouthOpenY} />
  ) : (
    <Live2DViewer
      modelPath={live2d.modelId ? '' : live2d.modelPath}
      modelData={modelData}
      scale={live2d.scale}
      xOffset={live2d.xOffset}
      yOffset={live2d.yOffset}
      lipSyncEnabled={live2d.lipSync}
      idleMotionEnabled={live2d.idleMotion}
      mouthOpenY={mouthOpenY}
    />
  );

  return (
    <div
      ref={panelRef}
      className={`relative flex flex-col bg-[var(--color-bg-secondary)] ${live2d.position === 'left' ? 'border-r' : 'border-l'} border-[var(--color-border)]`}
      style={{ width: layout.live2dWidth }}
      data-glass={glassAttributes['data-glass'] ?? undefined}
      data-glass-tier={glassAttributes['data-glass-tier'] ?? undefined}
    >
      <div className="flex items-center justify-between px-2 py-1 border-b border-[var(--color-border)]">
        <span className="text-xs font-medium text-[var(--color-text-secondary)]">Live2D</span>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setLive2DSettings({ position: live2d.position === 'left' ? 'right' : 'left' })}
            className="p-1 rounded hover:bg-[var(--color-bg-hover)] transition-colors text-[var(--color-text-tertiary)]"
            title={live2d.position === 'left' ? '移到右侧' : '移到左侧'}
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4" />
            </svg>
          </button>
          <button
            onClick={() => setLive2DSettings({ lipSync: !live2d.lipSync })}
            className={`p-1 rounded transition-colors ${
              live2d.lipSync ? 'text-[var(--color-accent)]' : 'text-[var(--color-text-tertiary)]'
            }`}
            title={live2d.lipSync ? '关闭口型同步' : '开启口型同步'}
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
            </svg>
          </button>
          <button
            onClick={toggleLive2DCollapsed}
            className="p-1 rounded hover:bg-[var(--color-bg-hover)] transition-colors text-[var(--color-text-tertiary)]"
            title="折叠 Live2D"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 19l-7-7 7-7m8 14l-7-7 7-7" />
            </svg>
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-hidden">
        {stageContent}
      </div>

      {driver && <ExpressionInfo driver={driver} />}

      <div className="text-center text-xs text-[var(--color-text-tertiary)] py-1 border-t border-[var(--color-border)]">
        {layout.live2dWidth}px
      </div>

      <div
        className={`absolute top-0 bottom-0 w-1 cursor-ew-resize hover:bg-[var(--color-accent)] transition-colors ${
          isResizing ? 'bg-[var(--color-accent)]' : 'bg-transparent'
        }`}
        style={{ [live2d.position === 'left' ? 'right' : 'left']: 0 }}
        onMouseDown={handleMouseDown}
      />
    </div>
  );
}

function DriverStageContent({
  driver,
  lipSyncEnabled,
  mouthOpenY,
}: {
  driver: IAvatarDriver;
  lipSyncEnabled: boolean;
  mouthOpenY: number;
}) {
  const state = useDriverState(driver);

  const lipSyncOverrides = useMemo<ParameterOverride[]>(() => {
    if (!lipSyncEnabled) return [];
    return [{ id: 'ParamMouthOpenY', value: mouthOpenY }];
  }, [lipSyncEnabled, mouthOpenY]);

  const allOverrides = useMemo<ParameterOverride[]>(() => {
    return [...lipSyncOverrides, ...state.parameterOverrides];
  }, [lipSyncOverrides, state.parameterOverrides]);

  const [transform, setTransform] = useState<StageTransform>(state.transform);

  return (
    <Live2DStage
      avatar={state.avatar}
      expressionMix={state.expressionMix}
      parameterOverrides={allOverrides}
      watermarkVisible={state.watermarkVisible}
      transform={transform}
      onTransformChange={setTransform}
      driver={driver}
    />
  );
}
