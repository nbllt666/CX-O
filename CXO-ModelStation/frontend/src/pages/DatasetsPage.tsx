/*
 * 数据集管理页：speaker 目录列表（名称/音频数量/大小/创建时间）、
 * 导入已有音频（multipart 文件直传，支持多选或 zip 包——后端契约不接受客户端路径）、
 * 删除数据集（确认后调用 DELETE）。
 */
import { useCallback, useState } from "react";
import { api } from "../api/client";
import type { DatasetInfo } from "../api/client";
import { ErrorBar, NoticeBar, formatBytes, formatTimestamp } from "../components/ui";
import { usePolling } from "../hooks/usePolling";

function toMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export default function DatasetsPage() {
  const fetcher = useCallback(async () => (await api.listDatasets()).datasets, []);
  const { data: datasets, error, stopped, refresh } = usePolling(fetcher, {
    intervalMs: 5000,
  });

  const [speakerName, setSpeakerName] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const handleFileChange = (fileList: FileList | null) => {
    setFiles(Array.from(fileList ?? []));
  };

  const handleImport = async () => {
    setActionError(null);
    setNotice(null);
    if (!speakerName.trim()) {
      setActionError("请填写 speaker 名称（仅字母/数字/下划线/连字符）");
      return;
    }
    if (files.length === 0) {
      setActionError("请选择要导入的音频文件（支持多选或单个 zip 包）");
      return;
    }
    setBusy(true);
    try {
      const result = await api.importDataset(speakerName.trim(), files);
      const skipNote = result.skipped.length > 0 ? `，zip 内跳过非音频成员 ${result.skipped.length} 个` : "";
      setNotice(`导入成功：${result.imported} 个文件已写入数据集「${result.name}」${skipNote}`);
      setFiles([]);
      refresh();
    } catch (e) {
      setActionError(toMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async (name: string) => {
    setActionError(null);
    setNotice(null);
    if (!window.confirm(`确认删除数据集「${name}」？目录内全部音频将被移除，操作不可恢复。`)) {
      return;
    }
    setBusy(true);
    try {
      await api.deleteDataset(name);
      setNotice(`数据集「${name}」已删除`);
      refresh();
    } catch (e) {
      setActionError(toMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <header className="page-header">
        <h2>数据集管理</h2>
        <p>管理 So-VITS-SVC 训练数据集（speaker 目录），每 5 秒自动刷新</p>
      </header>

      <ErrorBar message={error} stopped={stopped} onRetry={refresh} />

      <section className="card">
        <h3 className="card-title">导入已有音频</h3>
        <div className="form-grid">
          <div className="field">
            <label htmlFor="import-speaker">speaker 名称</label>
            <input
              id="import-speaker"
              value={speakerName}
              onChange={(e) => setSpeakerName(e.target.value)}
              placeholder="例如 speaker1"
            />
          </div>
          <div className="field field-full">
            <label htmlFor="import-files">音频文件（.wav/.mp3/.flac/.ogg，可多选；或单个 .zip 包）</label>
            <input
              id="import-files"
              type="file"
              multiple
              accept=".wav,.mp3,.flac,.ogg,.zip"
              onChange={(e) => handleFileChange(e.target.files)}
            />
            <span className="hint">文件经浏览器直传至后端受控目录，文件名仅取 basename，防路径穿越</span>
          </div>
        </div>
        <div className="form-actions">
          <button type="button" className="btn btn-primary" disabled={busy} onClick={handleImport}>
            导入
          </button>
          {files.length > 0 ? <span className="muted">已选择 {files.length} 个文件</span> : null}
        </div>
      </section>

      <NoticeBar message={notice} variant="success" />
      <NoticeBar message={actionError} variant="error" />

      <section className="card">
        <h3 className="card-title">数据集列表</h3>
        {datasets && datasets.length > 0 ? (
          <table className="data-table">
            <thead>
              <tr>
                <th>数据集名称</th>
                <th>音频数量</th>
                <th>总大小</th>
                <th>创建时间</th>
                <th>manifest</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {datasets.map((d: DatasetInfo) => (
                <tr key={d.name}>
                  <td>{d.name}</td>
                  <td>{d.file_count}</td>
                  <td>{formatBytes(d.total_size_bytes)}</td>
                  <td className="muted">{formatTimestamp(d.created_at)}</td>
                  <td>{d.has_manifest ? "有" : "无"}</td>
                  <td>
                    <button
                      type="button"
                      className="btn btn-danger btn-small"
                      disabled={busy}
                      onClick={() => handleDelete(d.name)}
                    >
                      删除
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="empty-tip">暂无数据集，可先在上方导入音频或前往「批量语料生成」</p>
        )}
      </section>
    </div>
  );
}
