/*
 * 批量语料生成页（一套流程）：
 *   音色描述（自然语言）→ qwen3 生成初始参考音频 → cosyvoice3 按参考音频
 *   零样本克隆生成全部语料 → 数据集自动登记编号（DS-001 起）。
 *   POST /api/datasets/generate 返回 dataset_id + task_id，轮询任务进度
 *   （done/total/skipped/failed/current_text），训练页直接按编号选择数据集。
 */
import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import { ErrorBar, NoticeBar, StatusBadge } from "../components/ui";
import { usePolling } from "../hooks/usePolling";

function toMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

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

  // 任务进度轮询：3s 间隔；任务结束（completed/failed）后自动停轮
  const { data: task } = usePolling(
    useCallback(() => api.getBatchTask(taskId as string), [taskId]),
    { intervalMs: 3000, enabled: pollingActive },
  );

  useEffect(() => {
    if (task && (task.status === "completed" || task.status === "failed")) {
      setPollingActive(false);
      setNotice(
        task.status === "completed"
          ? `数据集 ${datasetId ?? task.dataset_id} 生成完成：参考音频 1 条 + 语料 ${task.done - 1} 条（跳过重复 ${task.skipped} 条）`
          : `生成任务结束（存在失败）：${task.error ?? `失败 ${task.failed} 条`}`,
      );
    }
  }, [task, datasetId]);

  const handleSubmit = async () => {
    setActionError(null);
    setNotice(null);
    if (!voiceDescription.trim()) {
      setActionError("请填写音色描述（自然语言，例如：年轻女性，声音清亮，语速适中）");
      return;
    }
    const lines = textsText
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
    if (lines.length === 0) {
      setActionError("请填写至少一条语料文本（每行一条）");
      return;
    }

    setBusy(true);
    try {
      const res = await api.generateDataset({
        voice_description: voiceDescription.trim(),
        texts: lines.map((text) => ({ text })),
        ...(refText.trim() ? { ref_text: refText.trim() } : {}),
      });
      setTaskId(res.task_id);
      setDatasetId(res.dataset_id);
      setPollingActive(true);
      setNotice(
        `任务已提交（数据集编号 ${res.dataset_id}，参考音频 1 条 + 语料 ${res.total - 1} 条），进度将自动刷新`,
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
          一套流程：先按音色描述生成初始参考音频，再按参考音频把语料文本批量合成为训练数据，
          完成后自动分配数据集编号，训练时直接选择对应编号
        </p>
      </header>

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
            <label htmlFor="corpus-texts">语料文本（每行一条）</label>
            <textarea
              id="corpus-texts"
              value={textsText}
              onChange={(e) => setTextsText(e.target.value)}
              placeholder={"第一句语料\n第二句语料\n第三句语料"}
            />
          </div>
        </div>
        <div className="form-actions">
          <button type="button" className="btn btn-primary" disabled={busy} onClick={handleSubmit}>
            开始生成
          </button>
          <span className="hint">
            重复文本（内容一致）会自动跳过，不重复生成；完成后在「训练控制台」按数据集编号选择
          </span>
        </div>
      </section>

      <NoticeBar message={notice} variant={task?.status === "failed" ? "error" : "success"} />

      {task ? (
        <section className="card">
          <h3 className="card-title">
            任务进度 <StatusBadge status={task.status} />
          </h3>
          <p className="muted">
            数据集编号：<span className="mono">{task.dataset_id || "（分配中）"}</span>
          </p>
          <div className="progress-track">
            <div
              className="progress-fill"
              style={{ width: `${task.total > 0 ? Math.round(((task.done + task.failed) / task.total) * 100) : 0}%` }}
            />
          </div>
          <div className="progress-meta">
            <span>
              处理进度：{task.done + task.failed} / {task.total}
            </span>
            <span>成功 {task.done} · 跳过 {task.skipped} · 失败 {task.failed}</span>
          </div>
          <p className="muted section-gap">
            当前处理：{task.current_text ?? "（空闲）"}
          </p>
          <p className="muted">数据集目录：<span className="mono">{task.dataset_dir}</span></p>
          {task.failures.length > 0 ? (
            <>
              <h3 className="card-title section-gap">失败明细</h3>
              <ul className="muted">
                {task.failures.map((f) => (
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
