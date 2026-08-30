/**
 * PetChat — 桌宠对话气泡区。
 *
 * 行为口径对齐 CX-O-Frontend PetChat：
 * - 消息流式累积（updateLastAssistantMessage 追加增量）
 * - 收尾时解析头像驱动标签（parseAvatarTags → applyAvatarTags 下发驱动），
 *   气泡只显示剥离标签后的干净文本
 * - 仅保留最近 5 条做紧凑展示，新消息自动滚动到底
 *
 * 差异：TTS 不经本组件 HTTP 拉取——语音块由 useWebSocket 内部播放器自动播放，
 * 口型经 useTtsLipSync 频谱分接驱动。
 */
import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { SendHorizonal } from 'lucide-react';
import { parseAvatarTags } from '../../avatar/tagParser';
import { applyAvatarTags } from '../../avatar/applyTags';
import { createLabelTimeline } from '../../avatar/labelTimeline';
import type { LabelTimeline } from '../../avatar/labelTimeline';
import type { IAvatarDriver } from '../../avatar/types';

export interface PetMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  /** 声纹：注册说话人名（可选；仅 voice/ASR 路径带，打字输入不带） */
  speakerName?: string;
  /** 声纹：说话人标识（可选；未注册时为伪名 spk_N，渲染为「说话人N」小标签） */
  speakerId?: string;
}

/** 声纹小标签兜底文案：伪名 spk_N →「说话人N」（fallbackLabel 供 i18n），其余标识原样展示 */
function formatSpeakerLabel(
  speakerId: string | undefined,
  fallbackLabel: (index: string) => string,
): string {
  if (!speakerId) return '';
  const m = /^spk[_-]?(\d+)$/i.exec(speakerId);
  return m ? fallbackLabel(m[1]) : speakerId;
}

export interface PetChatHandle {
  /**
   * 追加消息；options.pinned=true 时该消息豁免 MAX_KEPT_MESSAGES 裁剪（C5：
   * ASR interim 气泡在识别期间不可被弹幕气泡挤出，否则 updateMessageContent 按 id
   * 更新失效、interim 文本展示丢失）。pinned 消息须由调用方在终态时显式 unpinMessage。
   */
  addMessage: (msg: PetMessage, options?: { pinned?: boolean }) => void;
  /**
   * 流式目标 id：占位气泡（a- 前缀）创建时登记，收尾/失败时清除。
   * 设置后 updateLast/finalize 按该 id 精确定位更新——弹幕播报（dv-）与
   * ASR interim（asr-）气泡随时插入不再串台；不参与 MAX_KEPT_MESSAGES 裁剪。
   * null 时回落旧行为（改末条 assistant），兼容既有单流调用方。
   */
  setStreamingTarget: (id: string | null) => void;
  /** 流式追加：把增量内容拼到最后一条助手消息上 */
  updateLastAssistantMessage: (delta: string) => void;
  /** 收尾：解析完整文本中的驱动标签并下发驱动，气泡替换为干净文本 */
  finalizeLastAssistantMessage: (fullContent: string) => void;
  /** 按 id 整体替换消息内容（ASR interim → final 就地更新气泡） */
  updateMessageContent: (id: string, content: string) => void;
  /** C5：解除 pinned 豁免（ASR final 落定/连接断开时调用，与 addMessage pinned 严格成对） */
  unpinMessage: (id: string) => void;
  /** 音画同步 Task3：按 TTS 累计原文进度推进标签时间线，触发已命中标签 */
  advanceTimeline: (cumulativeRaw: string) => void;
  /** 音画同步 Task3 兜底：TTS 播放结束/缺失 text_segment 时，触发剩余全部标签并重置 */
  flushRemaining: () => void;
}

interface PetChatProps {
  driver: IAvatarDriver | null;
  onSend: (message: string) => void;
  isLoading: boolean;
  isConnected: boolean;
  /** 输入行左侧附件槽（如「发送当前画面」按钮），由 PetPage 注入 */
  inputAccessory?: ReactNode;
  /** 音画同步 Task3：TTS 原文累计进度回调（同 useWebSocket.onTextProgress），PetChat 据此推进标签时间线 */
  onTextProgress?: (cumulativeRaw: string) => void;
}

/** 紧凑展示窗口：仅保留最近 N 条 */
const MAX_DISPLAY_MESSAGES = 5;
/** 底层保留上限：展示条数 + 流式余量，防止消息数组无界增长并被流式收尾切断 */
const MAX_KEPT_MESSAGES = MAX_DISPLAY_MESSAGES + 3;

export const PetChat = forwardRef<PetChatHandle, PetChatProps>(function PetChat(
  { driver, onSend, isLoading, isConnected, inputAccessory, onTextProgress },
  ref,
) {
  const { t } = useTranslation();
  const [messages, setMessages] = useState<PetMessage[]>([]);
  const [input, setInput] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  // driver 经 ref 透传给 finalize，避免流式回调因驱动切换过期
  const driverRef = useRef<IAvatarDriver | null>(null);
  driverRef.current = driver;
  // 音画同步 Task3：当前标签时间线（其 cleanText 作为气泡显示文本）
  const timelineRef = useRef<LabelTimeline | null>(null);
  // 记录父级传入的 TTS 原文进度回调（经 handle.advanceTimeline 推进）
  const onTextProgressRef = useRef(onTextProgress);
  onTextProgressRef.current = onTextProgress;
  // 流式目标消息 id（B1）：占位气泡创建时由 PetPage 登记为当前流式目标，
  // updateLast/finalize 按该 id 定位更新，避免 dv-/asr- 气泡插入后串台；
  // 裁剪时跳过该消息，防止流式中的气泡被挤出 MAX_KEPT_MESSAGES 窗口后增量永久丢失
  const streamingTargetIdRef = useRef<string | null>(null);
  // C5：pinned 消息 id 集合——豁免 MAX_KEPT_MESSAGES 裁剪的消息（当前仅 ASR interim 气泡）。
  // 有界性：由调用方保证 pin（addMessage options.pinned）与 unpin（unpinMessage）严格成对，
  // 集合不跨组件卸载存活（ref 随组件释放），不跨会话累积
  const pinnedIdsRef = useRef<Set<string>>(new Set());

  const setStreamingTarget = useCallback((id: string | null) => {
    streamingTargetIdRef.current = id;
  }, []);

  const unpinMessage = useCallback((id: string) => {
    pinnedIdsRef.current.delete(id);
  }, []);

  const addMessage = useCallback((msg: PetMessage, options?: { pinned?: boolean }) => {
    if (options?.pinned) pinnedIdsRef.current.add(msg.id);
    setMessages((prev) => {
      const next = [...prev, msg];
      if (next.length <= MAX_KEPT_MESSAGES) return next;
      // 有界裁剪：仅从头部丢弃旧消息，既阻止底层数组无界增长，又保住正在流式的气泡。
      // 豁免集合 = 流式目标消息（B1）+ pinned 消息（C5）——弹幕播报/ASR interim 气泡随时插入，
      // 若按窗口大小硬裁会把滑出窗口的流式中 a- 气泡永久丢弃，或使 asr- 气泡
      // 被 updateMessageContent 更新失效（按 id 无命中静默 no-op，interim 文本展示消失）
      const targetId = streamingTargetIdRef.current;
      const exempt = (id: string) =>
        (targetId != null && id === targetId) || pinnedIdsRef.current.has(id);
      let overflow = next.length - MAX_KEPT_MESSAGES;
      const kept: PetMessage[] = [];
      for (const m of next) {
        if (overflow > 0 && !exempt(m.id)) {
          overflow -= 1;
          continue;
        }
        kept.push(m);
      }
      return kept;
    });
  }, []);

  const updateLastAssistantMessage = useCallback((delta: string) => {
    setMessages((prev) => {
      // B1：设置了流式目标 → 按占位气泡 id 精确追加（弹幕/ASR 气泡插入不串台）；
      // 目标已不在消息列表（被清除/异常）时静默跳过，对齐既有防御
      const targetId = streamingTargetIdRef.current;
      if (targetId) {
        const idx = prev.findIndex((m) => m.id === targetId && m.role === 'assistant');
        if (idx === -1) return prev;
        const target = prev[idx];
        return [
          ...prev.slice(0, idx),
          { ...target, content: target.content + delta },
          ...prev.slice(idx + 1),
        ];
      }
      // 未设置目标：回落旧行为（改末条 assistant），兼容既有单流调用方
      const last = prev[prev.length - 1];
      if (last && last.role === 'assistant') {
        return [...prev.slice(0, -1), { ...last, content: last.content + delta }];
      }
      return prev;
    });
  }, []);

  const finalizeLastAssistantMessage = useCallback((fullContent: string) => {
    setMessages((prev) => {
      // B1：与 updateLast 同口径按流式目标定位；找不到时静默跳过（对齐既有防御）
      const targetId = streamingTargetIdRef.current;
      let index: number;
      if (targetId) {
        const idx = prev.findIndex((m) => m.id === targetId && m.role === 'assistant');
        if (idx === -1) return prev;
        index = idx;
      } else {
        const last = prev[prev.length - 1];
        if (!last || last.role !== 'assistant') return prev;
        index = prev.length - 1;
      }
      const target = prev[index];
      const { cleanText, tags } = parseAvatarTags(fullContent);
      if (tags.length > 0) {
        // 音画同步 Task3：含标签 → 构建时间线，标签随 TTS 朗读进度逐步触发（advanceTimeline），
        // 而非收尾时一次性 applyAvatarTags；气泡仍显示剥离标签后的干净文本
        timelineRef.current = createLabelTimeline(fullContent);
      } else {
        // 无标签：清空可能残留的旧时间线，避免污染下一条消息
        timelineRef.current = null;
      }
      const next = [...prev];
      next[index] = { ...target, content: cleanText };
      return next;
    });
  }, []);

  const updateMessageContent = useCallback((id: string, content: string) => {
    setMessages((prev) => prev.map((msg) => (msg.id === id ? { ...msg, content } : msg)));
  }, []);

  // 音画同步 Task3：按 TTS 累计原文进度推进时间线并触发已命中标签
  const advanceTimeline = useCallback((cumulativeRaw: string) => {
    const timeline = timelineRef.current;
    if (!timeline) return;
    // 无剩余标签时直接返回，避免不必要的推进调用
    if (timeline.getRemaining().length === 0) return;
    const hits = timeline.advanceTo(cumulativeRaw.length);
    if (driverRef.current && hits.length > 0) {
      applyAvatarTags(driverRef.current, hits.map((h) => h.tag));
    }
  }, []);

  // 音画同步 Task3 兜底：整句播放结束 / 缺失 text_segment → 触发剩余全部标签并重置
  const flushRemaining = useCallback(() => {
    const timeline = timelineRef.current;
    if (!timeline) return;
    const remaining = timeline.getRemaining();
    if (driverRef.current && remaining.length > 0) {
      applyAvatarTags(driverRef.current, remaining);
    }
    timeline.reset();
  }, []);

  useImperativeHandle(
    ref,
    () => ({
      addMessage,
      setStreamingTarget,
      updateLastAssistantMessage,
      finalizeLastAssistantMessage,
      updateMessageContent,
      unpinMessage,
      advanceTimeline,
      flushRemaining,
    }),
    [
      addMessage,
      setStreamingTarget,
      updateLastAssistantMessage,
      finalizeLastAssistantMessage,
      updateMessageContent,
      unpinMessage,
      advanceTimeline,
      flushRemaining,
    ],
  );

  const displayMessages = messages.slice(-MAX_DISPLAY_MESSAGES);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [displayMessages.length]);

  const handleSend = () => {
    const text = input.trim();
    if (!text || isLoading) return;
    addMessage({
      id: `u-${Date.now()}`,
      role: 'user',
      content: text,
      timestamp: new Date().toISOString(),
    });
    onSend(text);
    setInput('');
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="flex h-full flex-col" style={{ backgroundColor: 'transparent' }}>
      {/* 消息气泡区 */}
      <div className="flex-1 space-y-1.5 overflow-y-auto px-2 py-1">
        {displayMessages.map((msg) => {
          // D6：说话人小标签——注册名优先，未注册伪名 spk_N 兜底为「说话人N」；缺失不占位
          const speakerLabel =
            msg.speakerName ||
            formatSpeakerLabel(msg.speakerId, (index) =>
              t('pet.chat.speakerFallback', { index }),
            );
          return (
            <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div
                className={`max-w-[85%] whitespace-pre-wrap break-words rounded-xl px-2.5 py-1.5 text-xs leading-relaxed backdrop-blur-md ${
                  msg.role === 'user'
                    ? 'bg-primary/80 text-primary-foreground'
                    : 'glass-panel text-foreground'
                }`}
              >
                {msg.role === 'user' && speakerLabel ? (
                  <span className="mb-0.5 block text-[10px] leading-none text-primary-foreground/70">
                    {speakerLabel}
                  </span>
                ) : null}
                {msg.content}
              </div>
            </div>
          );
        })}
        <div ref={messagesEndRef} />
      </div>

      {/* 输入行 */}
      <div className="flex items-center gap-1.5 px-2 py-1.5">
        {inputAccessory}
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={isConnected ? t('pet.chat.placeholder') : t('pet.chat.offline')}
          disabled={isLoading}
          aria-label={t('pet.chat.placeholder')}
          className="glass-panel min-h-[28px] flex-1 rounded-lg px-2.5 py-1 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary/60 disabled:opacity-60"
        />
        <button
          type="button"
          onClick={handleSend}
          disabled={!input.trim() || isLoading}
          aria-label={t('pet.chat.send')}
          className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary/85 text-primary-foreground transition-opacity duration-fast hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <SendHorizonal className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
});
