import { useState, useEffect } from 'react';
import { DanmakuOverlay } from '../../components/Live/DanmakuOverlay';
import { useLiveWebSocket } from '../../hooks/useLiveWebSocket';
import type { LiveDanmakuData } from '../../hooks/useLiveWebSocket';

export function DanmakuSource() {
  const [danmakuList, setDanmakuList] = useState<LiveDanmakuData[]>([]);

  useEffect(() => {
    document.body.style.background = 'transparent';
    document.documentElement.style.background = 'transparent';
    return () => {
      document.body.style.background = '';
      document.documentElement.style.background = '';
    };
  }, []);

  useLiveWebSocket({
    onDanmaku: (data) => {
      setDanmakuList((prev) => [
        ...prev.slice(-49),
        { id: data.id || `dm-${Date.now()}`, content: data.content, username: data.username, color: data.color },
      ]);
    },
  });

  return (
    <div
      className="w-screen h-screen relative overflow-hidden"
      style={{ backgroundColor: 'transparent', width: 1920, height: 1080 }}
    >
      <DanmakuOverlay danmakuList={danmakuList} position="full" maxCount={60} speed={10} fontSize={28} />
    </div>
  );
}

export default DanmakuSource;
