import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import AudioWorkstationPage from './AudioWorkstationPage';
import i18n from '../../i18n';
import { voiceworkstationApi } from '@/api/clients/voiceworkstation';

/**
 * AudioWorkstationPage 冒烟 + Tab 切换 + API 接线测试（SubTask 7.4）：
 * voiceworkstationApi 整体打桩；默认渲染 VoxCPM 面板，
 * 逐 Tab 切换验证对应面板渲染并消费对应域接口；非占位校验。
 */
vi.mock('@/api/clients/voiceworkstation', () => ({
  voiceworkstationApi: {
    getVoxCPMStatus: vi.fn(),
    generateVoxCPM: vi.fn(),
    getSoVITSSVCStatus: vi.fn(),
    listSoVITSSVCModels: vi.fn(),
    sovitsSVCPreprocess: vi.fn(),
    startSoVITSSVCTrain: vi.fn(),
    stopSoVITSSVCTrain: vi.fn(),
    sovitsSVCInfer: vi.fn(),
    musicListSongs: vi.fn(),
    musicValidateScore: vi.fn(),
    musicSynthesize: vi.fn(),
    musicDeleteSong: vi.fn(),
    getOrpheusStatus: vi.fn(),
    synthesizeOrpheus: vi.fn(),
    synthesizeOrpheusStream: vi.fn(),
    getRefAudioStatus: vi.fn(),
    pregenerateRefs: vi.fn(),
    exportEmotionRefsZip: vi.fn(),
    importEmotionRefsZip: vi.fn(),
  },
  getVoiceWorkstationAudioUrl: (url: string) => url,
}));
const mocked = vi.mocked(voiceworkstationApi);

function renderPage(initialPath = '/') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <AudioWorkstationPage />
    </MemoryRouter>,
  );
}

describe('AudioWorkstationPage 音频工作站页', () => {
  beforeAll(async () => {
    await i18n.changeLanguage('zh-CN');
    mocked.getVoxCPMStatus.mockResolvedValue({ status: 'healthy', model_path: '' });
    mocked.getSoVITSSVCStatus.mockResolvedValue({
      task_id: null,
      status: 'idle',
      progress: 0,
      epoch: 0,
      total_epochs: 0,
      message: '',
      models: [],
    });
    mocked.listSoVITSSVCModels.mockResolvedValue({ status: 'ok', models: [] });
    mocked.getOrpheusStatus.mockResolvedValue({ status: 'healthy', url: '', voice: '' });
    mocked.getRefAudioStatus.mockResolvedValue({ is_running: false, progress: null, result: null, error: null });
    mocked.musicListSongs.mockResolvedValue({ songs: [] });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('渲染五个 Tab 按钮与默认 VoxCPM 面板，并消费 getVoxCPMStatus', () => {
    renderPage();

    for (const name of ['VoxCPM 生成', 'SVC 训练推理', '作曲合成', 'Orpheus 合成', '参考音频']) {
      expect(screen.getByRole('button', { name })).toBeInTheDocument();
    }
    // 默认 VoxCPM 面板
    expect(screen.getByText('生成模式')).toBeInTheDocument();
    expect(mocked.getVoxCPMStatus).toHaveBeenCalled();
    expect(screen.queryByText(/页面建设中/)).not.toBeInTheDocument();
  });

  it('切到 SVC Tab 渲染训练面板并消费 SVC 域接口', async () => {
    renderPage();
    screen.getByRole('button', { name: 'SVC 训练推理' }).click();

    expect(await screen.findByText('训练状态')).toBeInTheDocument();
    expect(mocked.getSoVITSSVCStatus).toHaveBeenCalled();
    expect(mocked.listSoVITSSVCModels).toHaveBeenCalled();
  });

  it('切到作曲合成 Tab 渲染歌曲列表并消费 musicListSongs', async () => {
    renderPage();
    screen.getByRole('button', { name: '作曲合成' }).click();

    expect(await screen.findByText('新建合成')).toBeInTheDocument();
    expect(mocked.musicListSongs).toHaveBeenCalled();
  });

  it('切到 Orpheus Tab 渲染合成面板并消费 getOrpheusStatus', async () => {
    renderPage();
    screen.getByRole('button', { name: 'Orpheus 合成' }).click();

    expect(await screen.findByText('Orpheus 情感合成')).toBeInTheDocument();
    expect(mocked.getOrpheusStatus).toHaveBeenCalled();
  });

  it('切到参考音频 Tab 渲染面板并消费 getRefAudioStatus', async () => {
    renderPage();
    screen.getByRole('button', { name: '参考音频' }).click();

    expect(await screen.findByText('参考音频模式')).toBeInTheDocument();
    expect(mocked.getRefAudioStatus).toHaveBeenCalled();
  });
});
