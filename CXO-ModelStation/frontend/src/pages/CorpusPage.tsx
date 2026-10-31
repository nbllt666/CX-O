/*
 * 批量语料生成页（两阶段可试听流程）：
 *   音色描述（自然语言）→ qwen3 生成初始参考音频（awaiting_review）→ 用户试听
 *   满意后继续（cosyvoice3 按参考音频零样本克隆全部语料）→ 数据集自动登记编号（DS-001 起）。
 *   POST /api/datasets/preview 只生成参考音频；POST /api/datasets/{id}/continue 续跑语料；
 *   两阶段共用 GET /api/datasets/batch-generate/{task_id} 轮询（done/total/phase/current_text）。
 */
import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import { ErrorBar, NoticeBar, StatusBadge } from "../components/ui";
import { usePolling } from "../hooks/usePolling";

function toMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

/** 任务阶段中文名（reference=初始参考音频试听，corpus=批量语料，clips=成片组装） */
const PHASE_LABELS: Record<string, string> = {
  reference: "参考音频（qwen3 声音设计）",
  corpus: "批量语料合成",
  clips: "成片组装",
};

export default function CorpusPage() {
  const [voiceDescription, setVoiceDescription] = useState("");
  const [refText, setRefText] = useState("");
  const [textsText, setTextsText] = useState("");

  const [taskId, setTaskId] = useState<string | null>(null);
  const [datasetId, setDatasetId] = useState<string | null>(null);
  const [pollingActive, setPollingActive] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  // 任务进度轮询：3s 间隔；终态 / awaiting_review（试听等待）后自动停轮
  const { data: task, error: pollError, stopped: pollStopped, refresh } = usePolling(
    useCallback(() => api.getBatchTask(taskId as string), [taskId]),
    { intervalMs: 3000, enabled: pollingActive },
  );

  // 仅展示当前任务，避免续跑提交后短暂展示上一轮（试听）任务的残影
  const activeTask = task && task.task_id === taskId ? task : null;
  const awaitingReview = activeTask?.status === "awaiting_review";

  useEffect(() => {
    if (!activeTask) {
      return;
    }
    if (activeTask.status === "awaiting_review") {
      setPollingActive(false);
      setNotice(
        `初始参考音频已生成（数据集编号 ${activeTask.dataset_id}），请先试听：` +
          "满意再点「继续生成其余语料」，不满意可改描述后重新生成",
      );
      return;
    }
    if (activeTask.status === "completed" || activeTask.status === "failed") {
      setPollingActive(false);
      setNotice(
        activeTask.status === "completed"
          ? `数据集 ${datasetId ?? activeTask.dataset_id} 生成完成：参考音频 1 条 + 语料 ${activeTask.done - 1} 条（跳过重复 ${activeTask.skipped} 条）`
          : `生成任务结束（存在失败）：${activeTask.error ?? `失败 ${activeTask.failed} 条`}`,
      );
    }
  }, [activeTask, datasetId]);

  const parseTexts = () =>
    textsText
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);

  /** 阶段一：只生成初始参考音频（reuseDataset=true 时复用编号重新生成，用于试听不满意重试） */
  const submitPreview = async (reuseDataset: boolean) => {
    const desc = voiceDescription.trim();
    if (!desc) {
      setActionError("请填写音色描述（自然语言，例如：年轻女性，声音清亮，语速适中）");
      return;
    }
    setActionError(null);
    setNotice(null);
    setBusy(true);
    try {
      const res = await api.previewDatasetReference({
        voice_description: desc,
        ...(refText.trim() ? { ref_text: refText.trim() } : {}),
        ...(reuseDataset && datasetId ? { dataset_id: datasetId } : {}),
      });
      setTaskId(res.task_id);
      setDatasetId(res.dataset_id);
      setPollingActive(true);
      setNotice(
        `数据集编号 ${res.dataset_id}：正在生成初始参考音频（qwen3 声音设计），完成后可试听确认`,
      );
    } catch (e) {
      setActionError(toMessage(e));
    } finally {
      setBusy(false);
    }
  };

  /** 阶段二：试听确认后，以该数据集的参考音频继续生成其余语料 */
  const handleContinue = async () => {
    setActionError(null);
    setNotice(null);
    if (!datasetId) {
      setActionError("请先生成初始参考音频并试听确认");
      return;
    }
    const lines = parseTexts();
    if (lines.length === 0) {
      setActionError("请填写至少一条语料文本（每行一条）");
      return;
    }
    setBusy(true);
    try {
      const res = await api.continueDatasetGeneration(datasetId, {
        texts: lines.map((text) => ({ text })),
      });
      setTaskId(res.task_id);
      setPollingActive(true);
      setNotice(
        `已确认参考音频，正在生成其余语料（共 ${res.total - 1} 句，逐句推进），进度将自动刷新`,
      );
    } catch (e) {
      setActionError(toMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <header className="page-header">
        <h2>批量语料生成</h2>
        <p>
          两阶段流程：先按音色描述生成初始参考音频，试听满意后再把语料文本批量合成为训练数据，
          完成后自动分配数据集编号，训练时直接选择对应编号
        </p>
      </header>

      <ErrorBar message={pollError} stopped={pollStopped} onRetry={refresh} />
      <ErrorBar message={actionError} />

      <section className="card">
        <h3 className="card-title">提交生成任务</h3>
        <div className="form-grid">
          <div className="field field-full">
            <label htmlFor="corpus-voice-description">音色描述（自然语言）</label>
            <textarea
              id="corpus-voice-description"
              value={voiceDescription}
              onChange={(e) => setVoiceDescription(e.target.value)}
              placeholder="例如：年轻女性，声音清亮，语速适中，带轻微东北口音"
            />
          </div>
          <div className="field field-full">
            <label htmlFor="corpus-ref-text">参考文本（可选，参考音频播报的内容）</label>
            <input
              id="corpus-ref-text"
              value={refText}
              onChange={(e) => setRefText(e.target.value)}
              placeholder="缺省使用内置示例句"
            />
          </div>
          <div className="field field-full">
            <label htmlFor="corpus-texts">语料文本（每行一条，试听确认后使用）</label>
            <textarea
              id="corpus-texts"
              value={textsText}
              onChange={(e) => setTextsText(e.target.value)}
              placeholder={"第一句语料\n第二句语料\n第三句语料"}
            />
          </div>
        </div>
        <div className="form-actions">
          <button
            type="button"
            className="btn btn-primary"
            disabled={busy || pollingActive}
            onClick={() => void submitPreview(false)}
          >
            生成参考音频（可试听）
          </button>
          <span className="hint">
            先只生成首条参考音频；试听后满意再继续生成其余语料。重复文本（内容一致）会自动跳过
          </span>
        </div>
      </section>

      <NoticeBar
        message={notice}
        variant={activeTask?.status === "failed" ? "error" : "success"}
      />

      {activeTask ? (
        <section className="card">
          <h3 className="card-title">
            任务进度 <StatusBadge status={activeTask.status} />
          </h3>
          <p className="muted">
            数据集编号：<span className="mono">{activeTask.dataset_id || "（分配中）"}</span>
            {activeTask.phase ? (
              <>
                {" · "}当前阶段：{PHASE_LABELS[activeTask.phase] ?? activeTask.phase}
              </>
            ) : null}
          </p>
          <div className="progress-track">
            <div
              className="progress-fill"
              style={{
                width: `${activeTask.total > 0 ? Math.round(((activeTask.done + activeTask.failed) / activeTask.total) * 100) : 0}%`,
              }}
            />
          </div>
          <div className="progress-meta">
            <span>
              处理进度：{activeTask.done + activeTask.failed} / {activeTask.total}
            </span>
            <span>
              成功 {activeTask.done} · 跳过 {activeTask.skipped} · 失败 {activeTask.failed}
            </span>
          </div>
          <p className="muted section-gap">
            当前处理：{activeTask.current_text ?? "（空闲）"}
          </p>
          {activeTask.ref_file ? (
            <div className="section-gap">
              <p className="muted">
                初始参考音频（试听）：<span className="mono">{activeTask.ref_file}</span>
              </p>
              <audio
                controls
                src={api.getAudioFileUrl(
                  "datasets",
                  "raw",
                  activeTask.speaker_name,
                  activeTask.ref_file,
                )}
              />
              {awaitingReview ? (
                <div className="form-actions">
                  <button
                    type="button"
                    className="btn btn-primary"
                    disabled={busy}
                    onClick={() => void handleContinue()}
                  >
                    继续生成其余语料
                  </button>
                  <button
                    type="button"
                    className="btn btn-ghost"
                    disabled={busy}
                    onClick={() => void submitPreview(true)}
                  >
                    按当前描述重新生成参考音频
                  </button>
                </div>
              ) : null}
            </div>
          ) : null}
          <p className="muted">数据集目录：<span className="mono">{activeTask.dataset_dir}</span></p>
          {activeTask.failures.length > 0 ? (
            <>
              <h3 className="card-title section-gap">失败明细</h3>
              <ul className="muted">
                {activeTask.failures.map((f) => (
                  <li key={f.index}>
                    [{f.index}] {f.text} —— {f.error}
                  </li>
                ))}
              </ul>
            </>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
