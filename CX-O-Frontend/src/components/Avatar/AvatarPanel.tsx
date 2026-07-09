import { useRef, useSyncExternalStore, useCallback } from 'react';
import { useSettingsStore, AvatarType } from '../../store/settingsStore';
import { Live2DPanel } from '../Live2D';
import { VRMPanel } from '../VRM';
import type { IAvatarDriver } from './AvatarDriver';
import type { ExpressionLayer } from './avatarManifest';

interface DriverSnapshot {
  avatar: IAvatarDriver['avatar'];
  mouthOpen: number;
  expressionMix: IAvatarDriver['expressionMix'];
  parameterOverrides: IAvatarDriver['parameterOverrides'];
  watermarkVisible: boolean;
  transform: IAvatarDriver['transform'];
}

interface AvatarPanelProps {
  audioElement: HTMLAudioElement | null;
  isPlaying: boolean;
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

function DriverExpressionOverlay({ driver }: { driver: IAvatarDriver }) {
  const state = useDriverState(driver);
  const activeExpressions = state.expressionMix.filter((layer: ExpressionLayer) => layer.weight > 0);

  const handleEmotionTrigger = useCallback((emotion: string) => {
    driver.setEmotion(emotion, 1.0);
  }, [driver]);

  return (
    <div className="absolute bottom-0 left-0 right-0 z-10 pointer-events-none">
      {activeExpressions.length > 0 && (
        <div className="px-2 py-1 text-xs text-[var(--color-text-tertiary)] bg-[var(--color-bg-secondary)]/80 backdrop-blur-sm border-t border-[var(--color-border)] flex flex-wrap gap-1 items-center">
          <span>表情:</span>
          {activeExpressions.map((layer: ExpressionLayer) => {
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
      )}
      <div className="px-2 py-1 bg-[var(--color-bg-secondary)]/80 backdrop-blur-sm border-t border-[var(--color-border)] pointer-events-auto">
        <div className="flex flex-wrap gap-1">
          {['happy', 'angry', 'sad', 'surprised', 'relaxed', 'neutral'].map((emotion) => (
            <button
              key={emotion}
              onClick={() => handleEmotionTrigger(emotion)}
              className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--color-bg-tertiary)] hover:bg-[var(--color-accent)]/20 text-[var(--color-text-secondary)] hover:text-[var(--color-accent)] transition-colors"
            >
              {emotion}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

export function AvatarPanel({ audioElement, isPlaying, driver }: AvatarPanelProps) {
  const { avatarType, live2d, vrm } = useSettingsStore();

  if (avatarType === 'none' || (!live2d.enabled && !vrm.enabled)) {
    return null;
  }

  if (avatarType === 'live2d' && live2d.enabled) {
    return (
      <div className="relative h-full">
        <Live2DPanel audioElement={audioElement} isPlaying={isPlaying} driver={driver} />
        {driver && <DriverExpressionOverlay driver={driver} />}
      </div>
    );
  }

  if (avatarType === 'vrm' && vrm.enabled) {
    return (
      <div className="relative self-stretch">
        <VRMPanel audioElement={audioElement} isPlaying={isPlaying} driver={driver} />
        {driver && <DriverExpressionOverlay driver={driver} />}
      </div>
    );
  }

  return null;
}

export function AvatarTypeSelector() {
  const { avatarType, setAvatarType } = useSettingsStore();

  const avatarTypes: { type: AvatarType; label: string; icon: React.ReactNode }[] = [
    {
      type: 'none',
      label: '无',
      icon: (
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636" />
        </svg>
      ),
    },
    {
      type: 'live2d',
      label: 'Live2D',
      icon: (
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.828 14.828a4 4 0 01-5.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
      ),
    },
    {
      type: 'vrm',
      label: 'VRM 3D',
      icon: (
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
        </svg>
      ),
    },
  ];

  return (
    <div className="flex items-center gap-1 p-1 bg-[var(--color-bg-tertiary)] rounded-lg">
      {avatarTypes.map(({ type, label, icon }) => (
        <button
          key={type}
          onClick={() => setAvatarType(type)}
          className={`flex items-center gap-1.5 px-2 py-1 rounded text-xs transition-colors ${
            avatarType === type
              ? 'bg-[var(--color-accent)] text-white'
              : 'text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-hover)]'
          }`}
          title={`切换到 ${label}`}
        >
          {icon}
          <span>{label}</span>
        </button>
      ))}
    </div>
  );
}
