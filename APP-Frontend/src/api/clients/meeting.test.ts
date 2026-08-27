/**
 * meetingApi dataOf 错误传播测试（第四轮体检 G 组 M4）。
 *
 * 场景：dataOf 原实现对失败响应直接 `res.data as T`，success=false 时上游
 * catch 拿到的是 undefined 静默传播。修复后必须抛出携带服务端真实原因的异常。
 */
import { describe, it, expect, vi, afterEach } from 'vitest';

import { meetingApi } from './meeting';
import { request } from '../base';

vi.mock('../base', () => ({ request: vi.fn() }));

const requestMock = request as unknown as ReturnType<typeof vi.fn>;

afterEach(() => {
  vi.clearAllMocks();
});

describe('meetingApi 失败响应错误传播（M4）', () => {
  it('success=false 且携带 error 字段：抛出真实服务端原因', async () => {
    requestMock.mockResolvedValue({
      success: false,
      data: null,
      error: '房间不存在或已结束',
      message: null,
    });
    await expect(meetingApi.getState('room-404')).rejects.toThrow('房间不存在或已结束');
  });

  it('success=false 且 error 缺失时回退 message 字段', async () => {
    requestMock.mockResolvedValue({ success: false, data: null, message: 'backend busy' });
    await expect(meetingApi.speak('r1', 'hello')).rejects.toThrow('backend busy');
  });

  it('error/message 均缺失时回退默认文案而非静默返回 undefined', async () => {
    requestMock.mockResolvedValue({ success: false, data: null });
    await expect(meetingApi.end('r1')).rejects.toThrow('会议请求失败');
  });

  it('res 为空引用时同样抛默认文案（不因可选链短路误判成功）', async () => {
    requestMock.mockResolvedValue(undefined);
    await expect(meetingApi.getState('r1')).rejects.toThrow('会议请求失败');
  });

  it('success=true 正常透传 data', async () => {
    const snapshot = { room_id: 'room-9', state: 'in_meeting' };
    requestMock.mockResolvedValue({ success: true, data: snapshot });
    await expect(meetingApi.getState('room-9')).resolves.toBe(snapshot);
  });
});
