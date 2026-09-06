/**
 * CoverPanel.test.tsx — 翻唱面板组件测试（split-audio-workstation-cxfc-modelstation SubTask 4.2 +
 * enhance-cover-pitch-analysis-duet SubTask 4.4）
 *
 * 覆盖（voiceworkstationApi 整体打桩，不经 HTTP）：
 *  1. 渲染冒烟：模型下拉 / 上传通道 / 路径输入 / 参数 / 推理按钮
 *  2. 主通道上传：uploadAudio 成功后取 audio_path 回填路径输入并展示已上传文件名
 *  3. 提交推理：sovitsSVCInfer 以回填路径调用，结果渲染 audio 播放器
 *  4. 上传失败错误态
 *  5. 音域分析（duet spec）：上传成功触发 analyzeCover 并预填 transpose（推荐值可改）
 *  6. range_warning 警告条 / profile_unavailable 提示展示
 *  7. 用户手改 transpose 后不再被 analyze 覆盖（重新上传才重置）
 *  8. analyze 失败静默降级：不阻塞手填 transpose
 *  9. 模式切换：双人合唱模式渲染 DuetPanel，单人内容隐藏
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import i18n from '../../../i18n';

vi.mock('@/api/clients/voiceworkstation', () => ({
  voiceworkstationApi: {
    listSoVITSSVCModels: vi.fn(),
    sovitsSVCInfer: vi.fn(),
    uploadAudio: vi.fn(),
    analyzeCover: vi.fn(),
    listCoverModelProfiles: vi.fn(),
    submitDuetCover: vi.fn(),
    getDuetCoverTask: vi.fn(),
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

/** POST /api/cover/analyze 响应 fixture（后端 api/cover.py 契约） */
const ANALYZE_RESULT = {
  status: 'success',
  audio_path: UPLOAD_RESULT.audio_path,
  separation_used: false,
  profile: {
    f0_median_hz: 220.0,
    f0_median_midi: 57.0,
    range_low_midi: 52.0,
    range_high_midi: 64.0,
    range_span_semitones: 12.0,
    voiced_ratio: 0.8,
  },
  model_name: 'model-a',
  target_profile: {
    speaker_name: 'model-a',
    f0_median_hz: 196.0,
    f0_median_midi: 55.0,
    range_low_midi: 50.0,
    range_high_midi: 62.0,
    range_span_semitones: 12.0,
    sample_count: 10,
    dataset_md5: 'abcdef',
    computed_at: '2026-09-06T00:00:00',
  },
  recommended_transpose: 2,
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
    mocked.analyzeCover.mockResolvedValue(ANALYZE_RESULT);
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

  // ── 音域分析 + 预填（enhance-cover-pitch-analysis-duet SubTask 4.2）──

  it('音域分析：上传成功触发 analyzeCover 并预填推荐 transpose', async () => {
    render(<CoverPanel />);
    await screen.findByTestId('cover-model-select');

    const input = screen.getByTestId('cover-upload-input');
    fireEvent.change(input, { target: { files: [makeAudioFile()] } });

    // analyze 以回填路径调用（未选模型 → model_name undefined）
    await waitFor(
      () => {
        expect(mocked.analyzeCover).toHaveBeenCalledWith(UPLOAD_RESULT.audio_path, undefined);
      },
      { timeout: 2000 }, // analyze 有 500ms 防抖
    );

    // 推荐 transpose=2 预填（可修改），并展示推荐徽标与源/目标音域对比
    const transposeInput = screen.getByTestId('cover-transpose-input') as HTMLInputElement;
    await waitFor(() => expect(transposeInput.value).toBe('2'));
    expect(screen.getByTestId('cover-analyze-recommended')).toHaveTextContent('推荐 +2 key');
    expect(screen.getByTestId('cover-range-compare')).toBeInTheDocument();
  });

  it('音域分析：range_warning 警告条展示', async () => {
    mocked.analyzeCover.mockResolvedValue({
      ...ANALYZE_RESULT,
      range_warning: '源音频音域跨度 15.0 半音，超过目标模型音域跨度 12.0 半音，翻唱后音区覆盖可能不足',
    });
    render(<CoverPanel />);
    await screen.findByTestId('cover-model-select');

    fireEvent.change(screen.getByTestId('cover-upload-input'), { target: { files: [makeAudioFile()] } });

    expect(await screen.findByTestId('cover-range-warning', {}, { timeout: 2000 })).toHaveTextContent(
      '源音频音域跨度 15.0 半音',
    );
  });

  it('音域分析：profile_unavailable 提示展示（模型训练数据不可得）', async () => {
    mocked.analyzeCover.mockResolvedValue({
      ...ANALYZE_RESULT,
      model_name: undefined,
      target_profile: undefined,
      recommended_transpose: undefined,
      profile_unavailable: '模型训练数据不可得，无法推荐 transpose',
    });
    render(<CoverPanel />);
    await screen.findByTestId('cover-model-select');

    fireEvent.change(screen.getByTestId('cover-upload-input'), { target: { files: [makeAudioFile()] } });

    expect(await screen.findByTestId('cover-profile-unavailable', {}, { timeout: 2000 })).toHaveTextContent(
      '模型训练数据不可得',
    );
    // 无推荐时不展示推荐徽标
    expect(screen.queryByTestId('cover-analyze-recommended')).not.toBeInTheDocument();
  });

  it('音域分析：用户手改 transpose 后 analyze 不覆盖（重新上传才重置）', async () => {
    render(<CoverPanel />);
    await screen.findByTestId('cover-model-select');

    // 上传 → 预填 2
    fireEvent.change(screen.getByTestId('cover-upload-input'), { target: { files: [makeAudioFile()] } });
    const transposeInput = screen.getByTestId('cover-transpose-input') as HTMLInputElement;
    await waitFor(() => expect(transposeInput.value).toBe('2'), { timeout: 2000 });

    // 用户手改为 -5
    fireEvent.change(transposeInput, { target: { value: '-5' } });

    // 切换模型触发重新 analyze（防抖后第二次调用，携带模型名）
    fireEvent.change(screen.getByTestId('cover-model-select'), { target: { value: MODELS[1].path } });
    await waitFor(
      () => {
        expect(mocked.analyzeCover).toHaveBeenLastCalledWith(UPLOAD_RESULT.audio_path, 'model-b');
      },
      { timeout: 2000 },
    );

    // 手改值不被覆盖
    expect((screen.getByTestId('cover-transpose-input') as HTMLInputElement).value).toBe('-5');
  });

  it('音域分析：analyze 失败静默降级，不阻塞手填 transpose', async () => {
    mocked.analyzeCover.mockRejectedValue(new Error('request failed'));
    render(<CoverPanel />);
    await screen.findByTestId('cover-model-select');

    fireEvent.change(screen.getByTestId('cover-upload-input'), { target: { files: [makeAudioFile()] } });
    await waitFor(
      () => {
        expect(mocked.analyzeCover).toHaveBeenCalled();
      },
      { timeout: 2000 },
    );
    await waitFor(() => expect(screen.queryByTestId('cover-analyze-loading')).not.toBeInTheDocument());

    // 手填 transpose 正常生效，无崩溃、无推荐徽标
    fireEvent.change(screen.getByTestId('cover-transpose-input'), { target: { value: '-1' } });
    expect((screen.getByTestId('cover-transpose-input') as HTMLInputElement).value).toBe('-1');
    expect(screen.queryByTestId('cover-analyze-recommended')).not.toBeInTheDocument();
  });

  // ── 模式切换（双人合唱面板挂载）──

  it('模式切换：双人合唱模式渲染 DuetPanel，单人内容隐藏', async () => {
    render(<CoverPanel />);
    await screen.findByTestId('cover-model-select');
    expect(screen.queryByTestId('duet-panel')).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId('cover-mode-duet'));
    expect(screen.getByTestId('duet-panel')).toBeInTheDocument();
    expect(screen.getByTestId('duet-upload-btn')).toBeInTheDocument();
    // DuetPanel 挂载后异步加载模型列表
    expect(await screen.findByTestId('duet-model-a-select')).toBeInTheDocument();
    expect(screen.queryByTestId('cover-infer-btn')).not.toBeInTheDocument();

    // 切回单人
    fireEvent.click(screen.getByTestId('cover-mode-solo'));
    expect(screen.getByTestId('cover-infer-btn')).toBeInTheDocument();
    expect(screen.queryByTestId('duet-panel')).not.toBeInTheDocument();
  });
});
