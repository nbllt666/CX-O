import { useState, useCallback, useRef, useEffect } from 'react';
import { VRMViewer } from './VRMViewer';
import { useSettingsStore } from '../../store/settingsStore';
import { getAvatar } from '../../services/avatarStorage';

interface VRMPanelProps {
  audioElement: HTMLAudioElement | null;
  isPlaying: boolean;
}

export function VRMPanel({ audioElement, isPlaying }: VRMPanelProps) {
  const { vrm, layout, toggleVRMCollapsed, setVRMWidth, setVRMSettings } = useSettingsStore();
  const [mouthOpenY, setMouthOpenY] = useState(0);
  const [isResizing, setIsResizing] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);
  const startXRef = useRef(0);
  const startWidthRef = useRef(0);
  const [modelData, setModelData] = useState<ArrayBuffer | undefined>(undefined);

  useEffect(() => {
    if (vrm.modelId) {
      console.log('[VRMPanel] Loading model:', vrm.modelId);
      getAvatar(vrm.modelId).then((avatar) => {
        if (avatar) {
          console.log('[VRMPanel] Avatar found, size:', avatar.data.size);
          avatar.data.arrayBuffer().then((buf) => {
            console.log('[VRMPanel] ArrayBuffer loaded, byteLength:', buf.byteLength);
            setModelData(buf);
          });
        } else {
          console.warn('[VRMPanel] Avatar not found for id:', vrm.modelId);
          setModelData(undefined);
        }
      });
    } else {
      console.log('[VRMPanel] No modelId, clearing data');
      setModelData(undefined);
    }
  }, [vrm.modelId]);

  useEffect(() => {
    if (!audioElement || !isPlaying || !vrm.lipSync) {
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
  }, [audioElement, isPlaying, vrm.lipSync]);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setIsResizing(true);
    startXRef.current = e.clientX;
    startWidthRef.current = layout.vrmWidth;
  }, [layout.vrmWidth]);

  useEffect(() => {
    if (!isResizing) return;

    const handleMouseMove = (e: MouseEvent) => {
      const deltaX = vrm.position === 'left' ? e.clientX - startXRef.current : startXRef.current - e.clientX;
      const newWidth = Math.max(vrm.minWidth, Math.min(vrm.maxWidth, startWidthRef.current + deltaX));
      setVRMWidth(newWidth);
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
  }, [isResizing, vrm.position, vrm.minWidth, vrm.maxWidth, setVRMWidth]);

  if (!vrm.enabled) {
    return null;
  }

  if (layout.vrmCollapsed) {
    return (
      <div className="flex flex-col items-center py-2 bg-[var(--color-bg-secondary)] border-r border-[var(--color-border)]">
        <button
          onClick={toggleVRMCollapsed}
          className="p-2 rounded hover:bg-[var(--color-bg-hover)] transition-colors"
          title="展开 VRM"
        >
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
          </svg>
        </button>
        <span className="text-xs text-[var(--color-text-tertiary)] mt-1 writing-mode-vertical" style={{ writingMode: 'vertical-rl' }}>
          VRM
        </span>
      </div>
    );
  }

  return (
    <div
      ref={panelRef}
      className="relative flex flex-col bg-[var(--color-bg-secondary)] border-r border-[var(--color-border)]"
      style={{ width: layout.vrmWidth }}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-2 py-1 border-b border-[var(--color-border)]">
        <span className="text-xs font-medium text-[var(--color-text-secondary)]">VRM 3D</span>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setVRMSettings({ lipSync: !vrm.lipSync })}
            className={`p-1 rounded transition-colors ${
              vrm.lipSync ? 'text-[var(--color-accent)]' : 'text-[var(--color-text-tertiary)]'
            }`}
            title={vrm.lipSync ? '关闭口型同步' : '开启口型同步'}
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
            </svg>
          </button>
          <button
            onClick={() => setVRMSettings({ lookAtMouse: !vrm.lookAtMouse })}
            className={`p-1 rounded transition-colors ${
              vrm.lookAtMouse ? 'text-[var(--color-accent)]' : 'text-[var(--color-text-tertiary)]'
            }`}
            title={vrm.lookAtMouse ? '关闭视线追踪' : '开启视线追踪'}
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
            </svg>
          </button>
          <button
            onClick={toggleVRMCollapsed}
            className="p-1 rounded hover:bg-[var(--color-bg-hover)] transition-colors text-[var(--color-text-tertiary)]"
            title="折叠 VRM"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 19l-7-7 7-7m8 14l-7-7 7-7" />
            </svg>
          </button>
        </div>
      </div>

      {/* VRM Canvas */}
      <div className="flex-1 overflow-hidden">
        <VRMViewer
          modelPath={vrm.modelId ? '' : vrm.modelPath}
          modelData={modelData}
          scale={vrm.scale}
          position={vrm.position3d}
          lipSyncEnabled={vrm.lipSync}
          lookAtMouse={vrm.lookAtMouse}
          mouthOpenY={mouthOpenY}
        />
      </div>

      {/* Width indicator */}
      <div className="text-center text-xs text-[var(--color-text-tertiary)] py-1 border-t border-[var(--color-border)]">
        {layout.vrmWidth}px
      </div>

      {/* Resize handle */}
      <div
        className={`absolute top-0 bottom-0 w-1 cursor-ew-resize hover:bg-[var(--color-accent)] transition-colors ${
          isResizing ? 'bg-[var(--color-accent)]' : 'bg-transparent'
        }`}
        style={{ [vrm.position === 'left' ? 'right' : 'left']: 0 }}
        onMouseDown={handleMouseDown}
      />
    </div>
  );
}
