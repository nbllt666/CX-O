// @vitest-environment node
/**
 * SubTask 2.5 键盘控制适配器单测（注入 mock 驱动）。
 * 额外断言：敏感输入（type 文本 / 组合键）绝不写入 console / 日志。
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { createKeyboardTool, type KeyboardDriver } from './keyboard';

function makeDriver(overrides: Partial<KeyboardDriver> = {}): KeyboardDriver {
  return {
    type: vi.fn(async () => undefined),
    press: vi.fn(async () => undefined),
    hotkey: vi.fn(async () => undefined),
    ...overrides,
  };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe('computer_keyboard_control', () => {
  it('type 成功且不写日志', async () => {
    const logSpy = vi.spyOn(console, 'log').mockImplementation(() => undefined);
    const driver = makeDriver();
    const res = await createKeyboardTool(driver)({ action: 'type', text: 'SECRET-PASSWORD-123' });
    expect(res.ok).toBe(true);
    expect(driver.type).toHaveBeenCalledWith('SECRET-PASSWORD-123');
    // 敏感输入不得出现在任何日志中
    expect(logSpy).not.toHaveBeenCalled();
    expect(JSON.stringify(logSpy.mock.calls)).not.toContain('SECRET-PASSWORD-123');
  });

  it('key / press 成功', async () => {
    const driver = makeDriver();
    const t = createKeyboardTool(driver);
    expect((await t({ action: 'key', key: 'enter' })).ok).toBe(true);
    expect((await t({ action: 'press', key: 'f5' })).ok).toBe(true);
    expect(driver.press).toHaveBeenCalledTimes(2);
  });

  it('hotkey 成功', async () => {
    const driver = makeDriver();
    const res = await createKeyboardTool(driver)({ action: 'hotkey', modifiers: ['ctrl', 'shift'], key: 'p' });
    expect(res.ok).toBe(true);
    expect(driver.hotkey).toHaveBeenCalledWith(['ctrl', 'shift'], 'p');
  });

  it('type 缺 text → INVALID_ARGUMENT 且不触碰驱动', async () => {
    const driver = makeDriver();
    const res = await createKeyboardTool(driver)({ action: 'type' });
    expect(res.code).toBe('INVALID_ARGUMENT');
    expect(driver.type).not.toHaveBeenCalled();
  });

  it('key 缺 key → INVALID_ARGUMENT', async () => {
    const res = await createKeyboardTool(makeDriver())({ action: 'key' });
    expect(res.code).toBe('INVALID_ARGUMENT');
  });

  it('hotkey 非法 modifiers → INVALID_ARGUMENT', async () => {
    const driver = makeDriver();
    const res = await createKeyboardTool(driver)({ action: 'hotkey', modifiers: ['ctrl', 'hack'], key: 'p' });
    expect(res.code).toBe('INVALID_ARGUMENT');
    expect(driver.hotkey).not.toHaveBeenCalled();
  });

  it('驱动失败 → EXECUTION_FAILED', async () => {
    const driver = makeDriver({ press: vi.fn(async () => { throw new Error('denied'); }) });
    const res = await createKeyboardTool(driver)({ action: 'press', key: 'a' });
    expect(res.code).toBe('EXECUTION_FAILED');
  });
});
