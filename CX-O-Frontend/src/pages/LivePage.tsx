import { useState, useCallback, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { LiveStage } from '@/components/business/live';
import { useLiveWebSocket } from '../hooks/useLiveWebSocket';
import { useSettingsStore } from '../store/settingsStore';
import { getAvatar } from '../services/avatarStorage';
import type { LiveDanmakuData } from '../hooks/useLiveWebSocket';
import { createAvatarDriver } from '@/components/business/avatar';
import type { IAvatarDriver } from '@/components/business/avatar';
import { resolveAvatarManifestById, getAvatarById } from '@/components/business/avatar/avatar-manifest';
import { parseAvatarTags, type AvatarTag } from '../lib/avatarTagParser';

function applyAvatarTags(driver: IAvatarDriver, tags: AvatarTag[]) {
  for (const tag of tags) {
    switch (tag.type) {
      case 'emotion':
        driver.setEmotion(tag.emotion, 1.0);
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
  // avatarType 为 'none'/'vrm' 时走 VRM：public/ 下无任何 Live2D 模型文件，
  // 唯一可用模型是 vrm.modelPath（/models/avatar.vrm）
  const effectiveAvatarType: 'live2d' | 'vrm' = avatarType === 'live2d' ? 'live2d' : 'vrm';
  const currentModelId = effectiveAvatarType === 'live2d' ? live2d.modelId : vrm.modelId;

  useEffect(() => {
    let cancelled = false;

    const loadFromManifest = async (avatarId: string) => {
      const baseAvatar = getAvatarById(avatarId);
      if (!baseAvatar) {
        if (!cancelled) setModelData(undefined);
        return;
      }
      try {
        const manifest = await resolveAvatarManifestById(baseAvatar.id);
        if (cancelled) return;
        const response = await fetch(manifest.modelJson);
        if (cancelled) return;
        if (!response.ok) {
          console.error(`[LivePage] manifest fetch failed: ${response.status} ${manifest.modelJson}`);
          setModelData(undefined);
          return;
        }
        const buffer = await response.arrayBuffer();
        if (cancelled) return;
        setModelData(buffer);
      } catch (error) {
        if (cancelled) return;
        console.error('[LivePage] Failed to load model from manifest:', error);
        setModelData(undefined);
      }
    };

    // VRM 最终回退：直接读取本地 modelPath（/models/avatar.vrm）
    const loadFromVrmPath = async () => {
      try {
        const response = await fetch(vrm.modelPath || '/models/avatar.vrm');
        if (cancelled) return;
        if (!response.ok) {
          console.error(`[LivePage] vrm modelPath fetch failed: ${response.status}`);
          setModelData(undefined);
          return;
        }
        const buffer = await response.arrayBuffer();
        if (cancelled) return;
        setModelData(buffer);
      } catch (error) {
        if (cancelled) return;
        console.error('[LivePage] Failed to load VRM from modelPath:', error);
        setModelData(undefined);
      }
    };

    if (currentModelId) {
      getAvatar(currentModelId).then((avatar) => {
        if (cancelled) return;
        if (avatar?.data) {
          avatar.data.arrayBuffer().then((buffer) => {
            if (cancelled) return;
            setModelData(buffer);
          }).catch((error) => {
            if (cancelled) return;
            console.error('Failed to load avatar:', error);
            // fallback：live2d 走公开 manifest；vrm 走本地 modelPath
            if (effectiveAvatarType === 'vrm') {
              void loadFromVrmPath();
            } else {
              void loadFromManifest(live2d.modelId || 'yumi');
            }
          });
        } else {
          // IndexedDB 无记录 → fallback
          if (effectiveAvatarType === 'vrm') {
            void loadFromVrmPath();
          } else {
            void loadFromManifest(live2d.modelId || 'yumi');
          }
        }
      }).catch((error) => {
        if (cancelled) return;
        console.error('Failed to load avatar:', error);
        if (effectiveAvatarType === 'vrm') {
          void loadFromVrmPath();
        } else {
          void loadFromManifest(live2d.modelId || 'yumi');
        }
      });
    } else if (effectiveAvatarType === 'vrm') {
      // VRM 无 modelId → 直接读本地 modelPath
      void loadFromVrmPath();
    } else {
      // live2d 无 modelId → 默认公开模型 yumi
      void loadFromManifest('yumi');
    }
    return () => {
      cancelled = true;
    };
  }, [currentModelId, effectiveAvatarType, live2d.modelId, vrm.modelId, vrm.modelPath]);

  useEffect(() => {
    let cancelled = false;
    const avatarId = effectiveAvatarType === 'live2d' ? (live2d.modelId || 'yumi') : (vrm.modelId || undefined);
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
  }, [effectiveAvatarType, live2d.modelId, vrm.modelId]);

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
    <div className="w-full h-full">
      <LiveStage
        avatarType={effectiveAvatarType}
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
          background: 'var(--color-bg-tertiary)',
          color: isConnected ? 'var(--color-success)' : 'var(--color-error)',
          backdropFilter: 'blur(8px)',
        }}
      >
        <span
          className="w-2 h-2 rounded-full animate-pulse"
          style={{ backgroundColor: isConnected ? 'var(--color-success)' : 'var(--color-error)' }}
        />
        {isConnected ? '已连接' : '未连接'}
        <span className="text-[var(--color-text-tertiary)]">|</span>
        <span className="text-[var(--color-text-tertiary)]">{connectionCount} 个客户端</span>
      </div>
    </div>
  );
}

export default LivePage;
