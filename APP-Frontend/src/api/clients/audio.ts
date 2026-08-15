/**
 * audio 域客户端：音频配置 / 音频文件 / TTS / ASR / 上传。
 * 端点面对齐 CX-O-Frontend clients/audio.ts。
 */
import { getApiBaseUrl, getHttpClient, request } from '../base';

/** Qwen3 参考音频资产（对应后端 ref_audio_asset.schema.json 公开形状） */
export interface RefAudioAsset {
  id: string;
  source: 'prompt' | 'file';
  prompt?: string;
  file_name?: string;
  ref_text?: string;
  checksum: string;
  format?: string;
  sample_rate?: number;
  channels?: number;
  duration_seconds?: number;
  size_bytes?: number;
  status: string;
  note?: string;
  created_at: string;
}

export const audioApi = {
  getAudioConfig(): Promise<Record<string, unknown>> {
    return request<Record<string, unknown>>({ url: '/api/audio/config' });
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

  // ── Qwen3 参考音频资产（/api/ref-audio-assets） ──

  listRefAudioAssets(): Promise<{ assets: RefAudioAsset[]; current_asset_id: string | null }> {
    return request<{ assets: RefAudioAsset[]; current_asset_id: string | null }>({ url: '/api/ref-audio-assets' });
  },

  async getCurrentRefAudioAsset(): Promise<{ asset: RefAudioAsset | null }> {
    return request<{ asset: RefAudioAsset | null }>({ url: '/api/ref-audio-assets/current' });
  },

  async setCurrentRefAudioAsset(assetId: string): Promise<{ asset: RefAudioAsset; current_asset_id: string }> {
    return request<{ asset: RefAudioAsset; current_asset_id: string }>({
      url: '/api/ref-audio-assets/current',
      method: 'put',
      data: { asset_id: assetId },
    });
  },

  async clearCurrentRefAudioAsset(): Promise<{ status: string; current_asset_id: null }> {
    return request<{ status: string; current_asset_id: null }>({
      url: '/api/ref-audio-assets/current',
      method: 'delete',
    });
  },

  async uploadRefAudioAsset(file: File, refText?: string, note?: string): Promise<{ asset: RefAudioAsset }> {
    const formData = new FormData();
    formData.append('file', file);
    if (refText) formData.append('ref_text', refText);
    if (note) formData.append('note', note);
    const response = await getHttpClient().post<{ asset: RefAudioAsset }>(
      '/api/ref-audio-assets/from-file',
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' } },
    );
    return response.data;
  },

  async generateRefAudioFromPrompt(prompt: string, language?: string): Promise<{ asset: RefAudioAsset }> {
    const response = await getHttpClient().post<{ asset: RefAudioAsset }>(
      '/api/ref-audio-assets/from-prompt',
      { prompt, language: language || undefined },
    );
    return response.data;
  },

  updateRefAudioAssetNote(assetId: string, note: string): Promise<RefAudioAsset> {
    return request<RefAudioAsset>({
      url: `/api/ref-audio-assets/${encodeURIComponent(assetId)}/note`,
      method: 'patch',
      data: { note },
    });
  },

  deleteRefAudioAsset(assetId: string): Promise<{ status: string; asset_id: string }> {
    return request<{ status: string; asset_id: string }>({
      url: `/api/ref-audio-assets/${encodeURIComponent(assetId)}`,
      method: 'delete',
    });
  },

  getRefAudioAssetAudioUrl(assetId: string): string {
    return `${getApiBaseUrl()}/api/ref-audio-assets/${encodeURIComponent(assetId)}/audio`;
  },
};
