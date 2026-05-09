import { useRef, useCallback, useMemo } from 'react';

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
  const nextIndexRef = useRef(0);

  const displayList = useMemo(() => {
    if (danmakuList.length <= maxCount) return danmakuList;
    return danmakuList.slice(-maxCount);
  }, [danmakuList, maxCount]);

  const tracksRef = useRef<{ top: number; bottom: number; scroll: number }>({
    top: 0,
    bottom: 0,
    scroll: 0,
  });

  const maxTracks = useMemo(() => Math.max(1, Math.floor((typeof window !== 'undefined' ? window.innerHeight : 800) / (fontSize + 8))), [fontSize]);

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

  const isRightMode = position === 'right';

  return (
    <div
      ref={containerRef}
      className="absolute inset-0 overflow-hidden pointer-events-none"
      style={{ zIndex: 10 }}
    >
      <style>{`
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
      `}</style>
      {displayList.map((item) => {
        const track = getTrack(item.type || 'scroll');
        const itemType = item.type || 'scroll';
        const topOffset = (track * (fontSize + 8)) + 8;

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
            key={`${item.id}-${nextIndexRef.current++}`}
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
