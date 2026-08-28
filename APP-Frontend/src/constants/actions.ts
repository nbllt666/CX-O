/**
 * Action 常量定义（前端镜像）
 * 镜像后端 CX-O-SERVER server/protocol/actions.py，作为前端协议字符串的单一真相源。
 * 后端变更时须手动同步本文件。
 */

export const ChatActions = {
  MESSAGE: 'chat.message',
  STREAM: 'chat.stream',
  MULTIMODAL: 'chat.multimodal',
} as const;

export const VoiceActions = {
  DUAL_STREAM: 'voice.dual_stream',
  PARTIAL: 'voice.partial',
  TTS_CHUNK: 'voice.tts_chunk',
  PREFILL_STARTED: 'voice.prefill_started',
} as const;

export const DreamActions = {
  SESSION_STARTED: 'dream.session_started',
  SESSION_COMPLETED: 'dream.session_completed',
  SURFACE: 'dream.surface',
  CONFIRM: 'dream.confirm',
  REJECT: 'dream.reject',
  PURGED: 'dream.purged',
} as const;

export type VoiceActionType =
  | typeof VoiceActions.PARTIAL
  | typeof VoiceActions.TTS_CHUNK
  | typeof VoiceActions.PREFILL_STARTED;
