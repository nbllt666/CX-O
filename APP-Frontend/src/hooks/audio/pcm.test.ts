import { describe, expect, it } from 'vitest';

import { computeRmsVolume, encodePcm16 } from './pcm';

describe('encodePcm16', () => {
  it('零输入产生零输出且长度一致', () => {
    const out = encodePcm16(new Float32Array([0, 0, 0]), 1);
    expect(out.length).toBe(3);
    expect(Array.from(out)).toEqual([0, 0, 0]);
  });

  it('满幅映射到 Int16 边界', () => {
    const out = encodePcm16(new Float32Array([1, -1]), 1);
    expect(out[0]).toBe(0x7fff);
    expect(out[1]).toBe(-0x8000);
  });

  it('增益在量化前应用', () => {
    const out = encodePcm16(new Float32Array([0.25]), 2);
    // Int16Array 赋值为向零截断（非四舍五入）
    expect(out[0]).toBe(Math.floor(0.5 * 0x7fff));
  });

  it('增益放大后钳制不回绕', () => {
    const out = encodePcm16(new Float32Array([0.9, -0.9]), 2);
    expect(out[0]).toBe(0x7fff);
    expect(out[1]).toBe(-0x8000);
  });

  it('零增益输出静音', () => {
    const out = encodePcm16(new Float32Array([0.8, -0.8]), 0);
    expect(Array.from(out)).toEqual([0, 0]);
  });

  it('非法增益按 1 处理', () => {
    const out = encodePcm16(new Float32Array([0.5]), Number.NaN);
    expect(out[0]).toBe(Math.floor(0.5 * 0x7fff));
  });
});

describe('computeRmsVolume', () => {
  it('空输入为 0', () => {
    expect(computeRmsVolume(new Float32Array(0), 1)).toBe(0);
  });

  it('静音为 0，满幅方波钳制到 1', () => {
    expect(computeRmsVolume(new Float32Array([0, 0]), 1)).toBe(0);
    expect(computeRmsVolume(new Float32Array([1, -1, 1]), 1)).toBe(1);
  });

  it('增益放大后仍钳制到 1', () => {
    expect(computeRmsVolume(new Float32Array([0.9, 0.9]), 2)).toBe(1);
  });
});
