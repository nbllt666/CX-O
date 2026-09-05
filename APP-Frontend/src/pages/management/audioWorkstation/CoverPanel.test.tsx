/**
 * CoverPanel.test.tsx — 翻唱面板组件测试（split-audio-workstation-cxfc-modelstation SubTask 4.2）
 *
 * 覆盖（voiceworkstationApi 整体打桩，不经 HTTP）：
 *  1. 渲染冒烟：模型下拉 / 上传通道 / 路径输入 / 参数 / 推理按钮
 *  2. 主通道上传：uploadAudio 成功后取 audio_path 回填路径输入并展示已上传文件名
 *  3. 提交推理：sovitsSVCInfer 以回填路径调用，结果渲染 audio 播放器
 *  4. 上传失败错误态
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import i18n from '../../../i18n';

vi.mock('@/api/clients/voiceworkstation', () => ({
  voiceworkstationApi: {
    listSoVITSSVCModels: vi.fn(),
    sovitsSVCInfer: vi.fn(),
    uploadAudio: vi.fn(),
  },
  getVoiceWorkstationAudioUrl: (url: string) => `http://test-voice${url}`,
}));

import { voiceworkstationApi } from '@/api/clients/voiceworkstation';
import CoverPanel from './CoverPanel';

const mocked = vi.mocked(voiceworkstationApi);

const MODELS = [
  { name: 'model-a', path: '/models/model-a', created: 1, g_model: null, d_model: null },
  { name: 'model-b', path: '/models/model-b', created: 2, g_model: null, d_model: null },
];

const UPLOAD_RESULT = {
  status: 'success',
  filename: 'abc123def456.wav',
  audio_path: 'C:/ws/data/input/abc123def456.wav',
};

const INFER_RESULT = {
  status: 'success',
  output_filename: 'out.wav',
  audio_url: '/api/audio-files/svc-results/out.wav',
};

function makeAudioFile(name = 'sample.wav'): File {
  return new File(['fake-audio-bytes'], name, { type: 'audio/wav' });
}

describe('CoverPanel 翻唱面板', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('zh-CN');
    mocked.listSoVITSSVCModels.mockResolvedValue({ status: 'success', models: MODELS });
    mocked.uploadAudio.mockResolvedValue(UPLOAD_RESULT);
    mocked.sovitsSVCInfer.mockResolvedValue(INFER_RESULT);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('渲染冒烟：模型下拉 / 上传通道 / 路径输入 / 参数与推理按钮', async () => {
    render(<CoverPanel />);

    // 模型列表加载完成后渲染下拉，且包含后端返回的模型项
    expect(await screen.findByTestId('cover-model-select')).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'model-a' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'model-b' })).toBeInTheDocument();

    // 上传通道 + 辅助路径输入 + 推理按钮
    expect(screen.getByTestId('cover-upload-btn')).toBeInTheDocument();
    expect(screen.getByTestId('cover-audio-path-input')).toBeInTheDocument();
    expect(screen.getByTestId('cover-speaker-id-input')).toBeInTheDocument();
    expect(screen.getByTestId('cover-transpose-input')).toBeInTheDocument();
    expect(screen.getByTestId('cover-cluster-model-input')).toBeInTheDocument();
    expect(screen.getByTestId('cover-infer-btn')).toBeInTheDocument();
    // 无训练/数据集 UI 残留
    expect(screen.queryByText(/批量数据集生成/)).not.toBeInTheDocument();
    expect(screen.queryByText(/开始训练/)).not.toBeInTheDocument();
  });

  it('主通道上传成功：取 audio_path 回填路径输入并展示已上传文件名', async () => {
    render(<CoverPanel />);
    await screen.findByTestId('cover-model-select');

    const input = screen.getByTestId('cover-upload-input') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [makeAudioFile()] } });

    await waitFor(() => {
      expect(mocked.uploadAudio).toHaveBeenCalledTimes(1);
    });
    const uploaded = mocked.uploadAudio.mock.calls[0][0] as File;
    expect(uploaded.name).toBe('sample.wav');

    // audio_path 回填到统一音频来源输入框，文件名可见
    const pathInput = screen.getByTestId('cover-audio-path-input') as HTMLInputElement;
    await waitFor(() => {
      expect(pathInput.value).toBe(UPLOAD_RESULT.audio_path);
    });
    expect(screen.getByTestId('cover-uploaded-filename')).toHaveTextContent('abc123def456.wav');
  });

  it('提交推理：以回填路径调用 sovitsSVCInfer 并渲染 audio 播放器', async () => {
    render(<CoverPanel />);
    await screen.findByTestId('cover-model-select');

    // 手输辅助通道路径 + 调整参数
    const pathInput = screen.getByTestId('cover-audio-path-input');
    fireEvent.change(pathInput, { target: { value: 'C:/ws/data/input/manual.wav' } });
    fireEvent.change(screen.getByTestId('cover-speaker-id-input'), { target: { value: '1' } });
    fireEvent.change(screen.getByTestId('cover-transpose-input'), { target: { value: '-2' } });

    fireEvent.click(screen.getByTestId('cover-infer-btn'));

    await waitFor(() => {
      expect(mocked.sovitsSVCInfer).toHaveBeenCalledTimes(1);
    });
    expect(mocked.sovitsSVCInfer).toHaveBeenCalledWith({
      audio_path: 'C:/ws/data/input/manual.wav',
      model_path: undefined,
      speaker_id: 1,
      transpose: -2,
      cluster_model_path: undefined,
    });

    // 结果渲染内嵌播放器，src 经 getVoiceWorkstationAudioUrl 拼接
    const player = await screen.findByTestId('cover-audio-player');
    expect(player).toHaveAttribute('src', `http://test-voice${INFER_RESULT.audio_url}`);
  });

  it('上传失败：展示错误态且不回填路径', async () => {
    mocked.uploadAudio.mockRejectedValue(new Error('upload rejected'));
    render(<CoverPanel />);
    await screen.findByTestId('cover-model-select');

    const input = screen.getByTestId('cover-upload-input');
    fireEvent.change(input, { target: { files: [makeAudioFile()] } });

    expect(await screen.findByTestId('cover-upload-error')).toBeInTheDocument();
    const pathInput = screen.getByTestId('cover-audio-path-input') as HTMLInputElement;
    expect(pathInput.value).toBe('');
    expect(screen.queryByTestId('cover-uploaded-filename')).not.toBeInTheDocument();
  });
});
