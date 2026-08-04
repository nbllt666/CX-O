import { useState, useEffect, useRef, useImperativeHandle, forwardRef } from 'react';
import { Live2DViewer } from './Live2D/Live2DViewer';
import { VRMViewer } from './VRM/VRMViewer';
import { useSettingsStore } from '../store/settingsStore';
import { getAvatar } from '../services/avatarStorage';
import { createAvatarDriver } from './Avatar/AvatarDriver';
import type { IAvatarDriver } from './Avatar/AvatarDriver';
import { resolveAvatarManifestById, getAvatarById } from './Avatar/avatarManifest';

export interface PetAvatarHandle {
  driver: IAvatarDriver | null;
  canvasRef: React.RefObject<HTMLCanvasElement | HTMLDivElement | null>;
}

interface PetAvatarProps {
  mouthOpenY: number;
  onDriverReady?: (driver: IAvatarDriver | null) => void;
}

export const PetAvatar = forwardRef<PetAvatarHandle, PetAvatarProps>(
  function PetAvatar({ mouthOpenY, onDriverReady }, ref) {
    const { avatarType, live2d, vrm } = useSettingsStore();
    const modelDataRef = useRef<ArrayBuffer | undefined>(undefined);
    const [dataVersion, setDataVersion] = useState(0);
    const [loading, setLoading] = useState(false);
    const canvasRef = useRef<HTMLCanvasElement | HTMLDivElement | null>(null);

    const driverRef = useRef<IAvatarDriver | null>(null);
    const [activeDriver, setActiveDriver] = useState<IAvatarDriver | null>(null);

    // Create independent IAvatarDriver instance (same pattern as ChatPage)
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

    // Load model data from avatar storage
    const currentModelId = avatarType === 'live2d' ? live2d.modelId : vrm.modelId;

    useEffect(() => {
      if (currentModelId) {
        setLoading(true);
        getAvatar(currentModelId).then((avatar) => {
          if (avatar?.data) {
            avatar.data.arrayBuffer().then((buf) => {
              modelDataRef.current = buf;
              setDataVersion(v => v + 1);
              setLoading(false);
            });
          } else {
            modelDataRef.current = undefined;
            setDataVersion(v => v + 1);
            setLoading(false);
          }
        });
      } else {
        modelDataRef.current = undefined;
        setDataVersion(v => v + 1);
        setLoading(false);
      }
    }, [currentModelId]);

    // Sync mouthOpenY to driver
    useEffect(() => {
      if (activeDriver) {
        activeDriver.setMouthOpen(mouthOpenY);
      }
    }, [mouthOpenY, activeDriver]);

    // Notify parent when driver becomes ready/changes
    useEffect(() => {
      onDriverReady?.(activeDriver);
    }, [activeDriver, onDriverReady]);

    useImperativeHandle(ref, () => ({
      driver: activeDriver,
      canvasRef,
    }), [activeDriver]);

    const effectiveAvatarType = avatarType === 'none' ? 'live2d' : avatarType;

    if (loading) {
      return (
        <div className="w-full h-full flex items-center justify-center" style={{ backgroundColor: 'transparent' }}>
          <div className="w-6 h-6 border-2 border-white/30 border-t-white rounded-full animate-spin" />
        </div>
      );
    }

    if (!modelDataRef.current) {
      return (
        <div className="w-full h-full flex items-center justify-center" style={{ backgroundColor: 'transparent' }}>
          <p className="text-white/50 text-xs">未配置模型</p>
        </div>
      );
    }

    return (
      <div
        className="w-full h-full"
        style={{ backgroundColor: 'transparent' }}
        ref={(el) => {
          if (el) {
            const canvas = el.querySelector('canvas');
            const container = el.querySelector('[class*="w-full h-full"]');
            canvasRef.current = (canvas || container || el) as HTMLCanvasElement | HTMLDivElement;
          }
        }}
      >
        {effectiveAvatarType === 'vrm' ? (
          <VRMViewer
            modelPath={modelDataRef.current ? "" : vrm.modelPath}
            modelDataRef={modelDataRef}
            dataVersion={dataVersion}
            scale={1.3}
            position={[0, -0.35, 0]}
            lipSyncEnabled
            lookAtMouse
            mouthOpenY={mouthOpenY}
            driver={activeDriver ?? undefined}
          />
        ) : (
          <Live2DViewer
            modelPath=""
            modelData={modelDataRef.current}
            scale={0.45}
            xOffset={0}
            yOffset={30}
            lipSyncEnabled
            idleMotionEnabled
            mouthOpenY={mouthOpenY}
            driver={activeDriver ?? undefined}
          />
        )}
      </div>
    );
  }
);
