/**
 * voiceworkstation 域客户端：作曲/翻唱CXFC 服务客户端（VWS 8200）。
 * 端点面对齐 split-audio-workstation-cxfc-modelstation 瘦身后的服务边界：
 * - 受控上传：POST /api/audio-uploads（翻唱音频入口，multipart 字段 file）
 * - So-VITS-SVC：/api/sovits-svc/models（只读）、/api/sovits-svc/infer（翻唱变声）
 * - 音乐：/api/music/score/validate、/import-musicxml、/synthesize、/tasks/{id}、/songs[/{id}]
 * - 翻唱音域分析（enhance-cover-pitch-analysis-duet）：/api/cover/analyze、/api/cover/model-profiles
 * - 双人合唱（enhance-cover-pitch-analysis-duet）：/api/cover/duet[/{task_id}]
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

// ── 翻唱音域分析（enhance-cover-pitch-analysis-duet）──

/** 源音频人声音域画像（POST /api/cover/analyze 的 profile；后端 VoiceProfile.to_dict()） */
export interface VoiceProfile {
  f0_median_hz: number;
  f0_median_midi: number;
  range_low_midi: number;
  range_high_midi: number;
  range_span_semitones: number;
  voiced_ratio: number;
}

/** 模型音域画像（voice_profile_store PROFILE_KEYS 冻结契约：get_profile/list_profiles 条目） */
export interface CoverModelProfile {
  speaker_name: string;
  f0_median_hz: number;
  f0_median_midi: number;
  range_low_midi: number;
  range_high_midi: number;
  range_span_semitones: number;
  sample_count: number;
  dataset_md5: string;
  computed_at: string;
}

/** POST /api/cover/analyze 响应：源 profile +（给 model_name 且画像可算时）推荐转调与音域对比 */
export interface CoverAnalyzeResult {
  status: string;
  audio_path: string;
  separation_used: boolean;
  profile: VoiceProfile;
  model_name?: string;
  target_profile?: CoverModelProfile;
  recommended_transpose?: number;
  range_warning?: string;
  profile_unavailable?: string;
}

/** GET /api/cover/model-profiles 响应 */
export interface CoverModelProfilesResult {
  status: string;
  profiles: CoverModelProfile[];
}

// ── 双人合唱（enhance-cover-pitch-analysis-duet）──

/** POST /api/cover/duet 请求体（api/duet.py DuetCreateRequest 对齐；模型可空=该声部保留原声） */
export interface DuetSubmitRequest {
  audio_path: string;
  model_a?: string | null;
  model_b?: string | null;
  transpose_a?: number | null;
  transpose_b?: number | null;
  auto_transpose?: boolean;
  query_a?: string | null;
  query_b?: string | null;
  gain_a?: number;
  gain_b?: number;
  accompaniment_gain?: number;
}

/** POST /api/cover/duet 响应（202 Accepted） */
export interface DuetSubmitResult {
  status: string;
  task_id: string;
}

/** GET /api/cover/duet/{task_id} 响应（duet_pipeline 任务记录契约） */
export interface DuetTaskStatus {
  task_id: string;
  created_at: string;
  status: string; // pending / running / completed / failed
  stage: string; // pending / separate / split / analyze / svc_a / svc_b / mix / done
  progress: number;
  stages: Record<string, string>; // 阶段名 → pending / running / completed / skipped / failed
  transposes: {
    a: number;
    b: number;
    source: string; // auto / explicit / fallback
    source_a: string;
    source_b: string;
    notes: string[];
  };
  analysis: { a?: VoiceProfile; b?: VoiceProfile };
  notes: string[];
  error: string | null;
  finished_at: string | null;
  params?: Record<string, unknown>;
  files?: Record<string, string>;
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

  // ── 翻唱音域分析（enhance-cover-pitch-analysis-duet）──

  /** POST /api/cover/analyze：源音频人声音域分析 +（给 modelName 时）对照模型画像的推荐转调 */
  analyzeCover(audioPath: string, modelName?: string): Promise<CoverAnalyzeResult> {
    return voiceWorkstationRequest<CoverAnalyzeResult>({
      url: '/api/cover/analyze',
      method: 'POST',
      data: { audio_path: audioPath, model_name: modelName?.trim() || null },
    });
  },

  /** GET /api/cover/model-profiles：全部模型音域画像列表 */
  listCoverModelProfiles(): Promise<CoverModelProfilesResult> {
    return voiceWorkstationRequest<CoverModelProfilesResult>({ url: '/api/cover/model-profiles' });
  },

  // ── 双人合唱（enhance-cover-pitch-analysis-duet）──

  /** POST /api/cover/duet：提交双人合唱任务（202，返回 task_id 异步执行） */
  submitDuetCover(data: DuetSubmitRequest): Promise<DuetSubmitResult> {
    return voiceWorkstationRequest<DuetSubmitResult>({ url: '/api/cover/duet', method: 'POST', data });
  },

  /** GET /api/cover/duet/{taskId}：任务状态/阶段/进度/实际 transpose/错误 */
  getDuetCoverTask(taskId: string): Promise<DuetTaskStatus> {
    return voiceWorkstationRequest<DuetTaskStatus>({
      url: `/api/cover/duet/${encodeURIComponent(taskId)}`,
    });
  },
};
