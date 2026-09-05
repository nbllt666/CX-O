import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import AudioWorkstationPage from './AudioWorkstationPage';
import i18n from '../../i18n';
import { voiceworkstationApi } from '@/api/clients/voiceworkstation';
import { audioApi } from '@/api/clients/audio';

/**
 * 作曲/翻唱CXFC 页冒烟 + Tab 切换 + API 接线测试（split-audio-workstation-cxfc-modelstation 后）：
 * voiceworkstationApi 与 audioApi 整体打桩；默认渲染翻唱（Cover）面板，
 * 逐 Tab 切换验证对应面板渲染并消费对应域接口；tab=svc 已移除，非法值回落默认 Tab。
 * 训练/数据集 UI 已整体迁至模型工作站独立前端（CXO-ModelStation/frontend）。
 */
vi.mock('@/api/clients/voiceworkstation', () => ({
  voiceworkstationApi: {
    listSoVITSSVCModels: vi.fn(),
    sovitsSVCInfer: vi.fn(),
    uploadAudio: vi.fn(),
    musicListSongs: vi.fn(),
    musicGetTask: vi.fn(),
    musicDeleteSong: vi.fn(),
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

describe('AudioWorkstationPage 作曲/翻唱CXFC 页', () => {
  beforeAll(async () => {
    await i18n.changeLanguage('zh-CN');
    mocked.listSoVITSSVCModels.mockResolvedValue({ status: 'success', models: [] });
    mocked.musicListSongs.mockResolvedValue({ songs: [] });
    mockedAudio.listRefAudioAssets.mockResolvedValue({ assets: [], current_asset_id: null });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('渲染三个 Tab 按钮与默认翻唱面板，并消费 models 接口', async () => {
    renderPage();

    for (const name of ['翻唱', '作曲合成', '参考音频资产']) {
      expect(screen.getByRole('button', { name })).toBeInTheDocument();
    }
    // 默认 Cover 面板：空模型列表提示 + 上传/推理通道渲染
    expect(await screen.findByTestId('cover-no-models')).toBeInTheDocument();
    expect(screen.getByTestId('cover-upload-btn')).toBeInTheDocument();
    expect(screen.getByTestId('cover-infer-btn')).toBeInTheDocument();
    expect(mocked.listSoVITSSVCModels).toHaveBeenCalled();
    // 无训练/数据集 UI 残留
    expect(screen.queryByText(/批量数据集生成/)).not.toBeInTheDocument();
    expect(screen.queryByText(/页面建设中/)).not.toBeInTheDocument();
  });

  it('tab=svc 已移除：非法参数回落默认翻唱 Tab', async () => {
    renderPage('/?tab=svc');

    expect(await screen.findByTestId('cover-no-models')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '翻唱' })).toHaveClass('bg-primary');
    expect(mocked.listSoVITSSVCModels).toHaveBeenCalled();
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
