/**
 * Qwen3 参考音频资产管理面板
 *
 * 替代旧 RefAudioPanel（情感参考音频批量生成）。
 * 消费 audioApi（主后端 CX-O-SERVER /api/ref-audio-assets）：
 * - 外部文件上传注册为 source=file 资产
 * - 提示词提交生成注册为 source=prompt 资产
 * - 列表/试听/注释/删除
 */
import { useCallback, useEffect, useState } from 'react';
import { Check, Download, Loader2, Pencil, Trash2, Upload, Wand2 } from 'lucide-react';
import { audioApi } from '@/api/clients/audio';
import type { RefAudioAsset } from '@/api/clients/audio';

export default function RefAudioAssetsPanel() {
  const [assets, setAssets] = useState<RefAudioAsset[]>([]);
  const [currentAssetId, setCurrentAssetId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadRefText, setUploadRefText] = useState('');
  const [uploadNote, setUploadNote] = useState('');
  const [prompt, setPrompt] = useState('');
  const [promptLanguage, setPromptLanguage] = useState('');
  const [editingNote, setEditingNote] = useState<string | null>(null);
  const [editNoteValue, setEditNoteValue] = useState('');

  const loadAssets = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await audioApi.listRefAudioAssets();
      setAssets(res.assets);
      setCurrentAssetId(res.current_asset_id ?? null);
    } catch (e) {
      setError('加载失败');
      console.error('[RefAudioAssetsPanel] list failed:', e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadAssets();
  }, [loadAssets]);

  const handleUpload = async () => {
    if (!uploadFile) return;
    setUploading(true);
    setError(null);
    try {
      await audioApi.uploadRefAudioAsset(uploadFile, uploadRefText || undefined, uploadNote || undefined);
      setUploadFile(null);
      setUploadRefText('');
      setUploadNote('');
      // 重置文件输入
      const el = document.getElementById('ref-asset-upload-input') as HTMLInputElement;
      if (el) el.value = '';
      await loadAssets();
    } catch (e) {
      setError('上传失败');
      console.error('[RefAudioAssetsPanel] upload failed:', e);
    } finally {
      setUploading(false);
    }
  };

  const handleGenerateFromPrompt = async () => {
    if (!prompt.trim()) return;
    setGenerating(true);
    setError(null);
    try {
      await audioApi.generateRefAudioFromPrompt(prompt.trim(), promptLanguage || undefined);
      setPrompt('');
      setPromptLanguage('');
      await loadAssets();
    } catch (e) {
      setError('生成失败');
      console.error('[RefAudioAssetsPanel] generate from prompt failed:', e);
    } finally {
      setGenerating(false);
    }
  };

  const handleDelete = async (assetId: string) => {
    setError(null);
    try {
      await audioApi.deleteRefAudioAsset(assetId);
      await loadAssets();
    } catch (e) {
      setError('删除失败');
      console.error('[RefAudioAssetsPanel] delete failed:', e);
    }
  };

  const handleSetCurrent = async (assetId: string) => {
    setError(null);
    try {
      await audioApi.setCurrentRefAudioAsset(assetId);
      await loadAssets();
    } catch (e) {
      setError('设为当前失败');
      console.error('[RefAudioAssetsPanel] set current failed:', e);
    }
  };

  const handleSaveNote = async (assetId: string) => {
    setError(null);
    try {
      await audioApi.updateRefAudioAssetNote(assetId, editNoteValue);
      setEditingNote(null);
      await loadAssets();
    } catch (e) {
      setError('更新注释失败');
      console.error('[RefAudioAssetsPanel] update note failed:', e);
    }
  };

  const startEditNote = (asset: RefAudioAsset) => {
    setEditingNote(asset.id);
    setEditNoteValue(asset.note || '');
  };

  const assetAudioUrl = (assetId: string) => audioApi.getRefAudioAssetAudioUrl(assetId);

  return (
    <section className="glass-panel space-y-5 p-5">
      {/* 页头说明 */}
      <p className="text-xs text-muted-foreground/70">
        Qwen3 参考音频资产管理 —— 上传外部音频文件或通过提示词生成参考音频，支持试听、注释、设为当前默认、删除。
      </p>

      {/* 错误提示 */}
      {error && (
        <p className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-400">{error}</p>
      )}

      {/* ── 上传外部文件 ── */}
      <div className="space-y-3 rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.04)] p-4">
        <h4 className="flex items-center gap-2 text-sm font-semibold">
          <Upload className="h-4 w-4 text-primary" />
          上传外部音频文件
        </h4>
        <input
          id="ref-asset-upload-input"
          type="file"
          accept=".wav,.mp3,.flac,.opus,.aac,.ogg,.m4a"
          onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)}
          className="w-full text-sm file:mr-3 file:rounded file:border-0 file:bg-primary/20 file:px-3 file:py-1 file:text-xs file:text-primary"
        />
        {uploadFile && (
          <div className="text-xs text-muted-foreground">
            已选: {uploadFile.name} ({(uploadFile.size / 1024).toFixed(1)} KB)
          </div>
        )}
        <input
          value={uploadRefText}
          onChange={(e) => setUploadRefText(e.target.value)}
          placeholder="参考文本（可选）"
          className="w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
        />
        <input
          value={uploadNote}
          onChange={(e) => setUploadNote(e.target.value)}
          placeholder="注释（可选）"
          className="w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
        />
        <button
          type="button"
          onClick={() => void handleUpload()}
          disabled={!uploadFile || uploading}
          className="flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-85 disabled:opacity-50"
        >
          {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
          {uploading ? '上传中...' : '上传注册'}
        </button>
      </div>

      {/* ── 提示词生成 ── */}
      <div className="space-y-3 rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.04)] p-4">
        <h4 className="flex items-center gap-2 text-sm font-semibold">
          <Wand2 className="h-4 w-4 text-primary" />
          提示词生成
        </h4>
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={3}
          placeholder="描述目标音色，例如「温柔可爱的少女音，说话带点撒娇感」"
          className="w-full resize-none rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
        />
        <input
          value={promptLanguage}
          onChange={(e) => setPromptLanguage(e.target.value)}
          placeholder="语言（可选，如 Chinese/English，留空自动识别）"
          className="w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
        />
        <button
          type="button"
          onClick={() => void handleGenerateFromPrompt()}
          disabled={!prompt.trim() || generating}
          className="flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-85 disabled:opacity-50"
        >
          {generating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wand2 className="h-4 w-4" />}
          {generating ? '生成中...' : '生成并注册'}
        </button>
      </div>

      {/* ── 资产列表 ── */}
      <div className="space-y-2">
        <h4 className="flex items-center gap-2 text-sm font-semibold">
          <Download className="h-4 w-4 text-primary" />
          已有资产 ({assets.length})
        </h4>

        {loading && (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        )}

        {!loading && assets.length === 0 && (
          <p className="py-4 text-center text-xs text-muted-foreground">暂无参考音频资产</p>
        )}

        <div className="space-y-2">
          {assets.map((asset) => (
            <div
              key={asset.id}
              className="flex flex-col gap-2 rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.04)] p-3"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0 flex-1 space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="rounded bg-primary/10 px-1.5 py-0.5 text-xs font-medium text-primary">
                      {asset.source === 'prompt' ? '提示词' : '文件'}
                    </span>
                    {currentAssetId === asset.id && (
                      <span className="rounded bg-emerald-500/15 px-1.5 py-0.5 text-xs font-medium text-emerald-400">
                        当前默认
                      </span>
                    )}
                    <span className="truncate text-xs font-mono text-muted-foreground" title={asset.id}>
                      {asset.id}
                    </span>
                  </div>
                  {asset.source === 'prompt' && asset.prompt && (
                    <p className="truncate text-xs text-muted-foreground" title={asset.prompt}>
                      {asset.prompt}
                    </p>
                  )}
                  {asset.source === 'file' && asset.file_name && (
                    <p className="truncate text-xs text-muted-foreground">{asset.file_name}</p>
                  )}
                  {asset.ref_text && (
                    <p className="truncate text-xs text-muted-foreground/70">参考文本: {asset.ref_text}</p>
                  )}
                  {asset.duration_seconds && asset.sample_rate && (
                    <p className="text-xs text-muted-foreground/50">
                      {asset.duration_seconds.toFixed(1)}s · {asset.sample_rate}Hz · {asset.channels || 1}ch · {asset.format || 'wav'}
                    </p>
                  )}
                  {/* 注释编辑 */}
                  {editingNote === asset.id ? (
                    <div className="flex items-center gap-2">
                      <input
                        value={editNoteValue}
                        onChange={(e) => setEditNoteValue(e.target.value)}
                        className="flex-1 rounded border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-2 py-1 text-xs focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
                        autoFocus
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') void handleSaveNote(asset.id);
                          if (e.key === 'Escape') setEditingNote(null);
                        }}
                      />
                      <button
                        type="button"
                        onClick={() => void handleSaveNote(asset.id)}
                        className="text-xs text-primary hover:underline"
                      >
                        保存
                      </button>
                      <button type="button" onClick={() => setEditingNote(null)} className="text-xs text-muted-foreground hover:underline">
                        取消
                      </button>
                    </div>
                  ) : (
                    asset.note && <p className="text-xs text-muted-foreground/70">注释: {asset.note}</p>
                  )}
                </div>
                <div className="flex shrink-0 items-center gap-1.5">
                  <button
                    type="button"
                    onClick={() => void handleSetCurrent(asset.id)}
                    disabled={currentAssetId === asset.id}
                    title={currentAssetId === asset.id ? '已是当前默认' : '设为当前默认'}
                    className="rounded p-1 text-muted-foreground transition-colors hover:text-primary disabled:opacity-40 disabled:hover:text-muted-foreground"
                  >
                    <Check className="h-3.5 w-3.5" />
                  </button>
                  <button
                    type="button"
                    onClick={() => startEditNote(asset)}
                    title="编辑注释"
                    className="rounded p-1 text-muted-foreground transition-colors hover:text-primary"
                  >
                    <Pencil className="h-3.5 w-3.5" />
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleDelete(asset.id)}
                    title="删除"
                    className="rounded p-1 text-muted-foreground transition-colors hover:text-red-400"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
              {/* 试听播放器 */}
              <audio controls preload="none" className="h-8 w-full" src={assetAudioUrl(asset.id)}>
                <track kind="captions" />
              </audio>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}