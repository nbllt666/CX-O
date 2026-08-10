import { describe, it, expect } from 'vitest';
import {
  pointInEllipse,
  pointInRect,
  shouldIgnoreMouse,
  DEFAULT_HIT_ELLIPSE,
  type ClientRect,
} from './hitGeometry';

const canvas: ClientRect = { x: 0, y: 0, width: 400, height: 300 };

describe('pointInEllipse', () => {
  it('椭圆中心命中', () => {
    expect(pointInEllipse(200, 135, canvas, DEFAULT_HIT_ELLIPSE)).toBe(true);
  });

  it('椭圆内靠近边缘命中', () => {
    // 归一化 (0.7, 0.45)：dx=(0.7-0.5)/0.3≈0.667，dy=0 → 0.444<1
    expect(pointInEllipse(280, 135, canvas, DEFAULT_HIT_ELLIPSE)).toBe(true);
  });

  it('椭圆外不命中', () => {
    // 画布左上角附近
    expect(pointInEllipse(10, 10, canvas, DEFAULT_HIT_ELLIPSE)).toBe(false);
  });

  it('画布外不命中', () => {
    expect(pointInEllipse(-5, 135, canvas, DEFAULT_HIT_ELLIPSE)).toBe(false);
    expect(pointInEllipse(200, 301, canvas, DEFAULT_HIT_ELLIPSE)).toBe(false);
  });

  it('退化画布（宽高为 0）不命中', () => {
    const empty: ClientRect = { x: 0, y: 0, width: 0, height: 0 };
    expect(pointInEllipse(0, 0, empty, DEFAULT_HIT_ELLIPSE)).toBe(false);
  });

  it('带偏移量的画布按客户端坐标换算', () => {
    const shifted: ClientRect = { x: 100, y: 50, width: 400, height: 300 };
    // 画布局部 (200,135) = 客户端 (300,185)：恰为椭圆中心 → 命中
    expect(pointInEllipse(300, 185, shifted, DEFAULT_HIT_ELLIPSE)).toBe(true);
    // 客户端 (150,100) = 画布局部 (50,50)：归一化 (0.125,0.167)，
    // dx=(0.125-0.5)/0.3=-1.25，dx²>1 → 椭圆外不命中
    expect(pointInEllipse(150, 100, shifted, DEFAULT_HIT_ELLIPSE)).toBe(false);
  });
});

describe('pointInRect', () => {
  const rect: ClientRect = { x: 10, y: 20, width: 100, height: 50 };

  it('矩形内命中（含边界）', () => {
    expect(pointInRect(10, 20, rect)).toBe(true);
    expect(pointInRect(110, 70, rect)).toBe(true);
    expect(pointInRect(60, 45, rect)).toBe(true);
  });

  it('矩形外不命中', () => {
    expect(pointInRect(9, 45, rect)).toBe(false);
    expect(pointInRect(60, 71, rect)).toBe(false);
  });

  it('零尺寸矩形不命中', () => {
    expect(pointInRect(10, 20, { x: 10, y: 20, width: 0, height: 0 })).toBe(false);
  });
});

describe('shouldIgnoreMouse', () => {
  const chatRect: ClientRect = { x: 0, y: 400, width: 400, height: 100 };

  it('命中头像椭圆 → 不穿透', () => {
    expect(shouldIgnoreMouse(200, 135, canvas, DEFAULT_HIT_ELLIPSE, [])).toBe(false);
  });

  it('命中附加交互矩形 → 不穿透', () => {
    expect(shouldIgnoreMouse(200, 450, canvas, DEFAULT_HIT_ELLIPSE, [chatRect])).toBe(false);
  });

  it('椭圆与矩形之外 → 穿透', () => {
    expect(shouldIgnoreMouse(5, 350, canvas, DEFAULT_HIT_ELLIPSE, [chatRect])).toBe(true);
  });

  it('无画布时仅按附加矩形判定', () => {
    expect(shouldIgnoreMouse(200, 135, null, DEFAULT_HIT_ELLIPSE, [])).toBe(true);
    expect(shouldIgnoreMouse(200, 450, null, DEFAULT_HIT_ELLIPSE, [chatRect])).toBe(false);
  });

  it('多个附加矩形任一命中即不穿透', () => {
    const menu: ClientRect = { x: 300, y: 100, width: 120, height: 200 };
    expect(shouldIgnoreMouse(350, 200, canvas, DEFAULT_HIT_ELLIPSE, [chatRect, menu])).toBe(false);
  });
});
