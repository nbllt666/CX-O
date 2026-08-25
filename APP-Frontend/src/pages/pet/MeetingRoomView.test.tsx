/**
 * MeetingRoomView 互动空间视图单测（T6.4）：
 *  - 消息流三态身份渲染（user/audience/agent）
 *  - 观众席开关调用 toggleAudience（meeting 内）
 *  - 建会面板"建会即开启观众席"随 start 提交
 *  - @agent 快捷点名插入输入框 + speak 携带 mention
 * useMeetingWebSocket 整体打桩，govern 可控 snapshot。
 */
import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import MeetingRoomView from './MeetingRoomView';
import i18n from '../../i18n';
import type { MeetingRoomSnapshot, MeetingSpeakResult } from '@/api/clients/meeting';
import type { Agent } from '@/api/types';

const h = vi.hoisted(() => ({
  snapshot: null as MeetingRoomSnapshot | null,
  isPolling: false,
  isError: false,
  start: vi.fn(),
  end: vi.fn(),
  speak: vi.fn(),
  toggleAudience: vi.fn(),
}));

vi.mock('@/api/clients/agents', () => ({
  agentsApi: { getAgents: vi.fn() },
}));

vi.mock('@/hooks/useMeetingWebSocket', () => ({
  useMeetingWebSocket: () => ({
    snapshot: h.snapshot,
    isPolling: h.isPolling,
    isError: h.isError,
    start: h.start,
    end: h.end,
    join: vi.fn(),
    leave: vi.fn(),
    speak: h.speak,
    toggleAudience: h.toggleAudience,
    refresh: vi.fn(),
  }),
}));

import { agentsApi } from '@/api/clients/agents';

const mockedAgents = vi.mocked(agentsApi.getAgents);

// 复用 AcpPage 测试的轻量 Agent 结构（仅 id/name 被视图使用）
const AGENT_LIST = [
  { id: 'agent-1', name: '小红', tags: [] },
  { id: 'agent-2', name: '小蓝', tags: [] },
] as unknown as Agent[];

const snapshotForMeeting = (
  over?: Partial<MeetingRoomSnapshot>,
): MeetingRoomSnapshot => ({
  room_id: 'room-1',
  user: 'user',
  state: 'in_meeting',
  max_agents: 3,
  agents: [
    { agent_id: 'agent-1', name: '小红' },
    { agent_id: 'agent-2', name: '小蓝' },
  ],
  token_holder: 'agent-1',
  transcript_turns: 1,
  audience_enabled: false,
  recent_messages: [],
  ...over,
});

const speakResult: MeetingSpeakResult = {
  decision: { mode: 'speak', speaker: 'a', participants: ['a'], intent: null, reason: '' },
  turns: [],
  transcript_turns: 2,
};

describe('MeetingRoomView 互动空间', () => {
  beforeAll(async () => {
    await i18n.changeLanguage('zh-CN');
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('建会面板：开启观众席后 start 提交 audience_enabled', async () => {
    h.snapshot = null;
    h.start.mockResolvedValue(snapshotForMeeting());
    mockedAgents.mockResolvedValue(AGENT_LIST);

    render(<MeetingRoomView />);
    await screen.findByText('选择参与者并开始会议');
    fireEvent.click(screen.getByTestId('audience-toggle-start'));
    fireEvent.click(screen.getByRole('button', { name: '开始会议' }));

    expect(h.start).toHaveBeenCalledWith(
      expect.objectContaining({ audience_enabled: true }),
    );
  });

  it('消息流三态渲染：用户/观众(名字)/Agent', async () => {
    h.snapshot = snapshotForMeeting({
      recent_messages: [
        { role: 'user', speaker: 'user', text: '主播好' },
        { role: 'agent', speaker: '小红', text: '大家好' },
        { role: 'audience', speaker: '观众甲', text: '前排围观' },
      ],
    });
    mockedAgents.mockResolvedValue(AGENT_LIST);

    render(<MeetingRoomView />);
    expect(await screen.findByText('主播好')).toBeInTheDocument();
    expect(screen.getByText('大家好')).toBeInTheDocument();
    expect(screen.getByText('前排围观')).toBeInTheDocument();
    // 观众以名字标识
    expect(screen.getByText('观众甲')).toBeInTheDocument();
    // 空态不出现
    expect(screen.queryByText('还没有消息')).not.toBeInTheDocument();
  });

  it('消息流为空显示空态提示', async () => {
    h.snapshot = snapshotForMeeting({ recent_messages: [] });
    mockedAgents.mockResolvedValue(AGENT_LIST);

    render(<MeetingRoomView />);
    expect(await screen.findByText('还没有消息')).toBeInTheDocument();
  });

  it('会议中观众席开关：调用 toggleAudience', async () => {
    h.snapshot = snapshotForMeeting({ audience_enabled: false });
    h.toggleAudience.mockResolvedValue(snapshotForMeeting({ audience_enabled: true }));
    mockedAgents.mockResolvedValue(AGENT_LIST);

    render(<MeetingRoomView />);
    const toggle = await screen.findByTestId('audience-toggle-live');
    fireEvent.click(toggle);

    expect(h.toggleAudience).toHaveBeenCalledWith(true);
  });

  it('@agent 快捷点名：插入 @名 到输入框并 speak 携带 mention', async () => {
    h.snapshot = snapshotForMeeting();
    h.speak.mockResolvedValue(speakResult);
    mockedAgents.mockResolvedValue(AGENT_LIST);

    render(<MeetingRoomView />);
    fireEvent.click(await screen.findByTestId('mention-agent-1'));

    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement;
    expect(textarea.value).toContain('@小红');

    fireEvent.click(screen.getByRole('button', { name: '发言' }));
    expect(h.speak).toHaveBeenCalledWith(
      expect.stringContaining('@小红'),
      expect.objectContaining({ role: 'user', mention: 'agent-1' }),
    );
  });
});