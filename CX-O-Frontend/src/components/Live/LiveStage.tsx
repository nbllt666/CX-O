import { useState, useRef, useEffect, useSyncExternalStore, useCallback } from 'react';
import { Live2DViewer } from '../Live2D';
import { VRMViewer } from '../VRM';
import { DanmakuOverlay } from './DanmakuOverlay';
import { SubtitleDisplay } from './SubtitleDisplay';
import type { IAvatarDriver } from '../Avatar/AvatarDriver';
import type { ParameterOverride } from '../Avatar/avatarManifest';

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
  const getSnapshot = useCallback(() => driver, [driver]);
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

  useEffect(() => {
    if (modelData !== modelDataRef.current) {
      modelDataRef.current = modelData;
      setDataVersion(v => v + 1);
    }
    return () => {};
  }, [modelData]);

  return (
    <div
      className="w-full h-screen relative overflow-hidden"
      style={{ backgroundColor: '#1a1a2e' }}
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
              <VRMViewer
                modelPath=""
                modelDataRef={modelDataRef}
                dataVersion={dataVersion}
                scale={1.0}
                position={[0, -0.3, 0]}
                lipSyncEnabled
                lookAtMouse
                mouthOpenY={driver ? driver.mouthOpen : mouthOpenY}
                driver={driver}
              />
            ) : driver ? (
              <DriverLive2DViewer
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
        >
          <button
            onClick={onModeSwitch}
            className="px-4 py-2 rounded-lg text-sm font-medium text-white/80 hover:text-white transition-colors"
            style={{
              background: 'rgba(255,255,255,0.1)',
              backdropFilter: 'blur(8px)',
              border: '1px solid rgba(255,255,255,0.15)',
            }}
          >
            拆分模式
          </button>
          <button
            onClick={onAudioPanelClick}
            className="px-4 py-2 rounded-lg text-sm font-medium text-white/80 hover:text-white transition-colors"
            style={{
              background: 'rgba(255,255,255,0.1)',
              backdropFilter: 'blur(8px)',
              border: '1px solid rgba(255,255,255,0.15)',
            }}
          >
            音频控制
          </button>
        </div>
      )}
    </div>
  );
}

export default LiveStage;
