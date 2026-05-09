import { useState } from 'react';
import { Live2DViewer } from '../../components/Live2D/Live2DViewer';
import { VRMViewer } from '../../components/VRM/VRMViewer';
import { useLiveWebSocket } from '../../hooks/useLiveWebSocket';

export function AvatarSource() {
  const [avatarType] = useState<'live2d' | 'vrm'>('live2d');
  const [mouthOpenY, setMouthOpenY] = useState(0);

  useLiveWebSocket({
    onVadStatus: (data) => {
      if (data.status === 'speech_start') {
        setMouthOpenY(Math.min(data.speech_duration_ms / 500, 1));
      } else if (data.status === 'speech_end') {
        setMouthOpenY(0);
      }
    },
  });

  return (
    <div
      className="w-screen h-screen flex items-center justify-center"
      style={{ backgroundColor: 'transparent', width: 1920, height: 1080 }}
    >
      {avatarType === 'vrm' ? (
        <VRMViewer
          modelPath=""
          scale={1.3}
          position={[0, -0.35, 0]}
          lipSyncEnabled
          lookAtMouse
          mouthOpenY={mouthOpenY}
        />
      ) : (
        <Live2DViewer
          modelPath=""
          scale={0.45}
          xOffset={0}
          yOffset={30}
          lipSyncEnabled
          idleMotionEnabled
          mouthOpenY={mouthOpenY}
        />
      )}
    </div>
  );
}

export default AvatarSource;
