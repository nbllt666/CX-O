import { useState, useEffect } from 'react';
import { SubtitleDisplay } from '@/components/business/live';
import { useLiveWebSocket } from '../../hooks/useLiveWebSocket';

export function SubtitleSource() {
  const [subtitleText, setSubtitleText] = useState('');

  useEffect(() => {
    document.body.style.background = 'transparent';
    document.documentElement.style.background = 'transparent';
    return () => {
      document.body.style.background = '';
      document.documentElement.style.background = '';
    };
  }, []);

  useLiveWebSocket({
    onStreamContent: (content) => setSubtitleText(content),
  });

  return (
    <div
      className="w-screen h-screen relative"
      style={{ backgroundColor: 'transparent', width: 1920, height: 1080 }}
    >
      <SubtitleDisplay
        text={subtitleText}
        position="bottom"
        maxLines={3}
        fontSize={32}
        background="color-mix(in srgb, var(--color-neutral-900) 50%, transparent)"
        typingSpeed={40}
      />
    </div>
  );
}

export default SubtitleSource;
