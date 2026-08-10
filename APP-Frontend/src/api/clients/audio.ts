/**
 * audio 域客户端：音频配置 / 音频文件 / TTS / ASR / 上传。
 * 端点面对齐 CX-O-Frontend clients/audio.ts。
 */
import { getApiBaseUrl, getHttpClient, request } from '../base';

export interface AudioFileInfo {
  name: string;
  size: number;
  modified: string;
}

export const audioApi = {
  getAudioConfig(): Promise<Record<string, unknown>> {
    return request<Record<string, unknown>>({ url: '/api/audio/config' });
  },

  getAudioFiles(): Promise<{ files: AudioFileInfo[] }> {
    return request<{ files: AudioFileInfo[] }>({ url: '/api/audio/files' });
  },

  async deleteAudioFile(filename: string): Promise<void> {
    await request({ url: `/api/audio/files/${encodeURIComponent(filename)}`, method: 'delete' });
  },

  /** TTS：二进制音频返回，需 arraybuffer 响应类型 */
  async textToSpeech(text: string): Promise<Blob> {
    const response = await getHttpClient().post<ArrayBuffer>(
      '/api/tts',
      { text },
      { responseType: 'arraybuffer' },
    );
    return new Blob([response.data], { type: 'audio/mp3' });
  },

  /** ASR：multipart 上传音频 Blob，后端返回 { status, text?, message? } */
  async speechToText(audioBlob: Blob): Promise<{ text: string }> {
    const formData = new FormData();
    formData.append('file', audioBlob);
    const response = await getHttpClient().post<{
      status: string;
      text?: string;
      message?: string;
      language?: string;
    }>('/api/asr/speech-to-text', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    if (response.data.status !== 'success') {
      throw new Error(response.data.message || '语音识别失败');
    }
    return { text: response.data.text || '' };
  },

  async uploadAudioFile(file: File): Promise<{ filename: string; url: string }> {
    const formData = new FormData();
    formData.append('file', file);
    const response = await getHttpClient().post<{ filename: string; url: string }>(
      '/api/audio/upload',
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' } },
    );
    return response.data;
  },

  getAudioFileUrl(filename: string): string {
    return `${getApiBaseUrl()}/api/audio/files/${encodeURIComponent(filename)}`;
  },
};
