/**
 * voiceworkstation 域客户端：音频工作站统一客户端。
 * 端点面对齐 CX-O-Frontend clients/voiceworkstation.ts：
 * - VoxCPM：/api/voxcpm/batch-dataset[/{task_id}]（批量 SVC 训练数据生成）
 * - So-VITS-SVC：/api/sovits-svc/preprocess、/train、/stop、/status、/models、/infer、/datasets CRUD
 * - 音乐：/api/music/score/validate、/import-musicxml、/synthesize、/tasks/{id}、/songs[/{id}]
 *
 * 说明：F5-TTS / Orpheus 引擎已随 Qwen3 TTS 迁移移除；VoxCPM 单条参考音频生成
 * 亦随 Task 7 移除，仅保留 voxcpm 批量数据集引擎。
 */
import { getVoiceWsClient, getVoiceWorkstationUrl, voiceWorkstationRequest } from '../base';

// ── 公共类型 ──

/** 生成/推理统一响应契约：文件名 + 可播放 URL（相对路径，需拼 VoiceWorkStation base） */
export interface VoiceWsAudioResult {
  status: string;
  output_filename: string;
  audio_url: string;
}

// ── VoxCPM 批量数据集 ──

export interface BatchDatasetTextItem {
  text: string;
  control?: string;
}

/** 批量数据集生成的 VoxCPM 模式（单条参考音频生成已随 Task 7 移除） */
export type VoxCPMBatchMode = 'design' | 'controllable_clone' | 'ultimate_clone';

export interface BatchDatasetRequest {
  speaker_name: string;
  texts: BatchDatasetTextItem[];
  mode?: VoxCPMBatchMode;
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
// F5-TTS / Orpheus 与情感参考音频批量生成已随 Qwen3 TTS 迁移移除；
// 参考音频统一由主后端 /api/ref-audio-assets（audioApi）管理，VoiceWorkStation 不再提供生成端点。

/** 将后端返回的相对 audio_url 拼接为可播放的完整 URL。 */
export function getVoiceWorkstationAudioUrl(audioUrl: string): string {
  if (/^https?:\/\//.test(audioUrl)) return audioUrl;
  const base = getVoiceWorkstationUrl().replace(/\/$/, '');
  return `${base}${audioUrl.startsWith('/') ? '' : '/'}${audioUrl}`;
}

export const voiceworkstationApi = {
  // ── VoxCPM 批量数据集 ──

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
};
