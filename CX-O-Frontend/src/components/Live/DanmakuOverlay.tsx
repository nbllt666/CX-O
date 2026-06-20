import { useRef, useCallback, useMemo, useState, useEffect } from 'react';

export interface DanmakuItem {
  id: string;
  content: string;
  username?: string;
  color?: string;
  type?: 'scroll' | 'top' | 'bottom';
}

interface DanmakuOverlayProps {
  danmakuList: DanmakuItem[];
  maxCount?: number;
  speed?: number;
  fontSize?: number;
  fontFamily?: string;
  opacity?: number;
  position?: 'right' | 'full';
}

export function DanmakuOverlay({
  danmakuList,
  maxCount = 50,
  speed = 8,
  fontSize = 24,
  fontFamily = 'sans-serif',
  opacity = 0.9,
  position = 'right',
}: DanmakuOverlayProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const activeIdsRef = useRef<Set<string>>(new Set());

  const displayList = useMemo(() => {
    if (danmakuList.length <= maxCount) return danmakuList;
    return danmakuList.slice(-maxCount);
  }, [danmakuList, maxCount]);

  const tracksRef = useRef<{ top: number; bottom: number; scroll: number }>({
    top: 0,
    bottom: 0,
    scroll: 0,
  });

  const [maxTracks, setMaxTracks] = useState(() => Math.max(1, Math.floor((typeof window !== 'undefined' ? window.innerHeight : 800) / (fontSize + 8))));

  useEffect(() => {
    const calculateTracks = () => {
      setMaxTracks(Math.max(1, Math.floor((typeof window !== 'undefined' ? window.innerHeight : 800) / (fontSize + 8))));
    };
    window.addEventListener('resize', calculateTracks);
    return () => window.removeEventListener('resize', calculateTracks);
  }, [fontSize]);

  const getTrack = useCallback((type: string) => {
    const tracks = tracksRef.current;
    if (type === 'top') {
      tracks.top = (tracks.top + 1) % maxTracks;
      return tracks.top;
    }
    if (type === 'bottom') {
      tracks.bottom = (tracks.bottom + 1) % maxTracks;
      return tracks.bottom;
    }
    tracks.scroll = (tracks.scroll + 1) % maxTracks;
    return tracks.scroll;
  }, [maxTracks]);

  const handleAnimationEnd = useCallback((id: string) => {
    activeIdsRef.current.delete(id);
  }, []);

  const itemsWithTracks = useMemo(() => {
    return displayList.map((item) => {
      const itemType = item.type || 'scroll';
      const track = getTrack(itemType);
      const topOffset = (track * (fontSize + 8)) + 8;
      return { item, itemType, track, topOffset };
    });
  }, [displayList, getTrack, fontSize]);

  const isRightMode = position === 'right';

  const styleContent = useMemo(() => `
    @keyframes danmaku-scroll {
      from { transform: translateX(100%); }
      to { transform: translateX(-100%); }
    }
    @keyframes danmaku-fadein {
      from { opacity: 0; transform: translateY(-4px); }
      to { opacity: 1; transform: translateY(0); }
    }
    .danmaku-item {
      will-change: transform, opacity;
      white-space: nowrap;
      text-shadow: 1px 1px 2px rgba(0,0,0,0.6);
      font-family: ${fontFamily};
    }
    .danmaku-scroll {
      animation: danmaku-scroll ${speed}s linear forwards;
      position: absolute;
      left: 0;
    }
    .danmaku-top, .danmaku-bottom {
      animation: danmaku-fadein 0.3s ease-out forwards, danmaku-fadeout 0.5s ease-in ${speed}s forwards;
      position: absolute;
      left: 50%;
      transform: translateX(-50%);
      text-align: center;
      width: 90%;
    }
    @keyframes danmaku-fadeout {
      from { opacity: ${opacity}; }
      to { opacity: 0; }
    }
  `, [fontFamily, speed, opacity]);

  return (
    <div
      ref={containerRef}
      className="absolute inset-0 overflow-hidden pointer-events-none"
      style={{ zIndex: 10 }}
    >
      <style>{styleContent}</style>
      {itemsWithTracks.map(({ item, itemType, topOffset }) => {
        let style: React.CSSProperties;

        if (itemType === 'scroll') {
          style = {
            top: `${topOffset}px`,
            fontSize: `${fontSize}px`,
            color: item.color || '#ffffff',
            opacity,
            right: isRightMode ? '40%' : undefined,
            maxWidth: isRightMode ? '60%' : undefined,
          };
        } else if (itemType === 'top') {
          style = {
            top: `${topOffset}px`,
            fontSize: `${fontSize - 2}px`,
            color: item.color || '#ffffff',
            opacity,
          };
        } else {
          style = {
            bottom: `${topOffset}px`,
            fontSize: `${fontSize - 2}px`,
            color: item.color || '#ffffff',
            opacity,
          };
        }

        const className = `danmaku-item danmaku-${itemType}`;

        return (
          <div
            key={item.id}
            className={className}
            style={style}
            onAnimationEnd={() => handleAnimationEnd(item.id)}
          >
            {item.username && (
              <span style={{ color: '#ffd93d', marginRight: 4 }}>
                {item.username}:
              </span>
            )}
            {item.content}
          </div>
        );
      })}
    </div>
  );
}

export default DanmakuOverlay;
