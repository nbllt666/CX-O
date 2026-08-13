/**
 * SubTask 2.4 屏幕控制适配器（computer_screen_control）。
 *
 * 支持 capture / click / move / scroll 动作，返回结构化成功结果或稳定错误码。
 * 真实系统输入经注入的 ScreenDriver 执行；单测注入 mock 替身，避免真实截屏/点击
 * 产生 OS 副作用。屏幕采集内容仅作为工具结果返回，不写入任何日志。
 */
import { errorResult, messageOf, okResult, type ToolResult } from './errors';

export interface CaptureResult {
  mimeType: string;
  dataUrl: string;
  width: number;
  height: number;
}

export interface ScreenDriver {
  capture(): Promise<CaptureResult>;
  move(x: number, y: number): Promise<void>;
  click(x: number, y: number, button?: 'left' | 'right' | 'middle'): Promise<void>;
  scroll(delta: number, x?: number, y?: number): Promise<void>;
}

export type ToolHandler = (params: Record<string, unknown>) => Promise<ToolResult>;

function toFiniteNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

export function createScreenTool(driver: ScreenDriver): ToolHandler {
  return async (params: Record<string, unknown>): Promise<ToolResult> => {
    const action = params.action;
    if (typeof action !== 'string') {
      return errorResult('INVALID_ARGUMENT', '缺少 action');
    }
    switch (action) {
      case 'capture': {
        try {
          const cap = await driver.capture();
          return okResult({
            mime_type: cap.mimeType,
            width: cap.width,
            height: cap.height,
            image: cap.dataUrl,
          });
        } catch (err) {
          return errorResult('EXECUTION_FAILED', `截屏失败: ${messageOf(err)}`);
        }
      }
      case 'move': {
        const x = toFiniteNumber(params.x);
        const y = toFiniteNumber(params.y);
        if (x === null || y === null) {
          return errorResult('INVALID_ARGUMENT', 'move 需要数字 x/y');
        }
        try {
          await driver.move(x, y);
          return okResult({ moved: true, x, y });
        } catch (err) {
          return errorResult('EXECUTION_FAILED', `移动失败: ${messageOf(err)}`);
        }
      }
      case 'click': {
        const x = toFiniteNumber(params.x);
        const y = toFiniteNumber(params.y);
        if (x === null || y === null) {
          return errorResult('INVALID_ARGUMENT', 'click 需要数字 x/y');
        }
        const button =
          params.button === 'right' || params.button === 'middle' ? params.button : 'left';
        try {
          await driver.click(x, y, button);
          return okResult({ clicked: true, x, y, button });
        } catch (err) {
          return errorResult('EXECUTION_FAILED', `点击失败: ${messageOf(err)}`);
        }
      }
      case 'scroll': {
        const delta = toFiniteNumber(params.delta);
        if (delta === null) {
          return errorResult('INVALID_ARGUMENT', 'scroll 需要数字 delta');
        }
        const x = toFiniteNumber(params.x) ?? undefined;
        const y = toFiniteNumber(params.y) ?? undefined;
        try {
          await driver.scroll(delta, x, y);
          return okResult({ scrolled: true, delta, x, y });
        } catch (err) {
          return errorResult('EXECUTION_FAILED', `滚动失败: ${messageOf(err)}`);
        }
      }
      default:
        return errorResult('INVALID_ARGUMENT', `未知动作: ${action}`);
    }
  };
}
