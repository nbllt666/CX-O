/**
 * ApiClient mixin: Audio domain operations.
 * Extracted from client.ts as part of M16 split.
 */
import { _ApiClientBase, getApiBaseUrl } from './_common';

export class _AudioClientMixin extends _ApiClientBase {
  async getAudioConfig(): Promise<Record<string, unknown>> {
    return this.request<Record<string, unknown>>({ url: '/api/audio/config' });
  }

  async getAudioFiles(): Promise<{ files: { name: string; size: number; modified: string }[] }> {
    return this.request<{ files: { name: string; size: number; modified: string }[] }>({ url: '/api/audio/files' });
  }

  async deleteAudioFile(filename: string): Promise<void> {
    await this.request({ url: `/api/audio/files/${filename}`, method: 'delete' });
  }

  async textToSpeech(text: string): Promise<Blob> {
    // BUG-F48: 单独走 axios 配置 responseType: 'arraybuffer'，确保返回正确的二进制数据
    const axiosInstance = this.client;
    const response = await axiosInstance.post<ArrayBuffer>(
      '/api/tts',
      { text },
      { responseType: 'arraybuffer' }
    );
    return new Blob([response.data], { type: 'audio/mp3' });
  }

  async speechToText(audioBlob: Blob): Promise<{ text: string }> {
    const formData = new FormData();
    formData.append('file', audioBlob);

    const axiosInstance = this.client;
    const response = await axiosInstance.post<{ status: string; text?: string; message?: string; language?: string }>(
      '/api/asr/speech-to-text',
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' } },
    );
    if (response.data.status !== 'success') {
      throw new Error(response.data.message || '语音识别失败');
    }
    return { text: response.data.text || '' };
  }

  async uploadAudioFile(file: File): Promise<{ filename: string; url: string }> {
    const formData = new FormData();
    formData.append('file', file);

    const axiosInstance = this.client;
    const response = await axiosInstance.post<{ filename: string; url: string }>('/api/audio/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return response.data;
  }

  getAudioFileUrl(filename: string): string {
    return `${getApiBaseUrl()}/api/audio/files/${filename}`;
  }
}