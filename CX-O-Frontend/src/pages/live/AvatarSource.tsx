import { useState, useEffect } from 'react';
import { Live2DViewer } from '../../components/Live2D/Live2DViewer';
import { VRMViewer } from '../../components/VRM/VRMViewer';
import { useLiveWebSocket } from '../../hooks/useLiveWebSocket';
import { useSettingsStore } from '../../store/settingsStore';
import { getAvatar } from '../../services/avatarStorage';

export function AvatarSource() {
  const [mouthOpenY, setMouthOpenY] = useState(0);
  const [modelData, setModelData] = useState<ArrayBuffer | undefined>(undefined);
  const [loading, setLoading] = useState(false);

  const { live2d, vrm, avatarType } = useSettingsStore();
  const currentModelId = avatarType === 'live2d' ? live2d.modelId : vrm.modelId;

  useEffect(() => {
    if (currentModelId) {
      setLoading(true);
      getAvatar(currentModelId).then((avatar) => {
        if (avatar) {
          avatar.data.arrayBuffer().then((buf) => {
            setModelData(buf);
            setLoading(false);
          });
        } else {
          setModelData(undefined);
          setLoading(false);
        }
      });
    } else {
      setModelData(undefined);
      setLoading(false);
    }
  }, [currentModelId]);

  useLiveWebSocket({
    onVadStatus: (data) => {
      if (data.status === 'speech_start' && data.speech_probability !== undefined) {
        setMouthOpenY(Math.min(data.speech_probability * 1.5, 1));
      } else if (data.status === 'speech_end') {
        setMouthOpenY(0);
      }
    },
  });

  const effectiveAvatarType = avatarType === 'none' ? 'live2d' : avatarType;

  if (loading) {
    return (
      <div
        className="w-screen h-screen flex items-center justify-center"
        style={{ backgroundColor: 'transparent', width: 1920, height: 1080 }}
      >
        <div className="w-8 h-8 border-2 border-white/30 border-t-white rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div
      className="w-screen h-screen flex items-center justify-center"
      style={{ backgroundColor: 'transparent', width: 1920, height: 1080 }}
    >
      {modelData ? (
        effectiveAvatarType === 'vrm' ? (
          <VRMViewer
            modelPath=""
            modelData={modelData}
            scale={1.3}
            position={[0, -0.35, 0]}
            lipSyncEnabled
            lookAtMouse
            mouthOpenY={mouthOpenY}
          />
        ) : (
          <Live2DViewer
            modelPath=""
            modelData={modelData}
            scale={0.45}
            xOffset={0}
            yOffset={30}
            lipSyncEnabled
            idleMotionEnabled
            mouthOpenY={mouthOpenY}
          />
        )
      ) : (
        <p className="text-white/50 text-sm">未配置模型</p>
      )}
    </div>
  );
}

export default AvatarSource;
