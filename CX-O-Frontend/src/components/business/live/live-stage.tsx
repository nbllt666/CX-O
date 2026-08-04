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
          {/* 弹幕飘屏层：覆盖模型画面，新弹幕从右向左飘过 */}
          <DanmakuOverlay danmakuList={danmakuList} position="full" />
        </div>

        {/* 右侧：弹幕互动面板（列表 + 空态），消除无弹幕时的大片空白 */}
        <div className="flex-1 relative p-4">
          <div
            className="glass-panel h-full rounded-xl flex flex-col overflow-hidden"
          >
            <div className="px-4 py-3 border-b border-[var(--color-border)] flex items-center justify-between flex-shrink-0">
              <span className="text-sm font-medium text-[var(--color-text-primary)]">弹幕互动</span>
              <span className="text-xs text-[var(--color-text-tertiary)]">
                {danmakuList.length} 条
              </span>
            </div>
            <div className="flex-1 overflow-y-auto px-4 py-3 flex flex-col justify-end gap-2">
              {danmakuList.length === 0 ? (
                <div className="flex-1 flex flex-col items-center justify-center text-center gap-2">
                  <svg
                    className="w-10 h-10 text-[var(--color-text-tertiary)] opacity-50"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={1.5}
                      d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
                    />
                  </svg>
                  <p className="text-sm text-[var(--color-text-tertiary)]">暂无弹幕</p>
                  <p className="text-xs text-[var(--color-text-tertiary)] opacity-70">
                    等待观众互动...
                  </p>
                </div>
              ) : (
                danmakuList.map((item) => (
                  <div key={item.id} className="text-sm leading-relaxed break-words">
                    {item.username && (
                      <span className="text-[var(--color-warning)] mr-1.5 font-medium">
                        {item.username}:
                      </span>
                    )}
                    <span style={{ color: item.color || 'var(--color-text-primary)' }}>
                      {item.content}
                    </span>
                  </div>
                ))
              )}
            </div>
          </div>
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
