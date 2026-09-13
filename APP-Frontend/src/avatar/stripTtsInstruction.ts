/**
 * <tts_instruction> 情感语音指令剥离工具（展示层专用）。
 *
 * LLM 回复中含 <tts_instruction>{...}</tts_instruction> 情感语音指令
 * （提示词口径：位于回复最前面输出），该块仅供服务端语音管线解析情感，
 * 前端展示层必须剥离——聊天气泡、流式增量显示与历史恢复均不应显示 JSON 原文。
 *
 * 剥离只影响展示：发送给 TTS / 驱动的数据流路径不经过本工具。
 */

/** 完整块：<tts_instruction> ... </tts_instruction>（容忍标签内空白与跨行 JSON） */
const FULL_BLOCK_RE = /<tts_instruction\s*>[\s\S]*?<\/tts_instruction\s*>/g;

/** 流式开标签：<tts_instruction 已出现但闭合标记未到（\b 防止误伤 <tts_instructionX 等非标签文本） */
const OPEN_TAG_RE = /<tts_instruction\b/;

/**
 * 剥离文本中的 <tts_instruction> 块并 trim。
 *
 * - 完整块（含闭合标记）：全部移除；
 * - 流式场景（只出现开标签、闭合未到）：返回开标签之前的文本，
 *   避免流式中途闪现 JSON 原文；
 * - 无标签：原文不变（仅 trim）；空串安全。
 */
export function stripTtsInstruction(text: string): string {
  // 1) 先移除所有完整块
  let result = text.replace(FULL_BLOCK_RE, '');
  // 2) 流式保护：仍残留开标签（闭合未到）→ 只保留开标签之前的文本
  const openIdx = result.search(OPEN_TAG_RE);
  if (openIdx !== -1) {
    result = result.slice(0, openIdx);
  }
  return result.trim();
}
