/**
 * vision client filterFrame 单测（spec add-vlm-frame-filter-face-match Task 5.5）。
 *
 * 验证 POST /api/vision/frame 请求形状与信号契约响应解析：
 * - data 按 { image, agent_id, source, ts } 下发（snake_case 对齐后端契约）；
 * - 响应为扁平信号契约（非 APIResponse 包裹），直接透传给调用方；
 * - request 抛错（网络失败/非 2xx 归一化）时原样上抛，由 PetPage 回退直通对话。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { filterFrame } from './vision';
import { request } from '../base';

vi.mock('../base', () => ({
  request: vi.fn(),
  // 以下为 vision.ts 模块级引用的其余 base 导出（filterFrame 路径不触达，仅需存在）
  getApiBaseUrl: vi.fn(() => 'http://127.0.0.1:8000'),
  normalizeError: vi.fn((e: unknown) => e),
  STORAGE_KEYS: { token: 'cxo-token' },
}));

const requestMock = request as unknown as ReturnType<typeof vi.fn>;

beforeEach(() => {
  requestMock.mockReset();
});

describe('filterFrame（POST /api/vision/frame）', () => {
  it('请求形状：url/method/data 按 {image, agent_id, source, ts} 冻结契约下发', async () => {
    requestMock.mockResolvedValue({ action: 'forward', filter_active: true });
    await filterFrame('data:image/webm;base64,AAAA', 'agent-9', 'camera', '2026-09-05T00:00:00Z');
    expect(requestMock).toHaveBeenCalledTimes(1);
    expect(requestMock).toHaveBeenCalledWith({
      url: '/api/vision/frame',
      method: 'post',
      data: {
        image: 'data:image/webm;base64,AAAA',
        agent_id: 'agent-9',
        source: 'camera',
        ts: '2026-09-05T00:00:00Z',
      },
    });
  });

  it('ts 省略时不下发该字段', async () => {
    requestMock.mockResolvedValue({ action: 'discard', filter_active: true });
    await filterFrame('img', 'agent-1', 'screen');
    const config = requestMock.mock.calls[0][0] as { data: Record<string, unknown> };
    expect(config.data.agent_id).toBe('agent-1');
    expect(config.data.source).toBe('screen');
    expect('ts' in config.data && config.data.ts !== undefined).toBe(false);
  });

  it('信号契约响应为扁平结构（非 APIResponse 包裹），原样透传', async () => {
    const contract = {
      action: 'summarize',
      summary: '用户翻动了文档',
      reason: '常规变化无需对话',
      importance: 'medium',
      degraded: false,
      face_labels: ['小A'],
      filter_active: true,
    };
    requestMock.mockResolvedValue(contract);
    await expect(filterFrame('img', 'agent-1', 'camera', 'ts')).resolves.toEqual(contract);
  });

  it('request 抛错（网络失败/非 2xx）时原样上抛，由调用方回退直通', async () => {
    requestMock.mockRejectedValue(new Error('无法连接到服务器，请检查后端服务是否启动'));
    await expect(filterFrame('img', 'agent-1', 'camera', 'ts')).rejects.toThrow(
      '无法连接到服务器，请检查后端服务是否启动',
    );
  });
});
