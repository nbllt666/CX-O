/*
 * 模型库页：模型列表按类型分组（So-VITS-SVC / MeloTTS）、选择模型 + 试听推理、
 * 结果内嵌播放。MeloTTS 组本期仅展示列表与「暂不支持试听」提示（spec 冻结：
 * melotts infer 不在本期）；后端 melotts 接口未就绪时该组降级提示，不影响 sovits 组。
 * 音频来源（sovits 试听）：
 * ① 从数据集目录快捷构造（speaker + 文件名 → 训练数据目录内相对路径，可先经
 *    /api/audio-files/datasets/ 预览确认文件存在）；
 * ② 手输服务端音频路径（须位于训练数据目录或 data/input 白名单内）。
 * 试听结果 audio_url 挂 /api/audio-files/audition/ 受控目录。
 */
import { useCallback, useState } from "react";
import { api } from "../api/client";
import type { InferResult, MelottsModelInfo, ModelInfo } from "../api/client";
import { ErrorBar, NoticeBar, formatEpochTime } from "../components/ui";
import { usePolling } from "../hooks/usePolling";

const DATASET_ROOT_HINT = "data/training/sovits_svc/raw";

function toMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

function baseName(path: string | null): string {
  if (!path) return "-";
  const normalized = path.replace(/\\/g, "/");
  return normalized.split("/").pop() || path;
}

export default function ModelsPage() {
  // ---- So-VITS-SVC 模型组（现有能力不变：选择 + 试听推理）----
  const modelsFetcher = useCallback(async () => (await api.listModels()).models, []);
  const { data: models, error, stopped, refresh } = usePolling(modelsFetcher, {
    intervalMs: 5000,
  });

  // ---- MeloTTS 模型组（独立轮询，接口未就绪时仅本组降级提示）----
  const melottsModelsFetcher = useCallback(
    async () => (await api.listMelottsModels()).models,
    [],
  );
  const {
    data: melottsModels,
    error: melottsError,
    stopped: melottsStopped,
  } = usePolling(melottsModelsFetcher, { intervalMs: 10000 });

  const datasetsFetcher = useCallback(async () => (await api.listDatasets()).datasets, []);
  const { data: datasets } = usePolling(datasetsFetcher, { intervalMs: 10000 });

  const [selectedModel, setSelectedModel] = useState<ModelInfo | null>(null);
  const [audioPath, setAudioPath] = useState("");
  const [helperSpeaker, setHelperSpeaker] = useState("");
  const [helperFile, setHelperFile] = useState("");
  const [speakerId, setSpeakerId] = useState("0");
  const [transpose, setTranspose] = useState("0");
  const [clusterModelPath, setClusterModelPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [result, setResult] = useState<InferResult | null>(null);

  const handleSelectModel = (model: ModelInfo) => {
    setSelectedModel(model);
    setActionError(null);
  };

  const handleFillFromDataset = () => {
    setActionError(null);
    if (!helperSpeaker) {
      setActionError("请先选择数据集（speaker）");
      return;
    }
    if (!helperFile.trim()) {
      setActionError("请填写数据集内的音频文件名（如 0001_ab12cd34.wav）");
      return;
    }
    setAudioPath(`${DATASET_ROOT_HINT}/${helperSpeaker}/${helperFile.trim()}`);
  };

  const previewUrl =
    helperSpeaker && helperFile.trim()
      ? api.getAudioFileUrl("datasets", helperSpeaker, helperFile.trim())
      : null;

  const handleInfer = async () => {
    setActionError(null);
    setNotice(null);
    setResult(null);
    if (!selectedModel) {
      setActionError("请先在列表中选择一个模型");
      return;
    }
    if (!audioPath.trim()) {
      setActionError("请填写音频路径（从数据集快捷填入或手输服务端路径）");
      return;
    }
    const speakerIdNum = Number(speakerId);
    const transposeNum = Number(transpose);
    if (!Number.isFinite(speakerIdNum) || speakerIdNum < 0) {
      setActionError("speaker_id 须为 ≥0 的整数");
      return;
    }
    if (!Number.isFinite(transposeNum)) {
      setActionError("transpose 须为整数（正数升调，负数降调）");
      return;
    }
    setBusy(true);
    try {
      const res = await api.infer({
        audio_path: audioPath.trim(),
        model_path: selectedModel.g_model ?? selectedModel.path,
        speaker_id: Math.floor(speakerIdNum),
        transpose: Math.round(transposeNum),
        ...(clusterModelPath.trim() ? { cluster_model_path: clusterModelPath.trim() } : {}),
      });
      setResult(res);
      setNotice("试听推理完成，可在下方播放结果");
    } catch (e) {
      setActionError(toMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <header className="page-header">
        <h2>模型库</h2>
        <p>已训练模型列表（按类型分组）与试听推理，每 5 秒自动刷新</p>
      </header>

      <ErrorBar message={error} stopped={stopped} onRetry={refresh} />
      <NoticeBar message={notice} variant="success" />
      <NoticeBar message={actionError} variant="error" />

      {/* ---- So-VITS-SVC 模型组 ---- */}
      <section className="card">
        <h3 className="card-title">
          模型列表（So-VITS-SVC）{selectedModel ? `（已选：${selectedModel.name}）` : ""}
        </h3>
        {models && models.length > 0 ? (
          <table className="data-table">
            <thead>
              <tr>
                <th>模型名称</th>
                <th>更新时间</th>
                <th>G 模型</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {models.map((m: ModelInfo) => (
                <tr key={m.path} className={selectedModel?.path === m.path ? "row-selected" : undefined}>
                  <td>{m.name}</td>
                  <td className="muted">{formatEpochTime(m.created)}</td>
                  <td className="mono">{baseName(m.g_model)}</td>
                  <td>
                    <button
                      type="button"
                      className="btn btn-ghost btn-small"
                      onClick={() => handleSelectModel(m)}
                    >
                      选择
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="empty-tip">暂无已训练模型，请先在「训练控制台」完成训练</p>
        )}
      </section>

      {/* ---- MeloTTS 模型组（本期无 infer：仅列表 + 提示）---- */}
      <section className="card">
        <h3 className="card-title">模型列表（MeloTTS）</h3>
        <p className="hint">MeloTTS 模型暂不支持试听（推理能力不在本期范围）</p>
        {melottsError ? (
          <p className="muted" role="status">
            MeloTTS 模型接口未就绪（后端可能尚未部署或服务不可达）：{melottsError}
            {melottsStopped ? "（自动刷新已停止）" : ""}
          </p>
        ) : melottsModels && melottsModels.length > 0 ? (
          <table className="data-table">
            <thead>
              <tr>
                <th>模型名称</th>
                <th>创建时间</th>
                <th>试听</th>
              </tr>
            </thead>
            <tbody>
              {melottsModels.map((m: MelottsModelInfo) => (
                <tr key={m.path}>
                  <td>{m.name}</td>
                  <td className="muted">{formatEpochTime(m.created)}</td>
                  <td className="muted">暂不支持试听</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : melottsModels ? (
          <p className="empty-tip">
            暂无 MeloTTS 模型，请先在「训练控制台」切换到 MeloTTS 完成训练
          </p>
        ) : (
          <p className="muted">加载中…</p>
        )}
      </section>

      <section className="card">
        <h3 className="card-title">试听推理</h3>
        <div className="form-grid">
          <div className="field">
            <label htmlFor="infer-dataset">从数据集选择音频（可选）</label>
            <select
              id="infer-dataset"
              value={helperSpeaker}
              onChange={(e) => setHelperSpeaker(e.target.value)}
            >
              <option value="">— 选择 speaker 数据集 —</option>
              {(datasets ?? []).map((d) => (
                <option key={d.name} value={d.name}>
                  {d.name}（{d.file_count} 个音频）
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="infer-file">数据集内文件名</label>
            <input
              id="infer-file"
              value={helperFile}
              onChange={(e) => setHelperFile(e.target.value)}
              placeholder="0001_ab12cd34.wav"
            />
          </div>
          <div className="field field-full">
            <label htmlFor="infer-audio-path">音频路径（服务端路径）</label>
            <div className="layout-row">
              <input
                id="infer-audio-path"
                value={audioPath}
                onChange={(e) => setAudioPath(e.target.value)}
                style={{ flex: 1, minWidth: 260 }}
                placeholder={`${DATASET_ROOT_HINT}/speaker1/0001.wav 或绝对路径`}
              />
              <button type="button" className="btn btn-ghost" onClick={handleFillFromDataset}>
                从数据集填入
              </button>
            </div>
            <span className="hint">
              须位于训练数据目录或 data/input 白名单内；相对路径以服务端工作目录为基准，若后端校验失败请改用绝对路径
            </span>
          </div>
          {previewUrl ? (
            <div className="field field-full">
              <label>推理前预览（源音频）</label>
              <audio className="audio-player" controls src={previewUrl} />
            </div>
          ) : null}
          <div className="field">
            <label htmlFor="infer-speaker-id">speaker_id</label>
            <input
              id="infer-speaker-id"
              type="number"
              min={0}
              value={speakerId}
              onChange={(e) => setSpeakerId(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="infer-transpose">transpose（变调半音）</label>
            <input
              id="infer-transpose"
              type="number"
              value={transpose}
              onChange={(e) => setTranspose(e.target.value)}
            />
          </div>
          <div className="field field-full">
            <label htmlFor="infer-cluster">cluster_model_path（可选，聚类模型路径）</label>
            <input
              id="infer-cluster"
              value={clusterModelPath}
              onChange={(e) => setClusterModelPath(e.target.value)}
            />
          </div>
        </div>
        <div className="form-actions">
          <button type="button" className="btn btn-primary" disabled={busy} onClick={handleInfer}>
            开始试听推理
          </button>
        </div>
        {result ? (
          <div className="section-gap">
            <p className="muted">
              输出文件：<span className="mono">{result.output_filename}</span>
            </p>
            <audio className="audio-player" controls src={result.audio_url} />
          </div>
        ) : null}
      </section>
    </div>
  );
}
