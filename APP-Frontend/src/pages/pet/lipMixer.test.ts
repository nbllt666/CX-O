import { describe, expect, it } from 'vitest';

import { pickLipSource } from './lipMixer';
import { vadStatusToSpeaking } from './vad';

describe('pickLipSource', () => {
  it('全部静默时为 none', () => {
    expect(pickLipSource(false, false, false)).toBe('none');
  });

  it('对话 TTS 优先级最高', () => {
    expect(pickLipSource(true, true, true)).toBe('tts');
    expect(pickLipSource(true, false, false)).toBe('tts');
  });

  it('弹幕播报让位 TTS、压过麦克风', () => {
    expect(pickLipSource(false, true, true)).toBe('danmaku');
    expect(pickLipSource(false, true, false)).toBe('danmaku');
  });

  it('仅麦克风说话时选 mic', () => {
    expect(pickLipSource(false, false, true)).toBe('mic');
  });
});

describe('vadStatusToSpeaking', () => {
  it('speech_start 置真、speech_end 置假', () => {
    expect(vadStatusToSpeaking('speech_start', false)).toBe(true);
    expect(vadStatusToSpeaking('speech_end', true)).toBe(false);
  });

  it('未知状态保持前值，避免口型卡死', () => {
    expect(vadStatusToSpeaking('', true)).toBe(true);
    expect(vadStatusToSpeaking('unknown', false)).toBe(false);
  });
});
