/**
 * applyTags 单测：标签到 IAvatarDriver 的分发逻辑。
 *
 * 用 vi.fn() 桩出完整 IAvatarDriver 接口，逐类标签验证调用面与参数透传；
 * sleep 标签只留日志、不下发驱动。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

import { applyAvatarTags } from './applyTags';
import type { IAvatarDriver, AvatarManifest } from './types';
import type { AvatarTag } from './tagParser';

function createMockDriver() {
  const manifest = { id: 'mock', avatarType: 'vrm' } as unknown as AvatarManifest;
  const driver: IAvatarDriver = {
    avatar: manifest,
    expressionMix: [],
    parameterOverrides: [],
    watermarkVisible: false,
    transform: { scale: 1, offsetX: 0, offsetY: 0 },
    mouthOpen: 0,
    setExpressionMix: vi.fn(),
    setParameterOverrides: vi.fn(),
    setWatermarkVisibility: vi.fn(),
    setTransform: vi.fn(),
    setMouthOpen: vi.fn(),
    subscribe: vi.fn(() => () => {}),
    getActiveExpressions: vi.fn(() => []),
    setEmotion: vi.fn(),
    triggerEmotionMotion: vi.fn(),
    triggerSpeechMotion: vi.fn(),
    bindRuntime: vi.fn(),
    update: vi.fn(),
    setBlendShapes: vi.fn(),
    setBoneRotations: vi.fn(),
    holdPose: vi.fn(),
    releasePose: vi.fn(),
    setWind: vi.fn(),
    destroy: vi.fn(),
  };
  return driver;
}

describe('applyAvatarTags 分发', () => {
  it('emotion → setEmotion(emotion, 1.0)', () => {
    const driver = createMockDriver();
    applyAvatarTags(driver, [{ type: 'emotion', emotion: 'happy' }]);
    expect(driver.setEmotion).toHaveBeenCalledWith('happy', 1.0);
  });

  it('blend → setBlendShapes 单条目数组', () => {
    const driver = createMockDriver();
    applyAvatarTags(driver, [{ type: 'blend', name: 'smile', weight: 0.7 }]);
    expect(driver.setBlendShapes).toHaveBeenCalledWith([{ name: 'smile', weight: 0.7 }]);
  });

  it('bone → setBoneRotations 透传旋转与速度', () => {
    const driver = createMockDriver();
    const rotation = { x: 0.1, y: 0.2, z: 0.3 };
    applyAvatarTags(driver, [{ type: 'bone', boneName: 'head', rotation, speed: 2 }]);
    expect(driver.setBoneRotations).toHaveBeenCalledWith([
      { boneName: 'head', rotation, speed: 2 },
    ]);
  });

  it('pose → holdPose(durationMs)；release → releasePose()', () => {
    const driver = createMockDriver();
    applyAvatarTags(driver, [{ type: 'pose', durationMs: 1500 }, { type: 'release' }]);
    expect(driver.holdPose).toHaveBeenCalledWith(1500);
    expect(driver.releasePose).toHaveBeenCalledTimes(1);
  });

  it('wind → setWind 整体透传', () => {
    const driver = createMockDriver();
    const wind: AvatarTag = {
      type: 'wind',
      direction: 90,
      strength: 0.5,
      gustStrength: 0.2,
      gustFrequency: 1,
      gustDuration: '2-5',
    };
    applyAvatarTags(driver, [wind]);
    expect(driver.setWind).toHaveBeenCalledWith(wind);
  });

  it('多标签按序依次下发', () => {
    const driver = createMockDriver();
    const calls: string[] = [];
    (driver.setEmotion as ReturnType<typeof vi.fn>).mockImplementation(() => calls.push('emotion'));
    (driver.releasePose as ReturnType<typeof vi.fn>).mockImplementation(() => calls.push('release'));

    applyAvatarTags(driver, [
      { type: 'emotion', emotion: 'sad' },
      { type: 'release' },
      { type: 'emotion', emotion: 'happy' },
    ]);

    expect(calls).toEqual(['emotion', 'release', 'emotion']);
  });
});

describe('sleep 标签', () => {
  beforeEach(() => {
    vi.spyOn(console, 'log').mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('仅日志留痕，不触碰任何驱动方法', () => {
    const driver = createMockDriver();
    applyAvatarTags(driver, [{ type: 'sleep', duration_ms: 800 }]);

    expect(console.log).toHaveBeenCalledWith('[avatar] sleep tag:', 800, 'ms');
    expect(driver.setEmotion).not.toHaveBeenCalled();
    expect(driver.setBlendShapes).not.toHaveBeenCalled();
    expect(driver.setBoneRotations).not.toHaveBeenCalled();
    expect(driver.holdPose).not.toHaveBeenCalled();
    expect(driver.releasePose).not.toHaveBeenCalled();
    expect(driver.setWind).not.toHaveBeenCalled();
  });
});

describe('空标签列表', () => {
  it('不产生任何驱动调用', () => {
    const driver = createMockDriver();
    expect(() => applyAvatarTags(driver, [])).not.toThrow();
    expect(driver.setEmotion).not.toHaveBeenCalled();
  });
});
