import { useSettingsStore, AvatarType } from '../../store/settingsStore';
import { Live2DPanel } from '../Live2D';
import { VRMPanel } from '../VRM';

interface AvatarPanelProps {
  audioElement: HTMLAudioElement | null;
  isPlaying: boolean;
}

export function AvatarPanel({ audioElement, isPlaying }: AvatarPanelProps) {
  const { avatarType, live2d, vrm } = useSettingsStore();

  if (avatarType === 'none' || (!live2d.enabled && !vrm.enabled)) {
    return null;
  }

  if (avatarType === 'live2d' && live2d.enabled) {
    return <Live2DPanel audioElement={audioElement} isPlaying={isPlaying} />;
  }

  if (avatarType === 'vrm' && vrm.enabled) {
    return <VRMPanel audioElement={audioElement} isPlaying={isPlaying} />;
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
