/**
 * voiceworkstation 域客户端：音频工作站统一客户端。
 * 端点面对齐 CX-O-Frontend clients/voiceworkstation.ts：
 * - VoxCPM：/api/voxcpm/generate、/status、/batch-dataset[/{task_id}]
 * - So-VITS-SVC：/api/sovits-svc/preprocess、/train、/stop、/status、/models、/infer、/datasets CRUD
 * - 音乐：/api/music/score/validate、/import-musicxml、/synthesize、/tasks/{id}、/songs[/{id}]
 * - 参考音频：/api/ref-audio/pregenerate、/export-zip、/import-zip、/status
 * - Orpheus TTS：/api/orpheus/synthesize、/synthesize-stream、/status
 *
 * 契约要点：
 * - pregenerate 为异步任务，需轮询 GET /api/ref-audio/status
 * - orpheus 流式返回裸 PCM（24kHz/16-bit/mono），前端补 WAV 头
 */
import { getVoiceWsClient, getVoiceWorkstationUrl, STORAGE_KEYS, voiceWorkstationRequest } from '../base';

// ── 公共类型 ──

/** 生成/推理统一响应契约：文件名 + 可播放 URL（相对路径，需拼 VoiceWorkStation base） */
export interface VoiceWsAudioResult {
  status: string;
  output_filename: string;
  audio_url: string;
}

// ── VoxCPM ──

export type VoxCPMMode = 'design' | 'controllable_clone' | 'ultimate_clone';

export interface VoxCPMGenerateRequest {
  mode: VoxCPMMode;
  text: string;
  control?: string;
  reference_audio_path?: string;
  prompt_audio_path?: string;
  prompt_text?: string;
  cfg_value?: number;
  inference_timesteps?: number;
}

export interface VoxCPMStatus {
  status: string; // healthy / unhealthy
  model_path: string;
}

export interface BatchDatasetTextItem {
  text: string;
  control?: string;
}

export type BatchDatasetEngine = 'f5tts' | 'orpheustts' | 'voxcpm';

export interface BatchDatasetRequest {
  speaker_name: string;
  texts: BatchDatasetTextItem[];
  mode?: VoxCPMMode;
  engine?: BatchDatasetEngine;
  control?: string;
  reference_audio_path?: string;
  prompt_audio_path?: string;
  prompt_text?: string;
  cfg_value?: number;
  inference_timesteps?: number;
}

export interface BatchDatasetTask {
  task_id: string;
  speaker_name: string;
  dataset_dir: string;
  mode: string;
  engine: string;
  status: string; // pending / running / completed / failed
  total: number;
  done: number;
  skipped: number;
  failed: number;
  current_text: string | null;
  error: string | null;
  failures: { index: number; text: string; error: string }[];
  created_at: string;
  finished_at: string | null;
}

// ── So-VITS-SVC ──

export interface SVCModel {
  name: string;
  path: string;
  created: number;
  g_model: string | null;
  d_model: string | null;
}

export interface SVCTrainStatus {
  task_id: string | null;
  status: string; // idle / running / stopped / completed / failed
  progress: number;
  epoch: number;
  total_epochs: number;
  message: string;
  models: SVCModel[];
}

export interface SVCPreprocessRequest {
  training_data_dir: string;
  speaker_name: string;
}

export interface SVCTrainRequest {
  training_data_dir?: string;
  epochs: number;
  batch_size: number;
  learning_rate: number;
  output_name?: string;
}

export interface SVCInferRequest {
  audio_path: string;
  model_path?: string;
  speaker_id?: number;
  transpose?: number;
  cluster_model_path?: string;
}

export interface SVCDataset {
  name: string;
  file_count: number;
  total_size_bytes: number;
  created_at: string;
  has_manifest: boolean;
}

// ── 音乐 ──

export interface ScoreValidateResponse {
  valid: boolean;
  errors: string[];
  score?: Record<string, unknown>;
}

export interface MusicSynthesizeRequest {
  score: Record<string, unknown>;
  voice_bank?: string;
  svc_model?: string;
  speaker_id?: number;
  transpose?: number;
  vocal_gain?: number;
  accompaniment_gain?: number;
}

export interface SongStep {
  name: string;
  status: string; // pending / running / completed / failed / skipped
  error: string | null;
}

export interface SongTask {
  song_id: string;
  title: string;
  status: string; // pending / running / completed / failed
  stage: string;
  progress: number;
  error: string | null;
  created_at: string;
  finished_at: string | null;
  steps?: SongStep[];
  files?: Record<string, string>;
  audio_url: string | null;
}

export interface SongSummary {
  song_id: string;
  title: string;
  status: string;
  stage: string;
  progress: number;
  error: string | null;
  created_at: string;
  finished_at: string | null;
  audio_url: string | null;
}

// ── 参考音频 ──

export type RefAudioMode = 'clone' | 'design';

export interface PregenerateRefsRequest {
  base_audio_path: string;
  sample_text?: string;
  transition_text?: string;
  force?: boolean;
  mode?: RefAudioMode;
  ultimate_clone?: boolean;
}

export interface PregenerateRefsResult {
  emotions: number;
  transitions: number;
  total: number;
  skipped: boolean;
}

export interface ImportEmotionRefsResponse {
  status: string;
  meta: {
    emotions: Array<{ file: string; emotion: string; text: string; instruct_text: string }>;
    transitions: Array<{
      file: string;
      from_emotion: string;
      to_emotion: string;
      text: string;
      instruct_text: string;
    }>;
  };
}

export interface RefAudioProgress {
  current: number;
  total: number;
  message: string;
}

export interface RefAudioStatus {
  is_running: boolean;
  progress: RefAudioProgress | null;
  result: PregenerateRefsResult | null;
  error: string | null;
}

// ── Orpheus TTS ──

export interface OrpheusSynthesizeRequest {
  text: string;
  voice?: string;
}

export interface OrpheusSynthesizeResult {
  status: string;
  audio_url: string;
  format: string;
}

export interface OrpheusStatus {
  status: string; // healthy / unhealthy
  url: string;
  voice: string;
}

/**
 * 将后端返回的相对 audio_url 拼接为可播放的完整 URL。
 */
export function getVoiceWorkstationAudioUrl(audioUrl: string): string {
  if (/^https?:\/\//.test(audioUrl)) return audioUrl;
  const base = getVoiceWorkstationUrl().replace(/\/$/, '');
  return `${base}${audioUrl.startsWith('/') ? '' : '/'}${audioUrl}`;
}

/**
 * 构造 44 字节 PCM WAV header。
 * Orpheus 流式端点返回 24000Hz、16-bit、mono 裸 PCM（后端已剥离 WAV 头），
 * 前端需自行补头后才能交由 <audio> 播放。
 */
function buildWavBlob(pcm: Uint8Array, sampleRate = 24000, numChannels = 1, bitsPerSample = 16): Blob {
  const byteRate = (sampleRate * numChannels * bitsPerSample) / 8;
  const blockAlign = (numChannels * bitsPerSample) / 8;
  const dataSize = pcm.byteLength;
  const buffer = new ArrayBuffer(44 + dataSize);
  const view = new DataView(buffer);

  const writeString = (offset: number, str: string) => {
    for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i));
  };

  writeString(0, 'RIFF');
  view.setUint32(4, 36 + dataSize, true);
  writeString(8, 'WAVE');
  writeString(12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, numChannels, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, byteRate, true);
  view.setUint16(32, blockAlign, true);
  view.setUint16(34, bitsPerSample, true);
  writeString(36, 'data');
  view.setUint32(40, dataSize, true);

  new Uint8Array(buffer, 44).set(pcm);
  return new Blob([buffer], { type: 'audio/wav' });
}

export const voiceworkstationApi = {
  // ── VoxCPM ──

  generateVoxCPM(data: VoxCPMGenerateRequest): Promise<VoiceWsAudioResult> {
    return voiceWorkstationRequest<VoiceWsAudioResult>({ url: '/api/voxcpm/generate', method: 'POST', data });
  },

  getVoxCPMStatus(): Promise<VoxCPMStatus> {
    return voiceWorkstationRequest<VoxCPMStatus>({ url: '/api/voxcpm/status' });
  },

  submitVoxCPMBatchDataset(data: BatchDatasetRequest): Promise<{ status: string; task_id: string; total: number }> {
    return voiceWorkstationRequest({ url: '/api/voxcpm/batch-dataset', method: 'POST', data });
  },

  getVoxCPMBatchDatasetTask(taskId: string): Promise<BatchDatasetTask> {
    return voiceWorkstationRequest<BatchDatasetTask>({
      url: `/api/voxcpm/batch-dataset/${encodeURIComponent(taskId)}`,
    });
  },

  // ── So-VITS-SVC ──

  sovitsSVCPreprocess(data: SVCPreprocessRequest): Promise<{ status: string; results: Record<string, unknown> }> {
    return voiceWorkstationRequest({ url: '/api/sovits-svc/preprocess', method: 'POST', data });
  },

  startSoVITSSVCTrain(data: SVCTrainRequest): Promise<{ status: string; task_id: string; message: string }> {
    return voiceWorkstationRequest({ url: '/api/sovits-svc/train', method: 'POST', data });
  },

  stopSoVITSSVCTrain(): Promise<{ status: string; message: string }> {
    return voiceWorkstationRequest({ url: '/api/sovits-svc/stop', method: 'POST' });
  },

  getSoVITSSVCStatus(): Promise<SVCTrainStatus> {
    return voiceWorkstationRequest<SVCTrainStatus>({ url: '/api/sovits-svc/status' });
  },

  listSoVITSSVCModels(): Promise<{ status: string; models: SVCModel[] }> {
    return voiceWorkstationRequest({ url: '/api/sovits-svc/models' });
  },

  sovitsSVCInfer(data: SVCInferRequest): Promise<VoiceWsAudioResult> {
    return voiceWorkstationRequest<VoiceWsAudioResult>({ url: '/api/sovits-svc/infer', method: 'POST', data });
  },

  // ── SVC 数据集管理 ──

  listSVCDatasets(): Promise<{ status: string; datasets: SVCDataset[] }> {
    return voiceWorkstationRequest({ url: '/api/sovits-svc/datasets' });
  },

  async importSVCDataset(speakerName: string, files: File[]): Promise<{
    status: string;
    name: string;
    imported: number;
    files: string[];
    skipped: string[];
  }> {
    const formData = new FormData();
    formData.append('speaker_name', speakerName);
    files.forEach((f) => formData.append('files', f));
    const response = await getVoiceWsClient().post<{
      status: string;
      name: string;
      imported: number;
      files: string[];
      skipped: string[];
    }>('/api/sovits-svc/datasets/import', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return response.data;
  },

  deleteSVCDataset(speakerName: string): Promise<{ status: string; message: string }> {
    return voiceWorkstationRequest({
      url: `/api/sovits-svc/datasets/${encodeURIComponent(speakerName)}`,
      method: 'DELETE',
    });
  },

  // ── 音乐 ──

  musicValidateScore(score: Record<string, unknown>): Promise<ScoreValidateResponse> {
    return voiceWorkstationRequest<ScoreValidateResponse>({
      url: '/api/music/score/validate',
      method: 'POST',
      data: score,
    });
  },

  async musicImportMusicXML(file: File): Promise<Record<string, unknown>> {
    const formData = new FormData();
    formData.append('file', file);
    const response = await getVoiceWsClient().post<Record<string, unknown>>(
      '/api/music/import-musicxml',
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' } },
    );
    return response.data;
  },

  musicSynthesize(data: MusicSynthesizeRequest): Promise<{ song_id: string; status: string }> {
    return voiceWorkstationRequest({ url: '/api/music/synthesize', method: 'POST', data });
  },

  musicGetTask(songId: string): Promise<SongTask> {
    return voiceWorkstationRequest<SongTask>({ url: `/api/music/tasks/${encodeURIComponent(songId)}` });
  },

  musicListSongs(): Promise<{ songs: SongSummary[] }> {
    return voiceWorkstationRequest<{ songs: SongSummary[] }>({ url: '/api/music/songs' });
  },

  musicGetSong(songId: string): Promise<SongTask> {
    return voiceWorkstationRequest<SongTask>({ url: `/api/music/songs/${encodeURIComponent(songId)}` });
  },

  musicDeleteSong(songId: string): Promise<{ status: string; song_id: string }> {
    return voiceWorkstationRequest({
      url: `/api/music/songs/${encodeURIComponent(songId)}`,
      method: 'DELETE',
    });
  },

  // ── 参考音频 ──

  pregenerateRefs(data: PregenerateRefsRequest): Promise<{ status: string; result: PregenerateRefsResult }> {
    return voiceWorkstationRequest({ url: '/api/ref-audio/pregenerate', method: 'POST', data });
  },

  async exportEmotionRefsZip(data: PregenerateRefsRequest): Promise<Blob> {
    const response = await getVoiceWsClient().post('/api/ref-audio/export-zip', data, {
      responseType: 'arraybuffer',
    });
    return new Blob([response.data], { type: 'application/zip' });
  },

  async importEmotionRefsZip(file: File): Promise<ImportEmotionRefsResponse> {
    const formData = new FormData();
    formData.append('file', file);
    const response = await getVoiceWsClient().post<ImportEmotionRefsResponse>(
      '/api/ref-audio/import-zip',
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' } },
    );
    return response.data;
  },

  /** 参考音频预生成是异步任务，提交后需轮询本方法获取进度与结果 */
  getRefAudioStatus(): Promise<RefAudioStatus> {
    return voiceWorkstationRequest<RefAudioStatus>({ url: '/api/ref-audio/status' });
  },

  // ── Orpheus TTS ──

  /** 非流式合成：落盘 WAV，返回 audio_url（相对路径，经 getVoiceWorkstationAudioUrl 拼接播放） */
  synthesizeOrpheus(data: OrpheusSynthesizeRequest): Promise<OrpheusSynthesizeResult> {
    return voiceWorkstationRequest<OrpheusSynthesizeResult>({
      url: '/api/orpheus/synthesize',
      method: 'POST',
      data,
    });
  },

  /**
   * 流式合成：逐块读取裸 PCM（24000Hz/16-bit/mono），补 WAV 头后返回可播放 Blob。
   * 使用原生 fetch 读取 ReadableStream；token 与 axios 拦截器保持一致来源（localStorage）。
   */
  async synthesizeOrpheusStream(
    data: OrpheusSynthesizeRequest,
    onProgress?: (receivedBytes: number) => void,
  ): Promise<Blob> {
    const base = getVoiceWorkstationUrl().replace(/\/$/, '');
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    const token = localStorage.getItem(STORAGE_KEYS.token);
    if (token) headers.Authorization = `Bearer ${token}`;

    const response = await fetch(`${base}/api/orpheus/synthesize-stream`, {
      method: 'POST',
      headers,
      body: JSON.stringify(data),
    });

    if (!response.ok || !response.body) {
      let detail = `HTTP ${response.status}`;
      try {
        const text = await response.text();
        if (text) detail += `: ${text.slice(0, 200)}`;
      } catch {
        // 忽略读取错误体失败
      }
      throw new Error(`Orpheus 流式合成失败: ${detail}`);
    }

    const reader = response.body.getReader();
    const chunks: Uint8Array[] = [];
    let received = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      if (value && value.length > 0) {
        chunks.push(value);
        received += value.length;
        onProgress?.(received);
      }
    }

    const merged = new Uint8Array(received);
    let offset = 0;
    for (const c of chunks) {
      merged.set(c, offset);
      offset += c.length;
    }
    return buildWavBlob(merged);
  },

  getOrpheusStatus(): Promise<OrpheusStatus> {
    return voiceWorkstationRequest<OrpheusStatus>({ url: '/api/orpheus/status' });
  },
};
