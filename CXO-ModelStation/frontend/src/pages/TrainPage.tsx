/*
 * 训练控制台页：模型类型切换（So-VITS-SVC / MeloTTS，分段控件），
 * 预处理表单、训练参数表单、训练状态进度轮询（3s）、停止按钮按类型渲染。
 * 训练状态 GET /api/sovits-svc/status、GET /api/melotts/status：progress 取值 0-1；
 * 两类训练共享「同一时间仅一个训练任务」互斥（409 时展示冲突提示）。
 */
import { useCallback, useState } from "react";
import { api, ApiClientError } from "../api/client";
import type { TrainStartRequest } from "../api/client";
import { ErrorBar, NoticeBar, StatusBadge } from "../components/ui";
import { usePolling } from "../hooks/usePolling";

/** 训练模型类型（分段控件切换，持久于组件状态） */
type TrainModelType = "sovits" | "melotts";

const TYPE_OPTIONS: { value: TrainModelType; label: string }[] = [
  { value: "sovits", label: "So-VITS-SVC" },
  { value: "melotts", label: "MeloTTS" },
];

const TYPE_LABELS: Record<TrainModelType, string> = {
  sovits: "So-VITS-SVC",
  melotts: "MeloTTS",
};

function toMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

/** 动作错误统一格式化：409（跨类型训练互斥）附加冲突说明 */
function formatActionError(e: unknown): string {
  const msg = toMessage(e);
  if (e instanceof ApiClientError && e.status === 409) {
    return `训练互斥冲突（同一时间仅允许一个训练任务）：${msg}`;
  }
  return msg;
}

export default function TrainPage() {
  const [modelType, setModelType] = useState<TrainModelType>("sovits");

  // 两类训练状态各自轮询，仅当前类型启用（切换即暂停另一类）
  const sovitsPoll = usePolling(useCallback(() => api.getTrainStatus(), []), {
    intervalMs: 3000,
    enabled: modelType === "sovits",
  });
  const melottsPoll = usePolling(useCallback(() => api.getMelottsStatus(), []), {
    intervalMs: 3000,
    enabled: modelType === "melotts",
  });

  const activePoll = modelType === "sovits" ? sovitsPoll : melottsPoll;
  const status = activePoll.data;
  const error = activePoll.error;
  const stopped = activePoll.stopped;
  const refresh = activePoll.refresh;

  // ---- sovits 表单状态（现状不变）----
  const [prepDir, setPrepDir] = useState("");
  const [prepSpeaker, setPrepSpeaker] = useState("speaker");
  const [epochs, setEpochs] = useState("10000");
  const [batchSize, setBatchSize] = useState("4");
  const [learningRate, setLearningRate] = useState("0.0001");
  const [outputName, setOutputName] = useState("");
  const [trainSpeaker, setTrainSpeaker] = useState("");

  // ---- melotts 表单状态 ----
  const [mPrepDir, setMPrepDir] = useState("");
  const [mPrepSpeaker, setMPrepSpeaker] = useState("speaker");
  const [mEpochs, setMEpochs] = useState("10000");
  const [mBatchSize, setMBatchSize] = useState("4");
  const [mLearningRate, setMLearningRate] = useState("0.0001");
  const [mOutputName, setMOutputName] = useState("");
  const [mLanguage, setMLanguage] = useState("ZH");

  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const running = status?.status === "running" || status?.status === "busy_starting";
  const progressPercent = status
    ? Math.min(100, Math.max(0, Math.round(status.progress * 100)))
    : 0;

  /** 类型切换：清空各自表单错误态与通知 */
  const handleTypeChange = (value: TrainModelType) => {
    if (value === modelType) {
      return;
    }
    setModelType(value);
    setActionError(null);
    setNotice(null);
  };

  /** 校验 epochs/batch_size/learning_rate 数值输入（sovits 与 melotts 共用口径） */
  const validateTrainNumbers = (
    epochsStr: string,
    batchStr: string,
    lrStr: string,
  ): { epochs: number; batch_size: number; learning_rate: number } | null => {
    const epochsNum = Number(epochsStr);
    const batchSizeNum = Number(batchStr);
    const lrNum = Number(lrStr);
    if (!Number.isFinite(epochsNum) || epochsNum < 1) {
      setActionError("epochs 须为 ≥1 的整数");
      return null;
    }
    if (!Number.isFinite(batchSizeNum) || batchSizeNum < 1) {
      setActionError("batch_size 须为 ≥1 的整数");
      return null;
    }
    if (!Number.isFinite(lrNum) || lrNum <= 0) {
      setActionError("learning_rate 须为正数");
      return null;
    }
    return {
      epochs: Math.floor(epochsNum),
      batch_size: Math.floor(batchSizeNum),
      learning_rate: lrNum,
    };
  };

  const handlePreprocess = async () => {
    setActionError(null);
    setNotice(null);
    if (!prepDir.trim()) {
      setActionError("请填写训练数据目录（相对路径锚定 CXO-ModelStation 根，如 data/training/sovits_svc/raw/speaker1）");
      return;
    }
    setBusy(true);
    try {
      const res = await api.preprocess({
        training_data_dir: prepDir.trim(),
        speaker_name: prepSpeaker.trim() || "speaker",
      });
      const entries = Object.entries(res.results);
      const okCount = entries.filter(([, v]) => v.success).length;
      setNotice(`预处理完成（${res.status === "success" ? "全部成功" : "部分成功"}）：${okCount}/${entries.length} 个 speaker 成功`);
    } catch (e) {
      setActionError(formatActionError(e));
    } finally {
      setBusy(false);
    }
  };

  const handleTrain = async () => {
    setActionError(null);
    setNotice(null);
    const nums = validateTrainNumbers(epochs, batchSize, learningRate);
    if (nums === null) {
      return;
    }
    const req: TrainStartRequest = { ...nums };
    if (outputName.trim()) {
      req.output_name = outputName.trim();
    }
    if (trainSpeaker.trim()) {
      req.speaker_name = trainSpeaker.trim();
    }
    setBusy(true);
    try {
      const res = await api.startTrain(req);
      setNotice(`${res.message}（task_id: ${res.task_id.slice(0, 8)}…），进度将自动刷新`);
      refresh();
    } catch (e) {
      setActionError(formatActionError(e));
    } finally {
      setBusy(false);
    }
  };

  const handleMelottsPreprocess = async () => {
    setActionError(null);
    setNotice(null);
    if (!mPrepDir.trim()) {
      setActionError("请填写数据集目录（相对路径锚定 CXO-ModelStation 根，如 data/training/sovits_svc/raw/speaker1）");
      return;
    }
    setBusy(true);
    try {
      const res = await api.melottsPreprocess({
        dataset_dir: mPrepDir.trim(),
        speaker_name: mPrepSpeaker.trim() || "speaker",
      });
      const entries = Object.entries(res.results);
      const okCount = entries.filter(([, v]) => v.success).length;
      setNotice(`MeloTTS 数据准备完成（${res.status === "success" ? "全部成功" : "部分成功"}）：${okCount}/${entries.length} 个 speaker 成功`);
    } catch (e) {
      setActionError(formatActionError(e));
    } finally {
      setBusy(false);
    }
  };

  const handleMelottsTrain = async () => {
    setActionError(null);
    setNotice(null);
    const nums = validateTrainNumbers(mEpochs, mBatchSize, mLearningRate);
    if (nums === null) {
      return;
    }
    const language = mLanguage.trim();
    setBusy(true);
    try {
      const res = await api.startMelottsTrain({
        ...nums,
        ...(mOutputName.trim() ? { output_name: mOutputName.trim() } : {}),
        ...(language ? { language } : {}),
      });
      setNotice(`${res.message}（task_id: ${res.task_id.slice(0, 8)}…），进度将自动刷新`);
      refresh();
    } catch (e) {
      setActionError(formatActionError(e));
    } finally {
      setBusy(false);
    }
  };

  const handleStop = async () => {
    setActionError(null);
    setNotice(null);
    if (!window.confirm(`确认停止当前 ${TYPE_LABELS[modelType]} 训练任务？`)) {
      return;
    }
    setBusy(true);
    try {
      const res =
        modelType === "sovits" ? await api.stopTrain() : await api.stopMelottsTrain();
      setNotice(res.message);
      refresh();
    } catch (e) {
      setActionError(formatActionError(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <header className="page-header">
        <h2>训练控制台</h2>
        <p>数据预处理 → 启动训练 → 进度监控，训练状态每 3 秒自动刷新</p>
      </header>

      <ErrorBar message={error} stopped={stopped} onRetry={refresh} />
      <NoticeBar message={notice} variant="success" />
      <NoticeBar message={actionError} variant="error" />

      <section className="card">
        <h3 className="card-title">模型类型</h3>
        <div className="layout-row" role="group" aria-label="训练模型类型选择">
          {TYPE_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              className={`btn ${modelType === opt.value ? "btn-primary" : "btn-ghost"}`}
              aria-pressed={modelType === opt.value}
              onClick={() => handleTypeChange(opt.value)}
            >
              {opt.label}
            </button>
          ))}
        </div>
        <p className="hint section-gap">
          两类训练共享「同一时间仅一个训练任务」约束：一类训练进行中时，另一类的启动请求会被拒绝（409）
        </p>
      </section>

      <section className="card">
        <h3 className="card-title">
          训练状态（{TYPE_LABELS[modelType]}） <StatusBadge status={status?.status ?? "idle"} />
        </h3>
        <div className="progress-track">
          <div className="progress-fill" style={{ width: `${progressPercent}%` }} />
        </div>
        <div className="progress-meta">
          <span>
            epoch：{status?.epoch ?? 0} / {status?.total_epochs ?? 0}
          </span>
          <span>进度：{progressPercent}%</span>
        </div>
        {status?.message ? <p className="muted">信息：{status.message}</p> : null}
        <div className="form-actions">
          <button
            type="button"
            className="btn btn-danger"
            disabled={busy || !running}
            onClick={handleStop}
          >
            停止训练
          </button>
        </div>
      </section>

      {modelType === "sovits" ? (
        <>
          <section className="card">
            <h3 className="card-title">数据预处理</h3>
            <div className="form-grid">
              <div className="field field-full">
                <label htmlFor="prep-dir">训练数据目录</label>
                <input
                  id="prep-dir"
                  value={prepDir}
                  onChange={(e) => setPrepDir(e.target.value)}
                  placeholder="data/training/sovits_svc/raw/speaker1"
                />
                <span className="hint">相对路径锚定 CXO-ModelStation 根目录；须位于 data/training 之内</span>
              </div>
              <div className="field">
                <label htmlFor="prep-speaker">speaker 名称</label>
                <input
                  id="prep-speaker"
                  value={prepSpeaker}
                  onChange={(e) => setPrepSpeaker(e.target.value)}
                />
              </div>
            </div>
            <div className="form-actions">
              <button type="button" className="btn btn-primary" disabled={busy} onClick={handlePreprocess}>
                开始预处理
              </button>
            </div>
          </section>

          <section className="card">
            <h3 className="card-title">启动训练</h3>
            <div className="form-grid">
              <div className="field">
                <label htmlFor="train-epochs">epochs</label>
                <input
                  id="train-epochs"
                  type="number"
                  min={1}
                  value={epochs}
                  onChange={(e) => setEpochs(e.target.value)}
                />
              </div>
              <div className="field">
                <label htmlFor="train-batch">batch_size</label>
                <input
                  id="train-batch"
                  type="number"
                  min={1}
                  value={batchSize}
                  onChange={(e) => setBatchSize(e.target.value)}
                />
              </div>
              <div className="field">
                <label htmlFor="train-lr">learning_rate</label>
                <input
                  id="train-lr"
                  type="number"
                  step="0.00001"
                  min={0.000001}
                  value={learningRate}
                  onChange={(e) => setLearningRate(e.target.value)}
                />
              </div>
              <div className="field">
                <label htmlFor="train-output">输出模型名（可选）</label>
                <input
                  id="train-output"
                  value={outputName}
                  onChange={(e) => setOutputName(e.target.value)}
                  placeholder="仅字母/数字/下划线/连字符"
                />
              </div>
              <div className="field">
                <label htmlFor="train-speaker">speaker 名称（可选）</label>
                <input
                  id="train-speaker"
                  value={trainSpeaker}
                  onChange={(e) => setTrainSpeaker(e.target.value)}
                  placeholder="默认 speaker"
                />
              </div>
            </div>
            <div className="form-actions">
              <button type="button" className="btn btn-primary" disabled={busy} onClick={handleTrain}>
                开始训练
              </button>
              <span className="hint">训练在后台异步进行，可在上方状态卡监控实时进度</span>
            </div>
          </section>
        </>
      ) : (
        <>
          <section className="card">
            <h3 className="card-title">数据准备（统一数据集 → 训练 filelist）</h3>
            <div className="form-grid">
              <div className="field field-full">
                <label htmlFor="melotts-prep-dir">数据集目录</label>
                <input
                  id="melotts-prep-dir"
                  value={mPrepDir}
                  onChange={(e) => setMPrepDir(e.target.value)}
                  placeholder="data/training/sovits_svc/raw/speaker1"
                />
                <span className="hint">
                  指向统一数据集 speaker 目录（manifest v2 含 text 条目方可生成训练 filelist）；
                  相对路径锚定 CXO-ModelStation 根目录，须位于 data/training 之内
                </span>
              </div>
              <div className="field">
                <label htmlFor="melotts-prep-speaker">speaker 名称</label>
                <input
                  id="melotts-prep-speaker"
                  value={mPrepSpeaker}
                  onChange={(e) => setMPrepSpeaker(e.target.value)}
                />
              </div>
            </div>
            <div className="form-actions">
              <button type="button" className="btn btn-primary" disabled={busy} onClick={handleMelottsPreprocess}>
                开始数据准备
              </button>
            </div>
          </section>

          <section className="card">
            <h3 className="card-title">启动训练（MeloTTS）</h3>
            <div className="form-grid">
              <div className="field">
                <label htmlFor="melotts-train-epochs">epochs</label>
                <input
                  id="melotts-train-epochs"
                  type="number"
                  min={1}
                  value={mEpochs}
                  onChange={(e) => setMEpochs(e.target.value)}
                />
              </div>
              <div className="field">
                <label htmlFor="melotts-train-batch">batch_size</label>
                <input
                  id="melotts-train-batch"
                  type="number"
                  min={1}
                  value={mBatchSize}
                  onChange={(e) => setMBatchSize(e.target.value)}
                />
              </div>
              <div className="field">
                <label htmlFor="melotts-train-lr">learning_rate</label>
                <input
                  id="melotts-train-lr"
                  type="number"
                  step="0.00001"
                  min={0.000001}
                  value={mLearningRate}
                  onChange={(e) => setMLearningRate(e.target.value)}
                />
              </div>
              <div className="field">
                <label htmlFor="melotts-train-output">输出模型名（可选）</label>
                <input
                  id="melotts-train-output"
                  value={mOutputName}
                  onChange={(e) => setMOutputName(e.target.value)}
                  placeholder="仅字母/数字/下划线/连字符"
                />
              </div>
              <div className="field">
                <label htmlFor="melotts-train-language">language（训练语言）</label>
                <input
                  id="melotts-train-language"
                  value={mLanguage}
                  onChange={(e) => setMLanguage(e.target.value)}
                  placeholder="默认 ZH"
                />
              </div>
            </div>
            <div className="form-actions">
              <button type="button" className="btn btn-primary" disabled={busy} onClick={handleMelottsTrain}>
                开始训练
              </button>
              <span className="hint">训练在后台异步进行，可在上方状态卡监控实时进度</span>
            </div>
          </section>
        </>
      )}
    </div>
  );
}
