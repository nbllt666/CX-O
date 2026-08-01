/**
 * @file audio-track.tsx — AudioTrack 业务封装组件（第4波业务封装，Liquid Glass 定制）
 * ============================================================================
 * 模块: 模块6 基础组件层（shadcn ui-v2）— 波4 业务封装组件
 * 落点: C:\CX-O\CX-O-Frontend\src\components\ui-v2\audio-track.tsx
 *
 * 契约对齐:
 *   - I5 frontend_components_uiv2.pyi §AudioTrack + §AudioTrackProps + §GlassComponentProps
 *   - D1 frontend_design_tokens.schema.json §component.audioTrack（token 消费，不硬编码颜色）
 *   - D2 glass_tier_config.schema.json §tiers（data-glass-tier 属性值）
 *   - D3 theme.schema.json（双主题通过 CSS 变量自动切换，无需 JS 介入）
 *   - D5 motion_springs.schema.json §springs.snappy（AudioTrack 默认 spring，音轨交互快速响应）
 *   - I3 frontend_motion.pyi §useGsapTimeline（GSAP timeline 协同，精度 ≤ 16ms）
 *   - merged.md §4.2 定制策略 + §4.3 第4波（业务封装，第10-12周，AudioWorkstation 页面）
 *
 * Liquid Glass 定制（I5 §AudioTrack docstring + merged.md §4.2）:
 *   - 业务封装组件基于 shadcn 基础组件重组，非从零实现（I5 §AudioTrack docstring）
 *   - 使用 Card（波1）作为音轨列表容器，Button（波1）作为静音/独奏控制，
 *     Input（波1，type='range'）作为音量滑块，Badge（波3）显示音轨名称/状态
 *   - 挂载 data-glass 属性，由 WebGL 层（I1 GlassRenderer）接管玻璃渲染
 *   - 与 GSAP 音符可视化时间线协同（I3 useGsapTimeline，精度 ≤ 16ms）
 *   - 提供 timelineRef prop 接收外部 GSAP timeline（不直接调用 useGsapTimeline hook，
 *     避免与模块3 内部实现耦合）
 *   - Framer Motion variants 替换 shadcn 默认 Tailwind transition
 *   - 通过 className + Tailwind utility 消费 token，不硬编码颜色
 *   - 双主题通过 CSS 变量自动切换，无需 JS 介入
 *
 * 跨模块导入约束（rules-0 §四 + MODULE-6 AGENTS.md §4.3）:
 *   - 仅 import 模块1 token（通过 className 消费 CSS 变量）
 *   - 仅 import 模块3 springs/variants（通过 motion-variants.ts 工厂）+ GsapTimeline 类型
 *   - 仅 import 模块4 GlassTier 类型（data-glass-tier 属性值）
 *   - 仅 import 本模块基础设施（inject-glass-style / motion-variants）
 *     + 波1/3 基础组件（Card / Button / Input / Badge）
 *   - 仅 import 第三方库 react / framer-motion
 *   - 禁止 import 模块5/7/8/9 内部实现
 *   - 禁止直接调用 useGsapTimeline hook（仅通过 timelineRef prop 接收外部 timeline）
 *
 * 默认 spring: snappy（D5 §springs.snappy.useCase=button-press，音轨交互快速响应）
 * OBS-C 守护: snappy 非 character（character 仅用于角色立绘动效）
 * ============================================================================
 */

import React, { useEffect, useCallback } from 'react';
import { motion, type Variants } from 'framer-motion';
import { cn } from '@/lib/utils';
import type { GsapTimeline } from '@/lib/motion';
import {
  glassPanelClass,
  buildGlassDataAttributes,
} from './inject-glass-style';
import {
  getComponentSpringTransition,
  getDefaultComponentSpring,
} from './motion-variants';
import type { GlassComponentProps } from './button';
import { Card } from './card';
import { Button } from './button';
import { Input } from './input';
import { Badge } from './badge';

// =============================================================================
// AudioTrackData 类型（音轨数据结构，对应 I5 §AudioTrackProps.tracks 元素）
// =============================================================================

/**
 * AudioTrack 音轨数据结构（对应 I5 §AudioTrackProps.tracks 元素）。
 *
 * I5 契约中 tracks 为 List[Dict[str, Any]]，此处给出具体的 TS 类型定义。
 * 字段对齐任务要求: {id, name, volume, muted, solo, color?}
 */
export interface AudioTrackData {
  /** 音轨唯一标识（number 类型，对齐 I5 §AudioTrackProps.onTrackChange 第一个参数 trackId: int） */
  readonly id: number;
  /** 音轨名称 */
  readonly name: string;
  /** 音量（0-100） */
  readonly volume: number;
  /** 是否静音 */
  readonly muted: boolean;
  /** 是否独奏 */
  readonly solo: boolean;
  /** 音轨颜色指示（可选，CSS 颜色值或 CSS 变量名，用于可视化指示） */
  readonly color?: string;
}

// =============================================================================
// AudioTrackProps（对应 I5 §AudioTrackProps）
// =============================================================================

/**
 * AudioTrack 业务组件 props（对应 I5 §AudioTrackProps）。
 *
 * 继承 GlassComponentProps（Liquid Glass 扩展，含 dataGlass/glassTier/glassVariant/motionVariants 四字段）。
 * 业务封装组件基于 shadcn 基础组件重组，非从零实现（I5 §AudioTrack docstring）。
 * AudioWorkstation 音轨组件，与 GSAP 音符可视化时间线协同（I3 useGsapTimeline，精度 ≤ 16ms）。
 */
export interface AudioTrackProps extends GlassComponentProps {
  /** 音轨列表 */
  readonly tracks: AudioTrackData[];
  /** 音轨变化回调（trackId + changes 对象，对齐 I5 §onTrackChange: Callable[[int, Any], None]） */
  readonly onTrackChange?: (trackId: number, changes: Record<string, unknown>) => void;
  /** 当前播放时间（秒，对齐 I5 §AudioTrackProps.currentTime: float） */
  readonly currentTime?: number;
  /** 自定义 className */
  readonly className?: string;
  /** 总时长（秒，用于播放头位置计算，默认 0） */
  readonly duration?: number;
  /**
   * GSAP timeline ref（外部传入，协同接口）。
   * 接收外部通过 useGsapTimeline 创建的 timeline ref，用于与音符可视化时间线协同。
   * AudioTrack 不直接调用 useGsapTimeline hook，仅通过此 prop 接收外部 timeline。
   * 当 currentTime 变化时，通过 timelineRef.current.seek() 同步 GSAP timeline 播放位置。
   */
  readonly timelineRef?: React.RefObject<GsapTimeline | null>;
}

// =============================================================================
// AudioTrackItemProps（子组件 props）
// =============================================================================

/**
 * AudioTrackItem 子组件 props。
 *
 * 封装单个音轨条目渲染，含名称、静音/独奏按钮、音量滑块。
 */
export interface AudioTrackItemProps {
  /** 音轨数据 */
  readonly track: AudioTrackData;
  /** 音轨变化回调 */
  readonly onTrackChange?: (trackId: number, changes: Record<string, unknown>) => void;
  /** 自定义 className */
  readonly className?: string;
}

// =============================================================================
// 辅助: 格式化播放时间（秒 → mm:ss）
// =============================================================================

/**
 * 格式化播放时间（秒数 → mm:ss 格式）。
 *
 * 对齐 I5 §AudioTrackProps.currentTime（float，秒）。
 * 用于头部当前时间显示。
 *
 * @param seconds 秒数
 * @returns mm:ss 格式的时间字符串
 */
function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '00:00';
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
}

// =============================================================================
// AudioTrack 组件实现
// =============================================================================

/**
 * AudioTrack 业务封装组件（第4波业务封装，Liquid Glass 定制）。
 *
 * 对应 I5 §AudioTrack: ``AudioTrack(props: AudioTrackProps): JSX.Element``。
 *
 * 业务封装策略（I5 §AudioTrack docstring）:
 *   - 基于 shadcn 基础组件重组，非从零实现
 *   - 使用 Card（波1）作为音轨列表容器
 *   - 使用 Button（波1）作为静音/独奏控制
 *   - 使用 Input（波1，type='range'）作为音量滑块
 *   - 使用 Badge（波3）显示音轨名称/状态
 *
 * Liquid Glass 定制（merged.md §4.2）:
 *   - 挂载 data-glass 属性，由 WebGL 层接管玻璃渲染
 *   - Framer Motion variants 替换 shadcn 默认 Tailwind transition
 *   - 通过 className + Tailwind utility 消费 token，不硬编码颜色
 *   - 双主题通过 CSS 变量自动切换，无需 JS 介入
 *
 * 默认 spring: snappy（D5 §springs.snappy.useCase=button-press，音轨交互快速响应）
 * OBS-C 守护: snappy 非 character
 *
 * 与 GSAP 音符可视化时间线协同（I3 useGsapTimeline，精度 ≤ 16ms）:
 *   - 通过 timelineRef prop 接收外部 GSAP timeline（不直接调用 useGsapTimeline hook）
 *   - 当 currentTime 变化时，通过 timelineRef.current.seek() 同步 GSAP timeline 播放位置
 *   - 播放头位置可视化基于 currentTime 与 duration 计算百分比
 *
 * 音轨控制:
 *   - 静音切换（Mute button）
 *   - 独奏切换（Solo button）
 *   - 音量调节（Volume slider，0-100）
 *   - 音轨名称显示
 *
 * 多音轨支持:
 *   - tracks 数组渲染多个 AudioTrackItem 条目
 *
 * @param props AudioTrack 组件配置（含 tracks/onTrackChange/currentTime + Liquid Glass 扩展字段）
 * @returns 渲染后的 AudioTrack
 */
export const AudioTrack = React.forwardRef<HTMLDivElement, AudioTrackProps>(
  function AudioTrack(
    {
      tracks,
      onTrackChange,
      currentTime = 0,
      className,
      duration = 0,
      timelineRef,
      dataGlass = true,
      glassTier,
      glassVariant,
      motionVariants,
    },
    ref,
  ) {
    void glassTier; // v2: glassTier 已废弃，保留解构以避免 spread 到 DOM
    // 获取 snappy spring 的 transition 参数（AudioTrack 默认 spring）
    // OBS-C 守护: snappy 非 character（character 仅用于角色立绘）
    const enterSpring = getComponentSpringTransition(
      glassVariant ?? getDefaultComponentSpring('AudioTrack'),
    );

    // AudioTrack 入场 variants（snappy spring，快速响应）
    const resolvedVariants: Variants =
      motionVariants ??
      ({
        initial: { opacity: 0, y: 10 },
        animate: { opacity: 1, y: 0, transition: enterSpring },
        exit: { opacity: 0, y: 10, transition: enterSpring },
      } as Variants);

    const glassAttributes = buildGlassDataAttributes(dataGlass);

    // 播放头位置百分比（基于 currentTime 与 duration）
    const progress =
      duration > 0 && currentTime >= 0
        ? Math.min((currentTime / duration) * 100, 100)
        : 0;

    // 与 GSAP timeline 协同: currentTime 变化时同步 GSAP timeline 播放位置
    // 不直接调用 useGsapTimeline hook，仅通过 timelineRef prop 接收外部 timeline
    useEffect(() => {
      if (timelineRef?.current && currentTime >= 0) {
        timelineRef.current.seek(currentTime);
      }
    }, [currentTime, timelineRef]);

    // 构建 AudioTrack 根 className（通过 className 消费 token，不硬编码颜色）
    const trackBaseClassName = cn(
      'flex flex-col w-full',
      'bg-[var(--audio-track-bg,var(--card-bg))]',
      'rounded-[var(--card-radius)]',
      'border border-[var(--card-border)]',
      'shadow-[var(--card-shadow)]',
      'text-[var(--color-text-primary)]',
      'transition-none', // 移除 shadcn 默认 Tailwind transition，由 Framer Motion 接管
      'overflow-hidden',
      className,
    );

    // 注入 glass 样式类（v2: 直接拼接 glassPanelClass，不再区分 tier）
    const composedClassName = cn(trackBaseClassName, glassPanelClass);

    return (
      <motion.div
        ref={ref}
        className={composedClassName}
        // data-glass 属性（由 WebGL 层 GlassRenderer 扫描接管渲染）
        data-glass={glassAttributes['data-glass'] ?? undefined}
        // Framer Motion variants（替换 shadcn 默认 Tailwind transition）
        variants={resolvedVariants}
        initial="initial"
        animate="animate"
        exit="exit"
        role="region"
        aria-label="音轨控制面板"
      >
        {/* 头部: 当前时间 + 播放头进度条 + 总时长 */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-[var(--card-border)] bg-[var(--audio-track-header-bg,transparent)]">
          <span className="text-sm font-mono text-[var(--audio-track-time-text,var(--color-text-primary))]">
            {formatDuration(currentTime)}
          </span>
          {/* 播放头进度条（基于 currentTime 与 duration 计算百分比） */}
          <div className="flex-1 h-1.5 bg-[var(--audio-track-progress-bg,var(--color-bg-secondary))] rounded-full overflow-hidden">
            <div
              className="h-full bg-[var(--audio-track-progress,var(--color-accent))] rounded-full transition-none"
              style={{ width: `${progress}%` }}
              aria-label={`播放进度 ${progress.toFixed(1)}%`}
            />
          </div>
          <span className="text-sm font-mono text-[var(--audio-track-duration-text,var(--color-text-tertiary))]">
            {formatDuration(duration)}
          </span>
        </div>

        {/* 音轨列表: Card 作为容器，渲染多个 AudioTrackItem */}
        <Card
          dataGlass={false}
          className={cn(
            'flex-1 overflow-y-auto',
            'bg-transparent border-0 shadow-none',
          )}
        >
          <div className="px-2 py-2">
            {tracks.length === 0 ? (
              <p className="text-sm text-[var(--color-text-tertiary)] text-center py-4">
                暂无音轨
              </p>
            ) : (
              tracks.map((track) => (
                <AudioTrackItem
                  key={track.id}
                  track={track}
                  onTrackChange={onTrackChange}
                />
              ))
            )}
          </div>
        </Card>
      </motion.div>
    );
  },
);

AudioTrack.displayName = 'AudioTrack';

// =============================================================================
// AudioTrackItem 子组件实现（封装单个音轨条目渲染）
// =============================================================================

/**
 * AudioTrackItem 子组件（封装单个音轨条目渲染）。
 *
 * 每个音轨条目含:
 *   - 音轨名称（Badge 显示）
 *   - 静音按钮（Button，muted 状态切换）
 *   - 独奏按钮（Button，solo 状态切换）
 *   - 音量滑块（Input type='range'，0-100）
 *   - 音量值显示
 *
 * 通过 className 消费 token，不硬编码颜色。
 */
export const AudioTrackItem = React.forwardRef<HTMLDivElement, AudioTrackItemProps>(
  function AudioTrackItem({ track, onTrackChange, className }, ref) {
    // 音轨条目进出场 variants（snappy spring 快速响应）
    const itemSpring = getComponentSpringTransition('snappy');
    const itemVariants: Variants = {
      initial: { opacity: 0, x: -10 },
      animate: { opacity: 1, x: 0, transition: itemSpring },
      exit: { opacity: 0, x: 10, transition: itemSpring },
    };

    // 静音切换
    const handleMuteToggle = useCallback(() => {
      onTrackChange?.(track.id, { muted: !track.muted });
    }, [track.id, track.muted, onTrackChange]);

    // 独奏切换
    const handleSoloToggle = useCallback(() => {
      onTrackChange?.(track.id, { solo: !track.solo });
    }, [track.id, track.solo, onTrackChange]);

    // 音量变化
    const handleVolumeChange = useCallback(
      (e: React.ChangeEvent<HTMLInputElement>) => {
        onTrackChange?.(track.id, { volume: Number(e.target.value) });
      },
      [track.id, onTrackChange],
    );

    return (
      <motion.div
        ref={ref}
        variants={itemVariants}
        initial="initial"
        animate="animate"
        exit="exit"
        className={cn(
          'flex items-center gap-2 px-3 py-2 mb-2 rounded-[var(--radius-md)]',
          'bg-[var(--audio-track-item-bg,var(--color-bg-secondary))]',
          'border border-[var(--audio-track-item-border,var(--card-border))]',
          'transition-none',
          track.muted && 'opacity-60',
          className,
        )}
      >
        {/* 音轨颜色指示（可选，使用 track.color） */}
        {track.color && (
          <span
            className="inline-block w-2 h-2 rounded-full shrink-0"
            style={{ backgroundColor: track.color }}
            aria-hidden="true"
          />
        )}

        {/* 音轨名称（Badge 显示） */}
        <Badge
          variant={track.solo ? 'anime' : 'default'}
          size="sm"
          dataGlass={false}
          className="shrink-0 min-w-[60px] justify-center"
        >
          {track.name}
        </Badge>

        {/* 静音按钮 */}
        <Button
          variant={track.muted ? 'danger' : 'secondary'}
          size="sm"
          onClick={handleMuteToggle}
          dataGlass={false}
        >
          {track.muted ? '取消静音' : '静音'}
        </Button>

        {/* 独奏按钮 */}
        <Button
          variant={track.solo ? 'primary' : 'secondary'}
          size="sm"
          onClick={handleSoloToggle}
          dataGlass={false}
        >
          {track.solo ? '取消独奏' : '独奏'}
        </Button>

        {/* 音量滑块（Input type='range'，0-100） */}
        <Input
          type="range"
          min={0}
          max={100}
          value={track.volume}
          onChange={handleVolumeChange}
          disabled={track.muted}
          dataGlass={false}
          className="flex-1 min-w-[80px]"
        />

        {/* 音量值显示 */}
        <span className="text-xs font-mono text-[var(--audio-track-volume-color,var(--color-text-tertiary))] shrink-0 w-8 text-right">
          {track.volume}
        </span>
      </motion.div>
    );
  },
);

AudioTrackItem.displayName = 'AudioTrackItem';
