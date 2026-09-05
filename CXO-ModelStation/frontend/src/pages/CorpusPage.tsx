/*
 * 批量语料生成页：speaker_name + 多行文本（每行一条）+ 引擎选择提交
 * POST /api/datasets/batch-generate 任务（三引擎：voxcpm / cosyvoice3_zero /
 * qwen3_voicedesign，运行时引擎参数经 engine_params 联动），轮询任务进度
 * （done/total/skipped/failed/current_text）。
 */
import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { BatchDatasetRequest, BatchEngine } from "../api/client";
import { ErrorBar, NoticeBar, StatusBadge } from "../components/ui";
import { usePolling } from "../hooks/usePolling";

const ENGINE_OPTIONS: { value: BatchEngine; label: string }[] = [
  { value: "voxcpm", label: "VoxCPM" },
  { value: "cosyvoice3_zero", label: "CosyVoice3 零样本克隆" },
  { value: "qwen3_voicedesign", label: "Qwen3 声音设计" },
];

const MODE_OPTIONS = [
  { value: "design", label: "design（声音设计）" },
  { value: "controllable_clone", label: "controllable_clone（可控克隆）" },
  { value: "ultimate_clone", label: "ultimate_clone（终极克隆）" },
];

function toMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export default function CorpusPage() {
  const [engine, setEngine] = useState<BatchEngine>("voxcpm");
  const [speakerName, setSpeakerName] = useState("");
  const [mode, setMode] = useState("design");
  const [control, setControl] = useState("");
  const [textsText, setTextsText] = useState("");
  const [referenceAudioPath, setReferenceAudioPath] = useState("");
  const [promptAudioPath, setPromptAudioPath] = useState("");
  const [promptText, setPromptText] = useState("");
  // ---- 运行时引擎联动参数（cosyvoice3_zero / qwen3_voicedesign）----
  const [refAudioPath, setRefAudioPath] = useState("");
  const [refText, setRefText] = useState("");
  const [voiceDescription, setVoiceDescription] = useState("");

  const [taskId, setTaskId] = useState<string | null>(null);
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
          ? `批量语料任务完成：新生成 ${task.done} 条，跳过重复 ${task.skipped} 条`
          : `批量语料任务结束（存在失败）：${task.error ?? `失败 ${task.failed} 条`}`,
      );
    }
  }, [task]);

  const handleEngineChange = (value: BatchEngine) => {
    setEngine(value);
    setActionError(null);
  };

  const handleSubmit = async () => {
    setActionError(null);
    setNotice(null);
    if (!speakerName.trim()) {
      setActionError("请填写 speaker 名称");
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

    const body: BatchDatasetRequest = {
      speaker_name: speakerName.trim(),
      texts: lines.map((text) => ({ text })),
      engine,
    };

    if (engine === "voxcpm") {
      // voxcpm 专属参数（现状行为不变）
      if (mode === "controllable_clone" && !referenceAudioPath.trim()) {
        setActionError("controllable_clone 模式需要填写参考音频路径");
        return;
      }
      if (mode === "ultimate_clone" && (!promptAudioPath.trim() || !promptText.trim())) {
        setActionError("ultimate_clone 模式需要填写提示音频路径与提示文本");
        return;
      }
      body.mode = mode;
      if (control.trim()) {
        body.control = control.trim();
      }
      if (mode === "controllable_clone") {
        body.reference_audio_path = referenceAudioPath.trim();
      }
      if (mode === "ultimate_clone") {
        body.prompt_audio_path = promptAudioPath.trim();
        body.prompt_text = promptText.trim();
      }
    } else if (engine === "cosyvoice3_zero") {
      if (!refAudioPath.trim()) {
        setActionError("CosyVoice3 零样本克隆需要填写参考音频路径");
        return;
      }
      body.engine_params = { ref_audio_path: refAudioPath.trim() };
      if (refText.trim()) {
        body.engine_params.ref_text = refText.trim();
      }
    } else {
      // qwen3_voicedesign
      if (!voiceDescription.trim()) {
        setActionError("Qwen3 声音设计需要填写音色描述");
        return;
      }
      body.engine_params = { voice_description: voiceDescription.trim() };
    }

    setBusy(true);
    try {
      const res = await api.submitBatchDataset(body);
      setTaskId(res.task_id);
      setPollingActive(true);
      setNotice(`任务已提交（共 ${res.total} 条），进度将自动刷新`);
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
          用 TTS 引擎（VoxCPM / CosyVoice3 零样本克隆 / Qwen3 声音设计）把文本清单
          批量生成为训练语料，写入对应 speaker 数据集
        </p>
      </header>

      <ErrorBar message={actionError} />

      <section className="card">
        <h3 className="card-title">提交批量任务</h3>
        <div className="form-grid">
          <div className="field field-full">
            <label htmlFor="corpus-engine">生成引擎</label>
            <div className="layout-row" role="group" aria-label="生成引擎选择">
              {ENGINE_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  className={`btn ${engine === opt.value ? "btn-primary" : "btn-ghost"}`}
                  aria-pressed={engine === opt.value}
                  onClick={() => handleEngineChange(opt.value)}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>
          <div className="field">
            <label htmlFor="corpus-speaker">speaker 名称</label>
            <input
              id="corpus-speaker"
              value={speakerName}
              onChange={(e) => setSpeakerName(e.target.value)}
              placeholder="例如 speaker1"
            />
          </div>
          {engine === "voxcpm" ? (
            <>
              <div className="field">
                <label htmlFor="corpus-mode">生成模式</label>
                <select id="corpus-mode" value={mode} onChange={(e) => setMode(e.target.value)}>
                  {MODE_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field field-full">
                <label htmlFor="corpus-control">控制描述（可选，任务级；描述音色/情绪等）</label>
                <input
                  id="corpus-control"
                  value={control}
                  onChange={(e) => setControl(e.target.value)}
                />
              </div>
              {mode === "controllable_clone" ? (
                <div className="field field-full">
                  <label htmlFor="corpus-refaudio">参考音频路径（服务端受控路径）</label>
                  <input
                    id="corpus-refaudio"
                    value={referenceAudioPath}
                    onChange={(e) => setReferenceAudioPath(e.target.value)}
                  />
                </div>
              ) : null}
              {mode === "ultimate_clone" ? (
                <>
                  <div className="field field-full">
                    <label htmlFor="corpus-prompt-audio">提示音频路径（服务端受控路径）</label>
                    <input
                      id="corpus-prompt-audio"
                      value={promptAudioPath}
                      onChange={(e) => setPromptAudioPath(e.target.value)}
                    />
                  </div>
                  <div className="field field-full">
                    <label htmlFor="corpus-prompt-text">提示文本</label>
                    <input
                      id="corpus-prompt-text"
                      value={promptText}
                      onChange={(e) => setPromptText(e.target.value)}
                    />
                  </div>
                </>
              ) : null}
            </>
          ) : null}
          {engine === "cosyvoice3_zero" ? (
            <>
              <div className="field field-full">
                <label htmlFor="corpus-ref-audio">参考音频路径（零样本克隆）</label>
                <input
                  id="corpus-ref-audio"
                  value={refAudioPath}
                  onChange={(e) => setRefAudioPath(e.target.value)}
                  placeholder="如 data/input/ref.wav"
                />
                <span className="hint">
                  文件可先在数据集页导入或置于 data/input/（服务端白名单路径）
                </span>
              </div>
              <div className="field field-full">
                <label htmlFor="corpus-ref-text">参考文本（可选，参考音频的转写内容）</label>
                <input
                  id="corpus-ref-text"
                  value={refText}
                  onChange={(e) => setRefText(e.target.value)}
                />
              </div>
            </>
          ) : null}
          {engine === "qwen3_voicedesign" ? (
            <div className="field field-full">
              <label htmlFor="corpus-voice-description">音色描述（自然语言）</label>
              <textarea
                id="corpus-voice-description"
                value={voiceDescription}
                onChange={(e) => setVoiceDescription(e.target.value)}
                placeholder="例如：年轻女性，声音清亮，语速适中，带轻微东北口音"
              />
            </div>
          ) : null}
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
            提交批量生成
          </button>
          <span className="hint">重复文本（内容+参数一致）会按 MD5 指纹自动跳过，不重复生成</span>
        </div>
      </section>

      <NoticeBar message={notice} variant={task?.status === "failed" ? "error" : "success"} />

      {task ? (
        <section className="card">
          <h3 className="card-title">
            任务进度 <StatusBadge status={task.status} />
          </h3>
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
          <p className="muted">生成引擎：{task.engine}</p>
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
