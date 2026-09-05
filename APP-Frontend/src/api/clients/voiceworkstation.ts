/**
 * voiceworkstation 域客户端：作曲/翻唱CXFC 服务客户端（VWS 8200）。
 * 端点面对齐 split-audio-workstation-cxfc-modelstation 瘦身后的服务边界：
 * - 受控上传：POST /api/audio-uploads（翻唱音频入口，multipart 字段 file）
 * - So-VITS-SVC：/api/sovits-svc/models（只读）、/api/sovits-svc/infer（翻唱变声）
 * - 音乐：/api/music/score/validate、/import-musicxml、/synthesize、/tasks/{id}、/songs[/{id}]
 *
 * 说明：训练域（preprocess/train/stop/status/datasets/voxcpm batch-dataset/workflow）
 * 已整体迁至 CXO-ModelStation（8300），由模型工作站独立前端承接，本客户端不再提供。
 */
import { getVoiceWsClient, getVoiceWorkstationUrl, voiceWorkstationRequest } from '../base';

// ── 公共类型 ──

/** 生成/推理统一响应契约：文件名 + 可播放 URL（相对路径，需拼 VoiceWorkStation base） */
export interface VoiceWsAudioResult {
  status: string;
  output_filename: string;
  audio_url: string;
}

// ── 受控上传 ──

/** POST /api/audio-uploads 响应：audio_path 为落盘绝对路径，可直接作为 infer 的 audio_path 入参 */
export interface AudioUploadResult {
  status: string;
  filename: string;
  audio_path: string;
}

// ── So-VITS-SVC ──

export interface SVCModel {
  name: string;
  path: string;
  created: number;
  g_model: string | null;
  d_model: string | null;
}

export interface SVCInferRequest {
  audio_path: string;
  model_path?: string;
  speaker_id?: number;
  transpose?: number;
  cluster_model_path?: string;
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
  // ── 受控上传 ──

  /** 本地音频上传（multipart 字段 file），落盘 infer 白名单根，返回 audio_path 可直接推理 */
  async uploadAudio(file: File): Promise<AudioUploadResult> {
    const formData = new FormData();
    formData.append('file', file);
    const response = await getVoiceWsClient().post<AudioUploadResult>('/api/audio-uploads', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return response.data;
  },

  // ── So-VITS-SVC（只读模型列表 + 翻唱推理）──

  listSoVITSSVCModels(): Promise<{ status: string; models: SVCModel[] }> {
    return voiceWorkstationRequest({ url: '/api/sovits-svc/models' });
  },

  sovitsSVCInfer(data: SVCInferRequest): Promise<VoiceWsAudioResult> {
    return voiceWorkstationRequest<VoiceWsAudioResult>({ url: '/api/sovits-svc/infer', method: 'POST', data });
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
