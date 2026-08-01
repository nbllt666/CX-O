/**
 * @file chat-panel.tsx — ChatPanel 业务封装组件（第4波业务封装，Liquid Glass 定制）
 * ============================================================================
 * 模块: 模块6 基础组件层（shadcn ui-v2）— 波4 业务封装组件
 * 落点: C:\CX-O\CX-O-Frontend\src\components\ui-v2\chat-panel.tsx
 *
 * 契约对齐:
 *   - I5 frontend_components_uiv2.pyi §ChatPanel + §ChatPanelProps + §GlassComponentProps
 *   - D1 frontend_design_tokens.schema.json §component.chatPanel（token 消费，不硬编码颜色）
 *   - D2 glass_tier_config.schema.json §tiers（data-glass-tier 属性值）
 *   - D3 theme.schema.json（双主题通过 CSS 变量自动切换，无需 JS 介入）
 *   - D5 motion_springs.schema.json §springs.sheet（ChatPanel 默认 spring，聊天面板入场）
 *   - I4 EmotionType（characterEmotion prop 为 string 类型，不直接 import 模块5）
 *   - merged.md §4.2 定制策略 + §4.3 第4波（业务封装，第10-12周，AudioWorkstation/Pet 页面）
 *
 * Liquid Glass 定制（I5 §ChatPanel docstring + merged.md §4.2）:
 *   - 业务封装组件基于 shadcn 基础组件重组，非从零实现（I5 §ChatPanel docstring）
 *   - 使用 Card（波1）作为消息列表容器，Avatar（波3）渲染角色头像，
 *     Input（波1）+ Button（波1）作为消息输入区，Badge（波3）显示角色情绪
 *   - 挂载 data-glass 属性，由 WebGL 层（I1 GlassRenderer）接管玻璃渲染
 *   - 集成角色情绪（I4 EmotionType）驱动角色表情切换（characterEmotion prop 为 string 类型）
 *   - 消息列表使用 Framer Motion AnimatePresence 处理消息进出场动画
 *   - Framer Motion variants 替换 shadcn 默认 Tailwind transition
 *   - 通过 className + Tailwind utility 消费 token，不硬编码颜色
 *   - 双主题通过 CSS 变量自动切换，无需 JS 介入
 *
 * 跨模块导入约束（rules-0 §四 + MODULE-6 AGENTS.md §4.3）:
 *   - 仅 import 模块1 token（通过 className 消费 CSS 变量）
 *   - 仅 import 模块3 springs/variants（通过 motion-variants.ts 工厂）
 *   - 仅 import 模块4 GlassTier 类型（data-glass-tier 属性值）
 *   - 仅 import 本模块基础设施（inject-glass-style / motion-variants）
 *     + 波1/3 基础组件（Card / Avatar / Input / Button / Badge）
 *   - 仅 import 第三方库 react / framer-motion
 *   - 禁止 import 模块5/7/8/9 内部实现
 *     （characterEmotion 为 string 类型，不 import 模块5 EmotionType 类型定义）
 *
 * 默认 spring: sheet（D5 §springs.sheet.useCase=sheet-modal，聊天面板入场）
 * OBS-C 守护: sheet 非 character（character 仅用于角色立绘动效，
 *   D5 §springs.character.useCaseRestriction=character-only）
 * ============================================================================
 */

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { motion, AnimatePresence, type Variants } from 'framer-motion';
import { cn } from '@/lib/utils';
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
import { Avatar } from './avatar';
import { Input } from './input';
import { Button } from './button';
import { Badge } from './badge';

// =============================================================================
// ChatMessageData 类型（消息数据结构，对应 I5 §ChatPanelProps.messages 元素）
// =============================================================================

/**
 * ChatPanel 消息数据结构（对应 I5 §ChatPanelProps.messages 元素）。
 *
 * I5 契约中 messages 为 List[Dict[str, Any]]，此处给出具体的 TS 类型定义。
 * 字段对齐任务要求: {id, role, content, timestamp?, emotion?}
 */
export interface ChatMessageData {
  /** 消息唯一标识 */
  readonly id: string | number;
  /** 消息角色（user=用户 / character=角色 / system=系统） */
  readonly role: 'user' | 'character' | 'system';
  /** 消息内容 */
  readonly content: string;
  /** 时间戳（可选，数字为 Unix ms，字符串为已格式化文本） */
  readonly timestamp?: number | string;
  /** 消息情绪（可选，用于角色消息的表情标注，I4 EmotionType 字符串值） */
  readonly emotion?: string;
}

// =============================================================================
// ChatPanelProps（对应 I5 §ChatPanelProps）
// =============================================================================

/**
 * ChatPanel 业务组件 props（对应 I5 §ChatPanelProps）。
 *
 * 继承 GlassComponentProps（Liquid Glass 扩展，含 dataGlass/glassTier/glassVariant/motionVariants 四字段）。
 * 业务封装组件基于 shadcn 基础组件重组，非从零实现（I5 §ChatPanel docstring）。
 */
export interface ChatPanelProps extends GlassComponentProps {
  /** 消息列表 */
  readonly messages: ChatMessageData[];
  /** 发送消息回调（输入框 Enter 键或点击发送按钮触发） */
  readonly onSend?: (text: string) => void;
  /** 角色情绪（来自 I4 EmotionType，string 类型，用于角色表情切换） */
  readonly characterEmotion?: string;
  /** 自定义 className */
  readonly className?: string;
  /** 角色名称（可选，用于头像 alt 和标题，默认"角色"） */
  readonly characterName?: string;
  /** 角色头像图片地址（可选，未提供时使用情绪 emoji 作为 fallback） */
  readonly characterAvatar?: string;
  /** 发送中状态（显示 loading，禁用输入） */
  readonly loading?: boolean;
  /** 输入框占位文本（默认"输入消息..."） */
  readonly placeholder?: string;
}

// =============================================================================
// ChatMessageProps（子组件 props）
// =============================================================================

/**
 * ChatMessage 子组件 props。
 *
 * 封装单条消息渲染，根据 message.role 决定布局（user 右对齐 / character 左对齐带头像 / system 居中）。
 */
export interface ChatMessageProps {
  /** 消息数据 */
  readonly message: ChatMessageData;
  /** 角色名称（可选，用于角色消息的头像 alt） */
  readonly characterName?: string;
  /** 角色头像图片地址（可选） */
  readonly characterAvatar?: string;
  /** 自定义 className */
  readonly className?: string;
}

// =============================================================================
// 角色情绪映射（characterEmotion → emoji + 中文标签）
// =============================================================================

/**
 * 角色情绪显示映射（characterEmotion → emoji + 中文标签）。
 *
 * characterEmotion 为 string 类型（I4 EmotionType 的字符串值），不直接 import 模块5。
 * 此映射用于 Avatar fallback 和 Badge 显示。
 * emoji 非颜色值，不违反"不硬编码颜色"约束。
 */
const EMOTION_DISPLAY: Readonly<
  Record<string, { readonly emoji: string; readonly label: string }>
> = {
  happy: { emoji: '😊', label: '开心' },
  sad: { emoji: '😢', label: '难过' },
  angry: { emoji: '😠', label: '生气' },
  neutral: { emoji: '😐', label: '平静' },
  surprised: { emoji: '😲', label: '惊讶' },
  shy: { emoji: '😳', label: '害羞' },
  excited: { emoji: '🤩', label: '兴奋' },
  thinking: { emoji: '🤔', label: '思考' },
};

/** 默认情绪显示（未知情绪或未提供情绪时使用） */
const DEFAULT_EMOTION_DISPLAY: { readonly emoji: string; readonly label: string } = {
  emoji: '🙂',
  label: '默认',
};

/**
 * 获取情绪显示信息（emoji + 中文标签）。
 *
 * @param emotion 情绪字符串（I4 EmotionType 字符串值）
 * @returns { emoji, label }，未知情绪返回默认值
 */
function getEmotionDisplay(emotion?: string): {
  readonly emoji: string;
  readonly label: string;
} {
  if (!emotion) return DEFAULT_EMOTION_DISPLAY;
  return EMOTION_DISPLAY[emotion] ?? { emoji: DEFAULT_EMOTION_DISPLAY.emoji, label: emotion };
}

// =============================================================================
// 辅助: 格式化时间戳
// =============================================================================

/**
 * 格式化时间戳为 HH:MM 格式。
 *
 * @param timestamp 时间戳（Unix ms 或已格式化字符串）
 * @returns 格式化后的时间字符串
 */
function formatTime(timestamp: number | string): string {
  if (typeof timestamp === 'string') return timestamp;
  const date = new Date(timestamp);
  const hours = String(date.getHours()).padStart(2, '0');
  const minutes = String(date.getMinutes()).padStart(2, '0');
  return `${hours}:${minutes}`;
}

// =============================================================================
// ChatPanel 组件实现
// =============================================================================

/**
 * ChatPanel 业务封装组件（第4波业务封装，Liquid Glass 定制）。
 *
 * 对应 I5 §ChatPanel: ``ChatPanel(props: ChatPanelProps): JSX.Element``。
 *
 * 业务封装策略（I5 §ChatPanel docstring）:
 *   - 基于 shadcn 基础组件重组，非从零实现
 *   - 使用 Card（波1）作为消息列表容器
 *   - 使用 Avatar（波3）渲染角色头像（结合 characterEmotion 切换表情）
 *   - 使用 Input（波1）+ Button（波1）作为消息输入区
 *   - 使用 Badge（波3）显示角色情绪状态
 *
 * Liquid Glass 定制（merged.md §4.2）:
 *   - 挂载 data-glass 属性，由 WebGL 层接管玻璃渲染
 *   - Framer Motion variants 替换 shadcn 默认 Tailwind transition
 *   - 消息列表使用 AnimatePresence 处理消息进出场动画
 *   - 通过 className + Tailwind utility 消费 token，不硬编码颜色
 *   - 双主题通过 CSS 变量自动切换，无需 JS 介入
 *
 * 默认 spring: sheet（D5 §springs.sheet.useCase=sheet-modal，聊天面板入场）
 * OBS-C 守护: sheet 非 character
 *
 * 集成角色情绪（I4 EmotionType）:
 *   - characterEmotion prop 接收情绪字符串（'happy'/'sad'/'angry'/'neutral' 等）
 *   - 通过 EMOTION_DISPLAY 映射到 Avatar fallback 显示不同 emoji
 *   - 情绪徽章使用 Badge variant='anime' 显示当前情绪中文标签
 *
 * 消息发送流程:
 *   - 输入框 Enter 键或点击发送按钮触发 onSend 回调
 *   - 发送后清空输入框
 *   - 支持发送中状态（loading prop）
 *
 * 自动滚动:
 *   - 新消息到达时自动滚动到消息列表底部
 *
 * @param props ChatPanel 组件配置（含 messages/onSend/characterEmotion + Liquid Glass 扩展字段）
 * @returns 渲染后的 ChatPanel
 */
export const ChatPanel = React.forwardRef<HTMLDivElement, ChatPanelProps>(
  function ChatPanel(
    {
      messages,
      onSend,
      characterEmotion,
      className,
      characterName = '角色',
      characterAvatar,
      loading = false,
      placeholder = '输入消息...',
      dataGlass = true,
      glassTier,
      glassVariant,
      motionVariants,
    },
    ref,
  ) {
    void glassTier; // v2: glassTier 已废弃，保留解构以避免 spread 到 DOM
    // 输入框状态
    const [inputValue, setInputValue] = useState('');
    // 消息列表底部 ref（用于自动滚动）
    const messagesEndRef = useRef<HTMLDivElement>(null);

    // 自动滚动到底部: 新消息到达时滚动
    useEffect(() => {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [messages.length]);

    // 获取 sheet spring 的 transition 参数（ChatPanel 默认 spring）
    // OBS-C 守护: sheet 非 character（character 仅用于角色立绘）
    const enterSpring = getComponentSpringTransition(
      glassVariant ?? getDefaultComponentSpring('ChatPanel'),
    );

    // ChatPanel 入场 variants（sheet spring，面板从下方滑入）
    // 若调用方提供 motionVariants 则直接使用，否则使用默认 sheet spring variants
    const resolvedVariants: Variants =
      motionVariants ??
      ({
        initial: { opacity: 0, y: 20 },
        animate: { opacity: 1, y: 0, transition: enterSpring },
        exit: { opacity: 0, y: 20, transition: enterSpring },
      } as Variants);

    const glassAttributes = buildGlassDataAttributes(dataGlass);

    // 情绪显示（emoji + 中文标签）
    const emotionDisplay = getEmotionDisplay(characterEmotion);

    // 发送消息: 清空输入框 + 触发 onSend 回调
    const handleSend = useCallback(() => {
      const trimmed = inputValue.trim();
      if (!trimmed || loading) return;
      onSend?.(trimmed);
      setInputValue('');
    }, [inputValue, loading, onSend]);

    // Enter 键发送（Shift+Enter 不触发，保留换行语义）
    const handleKeyDown = useCallback(
      (e: React.KeyboardEvent<HTMLInputElement>) => {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          handleSend();
        }
      },
      [handleSend],
    );

    // 构建 ChatPanel 根 className（通过 className 消费 token，不硬编码颜色）
    const panelBaseClassName = cn(
      'flex flex-col w-full h-full',
      'bg-[var(--chat-panel-bg,var(--card-bg))]',
      'rounded-[var(--card-radius)]',
      'border border-[var(--card-border)]',
      'shadow-[var(--card-shadow)]',
      'text-[var(--color-text-primary)]',
      'transition-none', // 移除 shadcn 默认 Tailwind transition，由 Framer Motion 接管
      'overflow-hidden',
      className,
    );

    // 注入 glass 样式类（v2: 直接拼接 glassPanelClass，不再区分 tier）
    const composedClassName = cn(panelBaseClassName, glassPanelClass);

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
        role="log"
        aria-label="聊天面板"
      >
        {/* 头部: 角色头像 + 名称 + 情绪徽章 */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-[var(--card-border)]">
          <Avatar
            src={characterAvatar}
            alt={characterName}
            fallback={emotionDisplay.emoji}
            size="md"
            shape="circle"
            dataGlass={false}
          />
          <div className="flex-1 min-w-0 flex items-center gap-2">
            <p className="text-sm font-medium text-[var(--color-text-primary)] truncate">
              {characterName}
            </p>
            {characterEmotion && (
              <Badge variant="anime" size="sm" dataGlass={false}>
                {emotionDisplay.label}
              </Badge>
            )}
          </div>
        </div>

        {/* 消息列表: Card 作为容器 + AnimatePresence 处理消息进出场 */}
        <Card
          dataGlass={false}
          className={cn(
            'flex-1 overflow-y-auto mx-2 my-2',
            'bg-[var(--chat-message-list-bg,transparent)]',
            'border-0 shadow-none',
          )}
        >
          <div className="px-2 py-2 min-h-[200px]">
            <AnimatePresence initial={false}>
              {messages.map((message) => (
                <ChatMessage
                  key={message.id}
                  message={message}
                  characterName={characterName}
                  characterAvatar={characterAvatar}
                />
              ))}
            </AnimatePresence>
            {/* 自动滚动锚点 */}
            <div ref={messagesEndRef} />
          </div>
        </Card>

        {/* 输入区: Input + 发送 Button */}
        <div className="flex items-center gap-2 px-4 py-3 border-t border-[var(--card-border)] bg-[var(--chat-input-bg,transparent)]">
          <Input
            type="text"
            placeholder={placeholder}
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={loading}
            dataGlass={false}
            className="flex-1"
          />
          <Button
            variant="primary"
            size="md"
            onClick={handleSend}
            loading={loading}
            disabled={loading || !inputValue.trim()}
            dataGlass={false}
          >
            发送
          </Button>
        </div>
      </motion.div>
    );
  },
);

ChatPanel.displayName = 'ChatPanel';

// =============================================================================
// ChatMessage 子组件实现（封装单条消息渲染）
// =============================================================================

/**
 * ChatMessage 子组件（封装单条消息渲染）。
 *
 * 根据 message.role 决定布局:
 *   - user: 右对齐，无头像，使用 --chat-message-user-bg
 *   - character: 左对齐，带头像，使用 --chat-message-character-bg
 *   - system: 居中，弱化样式
 *
 * 消息进出场动画使用 snappy spring（快速响应）。
 *
 * 通过 className 消费 token，不硬编码颜色。
 */
export const ChatMessage = React.forwardRef<HTMLDivElement, ChatMessageProps>(
  function ChatMessage({ message, characterName, characterAvatar, className }, ref) {
    const isUser = message.role === 'user';
    const isCharacter = message.role === 'character';
    const isSystem = message.role === 'system';

    // 消息进出场 variants（snappy spring 快速出现/消失）
    const messageSpring = getComponentSpringTransition('snappy');
    const messageVariants: Variants = {
      initial: { opacity: 0, y: 10 },
      animate: { opacity: 1, y: 0, transition: messageSpring },
      exit: { opacity: 0, y: -10, transition: messageSpring },
    };

    // 系统消息: 居中弱化
    if (isSystem) {
      return (
        <motion.div
          ref={ref}
          variants={messageVariants}
          initial="initial"
          animate="animate"
          exit="exit"
          className={cn(
            'flex justify-center my-2 transition-none',
            'text-xs text-[var(--color-text-tertiary)]',
            className,
          )}
        >
          <span className="px-3 py-1 rounded-[var(--radius-sm)] bg-[var(--chat-message-system-bg,transparent)]">
            {message.content}
          </span>
        </motion.div>
      );
    }

    // 用户/角色消息
    return (
      <motion.div
        ref={ref}
        variants={messageVariants}
        initial="initial"
        animate="animate"
        exit="exit"
        className={cn(
          'flex gap-2 mb-3 transition-none',
          isUser ? 'flex-row-reverse' : 'flex-row',
          className,
        )}
      >
        {/* 角色头像（仅角色消息显示） */}
        {isCharacter && (
          <Avatar
            src={characterAvatar}
            alt={characterName}
            size="sm"
            shape="circle"
            dataGlass={false}
            className="shrink-0"
          />
        )}
        {/* 消息气泡 */}
        <div
          className={cn(
            'max-w-[70%] rounded-[var(--radius-md)] px-3 py-2',
            'text-sm text-[var(--chat-message-text,var(--color-text-primary))]',
            'transition-none',
            isUser
              ? 'bg-[var(--chat-message-user-bg)]'
              : 'bg-[var(--chat-message-character-bg)]',
          )}
        >
          <p className="whitespace-pre-wrap break-words">{message.content}</p>
          {message.timestamp && (
            <span className="block mt-1 text-xs text-[var(--chat-message-time,var(--color-text-tertiary))]">
              {formatTime(message.timestamp)}
            </span>
          )}
        </div>
      </motion.div>
    );
  },
);

ChatMessage.displayName = 'ChatMessage';
