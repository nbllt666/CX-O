/*
 * API 客户端 — CXO-ModelStation 前端专用（不与 APP-Frontend 共享代码）。
 * 端点与响应类型以 modelstation/api 实现为准
 * （change-id: split-audio-workstation-cxfc-modelstation；
 *   extend-modelstation-standalone-melotts-datasets：
 *   批量生成端点改名 /api/datasets/batch-generate（三引擎），
 *   新增 /api/melotts 训练五端点）。
 * 开发模式经 vite proxy（/api → http://127.0.0.1:8300）；
 * 生产模式由 ModelStation 后端静态托管，同源直连。
 */

// ======================== 错误类型 ========================

export class ApiClientError extends Error {
  /** HTTP 状态码；0 表示网络不可达（后端未启动/连接失败） */
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiClientError";
    this.status = status;
  }
}

// ======================== 类型定义 ========================

export interface HealthInfo {
  status: string;
  service: string;
  version: string;
}

export interface DatasetInfo {
  name: string;
  /** 数据集编号（统一流程登记 DS-xxx；导入/历史数据集为 null） */
  dataset_id: string | null;
  file_count: number;
  total_size_bytes: number;
  created_at: string;
  has_manifest: boolean;
  /** manifest 结构版本（v2：条目含 text/engine；manifest 缺失/损坏时为 null） */
  manifest_version: number | null;
  /** manifest 条目总数 */
  entry_count: number;
  /** 含 text 的条目数（供 MeloTTS filelist 消费） */
  text_count: number;
  /** text 完整率（含 text 条目占比；manifest 缺失或条目为空时为 null） */
  text_ratio: number | null;
}

export interface ImportResult {
  status: string;
  name: string;
  imported: number;
  files: string[];
  skipped: string[];
}

export interface MessageResult {
  status: string;
  message: string;
}

/** POST /api/sovits-svc/preprocess 响应：status 为 success / partial */
export interface PreprocessResult {
  status: string;
  results: Record<string, { success: boolean } & Record<string, unknown>>;
}

/** POST /api/sovits-svc/preprocess 请求：数据来源二选一（编号或显式路径） */
export interface SVCPreprocessRequest {
  /** 数据集编号（统一流程 DS-xxx，如 DS-001） */
  dataset_id?: string;
  /** 数据根目录（含 raw/<speaker>；相对路径锚定 CXO-ModelStation 根） */
  training_data_dir?: string;
  speaker_name?: string;
}

export interface TrainStartRequest {
  epochs: number;
  batch_size: number;
  learning_rate: number;
  output_name?: string | null;
  speaker_name?: string | null;
  /** 数据集编号（统一流程 DS-xxx）；提供时覆盖 speaker_name */
  dataset_id?: string | null;
}

export interface TrainStartResult {
  status: string;
  task_id: string;
  message: string;
}

export interface ModelInfo {
  name: string;
  path: string;
  created: number;
  g_model: string | null;
  d_model: string | null;
}

export interface ModelsResult {
  status: string;
  models: ModelInfo[];
}

/** GET /api/sovits-svc/status：progress 取值 0-1 */
export interface TrainStatus {
  task_id: string | null;
  status: string;
  progress: number;
  epoch: number;
  total_epochs: number;
  message: string;
  models: ModelInfo[];
}

export interface InferRequest {
  audio_path: string;
  model_path?: string | null;
  speaker_id?: number;
  transpose?: number;
  cluster_model_path?: string | null;
}

export interface InferResult {
  status: string;
  output_filename: string;
  audio_url: string;
}

// ---- MeloTTS 训练（/api/melotts，形状与 sovits 同构）----

/** POST /api/melotts/preprocess 请求：数据来源二选一（编号或显式路径） */
export interface MelottsPreprocessRequest {
  /** 数据集编号（统一流程 DS-xxx，如 DS-001） */
  dataset_id?: string;
  /** 数据集目录（相对路径锚定 CXO-ModelStation 根，如 data/training/sovits_svc/raw/speaker1） */
  dataset_dir?: string;
  speaker_name?: string;
}

/** POST /api/melotts/preprocess 响应：与 sovits preprocess 同构（success / partial） */
export type MelottsPreprocessResult = PreprocessResult;

export interface MelottsTrainStartRequest {
  epochs: number;
  batch_size: number;
  learning_rate: number;
  output_name?: string | null;
  /** 训练语言（后端默认 ZH） */
  language?: string | null;
}

/** GET /api/melotts/models 列表项（MeloTTS 产物为目录，无 G/D 权重对） */
export interface MelottsModelInfo {
  name: string;
  path: string;
  created: number;
}

export interface MelottsModelsResult {
  status: string;
  models: MelottsModelInfo[];
}

/** GET /api/melotts/status：progress 取值 0-1（models 字段后端可选附带） */
export interface MelottsTrainStatus {
  task_id: string | null;
  status: string;
  progress: number;
  epoch: number;
  total_epochs: number;
  message: string;
  models?: MelottsModelInfo[];
}

export interface BatchTextItem {
  text: string;
}

/** 数据集生成引擎：cosyvoice3_zero（零样本克隆）/ qwen3_voicedesign（声音设计）；
 *  voxcpm 已停用（批量语料统一走一套流程 POST /api/datasets/generate） */
export type BatchEngine = "cosyvoice3_zero" | "qwen3_voicedesign";

/** 运行时引擎专属参数（按 engine 联动） */
export interface EngineParams {
  /** cosyvoice3_zero：参考音频路径（白名单：training_data_dir ∪ data/input） */
  ref_audio_path?: string;
  /** cosyvoice3_zero：可选参考转写文本（提升克隆质量） */
  ref_text?: string;
  /** qwen3_voicedesign：音色描述（自然语言文本） */
  voice_description?: string;
}

export interface BatchDatasetRequest {
  speaker_name: string;
  texts: BatchTextItem[];
  /** 生成引擎（后端默认 cosyvoice3_zero） */
  engine: BatchEngine;
  engine_params?: EngineParams;
}

/** POST /api/datasets/generate：统一流程请求（一套流程） */
export interface PipelineGenerateRequest {
  /** 音色描述（自然语言，用于 qwen3 生成初始参考音频） */
  voice_description: string;
  texts: BatchTextItem[];
  /** 参考音频播报文本（缺省用内置句） */
  ref_text?: string | null;
  /** 数据集目录名（缺省与编号相同） */
  name?: string | null;
}

/** POST /api/datasets/generate 响应 */
export interface PipelineGenerateResult {
  status: string;
  /** 数据集编号（DS-001 起，训练入口直接选择该编号） */
  dataset_id: string;
  name: string;
  task_id: string;
  dataset_dir: string;
  /** 总条数 = 1（参考音频）+ 语料文本数 */
  total: number;
}

export interface BatchDatasetSubmitResult {
  status: string;
  task_id: string;
  total: number;
}

export interface BatchTaskFailure {
  index: number;
  text: string;
  error: string;
}

/** GET /api/datasets/batch-generate/{task_id}：done 为本次新生成条数 */
export interface BatchTaskStatus {
  task_id: string;
  speaker_name: string;
  dataset_dir: string;
  /** 统一流程（pipeline）下 mode 为空串 */
  mode: string;
  /** 引擎来源：运行时引擎 / pipeline（统一流程） */
  engine: BatchEngine | "pipeline";
  /** 数据集编号（统一流程 DS-xxx；普通批量任务为空串） */
  dataset_id: string;
  status: string;
  total: number;
  done: number;
  skipped: number;
  failed: number;
  current_text: string | null;
  error: string | null;
  failures: BatchTaskFailure[];
  created_at: string;
  finished_at: string | null;
}

export interface WorkflowStep {
  id: string;
  name: string;
  status: string;
  output: unknown;
}

export interface WorkflowState {
  current_step: number;
  steps: WorkflowStep[];
}

export interface StepOutputResult {
  step_id: string;
  output: unknown;
  status: string;
}

/** 受控音频 category 白名单：audition=试听输出目录、datasets=训练数据目录 */
export type AudioFileCategory = "audition" | "datasets";

// ======================== 请求基础封装 ========================

const JSON_HEADERS = { "Content-Type": "application/json" };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, init);
  } catch (e) {
    throw new ApiClientError(
      0,
      `无法连接 ModelStation 后端：${e instanceof Error ? e.message : String(e)}`,
    );
  }
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body?.detail === "string") {
        detail = body.detail;
      } else if (body?.detail != null) {
        detail = JSON.stringify(body.detail);
      }
    } catch {
      // 非 JSON 响应体，保留状态码文案
    }
    throw new ApiClientError(res.status, detail);
  }
  return (await res.json()) as T;
}

// ======================== API 端点 ========================

export const api = {
  // ---- 健康检查 ----
  getHealth: () => request<HealthInfo>("/health"),

  // ---- So-VITS-SVC 训练（/api/sovits-svc）----
  preprocess: (req: SVCPreprocessRequest) =>
    request<PreprocessResult>("/api/sovits-svc/preprocess", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify(req),
    }),

  startTrain: (req: TrainStartRequest) =>
    request<TrainStartResult>("/api/sovits-svc/train", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify(req),
    }),

  stopTrain: () =>
    request<MessageResult>("/api/sovits-svc/stop", { method: "POST" }),

  getTrainStatus: () => request<TrainStatus>("/api/sovits-svc/status"),

  listModels: () => request<ModelsResult>("/api/sovits-svc/models"),

  infer: (req: InferRequest) =>
    request<InferResult>("/api/sovits-svc/infer", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify(req),
    }),

  // ---- SVC 数据集管理（/api/sovits-svc/datasets）----
  listDatasets: () =>
    request<{ status: string; datasets: DatasetInfo[] }>(
      "/api/sovits-svc/datasets",
    ),

  /** multipart 上传导入：仅接受文件直传（多文件或 zip 包），不接受客户端路径 */
  importDataset: (speakerName: string, files: File[]) => {
    const formData = new FormData();
    formData.append("speaker_name", speakerName);
    for (const file of files) {
      formData.append("files", file);
    }
    return request<ImportResult>("/api/sovits-svc/datasets/import", {
      method: "POST",
      body: formData,
    });
  },

  deleteDataset: (speakerName: string) =>
    request<MessageResult>(
      `/api/sovits-svc/datasets/${encodeURIComponent(speakerName)}`,
      { method: "DELETE" },
    ),

  // ---- 统一流程 / 批量语料生成（/api/datasets）----
  /** 一套流程：qwen3 初始参考音频 → cosyvoice 批量语料 → 数据集编号 */
  generateDataset: (req: PipelineGenerateRequest) =>
    request<PipelineGenerateResult>("/api/datasets/generate", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify(req),
    }),

  submitBatchDataset: (req: BatchDatasetRequest) =>
    request<BatchDatasetSubmitResult>("/api/datasets/batch-generate", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify(req),
    }),

  getBatchTask: (taskId: string) =>
    request<BatchTaskStatus>(
      `/api/datasets/batch-generate/${encodeURIComponent(taskId)}`,
    ),

  // ---- MeloTTS 训练（/api/melotts，形状与 sovits 同构）----
  melottsPreprocess: (req: MelottsPreprocessRequest) =>
    request<MelottsPreprocessResult>("/api/melotts/preprocess", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify(req),
    }),

  startMelottsTrain: (req: MelottsTrainStartRequest) =>
    request<TrainStartResult>("/api/melotts/train", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify(req),
    }),

  stopMelottsTrain: () =>
    request<MessageResult>("/api/melotts/stop", { method: "POST" }),

  getMelottsStatus: () => request<MelottsTrainStatus>("/api/melotts/status"),

  listMelottsModels: () => request<MelottsModelsResult>("/api/melotts/models"),

  // ---- 工作流（/api/workflow）----
  getWorkflowStatus: () => request<WorkflowState>("/api/workflow/status"),

  executeWorkflowStep: (stepId: string, body: Record<string, unknown> = {}) =>
    request<WorkflowState>(`/api/workflow/step/${encodeURIComponent(stepId)}/execute`, {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify(body),
    }),

  resetWorkflow: () =>
    request<WorkflowState>("/api/workflow/reset", { method: "POST" }),

  getStepOutput: (stepId: string) =>
    request<StepOutputResult>(`/api/workflow/step/${encodeURIComponent(stepId)}/output`),

  // ---- 受控音频文件 URL ----
  /**
   * 构造 /api/audio-files/{category}/{filename} URL。
   * datasets category 允许一层子路径（speaker/文件名），按段编码后拼接。
   */
  getAudioFileUrl: (category: AudioFileCategory, ...segments: string[]) =>
    `/api/audio-files/${category}/${segments.map((s) => encodeURIComponent(s)).join("/")}`,
};
