/**
 * SubTask 2.5 键盘控制适配器（computer_keyboard_control）。
 *
 * 支持 type / key / press / hotkey 动作。敏感输入（type 文本、组合键内容）绝不写入
 * 日志，仅在授权且参数合法时经注入的 KeyboardDriver 发送按键。单测注入 mock 替身。
 */
import { errorResult, messageOf, okResult, type ToolResult } from './errors';

export interface KeyboardDriver {
  type(text: string): Promise<void>;
  press(code: string): Promise<void>;
  hotkey(modifiers: string[], key: string): Promise<void>;
}

export type ToolHandler = (params: Record<string, unknown>) => Promise<ToolResult>;

const KNOWN_MODIFIERS = new Set(['ctrl', 'shift', 'alt', 'meta']);

export function createKeyboardTool(driver: KeyboardDriver): ToolHandler {
  return async (params: Record<string, unknown>): Promise<ToolResult> => {
    const action = params.action;
    if (typeof action !== 'string') {
      return errorResult('INVALID_ARGUMENT', '缺少 action');
    }
    switch (action) {
      case 'type': {
        if (typeof params.text !== 'string') {
          return errorResult('INVALID_ARGUMENT', 'type 需要字符串 text');
        }
        try {
          await driver.type(params.text);
          return okResult({ typed: true });
        } catch (err) {
          return errorResult('EXECUTION_FAILED', `输入失败: ${messageOf(err)}`);
        }
      }
      case 'key':
      case 'press': {
        if (typeof params.key !== 'string') {
          return errorResult('INVALID_ARGUMENT', `${action} 需要字符串 key`);
        }
        try {
          await driver.press(params.key);
          return okResult({ pressed: true, key: params.key });
        } catch (err) {
          return errorResult('EXECUTION_FAILED', `按键失败: ${messageOf(err)}`);
        }
      }
      case 'hotkey': {
        if (typeof params.key !== 'string') {
          return errorResult('INVALID_ARGUMENT', 'hotkey 需要字符串 key');
        }
        const modifiers = params.modifiers;
        if (
          !Array.isArray(modifiers) ||
          modifiers.length === 0 ||
          modifiers.some((m) => typeof m !== 'string' || !KNOWN_MODIFIERS.has(m))
        ) {
          return errorResult('INVALID_ARGUMENT', 'hotkey 需要合法 modifiers 数组');
        }
        try {
          await driver.hotkey(modifiers as string[], params.key);
          return okResult({ pressed: true, modifiers, key: params.key });
        } catch (err) {
          return errorResult('EXECUTION_FAILED', `组合键失败: ${messageOf(err)}`);
        }
      }
      default:
        return errorResult('INVALID_ARGUMENT', `未知动作: ${action}`);
    }
  };
}
