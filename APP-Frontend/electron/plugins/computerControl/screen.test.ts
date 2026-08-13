// @vitest-environment node
/**
 * SubTask 2.4 屏幕控制适配器单测（注入 mock 驱动，避免真实截屏/点击产生 OS 副作用）。
 */
import { describe, it, expect, vi } from 'vitest';
import { createScreenTool, type ScreenDriver } from './screen';

function makeDriver(overrides: Partial<ScreenDriver> = {}): ScreenDriver {
  return {
    capture: vi.fn(async () => ({ mimeType: 'image/png', dataUrl: 'data:image/png;base64,x', width: 1920, height: 1080 })),
    move: vi.fn(async () => undefined),
    click: vi.fn(async () => undefined),
    scroll: vi.fn(async () => undefined),
    ...overrides,
  };
}

describe('computer_screen_control', () => {
  it('capture 返回结构化结果', async () => {
    const driver = makeDriver();
    const tool = createScreenTool(driver);
    const res = await tool({ action: 'capture' });
    expect(res.ok).toBe(true);
    expect(res.output).toMatchObject({ mime_type: 'image/png', width: 1920, height: 1080 });
    expect(driver.capture).toHaveBeenCalledTimes(1);
  });

  it('move 成功', async () => {
    const driver = makeDriver();
    const res = await createScreenTool(driver)({ action: 'move', x: 100, y: 200 });
    expect(res.ok).toBe(true);
    expect(driver.move).toHaveBeenCalledWith(100, 200);
  });

  it('click 成功并透传按钮', async () => {
    const driver = makeDriver();
    const res = await createScreenTool(driver)({ action: 'click', x: 5, y: 6, button: 'right' });
    expect(res.ok).toBe(true);
    expect(driver.click).toHaveBeenCalledWith(5, 6, 'right');
  });

  it('scroll 成功', async () => {
    const driver = makeDriver();
    const res = await createScreenTool(driver)({ action: 'scroll', delta: -3 });
    expect(res.ok).toBe(true);
    expect(driver.scroll).toHaveBeenCalledWith(-3, undefined, undefined);
  });

  it('缺 action → INVALID_ARGUMENT', async () => {
    const driver = makeDriver();
    const res = await createScreenTool(driver)({});
    expect(res.code).toBe('INVALID_ARGUMENT');
    expect(driver.capture).not.toHaveBeenCalled();
  });

  it('move 缺数字坐标 → INVALID_ARGUMENT 且不触碰驱动', async () => {
    const driver = makeDriver();
    const res = await createScreenTool(driver)({ action: 'move', x: 'a', y: 1 });
    expect(res.code).toBe('INVALID_ARGUMENT');
    expect(driver.move).not.toHaveBeenCalled();
  });

  it('未知动作 → INVALID_ARGUMENT', async () => {
    const res = await createScreenTool(makeDriver())({ action: 'explode' });
    expect(res.code).toBe('INVALID_ARGUMENT');
  });

  it('驱动失败 → EXECUTION_FAILED', async () => {
    const driver = makeDriver({ capture: vi.fn(async () => { throw new Error('no source'); }) });
    const res = await createScreenTool(driver)({ action: 'capture' });
    expect(res.ok).toBe(false);
    expect(res.code).toBe('EXECUTION_FAILED');
  });
});
