import { useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { LiveStage } from '../components/Live/LiveStage';
import { useLiveWebSocket } from '../hooks/useLiveWebSocket';
import type { LiveDanmakuData } from '../hooks/useLiveWebSocket';

export function LivePage() {
  const navigate = useNavigate();
  const [danmakuList, setDanmakuList] = useState<LiveDanmakuData[]>([]);
  const [subtitleText, setSubtitleText] = useState('');
  const [mouthOpenY, setMouthOpenY] = useState(0);
  const [avatarType] = useState<'live2d' | 'vrm'>('live2d');

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
    setSubtitleText(content);
  }, []);

  const handleVadStatus = useCallback((data: { status: string; speech_duration_ms: number }) => {
    if (data.status === 'speech_start') {
      setMouthOpenY(Math.min(data.speech_duration_ms / 500, 1));
    } else if (data.status === 'speech_end') {
      setMouthOpenY(0);
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
        avatarType={avatarType}
        modelPath=""
        danmakuList={danmakuList}
        subtitleText={subtitleText}
        mouthOpenY={mouthOpenY}
        onModeSwitch={() => navigate('/live/split')}
        onAudioPanelClick={() => navigate('/live/split/audio')}
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
