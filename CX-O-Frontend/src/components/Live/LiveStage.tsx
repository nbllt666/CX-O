import { useState } from 'react';
import { Live2DViewer } from '../Live2D';
import { VRMViewer } from '../VRM';
import { DanmakuOverlay } from './DanmakuOverlay';
import { SubtitleDisplay } from './SubtitleDisplay';

interface LiveStageProps {
  avatarType?: 'live2d' | 'vrm';
  modelData?: ArrayBuffer;
  danmakuList: Array<{ id: string; content: string; username?: string; color?: string }>;
  subtitleText: string;
  mouthOpenY?: number;
  onModeSwitch?: () => void;
  onAudioPanelClick?: () => void;
}

export function LiveStage({
  avatarType = 'live2d',
  modelData,
  danmakuList,
  subtitleText,
  mouthOpenY = 0,
  onModeSwitch,
  onAudioPanelClick,
}: LiveStageProps) {
  const [showControls, setShowControls] = useState(false);

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
                modelData={modelData}
                scale={1.0}
                position={[0, -0.3, 0]}
                lipSyncEnabled
                lookAtMouse
                mouthOpenY={mouthOpenY}
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
