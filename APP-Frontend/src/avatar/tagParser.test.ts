/**
 * tagParser 单测：头像驱动标签解析。
 *
 * 覆盖：七类标签的正常解析、数值钳制、非法标签回退为文本、
 * 混合文本的 segments/cleanText 结构、stripAvatarTags 与情绪清单。
 */
import { describe, it, expect } from 'vitest';

import {
  parseAvatarTags,
  stripAvatarTags,
  getSupportedEmotions,
  type AvatarTag,
  type WindTag,
} from './tagParser';

function onlyTag(text: string): AvatarTag {
  const result = parseAvatarTags(text);
  expect(result.tags).toHaveLength(1);
  return result.tags[0];
}

describe('emotion 标签', () => {
  it('解析受支持的情绪并小写归一', () => {
    expect(onlyTag('[emotion:Happy]')).toEqual({ type: 'emotion', emotion: 'happy' });
    expect(onlyTag('[emotion:sad]')).toEqual({ type: 'emotion', emotion: 'sad' });
  });

  it('不受支持的情绪回退为文本', () => {
    const result = parseAvatarTags('[emotion:rage]');
    expect(result.tags).toHaveLength(0);
    expect(result.cleanText).toBe('[emotion:rage]');
  });
});

describe('blend 标签', () => {
  it('缺省权重为 1.0', () => {
    expect(onlyTag('[blend:smile]')).toEqual({ type: 'blend', name: 'smile', weight: 1.0 });
  });

  it('权重钳制到 [0, 1]', () => {
    expect(onlyTag('[blend:smile:0.6]')).toEqual({ type: 'blend', name: 'smile', weight: 0.6 });
    expect(onlyTag('[blend:smile:2.5]')).toEqual({ type: 'blend', name: 'smile', weight: 1 });
    expect(onlyTag('[blend:smile:-1]')).toEqual({ type: 'blend', name: 'smile', weight: 0 });
  });

  it('权重非数字时回退为文本', () => {
    expect(parseAvatarTags('[blend:smile:abc]').tags).toHaveLength(0);
  });
});

describe('bone 标签', () => {
  it('解析骨骼旋转与缺省速度 1.0', () => {
    expect(onlyTag('[bone:head:0.1:-0.2:0.3]')).toEqual({
      type: 'bone',
      boneName: 'head',
      rotation: { x: 0.1, y: -0.2, z: 0.3 },
      speed: 1.0,
    });
  });

  it('旋转钳制到 [-PI, PI]，速度钳制到 [0.1, 5.0]', () => {
    const tag = onlyTag('[bone:head:99:-99:0:99]');
    expect(tag).toEqual({
      type: 'bone',
      boneName: 'head',
      rotation: { x: Math.PI, y: -Math.PI, z: 0 },
      speed: 5.0,
    });
  });

  it('参数不足或非数字时回退为文本', () => {
    expect(parseAvatarTags('[bone:head:0.1]').tags).toHaveLength(0);
    expect(parseAvatarTags('[bone:head:x:0:0]').tags).toHaveLength(0);
  });
});

describe('pose / release 标签', () => {
  it('pose 缺省 3000ms，可显式指定，钳制到 [0, 30000]', () => {
    expect(onlyTag('[pose]')).toEqual({ type: 'pose', durationMs: 3000 });
    expect(onlyTag('[pose:1500]')).toEqual({ type: 'pose', durationMs: 1500 });
    expect(onlyTag('[pose:99999]')).toEqual({ type: 'pose', durationMs: 30000 });
  });

  it('release 无参数', () => {
    expect(onlyTag('[release]')).toEqual({ type: 'release' });
  });
});

describe('wind 标签', () => {
  it('解析方向/强度与阵风缺省值', () => {
    expect(onlyTag('[wind:90:0.5]')).toEqual({
      type: 'wind',
      direction: 90,
      strength: 0.5,
      gustStrength: 0,
      gustFrequency: 0.1,
      gustDuration: 0,
    });
  });

  it('阵风时长支持数字与区间字符串两种形态', () => {
    expect((onlyTag('[wind:0:1:0.5:2:3]') as WindTag).gustDuration).toBe(3);
    expect((onlyTag('[wind:0:1:0.5:2:2-5]') as WindTag).gustDuration).toBe('2-5');
  });

  it('方向/强度/阵风钳制；非法阵风时长回退为文本', () => {
    const tag = onlyTag('[wind:720:9:9:9:1]');
    expect(tag).toMatchObject({ direction: 360, strength: 1, gustStrength: 1, gustFrequency: 5 });
    expect(parseAvatarTags('[wind:0:1:0.5:2:abc]').tags).toHaveLength(0);
    expect(parseAvatarTags('[wind:0]').tags).toHaveLength(0);
  });
});

describe('sleep 标签', () => {
  it('时长钳制到 [100, 5000]', () => {
    expect(onlyTag('[sleep:500]')).toEqual({ type: 'sleep', duration_ms: 500 });
    expect(onlyTag('[sleep:10]')).toEqual({ type: 'sleep', duration_ms: 100 });
    expect(onlyTag('[sleep:99999]')).toEqual({ type: 'sleep', duration_ms: 5000 });
  });
});

describe('action 标签', () => {
  it('解析动作名并小写归一，cleanText 剥离合法标签', () => {
    expect(onlyTag('[action:wave]')).toEqual({ type: 'action', action: 'wave' });
    expect(parseAvatarTags('[action:wave]').cleanText).toBe('');
  });

  it('动作名大小写归一为小写', () => {
    expect(onlyTag('[action:Wave]')).toEqual({ type: 'action', action: 'wave' });
  });

  it('空参数 [action:] 不解析，保留为文本', () => {
    const result = parseAvatarTags('[action:]');
    expect(result.tags).toHaveLength(0);
    expect(result.cleanText).toBe('[action:]');
  });
});

describe('混合文本解析', () => {
  it('segments 保序、cleanText 剥离合法标签、非法标签原文保留', () => {
    const result = parseAvatarTags('你好[emotion:happy]世界[unknown:x]！');
    expect(result.tags).toEqual([{ type: 'emotion', emotion: 'happy' }]);
    expect(result.cleanText).toBe('你好世界[unknown:x]！');
    // 非法标签独立成 text 段，不与前后文本合并
    expect(result.segments.map((s) => s.type)).toEqual(['text', 'tag', 'text', 'text', 'text']);
  });

  it('stripAvatarTags 等价于 cleanText', () => {
    const text = '前[blend:a:0.5]中[sleep:200]后';
    expect(stripAvatarTags(text)).toBe(parseAvatarTags(text).cleanText);
    expect(stripAvatarTags(text)).toBe('前中后');
  });

  it('纯文本无标签时 segments 仅一个 text 段', () => {
    const result = parseAvatarTags('没有标签的句子');
    expect(result.tags).toHaveLength(0);
    expect(result.segments).toEqual([{ type: 'text', content: '没有标签的句子' }]);
  });
});

describe('getSupportedEmotions', () => {
  it('返回排序后的情绪清单且包含核心情绪', () => {
    const emotions = getSupportedEmotions();
    const sorted = [...emotions].sort();
    expect(emotions).toEqual(sorted);
    for (const core of ['happy', 'sad', 'angry', 'surprised', 'neutral']) {
      expect(emotions).toContain(core);
    }
  });
});
