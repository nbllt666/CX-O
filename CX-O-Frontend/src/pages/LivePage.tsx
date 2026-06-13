import { useState, useCallback, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { LiveStage } from '../components/Live/LiveStage';
import { useLiveWebSocket } from '../hooks/useLiveWebSocket';
import { useSettingsStore } from '../store/settingsStore';
import { getAvatar } from '../services/avatarStorage';
import type { LiveDanmakuData } from '../hooks/useLiveWebSocket';
import type { IAvatarDriver } from '../components/Avatar/AvatarDriver';
import { createAvatarDriver } from '../components/Avatar/AvatarDriver';
import { resolveAvatarManifestById, getAvatarById } from '../components/Avatar/avatarManifest';
import { parseAvatarTags, type AvatarTag } from '../lib/avatarTagParser';

function applyAvatarTags(driver: IAvatarDriver, tags: AvatarTag[]) {
  for (const tag of tags) {
    switch (tag.type) {
      case 'emotion':
        driver.setEmotion(tag.name, 1.0);
        break;
      case 'blend':
        driver.setBlendShapes([{ name: tag.name, weight: tag.weight }]);
        break;
      case 'bone':
        driver.setBoneRotations([{ boneName: tag.boneName, rotation: tag.rotation, speed: tag.speed }]);
        break;
      case 'pose':
        driver.holdPose(tag.durationMs);
        break;
      case 'release':
        driver.releasePose();
        break;
      case 'wind':
        driver.setWind(tag);
        break;
      case 'sleep':
        console.log('[avatar] sleep tag:', tag.ms, 'ms');
        break;
    }
  }
}

export function LivePage() {
  const navigate = useNavigate();
  const [danmakuList, setDanmakuList] = useState<LiveDanmakuData[]>([]);
  const [subtitleText, setSubtitleText] = useState('');
  const [mouthOpenY, setMouthOpenY] = useState(0);
  const [modelData, setModelData] = useState<ArrayBuffer | undefined>(undefined);
  const [activeDriver, setActiveDriver] = useState<IAvatarDriver | null>(null);
  const driverRef = useRef<IAvatarDriver | null>(null);

  const { live2d, vrm, avatarType } = useSettingsStore();
  const currentModelId = avatarType === 'live2d' ? live2d.modelId : vrm.modelId;

  useEffect(() => {
    let cancelled = false;
    if (currentModelId) {
      getAvatar(currentModelId).then((avatar) => {
        if (cancelled) return;
        if (avatar?.data) {
          avatar.data.arrayBuffer().then((buffer) => {
            if (cancelled) return;
            setModelData(buffer);
          });
        } else {
          setModelData(undefined);
        }
      });
    } else {
      setModelData(undefined);
    }
    return () => {
      cancelled = true;
    };
  }, [currentModelId]);

  useEffect(() => {
    let cancelled = false;
    const avatarId = avatarType === 'live2d' ? (live2d.modelId || 'yumi') : (vrm.modelId || undefined);
    const baseAvatar = avatarId ? getAvatarById(avatarId) : undefined;
    if (!baseAvatar) {
      driverRef.current = null;
      setActiveDriver(null);
      return;
    }
    resolveAvatarManifestById(baseAvatar.id)
      .then((manifest) => {
        if (cancelled) return;
        const driver = createAvatarDriver(manifest);
        driverRef.current = driver;
        setActiveDriver(driver);
      })
      .catch(() => {
        if (cancelled) return;
        const driver = createAvatarDriver(baseAvatar);
        driverRef.current = driver;
        setActiveDriver(driver);
      });
    return () => { cancelled = true; };
  }, [avatarType, live2d.modelId, vrm.modelId]);

  const handleDanmaku = useCallback((data: LiveDanmakuData) => {
    setDanmakuList((prev) => [
      ...prev.slice(-49),
      {
        id: data.id || `dm-${Date.now()}`,
        content: data.content,
        username: data.username,
        color: data.color,
      },
    ]);
  }, []);

  const handleStreamContent = useCallback((content: string) => {
    const { cleanText, tags } = parseAvatarTags(content);
    setSubtitleText(cleanText);
    const driver = driverRef.current;
    if (driver) {
      applyAvatarTags(driver, tags);
    }
  }, []);

  const handleVadStatus = useCallback((data: { status: string; speech_duration_ms: number; speech_probability?: number }) => {
    if (data.status === 'speech_start' && data.speech_probability !== undefined) {
      const value = Math.min(data.speech_probability * 1.5, 1);
      setMouthOpenY(value);
      driverRef.current?.setMouthOpen(value);
    } else if (data.status === 'speech_end') {
      setMouthOpenY(0);
      driverRef.current?.setMouthOpen(0);
    }
  }, []);

  const { isConnected, connectionCount } = useLiveWebSocket({
    onDanmaku: handleDanmaku,
    onStreamContent: handleStreamContent,
    onVadStatus: handleVadStatus,
  });

  return (
    <div className="w-full h-screen">
      <LiveStage
        avatarType={avatarType === 'none' ? 'live2d' : avatarType}
        modelData={modelData}
        danmakuList={danmakuList}
        subtitleText={subtitleText}
        mouthOpenY={mouthOpenY}
        onModeSwitch={() => navigate('/live/split')}
        onAudioPanelClick={() => navigate('/audio')}
        driver={activeDriver ?? undefined}
      />

      <div
        className="absolute top-4 right-4 flex items-center gap-2 px-3 py-1.5 rounded-full text-xs z-40"
        style={{
          background: 'rgba(0,0,0,0.5)',
          color: isConnected ? '#4ade80' : '#f87171',
          backdropFilter: 'blur(8px)',
        }}
      >
        <span
          className="w-2 h-2 rounded-full animate-pulse"
          style={{ backgroundColor: isConnected ? '#4ade80' : '#f87171' }}
        />
        {isConnected ? '已连接' : '未连接'}
        <span className="text-white/50">|</span>
        <span className="text-white/50">{connectionCount} 个客户端</span>
      </div>
    </div>
  );
}

export default LivePage;
