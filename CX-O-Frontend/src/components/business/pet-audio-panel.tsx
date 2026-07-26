/**
 * @file pet-audio-panel.tsx — PetAudioPanel 业务组件重组（模块7）
 * ============================================================================
 * 模块: 模块7 业务组件重组层 — B 组宠物/二次元类
 * 落点: C:\CX-O\CX-O-Frontend\src\components\business\pet-audio-panel.tsx
 * 原组件: src/components/PetAudioPanel.tsx
 *
 * 重组策略（MODULE-7 AGENTS.md §2.4）:
 *   - 保留现有业务逻辑（WebSocket、音频分析、麦克风、VAD 唇形同步）
 *   - UI 层注入 Liquid Glass + data-glass + motion variants
 *   - 硬编码颜色（#ef4444/#f59e0b/#22c55e/#4ade80/#f87171）替换为 CSS 变量
 *   - 通过 className 消费 token，不硬编码颜色
 *
 * 跨模块导入约束:
 *   - 仅 import 模块6 ui-v2 + 业务逻辑依赖（@/hooks/...）
 *   - 禁止 import 模块8/9 内部实现 + 旧 @/components/ 下组件
 * ============================================================================
 */

import { useState, useCallback } from 'react';
import { motion, type Variants } from 'framer-motion';
import { useLiveWebSocket } from '@/hooks/useLiveWebSocket';
import type { TTSSyncData, TTSTickData } from '@/hooks/useLiveWebSocket';
import { useAudioAnalyzer } from '@/hooks/useAudioAnalyzer';
import { useMicrophone } from '@/hooks/useMicrophone';
import {
  buildGlassDataAttributes,
  injectGlassClassName,
  isValidGlassTier,
  getComponentSpringTransition,
} from '@/components/ui-v2';

interface PetAudioPanelProps {
  onMouthOpenYChange: (value: number) => void;
}

export function PetAudioPanel({ onMouthOpenYChange }: PetAudioPanelProps) {
  const [ttsAudioElement, setTtsAudioElement] = useState<HTMLAudioElement | null>(null);
  const [isTTSPlaying, setIsTTSPlaying] = useState(false);

  // Audio analyzer for TTS lip sync
  useAudioAnalyzer({
    audioElement: ttsAudioElement,
    isPlaying: isTTSPlaying,
    enabled: true,
  });

  const { isConnected, sendAudio } = useLiveWebSocket({
    onVadStatus: (data) => {
      if (data.status === 'speech_start' && data.speech_probability !== undefined) {
        onMouthOpenYChange(Math.min(data.speech_probability * 1.5, 1));
      } else if (data.status === 'speech_end') {
        onMouthOpenYChange(0);
      }
    },
    onTTSSync: (data: TTSSyncData) => {
      handleTTSSync(data);
    },
    onTTSTick: (_data: TTSTickData) => {
      // TTS tick for sync alignment
    },
    onTTSEnd: () => {
      handleTTSEnd();
    },
  });

  const {
    isEnabled: micEnabled,
    currentLevel,
    toggle: toggleMicrophone,
  } = useMicrophone({
    onDataAvailable: (buf) => {
      if (sendAudio) sendAudio(buf);
    },
  });

  const handleTTSSync = useCallback((data: TTSSyncData) => {
    // Create audio element for TTS playback with lip sync
    if (data.text) {
      // The TTS audio will be played via the main chat flow
      // Here we just track the sync for mouth movement
      onMouthOpenYChange(0.6);
    }
  }, [onMouthOpenYChange]);

  const handleTTSEnd = useCallback(() => {
    onMouthOpenYChange(0);
    setIsTTSPlaying(false);
    setTtsAudioElement(null);
  }, [onMouthOpenYChange]);

  // Liquid Glass: data-glass + motion variants（snappy spring，快速响应）
  const glassTier = 'tier-3';
  const validTier = isValidGlassTier(glassTier) ? glassTier : undefined;
  const glassAttributes = buildGlassDataAttributes(true, validTier);
  const springTransition = getComponentSpringTransition('snappy');
  const panelVariants: Variants = {
    initial: { opacity: 0, scale: 0.95 },
    animate: { opacity: 1, scale: 1, transition: springTransition },
  };

  // 音量指示器颜色（通过 CSS 变量消费 token，不硬编码颜色）
  const volumeColor =
    currentLevel > 0.7
      ? 'var(--color-error)'
      : currentLevel > 0.3
        ? 'var(--color-warning)'
        : 'var(--color-success)';

  const panelBaseClassName = `flex items-center gap-2 px-2 py-1 transition-none ${
    micEnabled
      ? 'bg-[var(--color-error-bg)] text-[var(--color-error)]'
      : 'bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)]'
  }`;
  const composedClassName = validTier
    ? injectGlassClassName(panelBaseClassName, validTier)
    : panelBaseClassName;

  return (
    <motion.div
      className={composedClassName}
      data-glass={glassAttributes['data-glass'] ?? undefined}
      data-glass-tier={glassAttributes['data-glass-tier'] ?? undefined}
      variants={panelVariants}
      initial="initial"
      animate="animate"
      style={{ pointerEvents: 'auto' }}
    >
      {/* Mic toggle */}
      <button
        onClick={toggleMicrophone}
        className={`p-1.5 rounded-[var(--radius-sm)] transition-none ${
          micEnabled
            ? 'bg-[var(--color-error-bg)] text-[var(--color-error)] hover:bg-[var(--color-error-bg)]'
            : 'bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-hover)]'
        }`}
        title={micEnabled ? '关闭麦克风' : '开启麦克风'}
        aria-label={micEnabled ? '关闭麦克风' : '开启麦克风'}
      >
        {micEnabled ? (
          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
          </svg>
        ) : (
          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z" />
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2" />
          </svg>
        )}
      </button>

      {/* Volume indicator */}
      {micEnabled && (
        <div className="flex-1 h-1.5 rounded-full bg-[var(--color-bg-tertiary)] overflow-hidden">
          <div
            className="h-full rounded-full transition-all duration-75"
            style={{
              width: `${currentLevel * 100}%`,
              background: volumeColor,
            }}
          />
        </div>
      )}

      {/* Connection indicator */}
      <span
        className="w-1.5 h-1.5 rounded-full"
        style={{ backgroundColor: isConnected ? 'var(--color-success)' : 'var(--color-error)' }}
        aria-label={isConnected ? '已连接' : '未连接'}
      />
    </motion.div>
  );
}
