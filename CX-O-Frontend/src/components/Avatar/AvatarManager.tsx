import { useState, useEffect, useCallback, useRef } from 'react';
import { listAvatars, deleteAvatar, getAvatar, saveAvatar } from '../../services/avatarStorage';
import type { AvatarRecord } from '../../services/avatarStorage';
import { useSettingsStore } from '../../store/settingsStore';
import { Live2DViewer } from '../Live2D/Live2DViewer';
import { VRMViewer, DEFAULT_TWEAK_CONFIG, type VRMTweakConfig } from '../VRM/VRMViewer';
import { VRMTweakPanel } from '../VRM/VRMTweakPanel';

interface AvatarManagerProps {
  type: 'live2d' | 'vrm';
  onClose?: () => void;
}

interface PreviewState {
  avatar: AvatarRecord | null;
  dataVersion: number;
  tweakConfig: VRMTweakConfig;
}

export function AvatarManager({ type, onClose }: AvatarManagerProps) {
  const [avatars, setAvatars] = useState<AvatarRecord[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [previewState, setPreviewState] = useState<PreviewState>({
    avatar: null,
    dataVersion: 0,
    tweakConfig: { ...DEFAULT_TWEAK_CONFIG },
  });
  const previewDataRef = useRef<ArrayBuffer | undefined>(undefined);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingName, setEditingName] = useState('');
  const [isUploading, setIsUploading] = useState(false);

  const { live2d, vrm, setLive2DModelId, setVRMModelId, setVRMSettings } = useSettingsStore();
  const currentModelId = type === 'live2d' ? live2d.modelId : vrm.modelId;

  const loadAvatars = useCallback(async () => {
    setIsLoading(true);
    try {
      const allAvatars = await listAvatars();
      setAvatars(allAvatars.filter((a) => a.type === type));
    } catch (error) {
      console.error('Failed to load avatars:', error);
    } finally {
      setIsLoading(false);
    }
  }, [type]);

  useEffect(() => {
    loadAvatars();
  }, [loadAvatars]);

  const handleSelect = useCallback(
    (avatar: AvatarRecord) => {
      if (type === 'live2d') {
        setLive2DModelId(avatar.id);
      } else {
        setVRMModelId(avatar.id);
      }
      loadAvatars();
    },
    [type, setLive2DModelId, setVRMModelId, loadAvatars]
  );

  const handleDelete = useCallback(
    async (id: string) => {
      if (!confirm('确定要删除这个模型吗？')) return;

      try {
        await deleteAvatar(id);
        if (currentModelId === id) {
          if (type === 'live2d') {
            setLive2DModelId(undefined);
          } else {
            setVRMModelId(undefined);
          }
        }
        loadAvatars();
        if (previewState.avatar?.id === id) {
          setPreviewState(prev => ({ ...prev, avatar: null }));
        }
      } catch (error) {
        console.error('Failed to delete avatar:', error);
      }
    },
    [currentModelId, type, setLive2DModelId, setVRMModelId, loadAvatars, previewState.avatar]
  );

  const handlePreview = useCallback(async (avatar: AvatarRecord) => {
    const fullAvatar = await getAvatar(avatar.id);
    if (fullAvatar) {
      const arrayBuffer = await fullAvatar.data.arrayBuffer();
      previewDataRef.current = arrayBuffer;
      setPreviewState(prev => ({
        avatar: fullAvatar,
        dataVersion: prev.dataVersion + 1,
        tweakConfig: { ...DEFAULT_TWEAK_CONFIG },
      }));
    }
  }, []);

  const handleRename = useCallback(
    async (avatar: AvatarRecord) => {
      if (!editingName.trim()) return;
      const updated: AvatarRecord = { ...avatar, name: editingName.trim() };
      await deleteAvatar(avatar.id);
      await import('../../services/avatarStorage').then((m) => m.saveAvatar(updated));
      setEditingId(null);
      setEditingName('');
      loadAvatars();
    },
    [editingName, loadAvatars]
  );

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const formatDate = (timestamp: number) => {
    return new Date(timestamp).toLocaleDateString('zh-CN', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="w-full max-w-3xl max-h-[80vh] bg-[var(--color-bg-primary)] rounded-2xl shadow-2xl overflow-hidden flex flex-col">
        <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--color-border)]">
          <h2 className="text-lg font-semibold text-[var(--color-text-primary)]">
            {type === 'live2d' ? 'Live2D' : 'VRM'} 模型管理
          </h2>
          <button
            onClick={onClose}
            className="p-2 rounded-lg hover:bg-[var(--color-bg-hover)] transition-colors"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="flex-1 overflow-auto p-6">
          <div className="mb-6">
            <h3 className="text-sm font-medium text-[var(--color-text-secondary)] mb-3">上传模型</h3>
            <div
              className={`relative border-2 border-dashed rounded-xl p-8 text-center transition-all cursor-pointer ${
                isUploading
                  ? 'border-[var(--color-accent)] bg-[var(--color-accent)]/10'
                  : 'border-[var(--color-border)] hover:border-[var(--color-accent)]/50'
              }`}
            >
              <input
                type="file"
                accept={type === 'live2d' ? '.model.json,.model3.json,.zip' : '.vrm'}
                onChange={async (e) => {
                  const file = e.target.files?.[0];
                  if (!file) return;

                  const maxSize = 50 * 1024 * 1024;
                  if (file.size > maxSize) {
                    alert('文件大小不能超过 50MB');
                    return;
                  }

                  setIsUploading(true);
                  try {
                    const arrayBuffer = await file.arrayBuffer();
                    const blob = new Blob([arrayBuffer], { type: 'application/octet-stream' });

                    const avatar: AvatarRecord = {
                      id: crypto.randomUUID(),
                      name: file.name.replace(/\.[^.]+$/, ''),
                      type,
                      data: blob,
                      createdAt: Date.now(),
                      size: file.size,
                    };

                    await saveAvatar(avatar);
                    loadAvatars();
                  } catch (error) {
                    console.error('Upload failed:', error);
                    alert('上传失败');
                  } finally {
                    setIsUploading(false);
                  }
                  e.target.value = '';
                }}
                className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
                disabled={isUploading}
              />
              {isUploading ? (
                <div className="flex flex-col items-center">
                  <div className="w-8 h-8 border-2 border-[var(--color-accent)] border-t-transparent rounded-full animate-spin" />
                  <p className="text-sm text-[var(--color-text-secondary)] mt-2">上传中...</p>
                </div>
              ) : (
                <>
                  <div className="w-10 h-10 mx-auto mb-2 text-[var(--color-text-tertiary)]">
                    <svg fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                    </svg>
                  </div>
                  <p className="text-sm text-[var(--color-text-secondary)]">点击或拖拽上传模型</p>
                  <p className="text-xs text-[var(--color-text-tertiary)] mt-1">
                    {type === 'live2d' ? '支持 .model.json 或 .zip 文件' : '支持 .vrm 文件'}，最大 50MB
                  </p>
                </>
              )}
            </div>
          </div>

          <h3 className="text-sm font-medium text-[var(--color-text-secondary)] mb-3">已上传模型</h3>

          {isLoading ? (
            <div className="flex items-center justify-center h-40">
              <div className="w-8 h-8 border-2 border-[var(--color-accent)] border-t-transparent rounded-full animate-spin" />
            </div>
          ) : avatars.length === 0 ? (
            <div className="text-center py-12">
              <div className="w-16 h-16 mx-auto mb-4 text-[var(--color-text-tertiary)]">
                <svg fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={1.5}
                    d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4"
                  />
                </svg>
              </div>
              <p className="text-[var(--color-text-secondary)]">暂无上传的模型</p>
              <p className="text-sm text-[var(--color-text-tertiary)] mt-1">请使用上方上传区域添加模型</p>
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-4">
              {avatars.map((avatar) => (
                <div
                  key={avatar.id}
                  className={`p-4 rounded-xl border transition-all ${
                    currentModelId === avatar.id
                      ? 'border-[var(--color-accent)] bg-[var(--color-accent)]/10'
                      : 'border-[var(--color-border)] hover:border-[var(--color-accent)]/50'
                  }`}
                >
                  <div className="flex items-start justify-between mb-2">
                    {editingId === avatar.id ? (
                      <input
                        type="text"
                        value={editingName}
                        onChange={(e) => setEditingName(e.target.value)}
                        onBlur={() => handleRename(avatar)}
                        onKeyDown={(e) => e.key === 'Enter' && handleRename(avatar)}
                        className="px-2 py-1 text-sm bg-[var(--color-bg-tertiary)] border border-[var(--color-border)] rounded"
                        autoFocus
                      />
                    ) : (
                      <h3
                        className="font-medium text-[var(--color-text-primary)] cursor-pointer hover:text-[var(--color-accent)]"
                        onDoubleClick={() => {
                          setEditingId(avatar.id);
                          setEditingName(avatar.name);
                        }}
                      >
                        {avatar.name}
                      </h3>
                    )}
                    {currentModelId === avatar.id && (
                      <span className="text-xs px-2 py-0.5 rounded-full bg-[var(--color-accent)] text-white">
                        使用中
                      </span>
                    )}
                  </div>

                  <div className="text-xs text-[var(--color-text-tertiary)] mb-3">
                    {formatSize(avatar.size)} · {formatDate(avatar.createdAt)}
                  </div>

                  <div className="flex gap-2">
                    <button
                      onClick={() => handlePreview(avatar)}
                      className="flex-1 px-3 py-1.5 text-xs rounded-lg bg-[var(--color-bg-tertiary)] hover:bg-[var(--color-bg-hover)] transition-colors"
                    >
                      预览
                    </button>
                    <button
                      onClick={() => handleSelect(avatar)}
                      disabled={currentModelId === avatar.id}
                      className={`flex-1 px-3 py-1.5 text-xs rounded-lg transition-colors ${
                        currentModelId === avatar.id
                          ? 'bg-[var(--color-bg-tertiary)] text-[var(--color-text-tertiary)] cursor-not-allowed'
                          : 'bg-[var(--color-accent)] text-white hover:opacity-90'
                      }`}
                    >
                      使用
                    </button>
                    <button
                      onClick={() => handleDelete(avatar.id)}
                      className="px-3 py-1.5 text-xs rounded-lg bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-colors"
                    >
                      删除
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {previewState.avatar && previewDataRef.current && (
          <div className="fixed inset-0 z-60 flex items-center justify-center bg-black/70" onClick={() => { setPreviewState(prev => ({ ...prev, avatar: null })); previewDataRef.current = undefined; }}>
            <div
              className="flex bg-[var(--color-bg-secondary)] rounded-xl overflow-hidden shadow-2xl"
              style={{ width: 680, height: 440 }}
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex-1 relative" style={{ width: 440, height: 440 }}>
                {previewState.avatar.type === 'live2d' ? (
                  <Live2DViewer
                    modelPath=""
                    modelData={previewDataRef.current}
                    scale={0.3}
                  />
                ) : (
                  <VRMViewer
                    modelPath=""
                    modelDataRef={previewDataRef}
                    dataVersion={previewState.dataVersion}
                    scale={1.0}
                    tweakConfig={previewState.tweakConfig}
                  />
                )}
              </div>
              {previewState.avatar.type === 'vrm' && (
                <div className="w-[240px] p-3 border-l border-[var(--color-border)] flex flex-col">
                  <div className="text-sm font-medium text-[var(--color-text-primary)] mb-2">参数调节</div>
                  <VRMTweakPanel
                    config={previewState.tweakConfig}
                    onChange={(tc) => setPreviewState(prev => ({ ...prev, tweakConfig: tc }))}
                    onApply={() => {
                      const tc = previewState.tweakConfig;
                      setVRMSettings({ tweak: tc });
                      console.log('[AvatarManager] Applied tweak config to settings:', tc);
                    }}
                    onReset={() => setPreviewState(prev => ({ ...prev, tweakConfig: { ...DEFAULT_TWEAK_CONFIG } }))}
                  />
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default AvatarManager;
