import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import AudioWorkstationPage from './AudioWorkstationPage';
import i18n from '../../i18n';
import { voiceworkstationApi } from '@/api/clients/voiceworkstation';
import { audioApi } from '@/api/clients/audio';

/**
 * AudioWorkstationPage 冒烟 + Tab 切换 + API 接线测试（Qwen3 迁移后）：
 * voiceworkstationApi 与 audioApi 整体打桩；默认渲染 SVC 面板，
 * 逐 Tab 切换验证对应面板渲染并消费对应域接口；非占位校验。
 * F5-TTS / Orpheus / VoxCPM 单条参考音频生成已随 Qwen3 TTS 迁移移除。
 */
vi.mock('@/api/clients/voiceworkstation', () => ({
  voiceworkstationApi: {
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
    listSVCDatasets: vi.fn(),
    importSVCDataset: vi.fn(),
    deleteSVCDataset: vi.fn(),
    submitVoxCPMBatchDataset: vi.fn(),
    getVoxCPMBatchDatasetTask: vi.fn(),
  },
  getVoiceWorkstationAudioUrl: (url: string) => url,
}));

vi.mock('@/api/clients/audio', () => ({
  audioApi: {
    listRefAudioAssets: vi.fn(),
    uploadRefAudioAsset: vi.fn(),
    generateRefAudioFromPrompt: vi.fn(),
    updateRefAudioAssetNote: vi.fn(),
    deleteRefAudioAsset: vi.fn(),
    getRefAudioAssetAudioUrl: (id: string) => `/api/ref-audio-assets/${id}/audio`,
  },
}));

const mocked = vi.mocked(voiceworkstationApi);
const mockedAudio = vi.mocked(audioApi);

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
    mocked.listSVCDatasets.mockResolvedValue({ status: 'ok', datasets: [] });
    mocked.musicListSongs.mockResolvedValue({ songs: [] });
    mockedAudio.listRefAudioAssets.mockResolvedValue({ assets: [], current_asset_id: null });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('渲染三个 Tab 按钮与默认 SVC 面板，并消费 SVC 域接口', async () => {
    renderPage();

    for (const name of ['SVC 训练推理', '作曲合成', '参考音频资产']) {
      expect(screen.getByRole('button', { name })).toBeInTheDocument();
    }
    // 默认 SVC 面板
    expect(await screen.findByText('批量数据集生成')).toBeInTheDocument();
    expect(mocked.getSoVITSSVCStatus).toHaveBeenCalled();
    expect(mocked.listSVCDatasets).toHaveBeenCalled();
    expect(screen.queryByText(/页面建设中/)).not.toBeInTheDocument();
  });

  it('切到作曲合成 Tab 渲染歌曲列表并消费 musicListSongs', async () => {
    renderPage();
    screen.getByRole('button', { name: '作曲合成' }).click();

    expect(await screen.findByText('五线谱总谱')).toBeInTheDocument();
    expect(mocked.musicListSongs).toHaveBeenCalled();
  });

  it('切到参考音频资产 Tab 渲染资产面板并消费 listRefAudioAssets', async () => {
    renderPage();
    screen.getByRole('button', { name: '参考音频资产' }).click();

    expect(await screen.findByText(/Qwen3 参考音频资产管理/)).toBeInTheDocument();
    expect(mockedAudio.listRefAudioAssets).toHaveBeenCalled();
  });
});
