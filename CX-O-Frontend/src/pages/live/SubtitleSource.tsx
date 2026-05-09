import { useState } from 'react';
import { SubtitleDisplay } from '../../components/Live/SubtitleDisplay';
import { useLiveWebSocket } from '../../hooks/useLiveWebSocket';

export function SubtitleSource() {
  const [subtitleText, setSubtitleText] = useState('');

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
        background="rgba(0,0,0,0.5)"
        typingSpeed={40}
      />
    </div>
  );
}

export default SubtitleSource;
