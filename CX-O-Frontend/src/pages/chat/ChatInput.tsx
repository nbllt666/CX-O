/**
 * H4 拆分：输入区 + 语音控制 + 双流式引擎选择。
 *
 * Presentational 组件 — 仅接收 props 与回调，不持有状态。
 * 包含图片预览、文本输入、语音输入、发送/停止、语音输出/模式切换、
 * 双流式实时语音切换、TTS 引擎与音色选择、连接状态。
 */
import type { ChangeEvent, KeyboardEvent, RefObject } from 'react';
import { Button, Textarea } from '../../components/ui';
import type { Agent } from '../../api/client';

export type DualStreamEngine = 'f5-tts' | 'orpheus';

export interface ChatInputProps {
  selectedImages: string[];
  onRemoveImage: (index: number) => void;
  currentAgent?: Agent;
  fileInputRef: RefObject<HTMLInputElement>;
  maxChatImages: number;
  onImageSelect: (e: ChangeEvent<HTMLInputElement>) => void;
  input: string;
  onInputChange: (value: string) => void;
  onKeyDown: (e: KeyboardEvent<HTMLTextAreaElement>) => void;
  isLoading: boolean;
  isRecording: boolean;
  onToggleRecording: () => void;
  onCancelGeneration: () => void;
  onSend: () => void;
  enableVoiceOutput: boolean;
  onToggleVoiceOutput: () => void;
  isVoiceMode: boolean;
  onToggleVoiceMode: () => void;
  isDualStreamMode: boolean;
  onToggleDualStreamMode: () => void;
  dualStreamEngine: DualStreamEngine;
  onDualStreamEngineChange: (engine: DualStreamEngine) => void;
  orpheusVoice: string;
  onOrpheusVoiceChange: (voice: string) => void;
  isConnected: boolean;
}

export function ChatInput({
  selectedImages,
  onRemoveImage,
  currentAgent,
  fileInputRef,
  maxChatImages,
  onImageSelect,
  input,
  onInputChange,
  onKeyDown,
  isLoading,
  isRecording,
  onToggleRecording,
  onCancelGeneration,
  onSend,
  enableVoiceOutput,
  onToggleVoiceOutput,
  isVoiceMode,
  onToggleVoiceMode,
  isDualStreamMode,
  onToggleDualStreamMode,
  dualStreamEngine,
  onDualStreamEngineChange,
  orpheusVoice,
  onOrpheusVoiceChange,
  isConnected,
}: ChatInputProps) {
  return (
    <div className="border-t border-[var(--color-border)] pt-4">
      {/* 图片预览 */}
      {selectedImages.length > 0 && (
        <div className="flex gap-2 mb-2 flex-wrap">
          {selectedImages.map((img, index) => (
            <div key={index} className="relative">
              <img
                src={img}
                alt={`预览 ${index + 1}`}
                className="w-16 h-16 object-cover rounded border border-[var(--color-border)]"
              />
              <button
                onClick={() => onRemoveImage(index)}
                className="absolute -top-1 -right-1 w-5 h-5 bg-red-500 text-white rounded-full text-xs flex items-center justify-center hover:bg-red-600"
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}

      <div className="flex gap-2">
        {/* 图片上传按钮 - 仅当 Agent 启用视觉时显示 */}
        {currentAgent?.vision_enabled && (
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            multiple
            onChange={onImageSelect}
            className="hidden"
          />
        )}
        {currentAgent?.vision_enabled && (
          <Button
            variant="secondary"
            onClick={() => fileInputRef.current?.click()}
            disabled={isLoading || selectedImages.length >= maxChatImages}
            className="self-end"
            title={`上传图片（最多${maxChatImages}张）`}
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"
              />
            </svg>
          </Button>
        )}

        <Textarea
          value={input}
          onChange={(e) => onInputChange(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder={`给 ${currentAgent?.name || '助手'} 发送消息...`}
          className="flex-1 min-h-[48px] max-h-[200px]"
          disabled={isLoading}
        />

        {/* 右侧按钮组：语音输入 + 发送 */}
        <div className="flex flex-col gap-2">
          {/* 语音输入按钮 */}
          <Button
            variant={isRecording ? 'primary' : 'secondary'}
            onClick={onToggleRecording}
            disabled={isLoading}
            size="sm"
            className={`self-end ${isRecording ? 'animate-pulse bg-red-500 hover:bg-red-600' : ''}`}
            title={isRecording ? '停止录音' : '语音输入'}
          >
            {isRecording ? (
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                />
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M9 10a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1h-4a1 1 0 01-1-1v-4z"
                />
              </svg>
            ) : (
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z"
                />
              </svg>
            )}
          </Button>

          {/* 发送/停止按钮 */}
          {isLoading ? (
            <Button
              variant="secondary"
              onClick={onCancelGeneration}
              size="sm"
              className="self-end"
              title="停止生成"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                />
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M9 10a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1h-4a1 1 0 01-1-1v-4z"
                />
              </svg>
            </Button>
          ) : (
            <Button
              onClick={onSend}
              disabled={(!input.trim() && selectedImages.length === 0) || isLoading}
              size="sm"
              className="self-end"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"
                />
              </svg>
            </Button>
          )}
        </div>
      </div>
      <div className="flex items-center justify-between mt-2">
        <div className="flex items-center gap-4">
          <p className="text-xs text-[var(--color-text-tertiary)]">
            按 Enter 发送，Shift + Enter 换行
            {currentAgent?.vision_enabled && ' · 支持图片上传'}
          </p>
          {/* 语音输出开关 */}
          <button
            onClick={onToggleVoiceOutput}
            className={`flex items-center gap-1 text-xs px-2 py-1 rounded transition-colors ${
              enableVoiceOutput
                ? 'bg-[var(--color-accent-light)] text-[var(--color-accent)]'
                : 'text-[var(--color-text-tertiary)] hover:text-[var(--color-text-secondary)]'
            }`}
            title={enableVoiceOutput ? '关闭语音输出' : '开启语音输出'}
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M15.536 8.464a5 5 0 010 7.072m2.828-9.9a9 9 0 010 12.728M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z"
              />
            </svg>
            <span>{enableVoiceOutput ? '语音输出开' : '语音输出关'}</span>
          </button>
          {/* 语音对话模式切换（半双工，双流式激活时禁用以避免冲突） */}
          <button
            onClick={onToggleVoiceMode}
            disabled={isDualStreamMode}
            className={`flex items-center gap-1 text-xs px-2 py-1 rounded transition-colors ${
              isVoiceMode
                ? 'bg-[var(--color-accent-light)] text-[var(--color-accent)]'
                : 'text-[var(--color-text-tertiary)] hover:text-[var(--color-text-secondary)]'
            }`}
            title={isVoiceMode ? '退出语音对话模式' : '进入语音对话模式'}
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
              />
            </svg>
            <span>{isVoiceMode ? '语音模式' : '文本模式'}</span>
          </button>
          {/* 双流式实时语音模式切换（区别于半双工"语音模式"）：
              ASR Partial 主驱动 + TTS 边收边播 + 全双工可打断，TTFA < 300ms */}
          <button
            onClick={onToggleDualStreamMode}
            disabled={isVoiceMode || isLoading}
            className={`flex items-center gap-1 text-xs px-2 py-1 rounded transition-colors ${
              isDualStreamMode
                ? 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300'
                : 'text-[var(--color-text-tertiary)] hover:text-[var(--color-text-secondary)]'
            } ${isVoiceMode ? 'opacity-40 cursor-not-allowed' : ''}`}
            title={isDualStreamMode ? '退出双流式实时语音' : '进入双流式实时语音（全双工）'}
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z"
              />
            </svg>
            <span>{isDualStreamMode ? '双流式开' : '双流式语音'}</span>
          </button>
          {/* 双流式 TTS 引擎切换：仅双流式激活时显示，切换时重启会话以应用新引擎 */}
          {isDualStreamMode && (
            <>
              <select
                value={dualStreamEngine}
                onChange={(e) => onDualStreamEngineChange(e.target.value as DualStreamEngine)}
                className="text-xs px-2 py-1 rounded border border-[var(--color-border)] bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)] cursor-pointer outline-none"
                title="选择 TTS 引擎"
              >
                <option value="f5-tts">F5-TTS</option>
                <option value="orpheus">Orpheus</option>
              </select>
              {/* Orpheus 音色选择：仅 orpheus 引擎显示（F5-TTS 使用 ref_audio，不需要音色） */}
              {dualStreamEngine === 'orpheus' && (
                <select
                  value={orpheusVoice}
                  onChange={(e) => onOrpheusVoiceChange(e.target.value)}
                  className="text-xs px-2 py-1 rounded border border-[var(--color-border)] bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)] cursor-pointer outline-none"
                  title="选择 Orpheus 音色"
                >
                  <option value="tara">tara</option>
                  <option value="leah">leah</option>
                  <option value="jess">jess</option>
                  <option value="leo">leo</option>
                  <option value="dan">dan</option>
                  <option value="mia">mia</option>
                  <option value="zac">zac</option>
                  <option value="zoe">zoe</option>
                </select>
              )}
            </>
          )}
        </div>
        <div className="flex items-center gap-1 text-xs">
          <span
            className={`w-2 h-2 rounded-full ${isConnected ? 'bg-green-500' : 'bg-red-500'}`}
          />
          <span className="text-[var(--color-text-tertiary)]">
            {isConnected ? 'WebSocket' : 'SSE'}
          </span>
        </div>
      </div>
    </div>
  );
}
