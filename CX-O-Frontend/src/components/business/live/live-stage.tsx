import { useState, useRef, useEffect, useSyncExternalStore, useCallback } from 'react';
import { buildGlassDataAttributes, isValidGlassTier } from '@/components/ui-v2';
import { Live2DViewer } from '../live2d';
import { VRMViewer } from '../vrm';
import { DanmakuOverlay } from './danmaku-overlay';
import { SubtitleDisplay } from './subtitle-display';
import type { IAvatarDriver } from '../avatar/avatar-driver';
import type { ParameterOverride } from '../avatar/avatar-manifest';

// Liquid Glass: data-glass 属性构建（舞台容器层注入）
const glassTier = 'tier-2';
const validTier = isValidGlassTier(glassTier) ? glassTier : undefined;
const glassAttributes = buildGlassDataAttributes(true, validTier);

interface DriverSnapshot {
  avatar: IAvatarDriver['avatar'];
  mouthOpen: number;
  expressionMix: IAvatarDriver['expressionMix'];
  parameterOverrides: IAvatarDriver['parameterOverrides'];
  watermarkVisible: boolean;
  transform: IAvatarDriver['transform'];
}

interface LiveStageProps {
  avatarType?: 'live2d' | 'vrm';
  modelData?: ArrayBuffer;
  danmakuList: Array<{ id: string; content: string; username?: string; color?: string }>;
  subtitleText: string;
  mouthOpenY?: number;
  onModeSwitch?: () => void;
  onAudioPanelClick?: () => void;
  driver?: IAvatarDriver;
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

function DriverLive2DViewer({
  modelData,
  scale,
  xOffset,
  yOffset,
  lipSyncEnabled,
  idleMotionEnabled,
  driver,
}: {
  modelData: ArrayBuffer;
  scale: number;
  xOffset: number;
  yOffset: number;
  lipSyncEnabled: boolean;
  idleMotionEnabled: boolean;
  driver: IAvatarDriver;
}) {
  const state = useDriverState(driver);

  const lipSyncOverrides: ParameterOverride[] = lipSyncEnabled
    ? [{ id: 'ParamMouthOpenY', value: state.mouthOpen }]
    : [];

  const allOverrides: ParameterOverride[] = [
    ...lipSyncOverrides,
    ...state.parameterOverrides,
  ];

  return (
    <Live2DViewer
      modelPath=""
      modelData={modelData}
      scale={scale}
      xOffset={xOffset}
      yOffset={yOffset}
      lipSyncEnabled={false}
      idleMotionEnabled={idleMotionEnabled}
      mouthOpenY={0}
      expressionMix={state.expressionMix}
      parameterOverrides={allOverrides}
      driver={driver}
    />
  );
}

function DriverVRMViewer({
  modelDataRef,
  dataVersion,
  driverKey,
  driver,
}: {
  modelDataRef: React.RefObject<ArrayBuffer | undefined>;
  dataVersion: number;
  driverKey: number;
  driver: IAvatarDriver;
}) {
  const state = useDriverState(driver);

  return (
    <VRMViewer
      key={`vrm-${driverKey}`}
      modelPath=""
      modelDataRef={modelDataRef}
      dataVersion={dataVersion}
      scale={1.0}
      position={[0, -0.3, 0]}
      lipSyncEnabled
      lookAtMouse
      mouthOpenY={state.mouthOpen}
      driver={driver}
    />
  );
}

export function LiveStage({
  avatarType = 'live2d',
  modelData,
  danmakuList,
  subtitleText,
  mouthOpenY = 0,
  onModeSwitch,
  onAudioPanelClick,
  driver,
}: LiveStageProps) {
  const [showControls, setShowControls] = useState(false);
  const modelDataRef = useRef<ArrayBuffer | undefined>(undefined);
  const [dataVersion, setDataVersion] = useState(0);
  const prevDriverRef = useRef<IAvatarDriver | undefined>(driver);
  const [driverKey, setDriverKey] = useState(0);

  useEffect(() => {
    if (modelData !== modelDataRef.current) {
      modelDataRef.current = modelData;
      setDataVersion(v => v + 1);
    }
    return () => {};
  }, [modelData]);

  useEffect(() => {
    if (prevDriverRef.current !== driver) {
      prevDriverRef.current = driver;
      setDriverKey((k) => k + 1);
    }
    return () => {
      const d = prevDriverRef.current;
      if (d && typeof (d as unknown as { destroy?: () => void }).destroy === 'function') {
        try {
          (d as unknown as { destroy: () => void }).destroy();
        } catch {
          /* ignore destroy errors during unmount */
        }
      }
    };
  }, [driver]);

  return (
    <div
      className="w-full h-screen relative overflow-hidden bg-[var(--color-bg-primary)]"
      data-glass={glassAttributes['data-glass'] ?? undefined}
      data-glass-tier={glassAttributes['data-glass-tier'] ?? undefined}
      onMouseEnter={() => setShowControls(true)}
      onMouseLeave={() => setShowControls(false)}
    >
      <div className="absolute inset-0 flex">
        <div
          className="relative flex-shrink-0"
          style={{ width: '55%', height: '100%' }}
        >
          {modelData ? (
            avatarType === 'vrm' ? (
              driver ? (
                <DriverVRMViewer
                  modelDataRef={modelDataRef}
                  dataVersion={dataVersion}
                  driverKey={driverKey}
                  driver={driver}
                />
              ) : (
                <VRMViewer
                  key={`vrm-${driverKey}`}
                  modelPath=""
                  modelDataRef={modelDataRef}
                  dataVersion={dataVersion}
                  scale={1.0}
                  position={[0, -0.3, 0]}
                  lipSyncEnabled
                  lookAtMouse
                  mouthOpenY={mouthOpenY}
                />
              )
            ) : driver ? (
              <DriverLive2DViewer
                key={`live2d-${driverKey}`}
                modelData={modelData}
                scale={0.35}
                xOffset={0}
                yOffset={20}
                lipSyncEnabled
                idleMotionEnabled
                driver={driver}
              />
            ) : (
              <Live2DViewer
                modelPath=""
                modelData={modelData}
                scale={0.35}
                xOffset={0}
                yOffset={20}
                lipSyncEnabled
                idleMotionEnabled
                mouthOpenY={mouthOpenY}
              />
            )
          ) : (
            <div className="flex items-center justify-center h-full text-[var(--color-text-tertiary)]">
              等待模型加载...
            </div>
          )}
        </div>

        <div className="flex-1 relative">
          <DanmakuOverlay danmakuList={danmakuList} />
        </div>
      </div>

      <SubtitleDisplay text={subtitleText} position="bottom" />

      {showControls && (
        <div
          className="absolute bottom-4 left-1/2 -translate-x-1/2 flex gap-3 z-30 transition-opacity duration-200"
          style={{ opacity: showControls ? 1 : 0 }}
          data-glass={glassAttributes['data-glass'] ?? undefined}
          data-glass-tier={glassAttributes['data-glass-tier'] ?? undefined}
        >
          <button
            onClick={onModeSwitch}
            className="px-4 py-2 rounded-lg text-sm font-medium text-[var(--color-text-secondary)] hover:text-[var(--color-accent)] transition-colors bg-[var(--color-bg-secondary)]/60 border border-[var(--color-border)]"
          >
            拆分模式
          </button>
          <button
            onClick={onAudioPanelClick}
            className="px-4 py-2 rounded-lg text-sm font-medium text-[var(--color-text-secondary)] hover:text-[var(--color-accent)] transition-colors bg-[var(--color-bg-secondary)]/60 border border-[var(--color-border)]"
          >
            音频控制
          </button>
        </div>
      )}
    </div>
  );
}

export default LiveStage;
