/**
 * @file pet-avatar.tsx — PetAvatar 业务组件重组（模块7）
 * ============================================================================
 * 模块: 模块7 业务组件重组层 — B 组宠物/二次元类（保留二次元资产）
 * 落点: C:\CX-O\CX-O-Frontend\src\components\business\pet-avatar.tsx
 * 原组件: src/components/PetAvatar.tsx
 *
 * 重组策略（MODULE-7 AGENTS.md §2.4）:
 *   - 保留现有业务逻辑（模型加载、driver 创建、唇形同步、manifest 解析）
 *   - UI 层注入 Liquid Glass + data-glass + motion variants
 *   - 通过 className 消费 token，不硬编码颜色
 *
 * 二次元资产保留:
 *   - Live2DViewer / VRMViewer / AvatarDriver / avatarManifest 引用完整保留
 *   - 模型数据加载、driver 实例化、唇形同步逻辑不变
 *   - 仅重组 UI 容器层（loading/empty 状态 + canvas 容器）
 *
 * 跨模块导入约束:
 *   - import business/live2d/live2d-viewer + business/vrm/vrm-viewer + business/avatar/...
 *   - 仅 import 模块6 ui-v2 + 业务逻辑依赖（@/store, @/services）
 *   - 禁止 import 模块8/9 内部实现 + 旧 @/components/ 下组件
 * ============================================================================
 */

import { useState, useEffect, useRef, useImperativeHandle, forwardRef } from 'react';
import { motion, type Variants } from 'framer-motion';
import { Live2DViewer } from './live2d/live2d-viewer';
import { VRMViewer } from './vrm/vrm-viewer';
import { useSettingsStore } from '@/store/settingsStore';
import { getAvatar } from '@/services/avatarStorage';
import { createAvatarDriver } from './avatar/avatar-driver';
import type { IAvatarDriver } from './avatar/avatar-driver';
import { resolveAvatarManifestById, getAvatarById } from './avatar/avatar-manifest';
import {
  buildGlassDataAttributes,
  injectGlassClassName,
  isValidGlassTier,
  getComponentSpringTransition,
} from '@/components/ui-v2';

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
      let cancelled = false;

      const loadFromManifest = async (avatarId: string) => {
        const baseAvatar = getAvatarById(avatarId);
        if (!baseAvatar) {
          if (!cancelled) {
            modelDataRef.current = undefined;
            setDataVersion(v => v + 1);
            setLoading(false);
          }
          return;
        }
        try {
          const manifest = await resolveAvatarManifestById(baseAvatar.id);
          if (cancelled) return;
          const response = await fetch(manifest.modelJson);
          if (cancelled) return;
          if (!response.ok) {
            console.error(`[PetAvatar] manifest fetch failed: ${response.status} ${manifest.modelJson}`);
            modelDataRef.current = undefined;
            setDataVersion(v => v + 1);
            setLoading(false);
            return;
          }
          const buffer = await response.arrayBuffer();
          if (cancelled) return;
          modelDataRef.current = buffer;
          setDataVersion(v => v + 1);
          setLoading(false);
        } catch (error) {
          if (cancelled) return;
          console.error('[PetAvatar] Failed to load model from manifest:', error);
          modelDataRef.current = undefined;
          setDataVersion(v => v + 1);
          setLoading(false);
        }
      };

      if (currentModelId) {
        setLoading(true);
        getAvatar(currentModelId).then((avatar) => {
          if (cancelled) return;
          if (avatar?.data) {
            avatar.data.arrayBuffer().then((buf) => {
              if (cancelled) return;
              modelDataRef.current = buf;
              setDataVersion(v => v + 1);
              setLoading(false);
            }).catch(() => {
              if (cancelled) return;
              // IndexedDB 数据损坏 → fallback
              const fallbackId = avatarType === 'live2d'
                ? (live2d.modelId || 'yumi')
                : (vrm.modelId || 'yumi');
              void loadFromManifest(fallbackId);
            });
          } else {
            // IndexedDB 无记录 → fallback 到公开 manifest
            const fallbackId = avatarType === 'live2d'
              ? (live2d.modelId || 'yumi')
              : (vrm.modelId || 'yumi');
            void loadFromManifest(fallbackId);
          }
        }).catch(() => {
          if (cancelled) return;
          const fallbackId = avatarType === 'live2d'
            ? (live2d.modelId || 'yumi')
            : (vrm.modelId || 'yumi');
          void loadFromManifest(fallbackId);
        });
      } else {
        // currentModelId 为空 → 直接 fallback 到默认公开模型 yumi
        const fallbackId = avatarType === 'vrm' ? (vrm.modelId || 'yumi') : 'yumi';
        setLoading(true);
        void loadFromManifest(fallbackId);
      }
      return () => { cancelled = true; };
    }, [currentModelId, avatarType, live2d.modelId, vrm.modelId]);

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

    // Liquid Glass: data-glass + motion variants（glass spring，柔和入场）
    const glassTier = 'tier-3';
    const validTier = isValidGlassTier(glassTier) ? glassTier : undefined;
    const glassAttributes = buildGlassDataAttributes(true, validTier);
    const springTransition = getComponentSpringTransition('glass');
    const containerVariants: Variants = {
      initial: { opacity: 0, scale: 0.95 },
      animate: { opacity: 1, scale: 1, transition: springTransition },
    };
    const containerBaseClassName = 'w-full h-full transition-none';
    const composedClassName = validTier
      ? injectGlassClassName(containerBaseClassName, validTier)
      : containerBaseClassName;

    if (loading) {
      return (
        <motion.div
          className={composedClassName}
          data-glass={glassAttributes['data-glass'] ?? undefined}
          data-glass-tier={glassAttributes['data-glass-tier'] ?? undefined}
          variants={containerVariants}
          initial="initial"
          animate="animate"
          style={{ backgroundColor: 'transparent' }}
        >
          <div className="w-full h-full flex items-center justify-center">
            <div className="w-6 h-6 border-2 border-[var(--color-border)] border-t-[var(--color-accent)] rounded-full animate-spin" />
          </div>
        </motion.div>
      );
    }

    if (!modelDataRef.current) {
      return (
        <motion.div
          className={composedClassName}
          data-glass={glassAttributes['data-glass'] ?? undefined}
          data-glass-tier={glassAttributes['data-glass-tier'] ?? undefined}
          variants={containerVariants}
          initial="initial"
          animate="animate"
          style={{ backgroundColor: 'transparent' }}
        >
          <div className="w-full h-full flex items-center justify-center">
            <p className="text-[var(--color-text-tertiary)] text-xs">未配置模型</p>
          </div>
        </motion.div>
      );
    }

    return (
      <motion.div
        className={composedClassName}
        data-glass={glassAttributes['data-glass'] ?? undefined}
        data-glass-tier={glassAttributes['data-glass-tier'] ?? undefined}
        variants={containerVariants}
        initial="initial"
        animate="animate"
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
            modelPath=""
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
      </motion.div>
    );
  }
);
