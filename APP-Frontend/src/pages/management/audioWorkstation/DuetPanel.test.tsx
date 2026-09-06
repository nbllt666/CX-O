/**
 * DuetPanel.test.tsx — 双人合唱面板组件测试（enhance-cover-pitch-analysis-duet SubTask 4.4）
 *
 * 覆盖（voiceworkstationApi 整体打桩，不经 HTTP；轮询经 pollTask 注入，
 * 对齐 CompositionPanel 测试先例）：
 *  1. 渲染冒烟：上传通道 / 双模型下拉（含保留原声空选项）/ auto_transpose 默认开 /
 *     高级折叠默认收起 / 提交按钮（无源曲时禁用）
 *  2. 提交体断言（auto_transpose 开启）：不发送显式 transpose，未选模型与未填查询 → null
 *  3. 提交体断言（auto_transpose 关闭 + 高级参数）：请求体字段逐一核对
 *  4. 轮询 completed：pollTask 注入 → 阶段徽标 + 实际 transpose + 播放器出现
 *  5. 轮询 failed：阶段名 + 错误展示
 *  6. 提交 503（分离引擎未就绪）→ 专用提示
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import i18n from '../../../i18n';
import type { DuetTaskStatus } from '@/api/clients/voiceworkstation';

vi.mock('@/api/clients/voiceworkstation', () => ({
  voiceworkstationApi: {
    listSoVITSSVCModels: vi.fn(),
    uploadAudio: vi.fn(),
    submitDuetCover: vi.fn(),
    getDuetCoverTask: vi.fn(),
    analyzeCover: vi.fn(),
  },
  getVoiceWorkstationAudioUrl: (url: string) => `http://test-voice${url}`,
}));

import { voiceworkstationApi } from '@/api/clients/voiceworkstation';
import DuetPanel from './DuetPanel';

const mocked = vi.mocked(voiceworkstationApi);

const MODELS = [
  { name: 'model-a', path: '/models/model-a', created: 1, g_model: null, d_model: null },
  { name: 'model-b', path: '/models/model-b', created: 2, g_model: null, d_model: null },
];

const UPLOAD_RESULT = {
  status: 'success',
  filename: 'duet-song.wav',
  audio_path: 'C:/ws/data/input/duet-song.wav',
};

const SUBMIT_RESULT = { status: 'accepted', task_id: 'task-1' };

const COMPLETED_TASK: DuetTaskStatus = {
  task_id: 'task-1',
  created_at: '2026-09-06T00:00:00',
  status: 'completed',
  stage: 'done',
  progress: 1,
  stages: {
    separate: 'completed',
    split: 'completed',
    analyze: 'completed',
    svc_a: 'completed',
    svc_b: 'skipped',
    mix: 'completed',
  },
  transposes: {
    a: 2,
    b: 0,
    source: 'auto',
    source_a: 'auto',
    source_b: 'fallback',
    notes: ['B 声部未指定模型，保留原声，transpose 不生效'],
  },
  analysis: {},
  notes: ['B 声部未指定模型，保留原声'],
  error: null,
  finished_at: '2026-09-06T00:05:00',
  audio_url: '/api/audio-files/duet/task-1/final.wav',
};

const FAILED_TASK: DuetTaskStatus = {
  task_id: 'task-1',
  created_at: '2026-09-06T00:00:00',
  status: 'failed',
  stage: 'split',
  progress: 0.2,
  stages: { separate: 'completed', split: 'failed' },
  transposes: { a: 0, b: 0, source: 'fallback', source_a: 'fallback', source_b: 'fallback', notes: [] },
  analysis: {},
  notes: [],
  error: 'AudioSep split failed: checkpoint missing',
  finished_at: '2026-09-06T00:01:00',
  audio_url: null,
};

function makeAudioFile(name = 'duet-song.wav'): File {
  return new File(['fake-audio-bytes'], name, { type: 'audio/wav' });
}

describe('DuetPanel 双人合唱面板', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('zh-CN');
    mocked.listSoVITSSVCModels.mockResolvedValue({ status: 'success', models: MODELS });
    mocked.uploadAudio.mockResolvedValue(UPLOAD_RESULT);
    mocked.submitDuetCover.mockResolvedValue(SUBMIT_RESULT);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  /** 上传回填源曲路径（提交前置步骤） */
  async function uploadSource() {
    fireEvent.change(screen.getByTestId('duet-upload-input'), { target: { files: [makeAudioFile()] } });
    await waitFor(() => {
      expect(screen.getByTestId('duet-audio-path-input')).toHaveValue(UPLOAD_RESULT.audio_path);
    });
  }

  it('渲染冒烟：上传 / 双模型下拉（含保留原声）/ auto_transpose 默认开 / 高级折叠 / 提交按钮', async () => {
    render(<DuetPanel />);

    expect(await screen.findByTestId('duet-model-a-select')).toBeInTheDocument();
    expect(screen.getByTestId('duet-model-b-select')).toBeInTheDocument();
    // 两个模型下拉均含「保留原声」空选项与后端模型项（每下拉一份）
    expect(screen.getAllByRole('option', { name: '保留原声' })).toHaveLength(2);
    expect(screen.getAllByRole('option', { name: 'model-a' })).toHaveLength(2);

    // auto_transpose 默认开 → 手输 transpose 隐藏
    const autoToggle = screen.getByTestId('duet-auto-transpose-toggle') as HTMLInputElement;
    expect(autoToggle.checked).toBe(true);
    expect(screen.queryByTestId('duet-transpose-a-input')).not.toBeInTheDocument();

    // 高级折叠默认收起 → 查询/增益输入隐藏
    expect(screen.queryByTestId('duet-query-a-input')).not.toBeInTheDocument();
    expect(screen.queryByTestId('duet-gain-a-input')).not.toBeInTheDocument();

    // 提交按钮存在；无源曲时禁用
    const submitBtn = screen.getByTestId('duet-submit-btn') as HTMLButtonElement;
    expect(submitBtn).toBeDisabled();

    // 上传后启用
    await uploadSource();
    expect(screen.getByTestId('duet-submit-btn')).not.toBeDisabled();
  });

  it('提交体断言（auto_transpose 开启）：不发送显式 transpose，未选模型/未填查询 → null', async () => {
    render(<DuetPanel pollTask={vi.fn()} pollIntervalMs={10} />);
    await screen.findByTestId('duet-model-a-select');
    await uploadSource();

    fireEvent.click(screen.getByTestId('duet-submit-btn'));

    await waitFor(() => {
      expect(mocked.submitDuetCover).toHaveBeenCalledTimes(1);
    });
    expect(mocked.submitDuetCover).toHaveBeenCalledWith({
      audio_path: UPLOAD_RESULT.audio_path,
      model_a: null,
      model_b: null,
      auto_transpose: true,
      transpose_a: null,
      transpose_b: null,
      query_a: null,
      query_b: null,
      gain_a: 1,
      gain_b: 1,
      accompaniment_gain: 0.8,
    });
  });

  it('提交体断言（auto_transpose 关闭 + 高级参数）：请求体字段逐一核对', async () => {
    render(<DuetPanel pollTask={vi.fn()} pollIntervalMs={10} />);
    await screen.findByTestId('duet-model-a-select');
    await uploadSource();

    // 双模型选择
    fireEvent.change(screen.getByTestId('duet-model-a-select'), { target: { value: MODELS[0].path } });
    fireEvent.change(screen.getByTestId('duet-model-b-select'), { target: { value: MODELS[1].path } });

    // 关闭 auto_transpose → 手输 transpose
    fireEvent.click(screen.getByTestId('duet-auto-transpose-toggle'));
    expect(screen.getByTestId('duet-transpose-a-input')).toBeInTheDocument();
    fireEvent.change(screen.getByTestId('duet-transpose-a-input'), { target: { value: '-3' } });
    fireEvent.change(screen.getByTestId('duet-transpose-b-input'), { target: { value: '5' } });

    // 高级折叠展开 → 查询描述 + 增益
    fireEvent.click(screen.getByTestId('duet-advanced-toggle'));
    fireEvent.change(screen.getByTestId('duet-query-a-input'), { target: { value: 'male lead vocal' } });
    fireEvent.change(screen.getByTestId('duet-gain-a-input'), { target: { value: '1.2' } });
    fireEvent.change(screen.getByTestId('duet-accompaniment-gain-input'), { target: { value: '0.6' } });

    fireEvent.click(screen.getByTestId('duet-submit-btn'));

    await waitFor(() => {
      expect(mocked.submitDuetCover).toHaveBeenCalledTimes(1);
    });
    expect(mocked.submitDuetCover).toHaveBeenCalledWith({
      audio_path: UPLOAD_RESULT.audio_path,
      model_a: MODELS[0].path,
      model_b: MODELS[1].path,
      auto_transpose: false,
      transpose_a: -3,
      transpose_b: 5,
      query_a: 'male lead vocal',
      query_b: null,
      gain_a: 1.2,
      gain_b: 1,
      accompaniment_gain: 0.6,
    });
  });

  it('轮询 completed：阶段徽标 + 实际 transpose + 播放器出现', async () => {
    // 注入 pollTask 立即返回 completed（对齐 CompositionPanel 测试先例）
    const pollTask = vi.fn().mockResolvedValue(COMPLETED_TASK);
    render(<DuetPanel pollTask={pollTask} pollIntervalMs={10} />);
    await screen.findByTestId('duet-model-a-select');
    await uploadSource();

    fireEvent.click(screen.getByTestId('duet-submit-btn'));

    await waitFor(() => {
      expect(mocked.submitDuetCover).toHaveBeenCalledTimes(1);
    });

    // 任务块出现 → 轮询返回 completed → 六阶段徽标（含 skipped）与实际 transpose
    expect(await screen.findByTestId('duet-task')).toBeInTheDocument();
    expect(screen.getByTestId('duet-stage-mix')).toHaveAttribute('data-status', 'completed');
    expect(screen.getByTestId('duet-stage-svc_b')).toHaveAttribute('data-status', 'skipped');
    expect(screen.getByTestId('duet-transposes')).toHaveTextContent('2 / 0');

    // 成品播放器出现，src 指向 duet final.wav（经 getVoiceWorkstationAudioUrl 拼接）
    const player = await screen.findByTestId('duet-audio-player');
    expect(player).toHaveAttribute('src', `http://test-voice${COMPLETED_TASK.audio_url}`);
  });

  it('轮询 failed：展示阶段名 + 错误，且无播放器', async () => {
    const pollTask = vi.fn().mockResolvedValue(FAILED_TASK);
    render(<DuetPanel pollTask={pollTask} pollIntervalMs={10} />);
    await screen.findByTestId('duet-model-a-select');
    await uploadSource();

    fireEvent.click(screen.getByTestId('duet-submit-btn'));

    const errorEl = await screen.findByTestId('duet-task-error');
    expect(errorEl).toHaveTextContent('[split]');
    expect(errorEl).toHaveTextContent('AudioSep split failed');
    expect(screen.queryByTestId('duet-audio-player')).not.toBeInTheDocument();
  });

  it('提交 503（分离引擎未就绪）→ 展示 setup 指引专用提示', async () => {
    mocked.submitDuetCover.mockRejectedValue(
      new Error(
        '请求失败: 分离引擎未就绪（engines/demucs 或 engines/AudioSep 缺失）。请执行 python tools/setup_separation.py --clone 克隆引擎',
      ),
    );
    render(<DuetPanel />);
    await screen.findByTestId('duet-model-a-select');
    await uploadSource();

    fireEvent.click(screen.getByTestId('duet-submit-btn'));

    expect(await screen.findByTestId('duet-separation-unavailable')).toBeInTheDocument();
    expect(screen.queryByTestId('duet-task')).not.toBeInTheDocument();
  });
});
