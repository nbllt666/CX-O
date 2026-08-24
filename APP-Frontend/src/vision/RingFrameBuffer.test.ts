import { describe, expect, it } from 'vitest';

import { RingFrameBuffer } from './RingFrameBuffer';

/** 构造测试专用缓冲：Frame 用数字帧序号即可，便于断言顺序与内容 */
function makeBuffer(options?: { retentionMs?: number; maxFrames?: number }) {
  return new RingFrameBuffer<number>('camera', options);
}

describe('RingFrameBuffer 容量淘汰', () => {
  it('push 超过 maxFrames 后最旧帧被淘汰，latest(120) 返回最近 120 帧', () => {
    const buf = makeBuffer({ maxFrames: 120, retentionMs: 60_000 });
    // 连续压入 130 帧，均落在 60s 时间窗内（ts 递增 100ms），只触发容量淘汰
    for (let i = 0; i < 130; i++) {
      buf.push(i, i * 100);
    }
    // 130 条中淘汰最旧 10 条，仅剩最近 120 条
    const latest = buf.latest(120);
    expect(latest.length).toBe(120);
    expect(latest[0].frame).toBe(10);
    expect(latest[119].frame).toBe(129);
    // 最旧的帧 0~9 已被淘汰，不再出现在结果中
    expect(latest.some((f) => f.frame < 10)).toBe(false);
  });
});

describe('RingFrameBuffer 时间淘汰', () => {
  it('传入跨 >30s 的 ts 后，旧帧被时间窗淘汰', () => {
    const buf = makeBuffer({ retentionMs: 30_000, maxFrames: 1000 });
    buf.push(0, 0);
    buf.push(1, 10_000);
    buf.push(2, 20_000);
    // 距离最新帧 35s，帧 0 已超 30s 窗，被淘汰
    buf.push(3, 35_000);
    const latest = buf.latest(10);
    expect(latest.map((f) => f.frame)).toEqual([1, 2, 3]);
  });

  it('恰好位于窗口边界的帧保留，早于 cutoff 的淘汰', () => {
    const buf = makeBuffer({ retentionMs: 30_000, maxFrames: 1000 });
    buf.push(0, 0);
    buf.push(1, 5_000); // 距离最新 30s，恰好落边界，保留
    buf.push(2, 35_000);
    expect(buf.latest(10).map((f) => f.frame)).toEqual([1, 2]);
  });
});

describe('RingFrameBuffer slice 回溯边界', () => {
  it('取中间窗口只返回该窗口内的帧且按升序', () => {
    const buf = makeBuffer({ maxFrames: 1000 });
    for (let i = 0; i < 10; i++) {
      buf.push(i, i * 1_000);
    }
    // 闭区间 [3000, 6000]：应命中 ts 3~6 共 4 帧，升序
    const win = buf.slice(3_000, 6_000);
    expect(win.map((f) => f.frame)).toEqual([3, 4, 5, 6]);
  });

  it('闭区间边界端包含（相等即命中）', () => {
    const buf = makeBuffer();
    buf.push(1, 100);
    buf.push(2, 200);
    const win = buf.slice(100, 200);
    expect(win.map((f) => f.frame)).toEqual([1, 2]);
  });
});

describe('RingFrameBuffer 双源隔离', () => {
  it('screen 缓冲与 camera 缓冲互不影响', () => {
    const camera = new RingFrameBuffer<string>('camera');
    const screen = new RingFrameBuffer<string>('screen');
    // 两源独立写入
    camera.push('cam-1', 0);
    camera.push('cam-2', 1_000);
    screen.push('scr-1', 0);
    // camera 缓冲看不到 screen 的内容
    expect(camera.latest(10).map((f) => f.frame)).toEqual(['cam-1', 'cam-2']);
    expect(screen.latest(10).map((f) => f.frame)).toEqual(['scr-1']);
  });
});

describe('RingFrameBuffer 空缓冲', () => {
  it('空缓冲 slice/latest 返回空数组', () => {
    const buf = makeBuffer();
    expect(buf.slice(0, 1_000)).toEqual([]);
    expect(buf.latest(5)).toEqual([]);
    expect(buf.latest(0)).toEqual([]);
    expect(buf.latest(-1)).toEqual([]);
  });
});

describe('RingFrameBuffer 占位帧', () => {
  it('null 占位帧保持时间轴但不进入 slice/latest 结果', () => {
    const buf = makeBuffer();
    buf.push(1, 0);
    buf.push(null, 1_000); // 占位，无帧
    buf.push(2, 2_000);
    expect(buf.size).toBe(3); // 占位仍保留在时间轴上
    expect(buf.slice(0, 2_000).map((f) => f.frame)).toEqual([1, 2]);
    expect(buf.latest(10).map((f) => f.frame)).toEqual([1, 2]);
  });
});