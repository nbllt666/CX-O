/**
 * VAD 状态判定（纯逻辑，SubTask 4.2）。
 *
 * 服务端 Live WS vad_status 事件：status 为 'speech_start' / 'speech_end'
 * （CX-O-SERVER live_client.handle_audio 只在 state_changed 时推送）。
 * 其他/未知值保持前一状态，避免异常事件把口型卡在张开位。
 */
export function vadStatusToSpeaking(status: string, previousSpeaking: boolean): boolean {
  if (status === 'speech_start') return true;
  if (status === 'speech_end') return false;
  return previousSpeaking;
}
