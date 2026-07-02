import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { applyAvatarTags, groupTtsSegments, playTTSWithPauses } from './utils';
import { parseAvatarTags } from '../../lib/avatarTagParser';
import type { IAvatarDriver } from '../../components/Avatar/AvatarDriver';

function makeMockDriver(): IAvatarDriver & { calls: string[] } {
  const calls: string[] = [];
  return {
    calls,
    avatar: {} as never,
    expressionMix: [],
    parameterOverrides: [],
    watermarkVisible: false,
    transform: {} as never,
    mouthOpen: 0,
    setExpressionMix: vi.fn(() => calls.push('setExpressionMix')),
    setParameterOverrides: vi.fn(() => calls.push('setParameterOverrides')),
    setWatermarkVisibility: vi.fn(() => calls.push('setWatermarkVisibility')),
    setTransform: vi.fn(() => calls.push('setTransform')),
    setMouthOpen: vi.fn(() => calls.push('setMouthOpen')),
    subscribe: vi.fn(() => () => calls.push('unsubscribe')),
    getActiveExpressions: vi.fn(() => []),
    setEmotion: vi.fn((name: string, weight: number) => calls.push(`setEmotion:${name}:${weight}`)),
    triggerEmotionMotion: vi.fn(() => calls.push('triggerEmotionMotion')),
    triggerSpeechMotion: vi.fn(() => calls.push('triggerSpeechMotion')),
    bindRuntime: vi.fn(() => calls.push('bindRuntime')),
    update: vi.fn(() => calls.push('update')),
    setBlendShapes: vi.fn((entries) => calls.push(`setBlendShapes:${JSON.stringify(entries)}`)),
    setBoneRotations: vi.fn((entries) => calls.push(`setBoneRotations:${JSON.stringify(entries)}`)),
    holdPose: vi.fn((durationMs?: number) => calls.push(`holdPose:${durationMs}`)),
    releasePose: vi.fn(() => calls.push('releasePose')),
    setWind: vi.fn((params) => calls.push(`setWind:${JSON.stringify(params)}`)),
  } as unknown as IAvatarDriver & { calls: string[] };
}

describe('applyAvatarTags', () => {
  it('emotion tag 调用 driver.setEmotion(name, 1.0)', () => {
    const driver = makeMockDriver();
    applyAvatarTags(driver, [{ type: 'emotion', name: 'happy' }]);
    expect(driver.setEmotion).toHaveBeenCalledWith('happy', 1.0);
    expect(driver.calls).toEqual(['setEmotion:happy:1']);
  });

  it('blend tag 调用 driver.setBlendShapes([{name, weight}])', () => {
    const driver = makeMockDriver();
    applyAvatarTags(driver, [{ type: 'blend', name: 'smile', weight: 0.5 }]);
    expect(driver.setBlendShapes).toHaveBeenCalledWith([{ name: 'smile', weight: 0.5 }]);
  });

  it('bone tag 调用 driver.setBoneRotations([{boneName, rotation, speed}])', () => {
    const driver = makeMockDriver();
    const rotation = { x: 0.1, y: 0.2, z: 0.3 };
    applyAvatarTags(driver, [{ type: 'bone', boneName: 'head', rotation, speed: 2.0 }]);
    expect(driver.setBoneRotations).toHaveBeenCalledWith([{ boneName: 'head', rotation, speed: 2.0 }]);
  });

  it('pose tag 调用 driver.holdPose(durationMs)', () => {
    const driver = makeMockDriver();
    applyAvatarTags(driver, [{ type: 'pose', durationMs: 1500 }]);
    expect(driver.holdPose).toHaveBeenCalledWith(1500);
  });

  it('release tag 调用 driver.releasePose()', () => {
    const driver = makeMockDriver();
    applyAvatarTags(driver, [{ type: 'release' }]);
    expect(driver.releasePose).toHaveBeenCalledTimes(1);
  });

  it('wind tag 调用 driver.setWind(tag)', () => {
    const driver = makeMockDriver();
    const windTag = {
      type: 'wind' as const,
      direction: 90,
      strength: 0.5,
      gustStrength: 0.3,
      gustFrequency: 1.5,
      gustDuration: 200,
    };
    applyAvatarTags(driver, [windTag]);
    expect(driver.setWind).toHaveBeenCalledWith(windTag);
  });

  it('sleep tag 仅 console.log，不调用 driver 方法', () => {
    const driver = makeMockDriver();
    const logSpy = vi.spyOn(console, 'log').mockImplementation(() => {});
    applyAvatarTags(driver, [{ type: 'sleep', ms: 500 }]);
    expect(logSpy).toHaveBeenCalledWith('[avatar] sleep tag:', 500, 'ms');
    expect(driver.calls).toEqual([]);
    logSpy.mockRestore();
  });

  it('空 tags 数组不调用任何 driver 方法', () => {
    const driver = makeMockDriver();
    applyAvatarTags(driver, []);
    expect(driver.calls).toEqual([]);
  });

  it('多 tag 按顺序调用', () => {
    const driver = makeMockDriver();
    applyAvatarTags(driver, [
      { type: 'emotion', name: 'happy' },
      { type: 'pose', durationMs: 1000 },
      { type: 'release' },
    ]);
    expect(driver.calls).toEqual([
      'setEmotion:happy:1',
      'holdPose:1000',
      'releasePose',
    ]);
  });
});

describe('groupTtsSegments', () => {
  it('空 segments 返回空数组', () => {
    expect(groupTtsSegments([])).toEqual([]);
  });

  it('纯文本无 sleep tag 返回单一 group', () => {
    const segments = parseAvatarTags('hello world').segments;
    expect(groupTtsSegments(segments)).toEqual([{ text: 'hello world' }]);
  });

  it('文本 + sleep + 文本 → 两组，第一组带 sleepAfterMs', () => {
    const segments = parseAvatarTags('hello[sleep:500]world').segments;
    expect(groupTtsSegments(segments)).toEqual([
      { text: 'hello', sleepAfterMs: 500 },
      { text: 'world' },
    ]);
  });

  it('末尾 sleep tag 不产生新 group（textBuffer 空，已有 group）→ 累加到最后一组', () => {
    const segments = parseAvatarTags('hello[sleep:500][sleep:300]').segments;
    expect(groupTtsSegments(segments)).toEqual([
      { text: 'hello', sleepAfterMs: 800 },
    ]);
  });

  it('开头 sleep tag（textBuffer 空，无 group）→ 被忽略', () => {
    const segments = parseAvatarTags('[sleep:500]hello').segments;
    expect(groupTtsSegments(segments)).toEqual([{ text: 'hello' }]);
  });

  it('多个 sleep 在文本中间各自产生新 group', () => {
    const segments = parseAvatarTags('a[sleep:100]b[sleep:200]c').segments;
    expect(groupTtsSegments(segments)).toEqual([
      { text: 'a', sleepAfterMs: 100 },
      { text: 'b', sleepAfterMs: 200 },
      { text: 'c' },
    ]);
  });

  it('纯 sleep tag 无文本 → 返回空数组', () => {
    const segments = parseAvatarTags('[sleep:500]').segments;
    expect(groupTtsSegments(segments)).toEqual([]);
  });

  it('仅空白文本被过滤（trim 后为空不入 group）', () => {
    const segments = parseAvatarTags('   [sleep:500]   ').segments;
    expect(groupTtsSegments(segments)).toEqual([]);
  });

  it('连续 sleep 在文本之间：sleep 累加到前一组的 sleepAfterMs', () => {
    const segments = parseAvatarTags('a[sleep:100][sleep:200]b').segments;
    expect(groupTtsSegments(segments)).toEqual([
      { text: 'a', sleepAfterMs: 300 },
      { text: 'b' },
    ]);
  });
});

/**
 * 创建模拟 Blob 对象：绕过 jsdom Blob.arrayBuffer() 实现不稳定的问题。
 * 返回的对象满足 playTTSWithPauses 对 ttsFn 返回值的契约（仅需 .arrayBuffer() 方法）。
 */
function makeMockBlob(text: string): Blob {
  const bytes = new TextEncoder().encode(text);
  const buffer = new ArrayBuffer(bytes.length);
  new Uint8Array(buffer).set(bytes);
  return { arrayBuffer: async () => buffer } as unknown as Blob;
}

describe('playTTSWithPauses', () => {
  let ttsFn: ReturnType<typeof vi.fn>;
  let playFn: ReturnType<typeof vi.fn>;
  let errorSpy: ReturnType<typeof vi.spyOn>;
  let originalSetTimeout: typeof setTimeout;
  const sleepCalls: number[] = [];

  beforeEach(() => {
    sleepCalls.length = 0;
    originalSetTimeout = global.setTimeout;
    // 包装 setTimeout：记录请求时长但用真实 setTimeout(cb, 0) 触发，保证 Blob.arrayBuffer() 等
    // 异步 API 能正常 resolve（queueMicrotask 无法让 Blob 内部 Promise 完成）
    global.setTimeout = ((cb: () => void, ms: number) => {
      sleepCalls.push(ms);
      return originalSetTimeout(cb as TimerHandler, 0);
    }) as typeof setTimeout;

    ttsFn = vi.fn(async (text: string) => makeMockBlob(text));
    playFn = vi.fn(async () => {});
    errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  afterEach(() => {
    global.setTimeout = originalSetTimeout;
    errorSpy.mockRestore();
  });

  it('空 segments 不调用 tts/play', async () => {
    await playTTSWithPauses([], ttsFn, playFn);
    expect(ttsFn).not.toHaveBeenCalled();
    expect(playFn).not.toHaveBeenCalled();
    expect(sleepCalls).toEqual([]);
  });

  it('纯文本无 sleep → 调用一次 tts + 一次 play，isLastSegment=true', async () => {
    const segments = parseAvatarTags('hello world').segments;
    await playTTSWithPauses(segments, ttsFn, playFn);

    expect(ttsFn).toHaveBeenCalledTimes(1);
    expect(ttsFn).toHaveBeenCalledWith('hello world');
    expect(playFn).toHaveBeenCalledTimes(1);
    expect(playFn.mock.calls[0][1]).toBe(true);
    expect(sleepCalls).toEqual([]);
  });

  it('两组文本 + 中间 sleep → tts/play 各两次，最后一组 isLastSegment=true', async () => {
    const segments = parseAvatarTags('hello[sleep:500]world').segments;
    await playTTSWithPauses(segments, ttsFn, playFn);

    expect(ttsFn).toHaveBeenCalledTimes(2);
    expect(ttsFn).toHaveBeenNthCalledWith(1, 'hello');
    expect(ttsFn).toHaveBeenNthCalledWith(2, 'world');
    expect(playFn).toHaveBeenCalledTimes(2);
    expect(playFn.mock.calls[0][1]).toBe(false);
    expect(playFn.mock.calls[1][1]).toBe(true);
    expect(sleepCalls).toEqual([500]);
  });

  it('sleep 时长传入 setTimeout', async () => {
    const segments = parseAvatarTags('a[sleep:500]b').segments;
    await playTTSWithPauses(segments, ttsFn, playFn);
    expect(sleepCalls).toEqual([500]);
  });

  it('末尾 sleep 不等待（最后一组即使有 sleepAfterMs 也不 sleep）', async () => {
    const segments = parseAvatarTags('hello[sleep:500][sleep:300]').segments;
    await playTTSWithPauses(segments, ttsFn, playFn);

    // 只有一组（sleep 累加到 800），但末尾组不触发 sleep
    expect(ttsFn).toHaveBeenCalledTimes(1);
    expect(playFn).toHaveBeenCalledTimes(1);
    expect(playFn.mock.calls[0][1]).toBe(true);
    expect(sleepCalls).toEqual([]);
  });

  it('tts 抛错被吞掉，继续下一组', async () => {
    ttsFn = vi.fn(async (text: string) => {
      if (text === 'bad') throw new Error('tts failed');
      return makeMockBlob(text);
    });
    const segments = parseAvatarTags('bad[sleep:100]good').segments;
    await playTTSWithPauses(segments, ttsFn, playFn);

    expect(errorSpy).toHaveBeenCalledWith('语音合成失败:', expect.any(Error));
    expect(ttsFn).toHaveBeenCalledTimes(2);
    expect(playFn).toHaveBeenCalledTimes(1);
    expect(playFn.mock.calls[0][1]).toBe(true);
  });

  it('play 抛错被吞掉，继续下一组', async () => {
    playFn = vi.fn(async () => {
      throw new Error('play failed');
    });
    const segments = parseAvatarTags('a[sleep:100]b').segments;
    await playTTSWithPauses(segments, ttsFn, playFn);

    expect(errorSpy).toHaveBeenCalledTimes(2);
    expect(ttsFn).toHaveBeenCalledTimes(2);
    expect(playFn).toHaveBeenCalledTimes(2);
  });

  it('isLastSegment 仅最后一组为 true（即使中间组失败）', async () => {
    ttsFn = vi.fn(async (text: string) => {
      if (text === 'a') throw new Error('fail');
      return makeMockBlob(text);
    });
    const segments = parseAvatarTags('a[sleep:100]b[sleep:100]c').segments;
    await playTTSWithPauses(segments, ttsFn, playFn);

    expect(playFn).toHaveBeenCalledTimes(2); // a 失败，b 和 c 成功
    expect(playFn.mock.calls[0][1]).toBe(false); // b 不是最后
    expect(playFn.mock.calls[1][1]).toBe(true);  // c 是最后
  });

  it('playFn 收到的 audioData 是 ttsFn 返回 Blob 的 ArrayBuffer', async () => {
    const segments = parseAvatarTags('hi').segments;
    await playTTSWithPauses(segments, ttsFn, playFn);

    const arrayBuffer = playFn.mock.calls[0][0] as ArrayBuffer;
    expect(arrayBuffer).toBeInstanceOf(ArrayBuffer);
    const text = new TextDecoder().decode(arrayBuffer);
    expect(text).toBe('hi');
  });
});
