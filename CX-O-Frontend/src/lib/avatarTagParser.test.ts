import { describe, it, expect } from 'vitest';
import {
  parseAvatarTags,
  stripAvatarTags,
  type AvatarTag,
} from './avatarTagParser';

describe('avatarTagParser', () => {
  describe('parseAvatarTags - 纯文本', () => {
    it('无 tag 时返回整段文本为单一 text segment', () => {
      const result = parseAvatarTags('Hello world');
      expect(result.segments).toHaveLength(1);
      expect(result.segments[0]).toEqual({ type: 'text', content: 'Hello world' });
      expect(result.tags).toEqual([]);
      expect(result.cleanText).toBe('Hello world');
    });

    it('空字符串返回空 segments/tags/cleanText', () => {
      const result = parseAvatarTags('');
      expect(result.segments).toEqual([]);
      expect(result.tags).toEqual([]);
      expect(result.cleanText).toBe('');
    });
  });

  describe('parseAvatarTags - emotion tag', () => {
    it('解析 [emotion:name] 形式', () => {
      const result = parseAvatarTags('[emotion:happy]');
      expect(result.segments).toHaveLength(1);
      expect(result.segments[0]).toEqual({
        type: 'tag',
        tag: { type: 'emotion', emotion: 'happy' },
        raw: '[emotion:happy]',
      });
      expect(result.tags).toEqual([{ type: 'emotion', emotion: 'happy' }]);
      expect(result.cleanText).toBe('');
    });

    it('解析文本与 emotion tag 混合', () => {
      const result = parseAvatarTags('你好 [emotion:happy] 世界');
      expect(result.segments).toHaveLength(3);
      expect(result.segments[0]).toEqual({ type: 'text', content: '你好 ' });
      expect(result.segments[1]).toEqual({
        type: 'tag',
        tag: { type: 'emotion', emotion: 'happy' },
        raw: '[emotion:happy]',
      });
      expect(result.segments[2]).toEqual({ type: 'text', content: ' 世界' });
      expect(result.cleanText).toBe('你好  世界');
    });

    it('emotion 缺参数返回 null（原文当文本保留）', () => {
      const result = parseAvatarTags('[emotion]');
      expect(result.segments).toHaveLength(1);
      expect(result.segments[0]).toEqual({ type: 'text', content: '[emotion]' });
      expect(result.tags).toEqual([]);
    });

    it('emotion 不在 SUPPORTED_EMOTIONS 中返回 null（原文当文本保留）', () => {
      const result = parseAvatarTags('[emotion:invalid_emotion]');
      expect(result.segments).toHaveLength(1);
      expect(result.segments[0]).toEqual({ type: 'text', content: '[emotion:invalid_emotion]' });
      expect(result.tags).toEqual([]);
    });

    it('emotion 大小写不敏感（Happy → happy）', () => {
      const result = parseAvatarTags('[emotion:Happy]');
      expect(result.tags).toEqual([{ type: 'emotion', emotion: 'happy' }]);
    });
  });

  describe('parseAvatarTags - blend tag', () => {
    it('解析 [blend:name:weight] 形式', () => {
      const result = parseAvatarTags('[blend:smile:0.5]');
      expect(result.tags).toEqual([{ type: 'blend', name: 'smile', weight: 0.5 }]);
    });

    it('blend 缺 weight 默认 1.0', () => {
      const result = parseAvatarTags('[blend:smile]');
      expect(result.tags).toEqual([{ type: 'blend', name: 'smile', weight: 1.0 }]);
    });

    it('blend weight 超过 1 被 clamp 到 1', () => {
      const result = parseAvatarTags('[blend:smile:2.5]');
      expect(result.tags[0]).toEqual({ type: 'blend', name: 'smile', weight: 1 });
    });

    it('blend weight 小于 0 被 clamp 到 0', () => {
      const result = parseAvatarTags('[blend:smile:-0.5]');
      expect(result.tags[0]).toEqual({ type: 'blend', name: 'smile', weight: 0 });
    });

    it('blend weight 非数字返回 null', () => {
      const result = parseAvatarTags('[blend:smile:abc]');
      expect(result.tags).toEqual([]);
      expect(result.segments[0]).toEqual({ type: 'text', content: '[blend:smile:abc]' });
    });
  });

  describe('parseAvatarTags - bone tag', () => {
    it('解析 [bone:name:rx:ry:rz] 形式', () => {
      const result = parseAvatarTags('[bone:head:0.1:0.2:0.3]');
      expect(result.tags[0]).toEqual({
        type: 'bone',
        boneName: 'head',
        rotation: { x: 0.1, y: 0.2, z: 0.3 },
        speed: 1.0,
      });
    });

    it('bone 含 speed 参数', () => {
      const result = parseAvatarTags('[bone:head:0.1:0.2:0.3:2.0]');
      expect(result.tags[0]).toMatchObject({
        type: 'bone',
        boneName: 'head',
        speed: 2.0,
      });
    });

    it('bone 参数不足返回 null', () => {
      const result = parseAvatarTags('[bone:head:0.1:0.2]');
      expect(result.tags).toEqual([]);
    });

    it('bone rotation 被 clamp 到 [-PI, PI]', () => {
      const result = parseAvatarTags('[bone:head:10:20:30]');
      const tag = result.tags[0] as Extract<AvatarTag, { type: 'bone' }>;
      expect(tag.rotation.x).toBeCloseTo(Math.PI, 5);
      expect(tag.rotation.y).toBeCloseTo(Math.PI, 5);
      expect(tag.rotation.z).toBeCloseTo(Math.PI, 5);
    });

    it('bone speed 被 clamp 到 [0.1, 5.0]', () => {
      const tooFast = parseAvatarTags('[bone:head:0:0:0:99]');
      expect((tooFast.tags[0] as Extract<AvatarTag, { type: 'bone' }>).speed).toBe(5.0);

      const tooSlow = parseAvatarTags('[bone:head:0:0:0:0.01]');
      expect((tooSlow.tags[0] as Extract<AvatarTag, { type: 'bone' }>).speed).toBe(0.1);
    });
  });

  describe('parseAvatarTags - pose tag', () => {
    it('解析 [pose:durationMs] 形式', () => {
      const result = parseAvatarTags('[pose:1500]');
      expect(result.tags).toEqual([{ type: 'pose', durationMs: 1500 }]);
    });

    it('pose 无参数默认 3000ms', () => {
      const result = parseAvatarTags('[pose]');
      expect(result.tags).toEqual([{ type: 'pose', durationMs: 3000 }]);
    });

    it('pose 被 clamp 到 [0, 30000]', () => {
      const tooLong = parseAvatarTags('[pose:99999]');
      expect(tooLong.tags[0]).toEqual({ type: 'pose', durationMs: 30000 });

      const negative = parseAvatarTags('[pose:-100]');
      expect(negative.tags[0]).toEqual({ type: 'pose', durationMs: 0 });
    });
  });

  describe('parseAvatarTags - release tag', () => {
    it('解析 [release] 形式（无参数）', () => {
      const result = parseAvatarTags('[release]');
      expect(result.tags).toEqual([{ type: 'release' }]);
    });

    it('release 忽略附加参数', () => {
      const result = parseAvatarTags('[release:extra]');
      expect(result.tags).toEqual([{ type: 'release' }]);
    });
  });

  describe('parseAvatarTags - wind tag', () => {
    it('解析 [wind:direction:strength] 形式（gustFrequency 默认 0 被 clamp 到 0.1）', () => {
      const result = parseAvatarTags('[wind:90:0.5]');
      expect(result.tags[0]).toEqual({
        type: 'wind',
        direction: 90,
        strength: 0.5,
        gustStrength: 0,
        gustFrequency: 0.1,
        gustDuration: 0,
      });
    });

    it('wind 含 gust 参数', () => {
      const result = parseAvatarTags('[wind:0:0.5:0.3:1.5:200]');
      expect(result.tags[0]).toEqual({
        type: 'wind',
        direction: 0,
        strength: 0.5,
        gustStrength: 0.3,
        gustFrequency: 1.5,
        gustDuration: 200,
      });
    });

    it('wind gustDuration 支持范围字符串（如 100-300）', () => {
      const result = parseAvatarTags('[wind:0:0.5:0.3:1.5:100-300]');
      const tag = result.tags[0] as Extract<AvatarTag, { type: 'wind' }>;
      expect(tag.gustDuration).toBe('100-300');
    });

    it('wind 参数不足返回 null', () => {
      const result = parseAvatarTags('[wind:90]');
      expect(result.tags).toEqual([]);
    });

    it('wind direction 被 clamp 到 [0, 360]', () => {
      const result = parseAvatarTags('[wind:999:0.5]');
      const tag = result.tags[0] as Extract<AvatarTag, { type: 'wind' }>;
      expect(tag.direction).toBe(360);
    });

    it('wind strength 被 clamp 到 [0, 1]', () => {
      const result = parseAvatarTags('[wind:0:5]');
      const tag = result.tags[0] as Extract<AvatarTag, { type: 'wind' }>;
      expect(tag.strength).toBe(1);
    });
  });

  describe('parseAvatarTags - sleep tag', () => {
    it('解析 [sleep:ms] 形式', () => {
      const result = parseAvatarTags('[sleep:500]');
      expect(result.tags).toEqual([{ type: 'sleep', duration_ms: 500 }]);
    });

    it('sleep duration_ms 被 clamp 到 [100, 5000]', () => {
      const tooShort = parseAvatarTags('[sleep:50]');
      expect(tooShort.tags[0]).toEqual({ type: 'sleep', duration_ms: 100 });

      const tooLong = parseAvatarTags('[sleep:99999]');
      expect(tooLong.tags[0]).toEqual({ type: 'sleep', duration_ms: 5000 });
    });

    it('sleep 缺参数返回 null', () => {
      const result = parseAvatarTags('[sleep]');
      expect(result.tags).toEqual([]);
    });
  });

  describe('parseAvatarTags - 无效 tag 与未知类型', () => {
    it('未知 tag 类型原文当文本保留', () => {
      const result = parseAvatarTags('[unknown:foo]');
      expect(result.segments).toEqual([{ type: 'text', content: '[unknown:foo]' }]);
      expect(result.tags).toEqual([]);
    });

    it('多个无效与有效 tag 混合', () => {
      const result = parseAvatarTags('a[emotion:happy]b[invalid:y]c');
      expect(result.segments).toHaveLength(5);
      expect(result.segments[0]).toEqual({ type: 'text', content: 'a' });
      expect(result.segments[1].type).toBe('tag');
      expect(result.segments[2]).toEqual({ type: 'text', content: 'b' });
      expect(result.segments[3]).toEqual({ type: 'text', content: '[invalid:y]' });
      expect(result.segments[4]).toEqual({ type: 'text', content: 'c' });
      expect(result.tags).toHaveLength(1);
    });
  });

  describe('parseAvatarTags - 多 tag 场景', () => {
    it('连续两个 emotion tag 中间无文本', () => {
      const result = parseAvatarTags('[emotion:happy][emotion:sad]');
      expect(result.segments).toHaveLength(2);
      expect(result.tags).toHaveLength(2);
      expect(result.cleanText).toBe('');
    });

    it('混合多种 tag 类型', () => {
      const result = parseAvatarTags('hi [emotion:happy] then [pose:1000] done');
      expect(result.tags).toEqual([
        { type: 'emotion', emotion: 'happy' },
        { type: 'pose', durationMs: 1000 },
      ]);
      expect(result.cleanText).toBe('hi  then  done');
    });
  });

  describe('stripAvatarTags', () => {
    it('移除所有 tag，仅保留文本', () => {
      expect(stripAvatarTags('hello [emotion:happy] world')).toBe('hello  world');
    });

    it('无 tag 时原样返回', () => {
      expect(stripAvatarTags('plain text')).toBe('plain text');
    });

    it('全部为 tag 时返回空字符串', () => {
      expect(stripAvatarTags('[emotion:happy][pose:100]')).toBe('');
    });

    it('无效 tag 原文保留为文本', () => {
      expect(stripAvatarTags('[invalid:x]text')).toBe('[invalid:x]text');
    });
  });
});
