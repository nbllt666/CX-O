import { describe, expect, it } from 'vitest';

import { VisionEventDetector } from './VisionEventDetector';

/** 事件冷却用的间隔，超过 15s 冷却期以避免命中冷却闸 */
const COOLDOWN_MS = 15_000;

describe('VisionEventDetector 静止', () => {
  it('相邻帧差异小于 diffThreshold 返回 null（画面静止）', () => {
    const det = new VisionEventDetector();
    const same = [0, 0, 0];
    expect(det.feed(same, [0, 0, 0], 0, 'screen')).toBeNull();
    // 极微小差异但仍低于阈值（L2 归一化 0.0408 < 0.08）
    expect(det.feed([0, 0, 0], [0.07, 0, 0], 0, 'screen')).toBeNull();
  });
});

describe('VisionEventDetector 突变', () => {
  it('差异达到 abruptThreshold 触发 scene_change 事件', () => {
    const det = new VisionEventDetector();
    const ev = det.feed([0, 0, 0], [1, 1, 1], 0, 'screen');
    expect(ev).not.toBeNull();
    expect(ev?.type).toBe('scene_change');
    expect(ev?.ts).toBe(0);
    expect(ev?.source).toBe('screen');
    expect(ev?.magnitude).toBeGreaterThan(0.35);
    expect(ev?.lowPriority).toBeUndefined();
  });

  it('突变事件携带 camera 源信息', () => {
    const det = new VisionEventDetector();
    const ev = det.feed([0, 0, 0], [1, 1, 1], 100, 'camera');
    expect(ev?.type).toBe('scene_change');
    expect(ev?.source).toBe('camera');
  });
});

describe('VisionEventDetector 冷却', () => {
  it('同类事件在冷却期内不重复触发', () => {
    const det = new VisionEventDetector();
    expect(det.feed([0, 0, 0], [1, 1, 1], 0, 'screen')).not.toBeNull();
    // 冷却期内（<15s）再次突变 → 被冷却拦截
    expect(det.feed([1, 1, 1], [0, 0, 0], 5_000, 'screen')).toBeNull();
    // 超过冷却期后可再次触发
    expect(det.feed([0, 0, 0], [1, 1, 1], 0 + COOLDOWN_MS + 1, 'screen')).not.toBeNull();
  });

  it('不同事件类型冷却互相独立', () => {
    const det = new VisionEventDetector();
    // scene_change 冷却期内，user_action（不同类）仍可触发
    det.feed([0, 0, 0], [1, 1, 1], 0, 'screen'); // scene_change @0
    const medium = det.feed([0, 0, 0], [0.5, 0, 0], 5_000, 'screen'); // user_action @5000
    expect(medium?.type).toBe('user_action');
  });
});

describe('VisionEventDetector 每小时上限', () => {
  it('超过 maxClipsPerHour 后 canTrigger=false 且触发受阻', () => {
    const det = new VisionEventDetector({ maxClipsPerHour: 2 });
    const seq: Array<[number[], number[]]> = [
      [[0, 0, 0], [1, 1, 1]],
      [[0, 0, 0], [1, 1, 1]],
      [[0, 0, 0], [1, 1, 1]],
    ];
    // 每次推进 16s，避开同类冷却，共三次突变
    const evs = seq.map(([a, b], i) => det.feed(a, b, i * (COOLDOWN_MS + 1), 'screen'));
    expect(evs[0]).not.toBeNull();
    expect(evs[1]).not.toBeNull();
    // 第 3 次超过每小时上限（2）→ 拒绝触发
    expect(evs[2]).toBeNull();
    expect(det.getHourlyCount(2 * (COOLDOWN_MS + 1))).toBe(2);
    expect(det.canTrigger(2 * (COOLDOWN_MS + 1))).toBe(false);
  });

  it('滑窗滚动后旧触发不再占用预算', () => {
    const det = new VisionEventDetector({ maxClipsPerHour: 1 });
    det.feed([0, 0, 0], [1, 1, 1], 0, 'screen'); // 第 1 次 @0
    // 同滑窗内受阻（冷却已避开）
    expect(det.feed([0, 0, 0], [1, 1, 1], 5_000, 'screen')).toBeNull();
    // 一小时后旧触发滑出窗口，预算释放
    expect(det.feed([0, 0, 0], [1, 1, 1], HOUR_MS + 1, 'screen')).not.toBeNull();
  });
});

describe('VisionEventDetector 微变化 / 中变化', () => {
  it('微变化被忽略（返回 null 但不推进静止态）', () => {
    const det = new VisionEventDetector();
    // L2 归一化 0.1155：∈ [0.08, 0.16) → 微变化 → null
    expect(det.feed([0, 0, 0], [0.2, 0, 0], 0, 'screen')).toBeNull();
  });

  it('中变化产生低频 user_action（lowPriority）', () => {
    const det = new VisionEventDetector();
    // L2 归一化 0.2887：∈ [0.16, 0.35) → 中变化 → user_action
    const ev = det.feed([0, 0, 0], [0.5, 0, 0], 0, 'screen');
    expect(ev?.type).toBe('user_action');
    expect(ev?.lowPriority).toBe(true);
  });

  it('reset 清除冷却状态后可再次触发', () => {
    const det = new VisionEventDetector();
    det.feed([0, 0, 0], [1, 1, 1], 0, 'screen');
    expect(det.feed([1, 1, 1], [0, 0, 0], 1_000, 'screen')).toBeNull(); // 冷却中
    det.reset();
    expect(det.feed([0, 0, 0], [1, 1, 1], 1_000, 'screen')).not.toBeNull();
  });
});

describe('VisionEventDetector feedPresence', () => {
  it('active=false 产生 user_left，再 true 产生 user_returned', () => {
    const det = new VisionEventDetector();
    const left = det.feedPresence(false, 0, 'screen');
    expect(left?.type).toBe('user_left');
    expect(left?.source).toBe('screen');

    const returned = det.feedPresence(true, COOLDOWN_MS + 1, 'screen');
    expect(returned?.type).toBe('user_returned');
  });

  it('状态未翻转的重复调用不重复触发', () => {
    const det = new VisionEventDetector();
    expect(det.feedPresence(false, 0, 'screen')).not.toBeNull();
    // 仍为 false，无状态变化 → null
    expect(det.feedPresence(false, 5_000, 'screen')).toBeNull();
    expect(det.getHourlyCount(5_000)).toBe(0); // presence 不消耗打包预算
  });
});

const HOUR_MS = 3_600_000;