import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import AudioTestPage from './AudioTestPage';
import i18n from '../../i18n';
import { audioApi } from '@/api/clients/audio';

/**
 * AudioTestPage 冒烟 + 关键交互测试（SubTask 7.4）：
 * audioApi 整体打桩；覆盖 ASR 上传识别、TTS 合成播放、非占位校验。
 */
vi.mock('@/api/clients/audio', () => ({
  audioApi: {
    speechToText: vi.fn(),
    textToSpeech: vi.fn(),
  },
}));
const mocked = vi.mocked(audioApi);

describe('AudioTestPage 音频测试页', () => {
  beforeAll(async () => {
    await i18n.changeLanguage('zh-CN');
    URL.createObjectURL = vi.fn(() => 'blob:mock-audio') as unknown as typeof URL.createObjectURL;
    URL.revokeObjectURL = vi.fn() as unknown as typeof URL.revokeObjectURL;
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('渲染 ASR 与 TTS 两区块及使用说明（非占位页）', () => {
    render(<AudioTestPage />);

    expect(screen.getByText('ASR 语音识别')).toBeInTheDocument();
    expect(screen.getByText('TTS 语音合成')).toBeInTheDocument();
    expect(screen.getByText('使用说明')).toBeInTheDocument();
    expect(screen.queryByText(/页面建设中/)).not.toBeInTheDocument();
  });

  it('上传音频文件调用 speechToText 并展示识别结果', async () => {
    mocked.speechToText.mockResolvedValue({ text: '你好，世界' });

    render(<AudioTestPage />);
    const file = new File(['data'], 'test.wav', { type: 'audio/wav' });
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });

    expect(await screen.findByText('你好，世界')).toBeInTheDocument();
    expect(mocked.speechToText).toHaveBeenCalledWith(file);
  });

  it('TTS 输入文本调用 textToSpeech 并展示内嵌播放器', async () => {
    mocked.textToSpeech.mockResolvedValue(new Blob(['audio'], { type: 'audio/mp3' }));

    render(<AudioTestPage />);
    fireEvent.change(screen.getByLabelText('TTS 语音合成'), { target: { value: '你好' } });
    fireEvent.click(screen.getByRole('button', { name: '合成语音' }));

    await waitFor(() => {
      expect(mocked.textToSpeech).toHaveBeenCalledWith('你好');
    });
    expect(await screen.findByText('合成结果：')).toBeInTheDocument();
    const audio = document.querySelector('audio');
    expect(audio).not.toBeNull();
    expect(audio?.getAttribute('src')).toContain('blob:');
  });
});
