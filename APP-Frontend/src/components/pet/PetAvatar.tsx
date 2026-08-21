/**
 * PetAvatar — 桌宠头像容器。
 *
 * 职责：
 * - 从 settingsStore 读取头像类型与引擎设置，合成 AvatarManifest
 * - 创建独立 IAvatarDriver 实例（头像类型/模型路径变更时销毁重建，实时响应切换）
 * - 挂载 VRMViewer / Live2DViewer，把口型 ref 与设置项接进去
 *
 * 与 CX-O-Frontend pet-avatar 的差异：无 IndexedDB/服务端清单，
 * 模型固定走本地 public/models（settings 里的 modelPath 可覆盖默认值）。
 */
import { forwardRef, useEffect, useMemo, useRef, useState } from 'react';
import type { MutableRefObject } from 'react';
import { useTranslation } from 'react-i18next';
import { PawPrint } from 'lucide-react';
import { useSettingsStore } from '../../store/settingsStore';
import { useObsStore, resolveAvatarScale } from '../../store/obsStore';
import { isElectron } from '../../lib/isElectron';
import type { IAvatarDriver, SceneMode } from '../../avatar/types';
import { createAvatarDriver } from '../../avatar/createDriver';
import { createSyntheticLive2DManifest, createSyntheticVRMManifest } from '../../avatar/manifest';
import type { VowelWeights } from '../../hooks/useAudioAnalyzer';
import { VRMViewer } from './VRMViewer';
import { Live2DViewer } from './Live2DViewer';

interface PetAvatarProps {
  /** 口型：实时音量与元音权重 ref（useAudioAnalyzer 提供） */
  volumeRef?: MutableRefObject<number>;
  vowelWeightsRef?: MutableRefObject<VowelWeights>;
  onDriverReady?: (driver: IAvatarDriver | null) => void;
  /** 场景模式：'live' 时透传给 VRMViewer 启用直播视线策略，默认 'pet' */
  sceneMode?: SceneMode;
}

/** PetAvatar 命令式句柄（透传 VRMViewer 的读弹幕触发） */
export interface PetAvatarHandle {
  setReadingDanmaku: (state?: boolean) => void;
}

export const PetAvatar = forwardRef<PetAvatarHandle, PetAvatarProps>(function PetAvatar(
  { volumeRef, vowelWeightsRef, onDriverReady, sceneMode = 'pet' },
  ref,
) {
  const { t } = useTranslation();
  const avatarType = useSettingsStore((s) => s.avatarType);
  const live2d = useSettingsStore((s) => s.live2d);
  const vrm = useSettingsStore((s) => s.vrm);
  const captureWidth = useObsStore((s) => s.captureWidth);
  const captureHeight = useObsStore((s) => s.captureHeight);
  // 采集尺寸自适应因子（Electron 窗口已缩放时为 1；浏览器降级为按比例缩放）
  const obsScale = resolveAvatarScale(captureWidth, captureHeight, isElectron());

  const driverRef = useRef<IAvatarDriver | null>(null);
  const [activeDriver, setActiveDriver] = useState<IAvatarDriver | null>(null);

  // 清单合成（设置变更 → 新清单 → 下游重建）。
  // VRM 的实时 scale 不并入 manifest（清单保持稳定，避免每次缩放都整模型重建重载）；
  // 实时缩放经 VRMViewer 的 scale prop 走 updateStageTransform 应用，无需重建。
  const manifest = useMemo(() => {
    if (avatarType === 'vrm') {
      return createSyntheticVRMManifest(vrm.modelPath, 1, vrm.position3d);
    }
    if (avatarType === 'live2d') {
      return createSyntheticLive2DManifest(live2d.modelPath, live2d.scale * obsScale, live2d.xOffset, live2d.yOffset);
    }
    return null;
  }, [
    avatarType,
    vrm.modelPath,
    vrm.position3d,
    live2d.modelPath,
    live2d.scale,
    live2d.xOffset,
    live2d.yOffset,
    obsScale,
  ]);

  // 驱动实例：随清单重建（头像类型切换实时响应）
  useEffect(() => {
    if (!manifest) {
      driverRef.current = null;
      setActiveDriver(null);
      return;
    }
    const driver = createAvatarDriver(manifest);
    driverRef.current = driver;
    setActiveDriver(driver);
    return () => {
      driver.destroy();
      if (driverRef.current === driver) {
        driverRef.current = null;
      }
    };
  }, [manifest]);

  // 驱动就绪通知
  useEffect(() => {
    onDriverReady?.(activeDriver);
  }, [activeDriver, onDriverReady]);

  if (!manifest || avatarType === 'none') {
    return (
      <div className="flex h-full w-full flex-col items-center justify-center gap-2">
        <PawPrint className="h-10 w-10 text-primary opacity-60" />
        <p className="text-xs text-muted-foreground">{t('pet.avatar.disabled')}</p>
      </div>
    );
  }

  return (
    <div className="h-full w-full" style={{ backgroundColor: 'transparent' }}>
      {avatarType === 'vrm' ? (
        <VRMViewer
          ref={ref}
          modelPath={vrm.modelPath}
          avatar={manifest}
          driver={activeDriver}
          scale={vrm.scale * obsScale}
          position={vrm.position3d}
          lookAtMouse={vrm.lookAtMouse}
          sceneMode={sceneMode}
          animationConfig={vrm.animation}
          tweakConfig={vrm.tweak}
          volumeRef={volumeRef}
          vowelWeightsRef={vowelWeightsRef}
        />
      ) : (
        <Live2DViewer
          modelPath={live2d.modelPath}
          avatar={manifest}
          driver={activeDriver}
          idleMotionEnabled={live2d.idleMotion}
          animationConfig={live2d.animation}
          volumeRef={volumeRef}
        />
      )}
    </div>
  );
});
