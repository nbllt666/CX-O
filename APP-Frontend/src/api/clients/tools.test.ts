/**
 * toolsApi.testTool 请求体契约测试（D1）。
 *
 * 后端 ToolTestRequest 契约要求 { arguments: {...} }（tools.py:217-220，
 * arguments: Dict = {}）。修复前裸传 params，用户在测试弹窗填写的参数被
 * 后端忽略、恒以空参执行。本测试锁定包裹形状，防止回归。
 */
import { describe, it, expect, vi, afterEach } from 'vitest';

import { toolsApi } from './tools';
import { request } from '../base';

vi.mock('../base', () => ({ request: vi.fn() }));

const requestMock = request as unknown as ReturnType<typeof vi.fn>;

afterEach(() => {
  vi.clearAllMocks();
});

describe('toolsApi.testTool 请求体契约（D1）', () => {
  it('参数以 { arguments: ... } 包裹发送，URL 指向 /api/tools/{id}/test', async () => {
    requestMock.mockResolvedValue({ result: { value: 3 } });
    await toolsApi.testTool('calculator', { expression: '1+2' });

    expect(requestMock).toHaveBeenCalledTimes(1);
    expect(requestMock).toHaveBeenCalledWith(
      expect.objectContaining({
        url: '/api/tools/calculator/test',
        method: 'post',
        data: { arguments: { expression: '1+2' } },
      }),
    );
  });

  it('未填参数时不裸传 undefined（JSON 序列化后命中后端 arguments 默认空参）', async () => {
    requestMock.mockResolvedValue({ result: {} });
    await toolsApi.testTool('clock');

    const config = requestMock.mock.calls[0][0];
    expect(config.data).toEqual({ arguments: undefined });
    // JSON.stringify 丢弃 undefined → 请求体为 {}，与后端 Dict = {} 默认值对齐
    expect(JSON.stringify(config.data)).toBe('{}');
  });
});
