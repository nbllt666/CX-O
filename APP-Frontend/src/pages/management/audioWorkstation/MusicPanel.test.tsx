/**
 * MusicPanel 组件测试（R8-02 + R8-03 + 伴生3）：
 *  - 空乐谱（未填 / 解析后无 melody）提交被本地阻断，不发任何请求
 *  - 提交时标题注入 score JSON（后端 SynthesizeRequest 无独立 title 字段）
 *  - 合成受理成功后清空输入；请求失败时保留输入供重试
 *  - 存在进行中任务（pending/running）时 3s 轮询刷新列表，全部终态后停止
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act, cleanup } from '@testing-library/react';
import '@/i18n';

vi.mock('@/api/clients/voiceworkstation', () => ({
  voiceworkstationApi: {
    musicListSongs: vi.fn(),
    musicSynthesize: vi.fn(),
    musicValidateScore: vi.fn(),
    musicDeleteSong: vi.fn(),
  },
  getVoiceWorkstationAudioUrl: (url: string) => `http://test-voice${url}`,
}));

import { voiceworkstationApi } from '@/api/clients/voiceworkstation';
import type { MusicSynthesizeRequest, SongSummary } from '@/api/clients/voiceworkstation';
import MusicPanel from './MusicPanel';

const musicListSongs = vi.mocked(voiceworkstationApi.musicListSongs);
const musicSynthesize = vi.mocked(voiceworkstationApi.musicSynthesize);
const musicValidateScore = vi.mocked(voiceworkstationApi.musicValidateScore);

const SCORE_JSON = JSON.stringify({
  bpm: 120,
  melody: [{ pitch: 'C4', beats: 1, offset: 0, lyric: '你' }],
});

function makeSong(partial: Partial<SongSummary>): SongSummary {
  return {
    song_id: 's1',
    title: 'T',
    status: 'completed',
    stage: 'done',
    progress: 100,
    error: null,
    created_at: '',
    finished_at: null,
    audio_url: null,
    ...partial,
  };
}

async function fillAndSubmit(title: string, score: string): Promise<void> {
  fireEvent.change(screen.getByPlaceholderText('输入歌曲标题'), { target: { value: title } });
  fireEvent.change(screen.getByPlaceholderText('粘贴乐谱 JSON'), { target: { value: score } });
  fireEvent.click(screen.getByRole('button', { name: '开始合成' }));
}

beforeEach(() => {
  musicListSongs.mockReset();
  musicSynthesize.mockReset();
  musicValidateScore.mockReset();
  musicListSongs.mockResolvedValue({ songs: [] });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe('MusicPanel 合成提交', () => {
  it('乐谱为空时提交被本地阻断且不发请求', async () => {
    render(<MusicPanel />);
    await screen.findByText('暂无歌曲');
    await fillAndSubmit('测试歌', '   ');
    await waitFor(() => expect(screen.getByText('请先填写乐谱')).toBeInTheDocument());
    expect(musicSynthesize).not.toHaveBeenCalled();
    expect(musicValidateScore).not.toHaveBeenCalled();
  });

  it('乐谱解析后无 melody 时本地阻断', async () => {
    render(<MusicPanel />);
    await screen.findByText('暂无歌曲');
    await fillAndSubmit('测试歌', JSON.stringify({ bpm: 120 }));
    await waitFor(() => expect(screen.getByText('请先填写乐谱')).toBeInTheDocument());
    expect(musicSynthesize).not.toHaveBeenCalled();
  });

  it('提交时标题注入 score JSON，成功后清空输入', async () => {
    musicValidateScore.mockResolvedValue({ valid: true, errors: [] });
    musicSynthesize.mockResolvedValue({ song_id: 's1', status: 'pending' });
    render(<MusicPanel />);
    await screen.findByText('暂无歌曲');
    await fillAndSubmit('  测试歌  ', SCORE_JSON);
    await waitFor(() => expect(musicSynthesize).toHaveBeenCalledTimes(1));
    const req = musicSynthesize.mock.calls[0][0] as MusicSynthesizeRequest;
    expect(req.score.title).toBe('测试歌');
    expect(Array.isArray(req.score.melody)).toBe(true);
    await waitFor(() => {
      expect((screen.getByPlaceholderText('输入歌曲标题') as HTMLInputElement).value).toBe('');
      expect((screen.getByPlaceholderText('粘贴乐谱 JSON') as HTMLInputElement).value).toBe('');
    });
  });

  it('合成请求失败时保留输入供重试', async () => {
    musicValidateScore.mockResolvedValue({ valid: true, errors: [] });
    musicSynthesize.mockRejectedValue(new Error('boom'));
    render(<MusicPanel />);
    await screen.findByText('暂无歌曲');
    await fillAndSubmit('测试歌', SCORE_JSON);
    await waitFor(() =>
      expect(screen.getByText('合成失败，请重试（请检查乐谱 JSON 是否合法）')).toBeInTheDocument(),
    );
    expect((screen.getByPlaceholderText('输入歌曲标题') as HTMLInputElement).value).toBe('测试歌');
    expect((screen.getByPlaceholderText('粘贴乐谱 JSON') as HTMLInputElement).value).toBe(SCORE_JSON);
  });

  it('乐谱 JSON 解析失败走既有失败提示路径', async () => {
    render(<MusicPanel />);
    await screen.findByText('暂无歌曲');
    await fillAndSubmit('测试歌', '{invalid');
    await waitFor(() =>
      expect(screen.getByText('合成失败，请重试（请检查乐谱 JSON 是否合法）')).toBeInTheDocument(),
    );
    expect(musicSynthesize).not.toHaveBeenCalled();
  });
});

describe('MusicPanel 进行中任务轮询（R8-03）', () => {
  it('存在 pending/running 任务时 3s 轮询，全部终态后停止', async () => {
    vi.useFakeTimers();
    musicListSongs.mockResolvedValue({ songs: [makeSong({ status: 'running' })] });
    render(<MusicPanel />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(musicListSongs).toHaveBeenCalledTimes(1);

    // 3s 后轮询触发
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(musicListSongs).toHaveBeenCalledTimes(2);

    // 列表全部终态后停止轮询
    musicListSongs.mockResolvedValue({ songs: [makeSong({ status: 'completed' })] });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(musicListSongs).toHaveBeenCalledTimes(3);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(9000);
    });
    expect(musicListSongs).toHaveBeenCalledTimes(3);
  });

  it('全部任务均为终态时不挂轮询', async () => {
    vi.useFakeTimers();
    musicListSongs.mockResolvedValue({ songs: [makeSong({ status: 'completed' })] });
    render(<MusicPanel />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(musicListSongs).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(9000);
    });
    expect(musicListSongs).toHaveBeenCalledTimes(1);
  });
});
