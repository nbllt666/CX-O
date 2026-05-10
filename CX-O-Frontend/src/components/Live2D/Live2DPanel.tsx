import { useState, useCallback, useRef, useEffect } from 'react';
import { Live2DViewer } from './Live2DViewer';
import { useSettingsStore } from '../../store/settingsStore';
import { getAvatar } from '../../services/avatarStorage';

interface Live2DPanelProps {
  audioElement: HTMLAudioElement | null;
  isPlaying: boolean;
}

export function Live2DPanel({ audioElement, isPlaying }: Live2DPanelProps) {
  const { live2d, layout, toggleLive2DCollapsed, setLive2DWidth, setLive2DSettings } = useSettingsStore();
  const [mouthOpenY, setMouthOpenY] = useState(0);
  const [isResizing, setIsResizing] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);
  const startXRef = useRef(0);
  const startWidthRef = useRef(0);
  const [modelData, setModelData] = useState<ArrayBuffer | undefined>(undefined);

  useEffect(() => {
    if (live2d.modelId) {
      getAvatar(live2d.modelId).then((avatar) => {
        if (avatar) {
          avatar.data.arrayBuffer().then(setModelData);
        }
      });
    } else {
      setModelData(undefined);
    }
  }, [live2d.modelId]);

  useEffect(() => {
    if (!audioElement || !isPlaying || !live2d.lipSync) {
      setMouthOpenY(0);
      return;
    }

    let animationFrame: number;
    const audioContext = new (window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext)();
    const analyser = audioContext.createAnalyser();
    analyser.fftSize = 256;
    analyser.smoothingTimeConstant = 0.8;

    const source = audioContext.createMediaElementSource(audioElement);
    source.connect(analyser);
    analyser.connect(audioContext.destination);

    const dataArray = new Uint8Array(analyser.frequencyBinCount);

    const analyze = () => {
      analyser.getByteFrequencyData(dataArray);
      const sum = dataArray.reduce((acc, val) => acc + val, 0);
      const average = sum / dataArray.length;
      const normalizedVolume = Math.min(average / 100, 1);
      setMouthOpenY(normalizedVolume);
      animationFrame = requestAnimationFrame(analyze);
    };

    analyze();

    return () => {
      cancelAnimationFrame(animationFrame);
      source.disconnect();
      analyser.disconnect();
      audioContext.close();
    };
  }, [audioElement, isPlaying, live2d.lipSync]);

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
      <div className="flex flex-col items-center py-2 bg-[var(--color-bg-secondary)] border-r border-[var(--color-border)]">
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

  return (
    <div
      ref={panelRef}
      className="relative flex flex-col bg-[var(--color-bg-secondary)] border-r border-[var(--color-border)]"
      style={{ width: layout.live2dWidth }}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-2 py-1 border-b border-[var(--color-border)]">
        <span className="text-xs font-medium text-[var(--color-text-secondary)]">Live2D</span>
        <div className="flex items-center gap-1">
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

      {/* Live2D Canvas */}
      <div className="flex-1 overflow-hidden">
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
      </div>

      {/* Width indicator */}
      <div className="text-center text-xs text-[var(--color-text-tertiary)] py-1 border-t border-[var(--color-border)]">
        {layout.live2dWidth}px
      </div>

      {/* Resize handle */}
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
