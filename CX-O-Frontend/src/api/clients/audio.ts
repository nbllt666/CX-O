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

  async generateVoxCPM(data: {
    mode: string;
    text: string;
    control?: string;
    reference_audio_path?: string;
    prompt_audio_path?: string;
    prompt_text?: string;
  }): Promise<{ output_path: string }> {
    return this.voiceWorkstationRequest<{ output_path: string }>({
      url: '/api/voxcpm/generate',
      method: 'POST',
      data,
    });
  }

  async exportEmotionRefsZip(data: {
    base_audio_path: string;
    sample_text?: string;
    transition_text?: string;
  }): Promise<Blob> {
    const axiosInstance = this.voiceWorkstationClient;
    const response = await axiosInstance.post('/api/ref-audio/export-zip', data, {
      responseType: 'arraybuffer',
    });
    return new Blob([response.data], { type: 'application/zip' });
  }

  async sovitsSVCPreprocess(data: {
    training_data_dir: string;
    speaker_name: string;
  }): Promise<void> {
    await this.voiceWorkstationRequest({
      url: '/api/sovits-svc/preprocess',
      method: 'POST',
      data,
    });
  }

  async startSoVITSSVCTrain(data: {
    training_data_dir: string;
    model_name?: string;
    epochs: number;
    batch_size: number;
    learning_rate: number;
  }): Promise<void> {
    await this.voiceWorkstationRequest({
      url: '/api/sovits-svc/train',
      method: 'POST',
      data,
    });
  }

  async sovitsSVCInfer(data: {
    input_audio_path: string;
    ref_audio_path?: string;
  }): Promise<{ output_path: string }> {
    return this.voiceWorkstationRequest<{ output_path: string }>({
      url: '/api/sovits-svc/infer',
      method: 'POST',
      data,
    });
  }
}