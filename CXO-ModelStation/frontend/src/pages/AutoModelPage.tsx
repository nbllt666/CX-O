/*
 * 一键成模页（导航第一入口）：
 *   提示词模式两阶段：先只生成初始参考音频（qwen3 声音设计，status=awaiting_review），
 *   用户试听满意后再「继续」以 dataset_id 启动自动全流程（参考音频 → 语料生成 →
 *   数据准备 → 训练 → 产物收集）；上传参考音频 / 本地数据集模式仍一步启动。
 *   轮询分阶段进度（3s，completed/failed 停轮），完成后展示模型文件卡片。
 *   API：POST /api/pipeline/reference、POST /api/pipeline/run、GET /api/pipeline/run/{run_id}、
 *        POST /api/datasets/preview、GET /api/datasets/batch-generate/{task_id}。
 */
import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { PipelineRunRequest, PipelineStageId } from "../api/client";
import { ErrorBar, NoticeBar, StatusBadge } from "../components/ui";
import { usePolling } from "../hooks/usePolling";

/** 模型类型（分段控件切换，默认 MeloTTS） */
type ModelType = "melotts" | "sovits";

const MODEL_TYPE_OPTIONS: { value: ModelType; label: string }[] = [
  { value: "melotts", label: "MeloTTS" },
  { value: "sovits", label: "So-VITS-SVC" },
];

const MODEL_TYPE_LABELS: Record<string, string> = {
  melotts: "MeloTTS",
  sovits: "So-VITS-SVC",
};

/** 输入三选一：音色描述（提示词）/ 上传参考音频 / 本地数据集目录（仅 So-VITS） */
const INPUT_MODE_OPTIONS = [
  { value: "description", label: "音色描述" },
  { value: "reference", label: "上传参考音频" },
  { value: "dataset", label: "本地数据集" },
] as const;

type InputMode = (typeof INPUT_MODE_OPTIONS)[number]["value"];

/** 语料规模档位：按模型类型分档（合成后按句子边界拼为 5~15s 切片）
 *  - MeloTTS 典型值 50 片（小数据即可微调）；
 *  - So-VITS-SVC 通常需要数千片，最高允许 10000（合成耗时长，建议优先用本地数据集）。 */
const MELOTTS_CORPUS_OPTIONS = [
  { value: 20, label: "20 片（快速试音，合成约 3 分钟）" },
  { value: 50, label: "50 片（MeloTTS 典型值，合成约 8 分钟）" },
  { value: 100, label: "100 片（合成约 15 分钟）" },
  { value: 200, label: "200 片（合成约 30 分钟）" },
];
const SOVITS_CORPUS_OPTIONS = [
  { value: 100, label: "100 片（合成约 15 分钟）" },
  { value: 300, label: "300 片（合成约 45 分钟）" },
  { value: 500, label: "500 片（合成约 75 分钟）" },
  { value: 1000, label: "1000 片（合成约 2.5 小时）" },
  { value: 3000, label: "3000 片（合成约 7.5 小时）" },
  { value: 10000, label: "10000 片（合成约 25 小时，建议改用「本地数据集」）" },
];
const DEFAULT_CORPUS_TARGET: Record<ModelType, number> = { melotts: 50, sovits: 300 };

/** 阶段中文名映射 */
const STAGE_LABELS: Record<PipelineStageId, string> = {
  reference: "参考音频",
  corpus: "语料生成",
  preprocess: "数据准备",
  training: "训练",
  collect: "产物收集",
};

/** fitting_status 中文说明（判停语义） */
const FITTING_LABELS: Record<string, string> = {
  improving: "拟合中",
  converged: "已拟合（自动停止）",
  overfit_risk: "过拟合风险（自动停止）",
  max_epochs: "达到上限",
};

function toMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export default function AutoModelPage() {
  // ---- 输入二选一 ----
  const [inputMode, setInputMode] = useState<InputMode>("description");
  const [voiceDescription, setVoiceDescription] = useState("");
  const [refUploading, setRefUploading] = useState(false);
  const [refAudioPath, setRefAudioPath] = useState<string | null>(null);
  const [refFileName, setRefFileName] = useState<string | null>(null);
  const [refError, setRefError] = useState<string | null>(null);
  const [datasetDir, setDatasetDir] = useState("");

  // ---- 模型类型与高级可选 ----
  const [modelType, setModelType] = useState<ModelType>("melotts");
  const [textsText, setTextsText] = useState("");
  const [maxEpochsText, setMaxEpochsText] = useState("10000");
  const [corpusTarget, setCorpusTarget] = useState(50);
  const corpusOptions =
    modelType === "sovits" ? SOVITS_CORPUS_OPTIONS : MELOTTS_CORPUS_OPTIONS;

  // ---- 提示词模式：初始参考音频试听（awaiting_review 停轮，确认后携带 dataset_id 续跑）----
  const [previewTaskId, setPreviewTaskId] = useState<string | null>(null);
  const [previewDatasetId, setPreviewDatasetId] = useState<string | null>(null);
  const [previewActive, setPreviewActive] = useState(false);

  // ---- 运行与轮询（3s，completed/failed 停轮）----
  const [runId, setRunId] = useState<string | null>(null);
  const [pollingActive, setPollingActive] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const { data: run, error: pollError, stopped: pollStopped, refresh } = usePolling(
    useCallback(() => api.getPipelineRun(runId as string), [runId]),
    { intervalMs: 3000, enabled: pollingActive },
  );

  // 仅展示当前 run_id 的数据，避免提交新一轮后短暂展示上一轮残影
  const activeRun = run && run.run_id === runId ? run : null;

  // 参考音频试听任务轮询（复用批量任务查询端点）
  const { data: previewTask } = usePolling(
    useCallback(() => api.getBatchTask(previewTaskId as string), [previewTaskId]),
    { intervalMs: 3000, enabled: previewActive },
  );
  const activePreview =
    previewTask && previewTask.task_id === previewTaskId ? previewTask : null;
  const previewReady = activePreview?.status === "awaiting_review";

  useEffect(() => {
    if (!activePreview) {
      return;
    }
    if (activePreview.status === "awaiting_review") {
      setPreviewActive(false);
      setNotice(
        `初始参考音频已生成（数据集编号 ${activePreview.dataset_id}），请先试听；` +
          "满意后点「继续：生成语料并开始训练」，不满意可修改描述重新生成",
      );
      return;
    }
    if (activePreview.status === "failed") {
      setPreviewActive(false);
      setActionError(activePreview.error ?? "初始参考音频生成失败");
    }
  }, [activePreview]);

  // 运行结束（completed/failed）即停轮，并生成终态通知
  useEffect(() => {
    if (!activeRun || (activeRun.status !== "completed" && activeRun.status !== "failed")) {
      return;
    }
    setPollingActive(false);
    if (activeRun.status === "completed") {
      setNotice(
        activeRun.result
          ? `一键成模完成：模型 ${activeRun.result.model_name}`
          : "一键成模完成",
      );
    } else {
      const failedStage = activeRun.stages.find((s) => s.status === "failed");
      setNotice(
        `运行失败：${activeRun.error ?? "未知错误"}${
          failedStage
            ? `（阶段「${STAGE_LABELS[failedStage.id]}」：${failedStage.detail ?? "无详情"}）`
            : ""
        }`,
      );
    }
  }, [activeRun]);

  /** 参考音频选择后立即上传（multipart 单文件），成功记录服务端受控路径 */
  const handleRefFileSelect = async (file: File | null) => {
    setRefFileName(null);
    setRefAudioPath(null);
    setRefError(null);
    if (!file) {
      return;
    }
    setRefUploading(true);
    try {
      const res = await api.uploadReference(file);
      setRefAudioPath(res.ref_audio_path);
      setRefFileName(file.name);
    } catch (e) {
      setRefError(toMessage(e));
    } finally {
      setRefUploading(false);
    }
  };

  /** 阶段一（提示词模式）：只生成初始参考音频，完成后停在 awaiting_review 供试听 */
  const handlePreview = async () => {
    const desc = voiceDescription.trim();
    if (!desc) {
      setActionError("请填写音色描述，或切换到「上传参考音频」");
      return;
    }
    setActionError(null);
    setNotice(null);
    setBusy(true);
    try {
      const res = await api.previewDatasetReference({
        voice_description: desc,
        // 试听不满意重试时复用同一数据集编号（只替换参考音频）
        ...(previewDatasetId ? { dataset_id: previewDatasetId } : {}),
      });
      setPreviewTaskId(res.task_id);
      setPreviewDatasetId(res.dataset_id);
      setPreviewActive(true);
      setNotice(
        `数据集编号 ${res.dataset_id}：正在生成初始参考音频（qwen3 声音设计），完成后请试听确认`,
      );
    } catch (e) {
      setActionError(toMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const handleSubmit = async () => {
    setActionError(null);
    setNotice(null);
    if (inputMode === "description" && !voiceDescription.trim()) {
      setActionError("请填写音色描述，或切换到「上传参考音频」");
      return;
    }
    if (inputMode === "reference" && !refAudioPath) {
      setActionError("请先上传参考音频（或切换到「音色描述」）");
      return;
    }
    if (inputMode === "dataset") {
      if (!datasetDir.trim()) {
        setActionError("请填写本地数据集文件夹路径");
        return;
      }
      if (modelType !== "sovits") {
        setActionError("本地数据集模式仅支持 So-VITS-SVC（MeloTTS 训练需要音频-文本对）");
        return;
      }
    }
    // 提示词模式：尚未试听确认 → 先生成参考音频，确认后再走完整流程
    if (inputMode === "description" && !previewReady) {
      if (previewActive) {
        setActionError("初始参考音频生成中，请稍候并试听后再继续");
        return;
      }
      await handlePreview();
      return;
    }
    const lines = textsText
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
    const maxEpochs = Math.floor(Number(maxEpochsText));
    if (!Number.isFinite(maxEpochs) || maxEpochs < 1) {
      setActionError("训练轮数上限需为不小于 1 的整数");
      return;
    }
    const req: PipelineRunRequest = { model_type: modelType, max_epochs: maxEpochs };
    if (inputMode === "description") {
      // 已试听确认：携带 dataset_id 跳过参考音频阶段，直接生成语料并训练
      req.dataset_id = previewDatasetId as string;
    } else if (inputMode === "dataset") {
      req.dataset_dir = datasetDir.trim();
    } else if (refAudioPath) {
      req.ref_audio_path = refAudioPath;
    }
    if (lines.length > 0) {
      req.texts = lines.map((text) => ({ text }));
    }
    if (inputMode !== "dataset") {
      req.corpus_target_clips = corpusTarget;
    }
    setBusy(true);
    try {
      const res = await api.startPipelineRun(req);
      setRunId(res.run_id);
      setPollingActive(true);
      // 参考音频已确认并进入完整流程：收起试听确认区（run 卡片展示数据集编号）
      setPreviewActive(false);
      setPreviewTaskId(null);
      setPreviewDatasetId(null);
      setNotice("一键成模任务已提交，进度将自动刷新（每 3 秒）");
    } catch (e) {
      setActionError(toMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const corpusPercent =
    activeRun && activeRun.corpus.total > 0
      ? Math.round((activeRun.corpus.done / activeRun.corpus.total) * 100)
      : 0;
  const trainPercent = activeRun
    ? Math.min(100, Math.max(0, Math.round(activeRun.training.progress * 100)))
    : 0;

  return (
    <div>
      <header className="page-header">
        <h2>一键成模</h2>
        <p>
          输入音色提示词、上传参考音频或指定本地数据集文件夹，选择模型类型，系统自动完成全部流程并输出模型文件
        </p>
      </header>

      <ErrorBar message={pollError} stopped={pollStopped} onRetry={refresh} />
      <ErrorBar message={actionError} />

      <section className="card">
        <h3 className="card-title">输入方式（三选一）</h3>
        <div className="layout-row" role="group" aria-label="音色输入方式选择">
          {INPUT_MODE_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              className={`btn ${inputMode === opt.value ? "btn-primary" : "btn-ghost"}`}
              aria-pressed={inputMode === opt.value}
              onClick={() => {
                setInputMode(opt.value);
                // 本地数据集仅支持 So-VITS-SVC：选中时自动切到该模型类型
                if (opt.value === "dataset") {
                  setModelType("sovits");
                }
              }}
            >
              {opt.label}
            </button>
          ))}
        </div>
        <div className="form-grid section-gap">
          {inputMode === "description" ? (
            <div className="field field-full">
              <label htmlFor="auto-voice-description">音色描述（自然语言）</label>
              <textarea
                id="auto-voice-description"
                value={voiceDescription}
                onChange={(e) => {
                  setVoiceDescription(e.target.value);
                  // 描述变化后旧的试听结论失效：清空已确认数据集，需重新生成并试听
                  if (previewTaskId || previewDatasetId) {
                    setPreviewTaskId(null);
                    setPreviewDatasetId(null);
                    setPreviewActive(false);
                  }
                }}
                placeholder="例如：年轻女性，声音清亮，语速适中，带轻微东北口音"
              />
              <span className="hint">先只生成首条参考音频，试听满意后再继续生成语料并训练</span>
            </div>
          ) : inputMode === "dataset" ? (
            <div className="field field-full">
              <label htmlFor="auto-dataset-dir">本地数据集文件夹路径（绝对路径）</label>
              <input
                id="auto-dataset-dir"
                type="text"
                value={datasetDir}
                onChange={(e) => setDatasetDir(e.target.value)}
                placeholder="例如：D:\voice_data\speaker0_slices"
              />
              <span className="hint">
                递归扫描 .wav/.mp3/.flac/.ogg，自动统一转码 44.1kHz 单声道；
                So-VITS 建议数千条 5~15 秒切片（切片工具可参考 audio-slicer）
              </span>
            </div>
          ) : (
            <div className="field field-full">
              <label htmlFor="auto-ref-audio">参考音频文件（.wav/.mp3/.flac/.ogg）</label>
              <input
                id="auto-ref-audio"
                type="file"
                accept=".wav,.mp3,.flac,.ogg"
                disabled={refUploading}
                onChange={(e) => void handleRefFileSelect(e.target.files?.[0] ?? null)}
              />
              {refUploading ? <span className="hint">参考音频上传中…</span> : null}
              {refFileName ? <span className="muted">已上传：{refFileName}</span> : null}
              <NoticeBar message={refError} variant="error" />
            </div>
          )}
        </div>
      </section>

      <section className="card">
        <h3 className="card-title">模型类型</h3>
        <div className="layout-row" role="group" aria-label="模型类型选择">
          {MODEL_TYPE_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              className={`btn ${modelType === opt.value ? "btn-primary" : "btn-ghost"}`}
              aria-pressed={modelType === opt.value}
              onClick={() => {
                setModelType(opt.value);
                // 切模型类型时语料档位联动回该类型的推荐值（MeloTTS 50 / So-VITS 300）
                setCorpusTarget(DEFAULT_CORPUS_TARGET[opt.value]);
              }}
            >
              {opt.label}
            </button>
          ))}
        </div>
        <div className="form-grid section-gap">
          {inputMode !== "dataset" ? (
            <div className="field field-full">
              <label htmlFor="auto-corpus-target">语料规模（合成后按句子拼为 5~15 秒切片）</label>
              <select
                id="auto-corpus-target"
                value={corpusTarget}
                onChange={(e) => setCorpusTarget(Number(e.target.value))}
              >
                {corpusOptions.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
              <span className="hint">
                MeloTTS 典型 50 片即可微调；So-VITS 建议数千片，大批量合成耗时长，
                更推荐「本地数据集」入口导入现成切片
              </span>
            </div>
          ) : null}
          <div className="field field-full">
            <label htmlFor="auto-texts">语料文本覆盖（可选，每行一条）</label>
            <textarea
              id="auto-texts"
              value={textsText}
              onChange={(e) => setTextsText(e.target.value)}
              placeholder={"第一句语料\n第二句语料"}
            />
            <span className="hint">缺省使用内置语料</span>
          </div>
          <div className="field field-full">
            <label htmlFor="auto-max-epochs">训练轮数上限</label>
            <input
              id="auto-max-epochs"
              type="number"
              min={1}
              step={1}
              value={maxEpochsText}
              onChange={(e) => setMaxEpochsText(e.target.value)}
            />
            <span className="hint">
              默认 10000 轮封顶；训练中会按损失自动判断，不再进步或过拟合时提前停止
            </span>
          </div>
        </div>
        <div className="form-actions">
          <button
            type="button"
            className="btn btn-primary"
            disabled={busy || refUploading || previewActive}
            onClick={() => void handleSubmit()}
          >
            {inputMode === "description"
              ? previewReady
                ? "继续：生成语料并开始训练"
                : "生成参考音频（可试听）"
              : "开始"}
          </button>
          <span className="hint">
            {inputMode === "description"
              ? "先生成首条参考音频，试听满意后继续：语料生成 → 数据准备 → 训练 → 产物收集"
              : "开始后自动完成：语料生成 / 数据集导入 → 数据准备 → 训练 → 产物收集"}
          </span>
        </div>
      </section>

      <NoticeBar
        message={notice}
        variant={activeRun?.status === "failed" ? "error" : "success"}
      />

      {inputMode === "description" && (previewActive || activePreview) ? (
        <section className="card">
          <h3 className="card-title">
            初始参考音频试听{" "}
            {activePreview ? (
              <StatusBadge status={activePreview.status} />
            ) : (
              <span className="muted">（生成中）</span>
            )}
          </h3>
          <p className="muted">
            数据集编号：<span className="mono">{previewDatasetId ?? activePreview?.dataset_id ?? "（分配中）"}</span>
            {activePreview?.phase ? <> · 阶段：参考音频（qwen3 声音设计）</> : null}
          </p>
          {activePreview?.ref_file ? (
            <>
              <audio
                controls
                src={api.getAudioFileUrl(
                  "datasets",
                  "raw",
                  activePreview.speaker_name,
                  activePreview.ref_file,
                )}
              />
              <p className="muted section-gap">
                试听满意后点上方「继续：生成语料并开始训练」；不满意可修改音色描述后重新生成，
                或直接按当前描述重试一条参考音频
              </p>
            </>
          ) : (
            <p className="muted">
              正在生成初始参考音频（qwen3 声音设计），生成完成后即可试听…
            </p>
          )}
          <div className="form-actions">
            <button
              type="button"
              className="btn btn-ghost"
              disabled={busy || previewActive}
              onClick={() => void handlePreview()}
            >
              按当前描述重新生成参考音频
            </button>
            <span className="hint">同一数据集只保留最新一条参考音频，旧文件会自动清理</span>
          </div>
        </section>
      ) : null}

      {activeRun ? (
        <section className="card">
          <h3 className="card-title">
            运行进度 <StatusBadge status={activeRun.status} />
          </h3>
          <p className="muted">
            模型类型：{MODEL_TYPE_LABELS[activeRun.model_type] ?? activeRun.model_type}
            {activeRun.dataset_id ? (
              <>
                {" · "}数据集编号：<span className="mono">{activeRun.dataset_id}</span>
              </>
            ) : null}
          </p>
          <table className="data-table">
            <thead>
              <tr>
                <th>阶段</th>
                <th>状态</th>
                <th>说明</th>
              </tr>
            </thead>
            <tbody>
              {activeRun.stages.map((stage) => (
                <tr key={stage.id}>
                  <td>{STAGE_LABELS[stage.id]}</td>
                  <td>
                    <StatusBadge status={stage.status} />
                  </td>
                  <td className="muted">{stage.detail ?? "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="progress-track section-gap">
            <div className="progress-fill" style={{ width: `${corpusPercent}%` }} />
          </div>
          <div className="progress-meta">
            <span>
              语料生成：{activeRun.corpus.done} / {activeRun.corpus.total}
            </span>
          </div>
          <div className="progress-track">
            <div className="progress-fill" style={{ width: `${trainPercent}%` }} />
          </div>
          <div className="progress-meta">
            <span>
              训练：epoch {activeRun.training.epoch} / {activeRun.training.total_epochs}
            </span>
            <span>进度：{trainPercent}%</span>
          </div>
          {activeRun.training.fitting_status ? (
            <p className="muted">
              拟合状态：{FITTING_LABELS[activeRun.training.fitting_status] ?? activeRun.training.fitting_status}
              {activeRun.training.stop_reason ? `（${activeRun.training.stop_reason}）` : ""}
            </p>
          ) : null}
        </section>
      ) : null}

      {activeRun?.status === "completed" && activeRun.result ? (
        <section className="card">
          <h3 className="card-title">模型文件</h3>
          <p>
            模型名：<span className="mono">{activeRun.result.model_name}</span>
          </p>
          <p className="muted">
            模型目录：<span className="mono">{activeRun.result.model_dir}</span>
          </p>
          <p className="muted section-gap">产物文件：</p>
          <ul className="muted">
            {activeRun.result.files.map((file, index) => (
              <li key={`${file}-${index}`}>
                <span className="mono">{file}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
