/**
 * avatarManifest client 单测（spec enhance-emotion-tts-and-action-presets Task 5.2）。
 *
 * 验证上报契约与容错口径：
 * - reportAvatarManifest：POST /api/avatar-manifest，data 按 {agent_id, actions[, expressions]}
 *   snake_case 冻结契约下发（对齐后端 AvatarManifestReport）；expressions 省略时不下发该字段；
 * - reportManifestActions：manifest 就绪触发上报（actions=motions keys，expressions=expressions[].id）、
 *   agentId 正确传递、空 actions 跳过上报（不覆盖服务端有用缓存）、manifest/agentId 缺失跳过、
 *   上报失败静默（console.warn，不向调用方抛错——绝不影响头像加载主流程）。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

import { reportAvatarManifest, reportManifestActions } from './avatarManifest';
import { request } from '../base';
import type { AvatarManifest } from '../../avatar/types';

vi.mock('../base', () => ({
  request: vi.fn(),
  // 以下为模块级引用的其余 base 导出（上报路径不触达，仅需存在）
  getApiBaseUrl: vi.fn(() => 'http://127.0.0.1:8000'),
  normalizeError: vi.fn((e: unknown) => e),
  STORAGE_KEYS: { token: 'cxo-token' },
}));

const requestMock = request as unknown as ReturnType<typeof vi.fn>;

beforeEach(() => {
  requestMock.mockReset();
  requestMock.mockResolvedValue({
    status: 'success',
    agent_id: 'agent-1',
    actions_count: 2,
    expressions_count: 1,
    updated_at: '2026-09-12T00:00:00',
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

/** 构造最小可用 manifest（motions + expressions） */
function makeManifest(overrides: Partial<AvatarManifest> = {}): AvatarManifest {
  return {
    id: 'mock-avatar',
    name: 'Mock',
    summary: '',
    persona: { tone: '', traits: [], styleRules: [] },
    modelJson: '',
    scaleMultiplier: 1,
    verticalOffset: 0,
    modelTransform: { scale: 1, offsetX: 0, offsetY: 0 },
    transformDefaults: { scale: 1, offsetX: 0, offsetY: 0 },
    expressions: [
      { id: 'smile', label: '微笑', kind: 'emotion', prompt: '', binding: { mode: 'preset', params: {} } },
      { id: 'angry', label: '生气', kind: 'emotion', prompt: '', binding: { mode: 'preset', params: {} } },
    ],
    motions: { wave: { file: 'a.vrma' }, nod: { file: 'b.vrma' } },
    avatarType: 'vrm',
    ...overrides,
  } as unknown as AvatarManifest;
}

describe('reportAvatarManifest（POST /api/avatar-manifest）', () => {
  it('请求形状：url/method/data 按 {agent_id, actions, expressions} 冻结契约下发', async () => {
    await reportAvatarManifest({ agentId: 'agent-1', actions: ['wave'], expressions: ['smile'] });
    expect(requestMock).toHaveBeenCalledTimes(1);
    expect(requestMock).toHaveBeenCalledWith({
      url: '/api/avatar-manifest',
      method: 'post',
      data: { agent_id: 'agent-1', actions: ['wave'], expressions: ['smile'] },
    });
  });

  it('expressions 省略时不下发该字段（后端缺省空清单）', async () => {
    await reportAvatarManifest({ agentId: 'agent-1', actions: ['wave'] });
    const config = requestMock.mock.calls[0][0] as { data: Record<string, unknown> };
    expect('expressions' in config.data).toBe(false);
  });

  it('request 抛错（网络失败/非 2xx 归一化）时原样上抛', async () => {
    requestMock.mockRejectedValue(new Error('请求失败: 无法连接到服务器'));
    await expect(
      reportAvatarManifest({ agentId: 'agent-1', actions: ['wave'] }),
    ).rejects.toThrow('请求失败');
  });
});

describe('reportManifestActions（manifest 就绪触发上报）', () => {
  it('manifest 就绪且 actions 非空时上报：actions=motions keys、expressions=expressions[].id', async () => {
    await reportManifestActions(makeManifest(), 'agent-9');
    expect(requestMock).toHaveBeenCalledTimes(1);
    const config = requestMock.mock.calls[0][0] as { data: Record<string, unknown> };
    expect(config.data.agent_id).toBe('agent-9');
    expect(config.data.actions).toEqual(['wave', 'nod']);
    expect(config.data.expressions).toEqual(['smile', 'angry']);
  });

  it('agentId 正确传递：路由 query 来的 windowAgentId 原样透传', async () => {
    await reportManifestActions(makeManifest(), 'live-window-agent');
    const config = requestMock.mock.calls[0][0] as { data: Record<string, unknown> };
    expect(config.data.agent_id).toBe('live-window-agent');
  });

  it('空 actions 跳过上报（不覆盖服务端有用缓存）', async () => {
    await reportManifestActions(makeManifest({ motions: undefined }), 'agent-1');
    await reportManifestActions(makeManifest({ motions: {} }), 'agent-1');
    expect(requestMock).not.toHaveBeenCalled();
  });

  it('manifest 缺失或 agentId 缺失时跳过上报', async () => {
    await reportManifestActions(null, 'agent-1');
    await reportManifestActions(undefined, 'agent-1');
    await reportManifestActions(makeManifest(), null);
    await reportManifestActions(makeManifest(), undefined);
    expect(requestMock).not.toHaveBeenCalled();
  });

  it('上报失败静默：console.warn 且不向调用方抛错（不影响头像加载主流程）', async () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    requestMock.mockRejectedValue(new Error('网络断开'));
    await expect(reportManifestActions(makeManifest(), 'agent-1')).resolves.toBeUndefined();
    expect(warnSpy).toHaveBeenCalledTimes(1);
    expect(String(warnSpy.mock.calls[0][0])).toContain('上报失败');
  });
});
