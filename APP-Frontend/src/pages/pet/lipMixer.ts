/**
 * 口型数据源优先级裁决（纯逻辑，SubTask 4.2/4.3/4.4 汇合点）。
 *
 * 桌宠头像只有一张嘴，三路音源竞争同一组口型 ref：
 * - tts      对话 TTS 播放（useWebSocket 内部播放器 + useTtsLipSync 频谱）
 * - danmaku  弹幕播报（useDanmakuVoice 频谱）
 * - mic      用户说话 VAD（useMicAsrUplink 本地频谱，仅服务端判定说话中有效）
 *
 * 优先级：tts > danmaku > mic > none。
 * 理由：对话回复是用户最关注的语音；弹幕播报次之；用户自己说话的
 * 口型反馈优先级最低（听到自己声音时头像跟嘴即可，被打断时立即让位）。
 */
export type LipSourceId = 'tts' | 'danmaku' | 'mic' | 'none';

export function pickLipSource(
  ttsPlaying: boolean,
  danmakuPlaying: boolean,
  micSpeaking: boolean,
): LipSourceId {
  if (ttsPlaying) return 'tts';
  if (danmakuPlaying) return 'danmaku';
  if (micSpeaking) return 'mic';
  return 'none';
}
