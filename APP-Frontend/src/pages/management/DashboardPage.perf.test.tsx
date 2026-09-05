import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import DashboardPage from './DashboardPage';
import i18n from '../../i18n';
import { metricsApi } from '@/api/clients/metrics';
import { healthApi } from '@/api/clients/health';
import { memoriesApi } from '@/api/clients/memories';
import { chatApi } from '@/api/clients/chat';
import { agentsApi } from '@/api/clients/agents';
import type { VoiceLatencyStats } from '@/api/clients/metrics';

/**
 * DashboardPage 性能指标区块测试（enhance-cxfc-admin-and-integrate-dream Task 5）：
 * metricsApi 与页面依赖的其他 api clients 全部打桩，避免真实网络；
 * 覆盖三态——有数据（四段非零，P50/P95 数值可见）、空数据（暂无样本）、
 * 请求失败（静默降级为空态+提示，不影响页面其他区块）。
 */
vi.mock('@/api/clients/metrics', () => ({
  metricsApi: {
    getVoiceLatency: vi.fn(),
  },
}));

vi.mock('@/api/clients/health', () => ({
  healthApi: {
    getHealth: vi.fn(),
  },
}));

vi.mock('@/api/clients/memories', () => ({
  memoriesApi: {
    getStats: vi.fn(),
  },
}));

vi.mock('@/api/clients/chat', () => ({
  chatApi: {
    getSessions: vi.fn(),
  },
}));

vi.mock('@/api/clients/agents', () => ({
  agentsApi: {
    getAgents: vi.fn(),
  },
}));

const mockedGetVoiceLatency = vi.mocked(metricsApi.getVoiceLatency);

function seg(p50: number | null, p95: number | null, count: number) {
  return { p50, p95, max: p95, count };
}

const SAMPLE_STATS: VoiceLatencyStats = {
  summary: {
    asr: seg(320, 540, 12),
    ttft: seg(450, 890, 12),
    tts_first: seg(180, 420, 10),
    e2e: seg(980, 1500, 12),
  },
  recent: [],
  buffer_size: 12,
};

const EMPTY_STATS: VoiceLatencyStats = {
  summary: {
    asr: seg(null, null, 0),
    ttft: seg(null, null, 0),
    tts_first: seg(null, null, 0),
    e2e: seg(null, null, 0),
  },
  recent: [],
  buffer_size: 0,
};

/** 页面其余区块依赖的主数据打桩（健康面板/统计卡/快捷操作/服务统计均需可渲染） */
function mockPageBaseData(): void {
  vi.mocked(healthApi.getHealth).mockResolvedValue({
    status: 'ok',
    version: 'test-version',
  } as never);
  vi.mocked(memoriesApi.getStats).mockResolvedValue({
    total_memories: 3,
    archived_memories: 1,
    total_messages: 5,
  } as never);
  vi.mocked(chatApi.getSessions).mockResolvedValue([] as never);
  vi.mocked(agentsApi.getAgents).mockResolvedValue([] as never);
}

describe('DashboardPage 性能指标区块', () => {
  beforeAll(async () => {
    await i18n.changeLanguage('zh-CN');
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('有数据：四段 P50/P95 数值与段名可见，样本数展示，无空态文案', async () => {
    mockPageBaseData();
    mockedGetVoiceLatency.mockResolvedValue(SAMPLE_STATS);

    render(
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText('性能指标')).toBeInTheDocument();
    // 四段段名
    expect(screen.getByText('语音识别')).toBeInTheDocument();
    expect(screen.getByText('LLM 首 Token')).toBeInTheDocument();
    expect(screen.getByText('TTS 首帧')).toBeInTheDocument();
    expect(screen.getByText('端到端')).toBeInTheDocument();
    // P50/P95 标签各出现 4 次（每段两条）
    expect(screen.getAllByText('P50')).toHaveLength(4);
    expect(screen.getAllByText('P95')).toHaveLength(4);
    // 数值真实显示（含单位 ms）
    expect(screen.getByText('320 ms')).toBeInTheDocument();
    expect(screen.getByText('890 ms')).toBeInTheDocument();
    expect(screen.getByText('980 ms')).toBeInTheDocument();
    expect(screen.getByText('1500 ms')).toBeInTheDocument();
    // 样本数
    expect(screen.getByText(/样本数/)).toBeInTheDocument();
    // 有数据时不得出现空态文案
    expect(screen.queryByText('暂无样本')).not.toBeInTheDocument();
  });

  it('空数据：全部 count 为 0 时显示「暂无样本」且不渲染横条数值', async () => {
    mockPageBaseData();
    mockedGetVoiceLatency.mockResolvedValue(EMPTY_STATS);

    render(
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText('性能指标')).toBeInTheDocument();
    expect(screen.getByText('暂无样本')).toBeInTheDocument();
    expect(screen.queryByText('320 ms')).not.toBeInTheDocument();
    // P50/P95 标签随横条一起不渲染
    expect(screen.queryByText('P50')).not.toBeInTheDocument();
  });

  it('请求失败：静默降级为空态+提示，页面其他区块正常渲染', async () => {
    mockPageBaseData();
    mockedGetVoiceLatency.mockRejectedValue(new Error('503 collector down'));

    render(
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText('暂无样本')).toBeInTheDocument();
    expect(screen.getByText('指标拉取失败，将在下轮自动重试')).toBeInTheDocument();
    // 静默降级：其他区块不受影响
    expect(screen.getByText('后端健康状态')).toBeInTheDocument();
    expect(screen.getByText('快捷操作')).toBeInTheDocument();
    expect(screen.getByText('服务统计')).toBeInTheDocument();
  });
});
