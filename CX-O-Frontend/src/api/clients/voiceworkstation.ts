/**
 * ApiClient mixin: 音频工作站统一客户端。
 *
 * 覆盖 CX-O-VoiceWorkStation 后端全部已冻结契约端点：
 * - VoxCPM：/api/voxcpm/generate、/api/voxcpm/status、/api/voxcpm/batch-dataset[/{task_id}]
 * - So-VITS-SVC：/api/sovits-svc/preprocess、/train、/stop、/status、/models、/infer、/datasets CRUD
 * - 音乐：/api/music/score/validate、/import-musicxml、/synthesize、/tasks/{id}、/songs[/{id}]
 * - 参考音频：/api/ref-audio/pregenerate、/export-zip、/import-zip、/status（两模式 clone/design + ultimate_clone）
 * - Orpheus TTS：/api/orpheus/synthesize、/synthesize-stream、/status（情感标签原样透传）
 *
 * 契约对齐要点（spec: refactor-audiostation-engine-consolidation）：
 * - pregenerate 为异步任务，返回 { status:"running", result:null }，需轮询 GET /api/ref-audio/status
 * - pregenerate 新增 mode（clone/design，默认 clone）+ ultimate_clone（仅 clone 模式）
 * - batch-dataset 新增 engine（f5tts/orpheustts/voxcpm，默认 voxcpm），BatchDatasetTask 含 engine 字段
 * - orpheus 非流式返回 { status, audio_url, format }；流式返回裸 PCM（24kHz/16-bit/mono），前端补 WAV 头
 *
 * 历史契约对齐要点（spec: add-voicews-music-cxfc-suite）：
 * - generate / infer 响应为 { status, output_filename, audio_url }（无 output_path / base64）
 * - 训练请求字段 output_name（非 model_name）；训练状态值为 running（非 training）
 * - /api/sovits-svc/status 附带 models（{name, path, created, g_model, d_model}[]）
 * - infer 请求字段 audio_path / model_path / speaker_id / transpose / cluster_model_path
 * - pregenerate 端点为 /api/ref-audio/pregenerate（非 /pregenerate-refs）
 *
 * Spec: refactor-audiostation-engine-consolidation Task 9.5
 */
import { _ApiClientBase, getVoiceWorkstationUrl } from './_common';

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

/** 批量数据集生成引擎来源（SVC 训练数据多来源） */
export type BatchDatasetEngine = 'f5tts' | 'orpheustts' | 'voxcpm';

export interface BatchDatasetRequest {
  speaker_name: string;
  texts: BatchDatasetTextItem[];
  mode?: VoxCPMMode;
  /** 引擎来源，默认 voxcpm（向后兼容） */
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
  /** 生成该数据集所用的引擎（f5tts / orpheustts / voxcpm） */
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

/** 参考音频生成模式：clone（克隆模式，默认）/ design（提示词模式） */
export type RefAudioMode = 'clone' | 'design';

export interface PregenerateRefsRequest {
  base_audio_path: string;
  sample_text?: string;
  transition_text?: string;
  force?: boolean;
  /** 生成模式，默认 clone（向后兼容） */
  mode?: RefAudioMode;
  /** 克隆模式高级选项：极致克隆（参考音频 + 文本续写），仅 clone 模式生效 */
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
    transitions: Array<{ file: string; from_emotion: string; to_emotion: string; text: string; instruct_text: string }>;
  };
}

/** 参考音频预生成进度（GET /api/ref-audio/status 轮询返回） */
export interface RefAudioProgress {
  current: number;
  total: number;
  message: string;
}

/** 参考音频预生成异步状态 */
export interface RefAudioStatus {
  is_running: boolean;
  progress: RefAudioProgress | null;
  result: PregenerateRefsResult | null;
  error: string | null;
}

// ── Orpheus TTS ──

/** Orpheus 合成请求：text 中的 <laugh>/<giggle> 等标签原样透传 */
export interface OrpheusSynthesizeRequest {
  text: string;
  /** Orpheus 预设音色（如 tara/leo），留空用配置默认值 */
  voice?: string;
}

/** 非流式合成响应：落盘 WAV，返回 audio_url（相对路径，需拼 VoiceWorkStation base） */
export interface OrpheusSynthesizeResult {
  status: string;
  audio_url: string;
  format: string;
}

/** Orpheus 服务健康状态 */
export interface OrpheusStatus {
  status: string; // healthy / unhealthy
  url: string;
  voice: string;
}

/**
 * 将后端返回的相对 audio_url 拼接为可播放的完整 URL。
 * 开发态 base 为 /voice-station（vite 代理），生产态为 VoiceWorkStation 直连地址。
 */
export function getVoiceWorkstationAudioUrl(audioUrl: string): string {
  if (/^https?:\/\//.test(audioUrl)) return audioUrl;
  const base = getVoiceWorkstationUrl().replace(/\/$/, '');
  return `${base}${audioUrl.startsWith('/') ? '' : '/'}${audioUrl}`;
}

/**
 * 构造 44 字节 PCM WAV header（data_size 占位由实际 PCM 长度填充）。
 * Orpheus 流式端点返回的是 24000Hz、16-bit、mono 裸 PCM（后端已剥离 WAV 头），
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
  view.setUint32(16, 16, true); // PCM chunk size
  view.setUint16(20, 1, true); // audio format = PCM
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

export class _VoiceWorkstationClientMixin extends _ApiClientBase {
  // ── VoxCPM ──

  async generateVoxCPM(data: VoxCPMGenerateRequest): Promise<VoiceWsAudioResult> {
    return this.voiceWorkstationRequest<VoiceWsAudioResult>({
      url: '/api/voxcpm/generate',
      method: 'POST',
      data,
    });
  }

  async getVoxCPMStatus(): Promise<VoxCPMStatus> {
    return this.voiceWorkstationRequest<VoxCPMStatus>({ url: '/api/voxcpm/status' });
  }

  async submitVoxCPMBatchDataset(data: BatchDatasetRequest): Promise<{ status: string; task_id: string; total: number }> {
    return this.voiceWorkstationRequest<{ status: string; task_id: string; total: number }>({
      url: '/api/voxcpm/batch-dataset',
      method: 'POST',
      data,
    });
  }

  async getVoxCPMBatchDatasetTask(taskId: string): Promise<BatchDatasetTask> {
    return this.voiceWorkstationRequest<BatchDatasetTask>({
      url: `/api/voxcpm/batch-dataset/${taskId}`,
    });
  }

  // ── So-VITS-SVC ──

  async sovitsSVCPreprocess(data: SVCPreprocessRequest): Promise<{ status: string; results: Record<string, unknown> }> {
    return this.voiceWorkstationRequest<{ status: string; results: Record<string, unknown> }>({
      url: '/api/sovits-svc/preprocess',
      method: 'POST',
      data,
    });
  }

  async startSoVITSSVCTrain(data: SVCTrainRequest): Promise<{ status: string; task_id: string; message: string }> {
    return this.voiceWorkstationRequest<{ status: string; task_id: string; message: string }>({
      url: '/api/sovits-svc/train',
      method: 'POST',
      data,
    });
  }

  async stopSoVITSSVCTrain(): Promise<{ status: string; message: string }> {
    return this.voiceWorkstationRequest<{ status: string; message: string }>({
      url: '/api/sovits-svc/stop',
      method: 'POST',
    });
  }

  async getSoVITSSVCStatus(): Promise<SVCTrainStatus> {
    return this.voiceWorkstationRequest<SVCTrainStatus>({ url: '/api/sovits-svc/status' });
  }

  async listSoVITSSVCModels(): Promise<{ status: string; models: SVCModel[] }> {
    return this.voiceWorkstationRequest<{ status: string; models: SVCModel[] }>({
      url: '/api/sovits-svc/models',
    });
  }

  async sovitsSVCInfer(data: SVCInferRequest): Promise<VoiceWsAudioResult> {
    return this.voiceWorkstationRequest<VoiceWsAudioResult>({
      url: '/api/sovits-svc/infer',
      method: 'POST',
      data,
    });
  }

  // ── SVC 数据集管理 ──

  async listSVCDatasets(): Promise<{ status: string; datasets: SVCDataset[] }> {
    return this.voiceWorkstationRequest<{ status: string; datasets: SVCDataset[] }>({
      url: '/api/sovits-svc/datasets',
    });
  }

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
    const response = await this.voiceWorkstationClient.post<{
      status: string;
      name: string;
      imported: number;
      files: string[];
      skipped: string[];
    }>('/api/sovits-svc/datasets/import', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return response.data;
  }

  async deleteSVCDataset(speakerName: string): Promise<{ status: string; message: string }> {
    return this.voiceWorkstationRequest<{ status: string; message: string }>({
      url: `/api/sovits-svc/datasets/${encodeURIComponent(speakerName)}`,
      method: 'DELETE',
    });
  }

  // ── 音乐 ──

  async musicValidateScore(score: Record<string, unknown>): Promise<ScoreValidateResponse> {
    return this.voiceWorkstationRequest<ScoreValidateResponse>({
      url: '/api/music/score/validate',
      method: 'POST',
      data: score,
    });
  }

  async musicImportMusicXML(file: File): Promise<Record<string, unknown>> {
    const formData = new FormData();
    formData.append('file', file);
    const response = await this.voiceWorkstationClient.post<Record<string, unknown>>(
      '/api/music/import-musicxml',
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' } },
    );
    return response.data;
  }

  async musicSynthesize(data: MusicSynthesizeRequest): Promise<{ song_id: string; status: string }> {
    return this.voiceWorkstationRequest<{ song_id: string; status: string }>({
      url: '/api/music/synthesize',
      method: 'POST',
      data,
    });
  }

  async musicGetTask(songId: string): Promise<SongTask> {
    return this.voiceWorkstationRequest<SongTask>({
      url: `/api/music/tasks/${encodeURIComponent(songId)}`,
    });
  }

  async musicListSongs(): Promise<{ songs: SongSummary[] }> {
    return this.voiceWorkstationRequest<{ songs: SongSummary[] }>({ url: '/api/music/songs' });
  }

  async musicGetSong(songId: string): Promise<SongTask> {
    return this.voiceWorkstationRequest<SongTask>({
      url: `/api/music/songs/${encodeURIComponent(songId)}`,
    });
  }

  async musicDeleteSong(songId: string): Promise<{ status: string; song_id: string }> {
    return this.voiceWorkstationRequest<{ status: string; song_id: string }>({
      url: `/api/music/songs/${encodeURIComponent(songId)}`,
      method: 'DELETE',
    });
  }

  // ── 参考音频（CosyVoice 情感参考） ──

  async pregenerateRefs(data: PregenerateRefsRequest): Promise<{ status: string; result: PregenerateRefsResult }> {
    return this.voiceWorkstationRequest<{ status: string; result: PregenerateRefsResult }>({
      url: '/api/ref-audio/pregenerate',
      method: 'POST',
      data,
    });
  }

  async exportEmotionRefsZip(data: PregenerateRefsRequest): Promise<Blob> {
    const response = await this.voiceWorkstationClient.post('/api/ref-audio/export-zip', data, {
      responseType: 'arraybuffer',
    });
    return new Blob([response.data], { type: 'application/zip' });
  }

  async importEmotionRefsZip(file: File): Promise<ImportEmotionRefsResponse> {
    const formData = new FormData();
    formData.append('file', file);
    const response = await this.voiceWorkstationClient.post<ImportEmotionRefsResponse>(
      '/api/ref-audio/import-zip',
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' } },
    );
    return response.data;
  }

  /** 参考音频预生成是异步任务，提交后需轮询 GET /api/ref-audio/status 获取进度与结果 */
  async getRefAudioStatus(): Promise<RefAudioStatus> {
    return this.voiceWorkstationRequest<RefAudioStatus>({ url: '/api/ref-audio/status' });
  }

  // ── Orpheus TTS ──

  /** 非流式合成：落盘 WAV，返回 audio_url（相对路径，需经 getVoiceWorkstationAudioUrl 拼接播放） */
  async synthesizeOrpheus(data: OrpheusSynthesizeRequest): Promise<OrpheusSynthesizeResult> {
    return this.voiceWorkstationRequest<OrpheusSynthesizeResult>({
      url: '/api/orpheus/synthesize',
      method: 'POST',
      data,
    });
  }

  /**
   * 流式合成：逐块读取裸 PCM（24000Hz/16-bit/mono），补 WAV 头后返回可播放 Blob。
   * onProgress 回调在每次收到数据块时触发，可用于展示「流式接收中…」状态。
   * 使用原生 fetch 读取 ReadableStream；token 与 axios 拦截器保持一致来源（localStorage）。
   */
  async synthesizeOrpheusStream(
    data: OrpheusSynthesizeRequest,
    onProgress?: (receivedBytes: number) => void,
  ): Promise<Blob> {
    const base = getVoiceWorkstationUrl().replace(/\/$/, '');
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    const token = localStorage.getItem('cxhms-token');
    if (token) headers['Authorization'] = `Bearer ${token}`;

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

    // 合并所有 PCM 块并补 WAV 头
    const merged = new Uint8Array(received);
    let offset = 0;
    for (const c of chunks) {
      merged.set(c, offset);
      offset += c.length;
    }
    return buildWavBlob(merged);
  }

  /** Orpheus 服务健康检查 */
  async getOrpheusStatus(): Promise<OrpheusStatus> {
    return this.voiceWorkstationRequest<OrpheusStatus>({ url: '/api/orpheus/status' });
  }
}
