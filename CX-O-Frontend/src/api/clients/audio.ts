/**
 * ApiClient mixin: Audio domain operations.
 * Extracted from client.ts as part of M16 split.
 */
import type { _ApiClientBase } from './_common';
import { getApiBaseUrl } from './_common';

// Declaration merging: let TypeScript know _AudioClientMixin can access _ApiClientBase's methods
export interface _AudioClientMixin extends _ApiClientBase {}

export class _AudioClientMixin {
  async getAudioConfig(): Promise<Record<string, unknown>> {
    return this.request<Record<string, unknown>>({ url: '/api/audio/config' });
  }

  async getAudioFiles(): Promise<{ files: { name: string; size: number; modified: string }[] }> {
    return this.request<{ files: { name: string; size: number; modified: string }[] }>({ url: '/api/audio/files' });
  }

  async deleteAudioFile(filename: string): Promise<void> {
    await this.request({ url: `/api/audio/files/${filename}`, method: 'delete' });
  }

  async pregenerateRefs(data: {
    base_audio_path: string;
    sample_text?: string;
    transition_text?: string;
  }): Promise<{
    status: string;
    emotions_count: number;
    transitions_count: number;
    total: number;
  }> {
    return this.voiceWorkstationRequest<{
      status: string;
      emotions_count: number;
      transitions_count: number;
      total: number;
    }>({
      url: '/pregenerate-refs',
      method: 'POST',
      data,
    });
  }

  async importEmotionRefsZip(file: File): Promise<{
    status: string;
    meta: {
      emotions: Array<{ file: string; emotion: string; text: string; instruct_text: string }>;
      transitions: Array<{ file: string; from_emotion: string; to_emotion: string; text: string; instruct_text: string }>;
    };
  }> {
    const formData = new FormData();
    formData.append('file', file);
    const axiosInstance = this.voiceWorkstationClient;
    const response = await axiosInstance.post('/api/ref-audio/import-zip', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return response.data;
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
    formData.append('audio', audioBlob);

    const axiosInstance = this.client;
    const response = await axiosInstance.post<{ text: string }>('/api/asr', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return response.data;
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