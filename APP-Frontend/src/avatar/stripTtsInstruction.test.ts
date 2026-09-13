/**
 * stripTtsInstruction 单测：<tts_instruction> 情感语音指令剥离（展示层）。
 *
 * 覆盖：完整块剥离、多块剥离、无标签原文不变、流式未闭合只显示开标签前
 * 文本、空串安全，以及标签前置口径（回复最前面）下的典型形态。
 */
import { describe, it, expect } from 'vitest';

import { stripTtsInstruction } from './stripTtsInstruction';

describe('stripTtsInstruction', () => {
  it('剥离完整块，仅保留正文（标签前置口径）', () => {
    const text = '<tts_instruction>{"emotion":"happy","speed":1.1}</tts_instruction>你好呀！';
    expect(stripTtsInstruction(text)).toBe('你好呀！');
  });

  it('剥离多个完整块', () => {
    const text =
      '前<tts_instruction>{"a":1}</tts_instruction>中<tts_instruction>{"b":2}</tts_instruction>后';
    expect(stripTtsInstruction(text)).toBe('前中后');
  });

  it('块内含换行与空白的多行 JSON 也能剥离', () => {
    const text = '<tts_instruction>\n  {"emotion": "happy"}\n</tts_instruction>\n正文内容';
    expect(stripTtsInstruction(text)).toBe('正文内容');
  });

  it('无标签时原文不变（仅 trim）', () => {
    expect(stripTtsInstruction('普通回复文本')).toBe('普通回复文本');
    expect(stripTtsInstruction('  带首尾空白  ')).toBe('带首尾空白');
  });

  it('流式未闭合：只显示开标签之前的文本', () => {
    // 开标签在最前：无正文可显示
    expect(stripTtsInstruction('<tts_instruction>{"emotion":"hap')).toBe('');
    // 正文在前：保留开标签之前的文本
    expect(stripTtsInstruction('你好<tts_instruction>{"emotion":"hap')).toBe('你好');
    // 刚吐出开标签名、连 > 都未到
    expect(stripTtsInstruction('你好<tts_instruction')).toBe('你好');
  });

  it('完整块与未闭合开标签混合：移除完整块后按流式截断', () => {
    const text = '前<tts_instruction>{"a":1}</tts_instruction>中<tts_instruction>{"b":';
    expect(stripTtsInstruction(text)).toBe('前中');
  });

  it('空串安全', () => {
    expect(stripTtsInstruction('')).toBe('');
  });

  it('不误伤含相似前缀的普通文本', () => {
    expect(stripTtsInstruction('normal text with tts_instructionX inside')).toBe(
      'normal text with tts_instructionX inside',
    );
  });
});
