import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import AutonomyPage from './AutonomyPage';
import i18n from '../../i18n';
import { autonomyApi } from '@/api/clients/autonomy';
import type { AutonomyAuditEntry, AutonomyConfig, AutonomyStatus } from '@/api/types';

/**
 * AutonomyPage「Agent 生活」冒烟 + 关键交互测试（P4-T1）：
 * autonomyApi 整体打桩，避免真实网络；覆盖状态/动机/预算/审计渲染、
 * 未启用降级态、启用/禁用/暂停/恢复控制、自动启动开关、审计字段渲染与后端错误态。
 * 注：页面已移除紧急停止入口（spec remove-autonomy-stop-paths）；「禁用」（总开关回退）
 * 与「暂停/恢复」由评审 Issue1 + 人类裁定后恢复（UI 入口与后端 CONTROL_ACTIONS 对齐）。
 */
vi.mock('@/api/clients/autonomy', () => ({
  autonomyApi: {
    getStatus: vi.fn(),
    control: vi.fn(),
    getAudit: vi.fn(),
    getConfig: vi.fn(),
    updateConfig: vi.fn(),
  },
}));

const mocked = vi.mocked(autonomyApi);

const ACTIVE_STATUS: AutonomyStatus = {
  status: 'running',
  motivations: { curiosity: 0.8, social_need: 0.5, creative_drive: 0.6, fatigue: 0.2 },
  last_action: 'write_post',
  last_cycle_at: '2026-08-22T10:00:00Z',
  daily_budget_used_tokens: 120000,
  budget_reset_date: '2026-08-22',
  diary_last_at: '2026-08-22T09:00:00Z',
};

const DISABLED_STATUS: AutonomyStatus = { status: 'disabled' };

const PAUSED_STATUS: AutonomyStatus = {
  status: 'paused',
  motivations: { curiosity: 0.4, social_need: 0.3, creative_drive: 0.2, fatigue: 0.6 },
  last_action: 'write_post',
  last_cycle_at: '2026-08-22T10:00:00Z',
  daily_budget_used_tokens: 1000,
  budget_reset_date: '2026-08-22',
};

const SAMPLE_AUDIT: AutonomyAuditEntry[] = [
  {
    timestamp: '2026-08-22T10:00:00Z',
    action: 'read_news',
    target: 'live',
    result: 'success',
    trigger_reason: '灵感触发',
  },
  {
    timestamp: '2026-08-22T09:30:00Z',
    action: 'write_memory',
    result: 'skipped',
    trigger_reason: '静默时段',
  },
];

const SAMPLE_CONFIG: AutonomyConfig = {
  enabled: true,
  auto_start: true,
  agent_id: 'default',
  loop_interval_minutes: 15,
  rss_sources: [],
  search: { mcp_server_name: 'free-search-mcp', fallback_rss: true },
  schedule: {
    wake_time: '08:00',
    sleep_time: '02:00',
    golden_start: '19:00',
    golden_end: '23:00',
    diary_time: '02:00',
    quiet_windows: [],
  },
  budget: {
    daily_token_limit: 2000000,
    daily_llm_calls_limit: 0,
    cost_alert_threshold: 0.8,
    overspend_mode: 'sleep',
  },
  platforms: [],
  permissions: { allowed_actions: [], blocked_actions: [] },
  safety: {
    content_gate_enabled: true,
    persona_check_enabled: true,
    post_rate_per_hour: 5,
    user_online_sleep: true,
    leave_mode_authorize: true,
  },
  store_path: '',
};

describe('AutonomyPage Agent 生活页', () => {
  beforeAll(async () => {
    await i18n.changeLanguage('zh-CN');
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('加载后渲染状态/动机/预算/审计', async () => {
    mocked.getStatus.mockResolvedValue(ACTIVE_STATUS);
    mocked.getConfig.mockResolvedValue(SAMPLE_CONFIG);
    mocked.getAudit.mockResolvedValue({ items: SAMPLE_AUDIT, total: 2 });

    render(<AutonomyPage />);

    // 状态徽章 + 上次行动
    expect(await screen.findByText('运行中')).toBeInTheDocument();
    expect(screen.getByText('write_post')).toBeInTheDocument();
    // 动机
    expect(screen.getByText('好奇心')).toBeInTheDocument();
    expect(screen.getByText('80%')).toBeInTheDocument();
    expect(screen.getByText('疲惫度')).toBeInTheDocument();
    // 预算（含 2,000,000 限额文案）
    expect(screen.getByText(/2,000,000/)).toBeInTheDocument();
    // 审计
    expect(screen.getByText('read_news')).toBeInTheDocument();
    expect(screen.getByText('write_memory')).toBeInTheDocument();
    expect(screen.getByText('live')).toBeInTheDocument();
    expect(screen.getByText('成功')).toBeInTheDocument();
    expect(screen.getByText('已跳过')).toBeInTheDocument();
    expect(screen.getByText('灵感触发')).toBeInTheDocument();
    expect(screen.getByText('静默时段')).toBeInTheDocument();
    expect(screen.queryByText(/页面建设中/)).not.toBeInTheDocument();
    // running 态提供「禁用」「暂停」两个入口，不提供「恢复」/急停
    expect(screen.getByRole('button', { name: '禁用' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '暂停' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '恢复' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '紧急停止' })).not.toBeInTheDocument();
    expect(screen.getByRole('checkbox')).toBeInTheDocument();
  });

  it('后端返回 disabled 时显示未启用态', async () => {
    mocked.getStatus.mockResolvedValue(DISABLED_STATUS);
    mocked.getConfig.mockResolvedValue({ ...SAMPLE_CONFIG, enabled: false });
    mocked.getAudit.mockResolvedValue({ items: [], total: 0 });

    render(<AutonomyPage />);

    expect(await screen.findByText('自主系统未启用')).toBeInTheDocument();
    expect(screen.getByText('未启用')).toBeInTheDocument(); // 状态徽章
    expect(screen.getByRole('button', { name: '启用' })).toBeInTheDocument();
  });

  it('paused 状态显示「恢复」按钮并触发 control("resume")', async () => {
    mocked.getStatus.mockResolvedValue(PAUSED_STATUS);
    mocked.getConfig.mockResolvedValue(SAMPLE_CONFIG);
    mocked.getAudit.mockResolvedValue({ items: [], total: 0 });
    mocked.control.mockResolvedValue({
      status: 'ok',
      state: { enabled: true, running: true, status: 'running' },
    });

    render(<AutonomyPage />);
    expect(await screen.findByText('已暂停')).toBeInTheDocument();
    // paused 态：「禁用」与「恢复」并存，「暂停」入口不出现（非 running）
    expect(screen.getByRole('button', { name: '禁用' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '暂停' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '紧急停止' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '恢复' }));
    await waitFor(() => {
      expect(mocked.control).toHaveBeenCalledWith('resume');
    });
  });

  it('暂停按钮触发 control("pause")（running 态可用）', async () => {
    mocked.getStatus.mockResolvedValue(ACTIVE_STATUS);
    mocked.getConfig.mockResolvedValue(SAMPLE_CONFIG);
    mocked.getAudit.mockResolvedValue({ items: [], total: 0 });
    mocked.control.mockResolvedValue({
      status: 'ok',
      state: { enabled: true, running: false, status: 'paused' },
    });

    render(<AutonomyPage />);
    expect(await screen.findByRole('button', { name: '暂停' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '暂停' }));
    await waitFor(() => {
      expect(mocked.control).toHaveBeenCalledWith('pause');
    });
  });

  it('禁用按钮触发 control("disable")（启用后总开关可回退）', async () => {
    mocked.getStatus.mockResolvedValue(ACTIVE_STATUS);
    mocked.getConfig.mockResolvedValue(SAMPLE_CONFIG);
    mocked.getAudit.mockResolvedValue({ items: [], total: 0 });
    mocked.control.mockResolvedValue({
      status: 'ok',
      state: { enabled: false, running: false, status: 'paused' },
    });

    render(<AutonomyPage />);
    expect(await screen.findByRole('button', { name: '禁用' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '禁用' }));
    await waitFor(() => {
      expect(mocked.control).toHaveBeenCalledWith('disable');
    });
  });

  it('启用按钮触发 control("enable")', async () => {
    mocked.getStatus.mockResolvedValue(DISABLED_STATUS);
    mocked.getConfig.mockResolvedValue({ ...SAMPLE_CONFIG, enabled: false });
    mocked.getAudit.mockResolvedValue({ items: [], total: 0 });
    mocked.control.mockResolvedValue({
      status: 'ok',
      state: { enabled: true, running: true, status: 'running' },
    });

    render(<AutonomyPage />);
    expect(await screen.findByRole('button', { name: '启用' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '启用' }));
    await waitFor(() => {
      expect(mocked.control).toHaveBeenCalledWith('enable');
    });
  });

  it('自动启动开关触发 updateConfig({auto_start:false})', async () => {
    mocked.getStatus.mockResolvedValue(ACTIVE_STATUS);
    mocked.getConfig.mockResolvedValue(SAMPLE_CONFIG);
    mocked.getAudit.mockResolvedValue({ items: [], total: 0 });
    mocked.updateConfig.mockResolvedValue({ ...SAMPLE_CONFIG, auto_start: false });

    render(<AutonomyPage />);
    const checkbox = await screen.findByRole('checkbox');
    expect(checkbox).toBeChecked();
    fireEvent.click(checkbox);
    await waitFor(() => {
      expect(mocked.updateConfig).toHaveBeenCalledWith({ auto_start: false });
    });
  });

  it('后端错误时显示错误态不崩溃', async () => {
    mocked.getStatus.mockResolvedValue(null);
    mocked.getConfig.mockResolvedValue(null);
    mocked.getAudit.mockResolvedValue(null);

    render(<AutonomyPage />);

    expect(
      await screen.findByText('加载失败，请检查后端连接后重试'),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '重试' })).toBeInTheDocument();
  });
});
