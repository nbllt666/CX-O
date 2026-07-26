import { useState, useCallback, useRef, useEffect } from 'react';
import { VRMViewer } from './vrm-viewer';
import { buildGlassDataAttributes, isValidGlassTier } from '@/components/ui-v2';
import { useSettingsStore } from '@/store/settingsStore';
import type { VRMWindConfig } from '@/store/settingsStore';
import { getAvatar } from '@/services/avatarStorage';
import { useAudioAnalyzer } from '@/hooks/useAudioAnalyzer';
import type { IAvatarDriver } from '../avatar/avatar-driver';
import type { ExpressionLayer } from '../avatar/avatar-manifest';

// Liquid Glass: data-glass 属性构建（面板容器注入）
const glassTier = 'tier-2';
const validTier = isValidGlassTier(glassTier) ? glassTier : undefined;
const glassAttributes = buildGlassDataAttributes(true, validTier);

interface VRMPanelProps {
  audioElement: HTMLAudioElement | null;
  isPlaying: boolean;
  driver?: IAvatarDriver;
}

export function VRMPanel({ audioElement, isPlaying, driver }: VRMPanelProps) {
  const { vrm, layout, toggleVRMCollapsed, setVRMWidth, setVRMSettings } = useSettingsStore();
  const [isResizing, setIsResizing] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);
  const startXRef = useRef(0);
  const startWidthRef = useRef(0);
  const modelDataRef = useRef<ArrayBuffer | undefined>(undefined);
  const [dataVersion, setDataVersion] = useState(0);
  const [activeExpressions, setActiveExpressions] = useState<ExpressionLayer[]>([]);
  const [showExpressionInfo, setShowExpressionInfo] = useState(false);
  const [showWindSettings, setShowWindSettings] = useState(false);

  const { volume: mouthOpenY } = useAudioAnalyzer({
    audioElement,
    isPlaying,
    enabled: vrm.lipSync,
  });

  useEffect(() => {
    if (vrm.modelId) {
      getAvatar(vrm.modelId).then((avatar) => {
        if (avatar?.data) {
          avatar.data.arrayBuffer().then((buf) => {
            modelDataRef.current = buf;
            setDataVersion(v => v + 1);
          });
        } else {
          modelDataRef.current = undefined;
          setDataVersion(v => v + 1);
        }
      });
    } else {
      modelDataRef.current = undefined;
      setDataVersion(v => v + 1);
    }
  }, [vrm.modelId]);

  useEffect(() => {
    if (!driver) return;
    const interval = setInterval(() => {
      setActiveExpressions(driver.getActiveExpressions());
    }, 500);
    return () => clearInterval(interval);
  }, [driver]);

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

  const handleEmotionTrigger = useCallback((emotion: string) => {
    if (driver) {
      driver.setEmotion(emotion, 1.0);
      driver.triggerEmotionMotion(emotion as 'happy' | 'angry' | 'sad' | 'surprised' | 'relaxed' | 'neutral');
    }
  }, [driver]);

  const handleWindChange = useCallback(<K extends keyof VRMWindConfig>(key: K, value: VRMWindConfig[K]) => {
    const newWind = { ...vrm.wind, [key]: value };
    setVRMSettings({ wind: newWind });
    if (driver) {
      driver.setWind({ [key]: value });
    }
  }, [vrm.wind, setVRMSettings, driver]);

  if (!vrm.enabled) {
    return null;
  }

  if (layout.vrmCollapsed) {
    return (
      <div className={`flex flex-col items-center py-2 bg-[var(--color-bg-secondary)] ${vrm.position === 'left' ? 'border-r' : 'border-l'} border-[var(--color-border)]`}>
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
      className={`relative flex flex-col h-full bg-[var(--color-bg-secondary)] ${vrm.position === 'left' ? 'border-r' : 'border-l'} border-[var(--color-border)]`}
      style={{ width: layout.vrmWidth }}
      data-glass={glassAttributes['data-glass'] ?? undefined}
      data-glass-tier={glassAttributes['data-glass-tier'] ?? undefined}
    >
      <div className="flex items-center justify-between px-2 py-1 border-b border-[var(--color-border)]">
        <span className="text-xs font-medium text-[var(--color-text-secondary)]">VRM 3D</span>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setVRMSettings({ position: vrm.position === 'left' ? 'right' : 'left' })}
            className="p-1 rounded hover:bg-[var(--color-bg-hover)] transition-colors text-[var(--color-text-tertiary)]"
            title={vrm.position === 'left' ? '移到右侧' : '移到左侧'}
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4" />
            </svg>
          </button>
          {driver && (
            <button
              onClick={() => setShowExpressionInfo(!showExpressionInfo)}
              className={`p-1 rounded transition-colors ${
                showExpressionInfo ? 'text-[var(--color-accent)]' : 'text-[var(--color-text-tertiary)]'
              }`}
              title={showExpressionInfo ? '隐藏表情信息' : '显示表情信息'}
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.828 14.828a4 4 0 01-5.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </button>
          )}
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
            onClick={() => setShowWindSettings(!showWindSettings)}
            className={`p-1 rounded transition-colors ${
              showWindSettings ? 'text-[var(--color-accent)]' : 'text-[var(--color-text-tertiary)]'
            }`}
            title={showWindSettings ? '隐藏风场设置' : '显示风场设置'}
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.59 4.59A2 2 0 1111 8H2m10.59 11.41A2 2 0 1014 16H2m15.73-8.27A2.5 2.5 0 1119.5 12H2" />
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

      {driver && showExpressionInfo && (
        <div className="px-2 py-1 border-b border-[var(--color-border)] bg-[var(--color-bg-tertiary)]">
          <div className="text-xs text-[var(--color-text-tertiary)] mb-1">活跃表情</div>
          {activeExpressions.length === 0 ? (
            <div className="text-xs text-[var(--color-text-tertiary)]">无</div>
          ) : (
            <div className="flex flex-wrap gap-1">
              {activeExpressions.map((expr, i) => (
                <span
                  key={`${expr.key}-${i}`}
                  className="text-xs px-1.5 py-0.5 rounded bg-[var(--color-accent)]/20 text-[var(--color-accent)]"
                >
                  {expr.key} {(expr.weight * 100).toFixed(0)}%
                </span>
              ))}
            </div>
          )}
          <div className="text-xs text-[var(--color-text-tertiary)] mt-1 mb-1">动作触发</div>
          <div className="flex flex-wrap gap-1">
            {['happy', 'angry', 'sad', 'surprised', 'relaxed'].map((emotion) => (
              <button
                key={emotion}
                onClick={() => handleEmotionTrigger(emotion)}
                className="text-xs px-1.5 py-0.5 rounded bg-[var(--color-bg-secondary)] hover:bg-[var(--color-accent)]/20 text-[var(--color-text-secondary)] hover:text-[var(--color-accent)] transition-colors"
              >
                {emotion}
              </button>
            ))}
          </div>
        </div>
      )}

      {showWindSettings && (
        <div className="px-2 py-1.5 border-b border-[var(--color-border)] bg-[var(--color-bg-tertiary)]">
          <div className="text-xs text-[var(--color-text-tertiary)] mb-1">风场设置</div>
          <div className="flex flex-col gap-1.5">
            <WindSlider
              label="方向"
              value={vrm.wind.direction}
              min={0}
              max={360}
              step={1}
              onChange={v => handleWindChange('direction', v)}
              format={v => `${v.toFixed(0)}°`}
            />
            <WindSlider
              label="强度"
              value={vrm.wind.strength}
              min={0}
              max={1}
              step={0.01}
              onChange={v => handleWindChange('strength', v)}
            />
            <WindSlider
              label="阵风强度"
              value={vrm.wind.gustStrength}
              min={0}
              max={1}
              step={0.01}
              onChange={v => handleWindChange('gustStrength', v)}
            />
            <WindSlider
              label="阵风频率"
              value={vrm.wind.gustFrequency}
              min={0.1}
              max={5}
              step={0.1}
              onChange={v => handleWindChange('gustFrequency', v)}
              format={v => `${v.toFixed(1)}Hz`}
            />
            <div className="flex flex-col gap-0.5">
              <div className="flex justify-between">
                <span className="text-[var(--color-text-secondary)] text-xs">阵风持续</span>
                <span className="text-[var(--color-text-tertiary)] tabular-nums w-12 text-right text-xs">
                  {typeof vrm.wind.gustDuration === 'number' ? `${vrm.wind.gustDuration.toFixed(1)}s` : vrm.wind.gustDuration}
                </span>
              </div>
              <input
                type="text"
                value={vrm.wind.gustDuration}
                onChange={e => {
                  const raw = e.target.value;
                  const num = parseFloat(raw);
                  if (!isNaN(num)) {
                    handleWindChange('gustDuration', num);
                  } else if (/^\d+(\.\d+)?-\d+(\.\d+)?$/.test(raw)) {
                    handleWindChange('gustDuration', raw);
                  }
                }}
                className="w-full h-6 px-1.5 rounded bg-[var(--color-bg-secondary)] border border-[var(--color-border)] text-xs text-[var(--color-text-primary)] outline-none focus:border-[var(--color-accent)]"
                placeholder="秒数 或 min-max"
              />
            </div>
          </div>
        </div>
      )}

      <div className="flex-1 overflow-hidden">
        <VRMViewer
          modelPath={vrm.modelId ? '' : vrm.modelPath}
          modelDataRef={modelDataRef}
          dataVersion={dataVersion}
          scale={vrm.scale}
          position={vrm.position3d}
          lipSyncEnabled={vrm.lipSync}
          lookAtMouse={vrm.lookAtMouse}
          mouthOpenY={mouthOpenY}
          tweakConfig={vrm.tweak}
          driver={driver}
          animationConfig={vrm.animation}
          renderScale={vrm.renderScale}
          devicePixelRatio={vrm.devicePixelRatio}
          idleAnimation={vrm.idleAnimation}
          windConfig={vrm.wind}
        />
      </div>

      <div className="text-center text-xs text-[var(--color-text-tertiary)] py-1 border-t border-[var(--color-border)]">
        {layout.vrmWidth}px
      </div>

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

function WindSlider({
  label,
  value,
  min,
  max,
  step,
  onChange,
  format = v => v.toFixed(2),
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: number) => void;
  format?: (v: number) => string;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <div className="flex justify-between">
        <span className="text-[var(--color-text-secondary)] text-xs">{label}</span>
        <span className="text-[var(--color-text-tertiary)] tabular-nums w-12 text-right text-xs">{format(value)}</span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={e => onChange(parseFloat(e.target.value))}
        className="w-full h-1 rounded-full appearance-none cursor-pointer accent-[var(--color-accent)]
          [&::-webkit-slider-runnable-track]:rounded-full [&::-webkit-slider-runnable-track]:h-1
          [&::-webkit-slider-runnable-track]:bg-[var(--color-bg-secondary)]
          [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3
          [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-[var(--color-accent)]
          [&::-webkit-slider-thumb]:mt-[-4px]"
      />
    </div>
  );
}
