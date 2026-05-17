import { useState, useEffect, useCallback, useRef } from 'react';
import { listAvatars, deleteAvatar, getAvatar, updateAvatar } from '../../services/avatarStorage';
import type { AvatarRecord } from '../../services/avatarStorage';
import {
  useSettingsStore,
  DEFAULT_VRM_TWEAK,
  DEFAULT_ANIMATION_SETTINGS,
  type VRMTweakConfig,
  type AnimationSettings,
} from '../../store/settingsStore';
import { Live2DViewer } from '../Live2D/Live2DViewer';
import { VRMViewer } from '../VRM/VRMViewer';
import { api } from '../../api/client';

interface AvatarManagerProps {
  type: 'live2d' | 'vrm';
  onClose?: () => void;
}

type TabKey = 'model' | 'appearance' | 'lipSync' | 'emotion' | 'animation' | 'render';

export function AvatarManager({ type, onClose }: AvatarManagerProps) {
  const [avatars, setAvatars] = useState<AvatarRecord[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isUploading, setIsUploading] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingName, setEditingName] = useState('');
  const [activeTab, setActiveTab] = useState<TabKey>('model');

  const [previewData, setPreviewData] = useState<ArrayBuffer | undefined>(undefined);
  const [dataVersion, setDataVersion] = useState(0);
  const previewDataRef = useRef<ArrayBuffer | undefined>(undefined);

  const {
    live2d, vrm,
    setLive2DModelId, setVRMModelId,
    setLive2DSettings, setVRMSettings,
  } = useSettingsStore();

  const currentModelId = type === 'live2d' ? live2d.modelId : vrm.modelId;

  const [tweakConfig, setTweakConfig] = useState<VRMTweakConfig>(
    vrm.tweak || { ...DEFAULT_VRM_TWEAK }
  );
  const [animConfig, setAnimConfig] = useState<AnimationSettings>(
    (type === 'live2d' ? live2d.animation : vrm.animation) || { ...DEFAULT_ANIMATION_SETTINGS }
  );
  const [renderScale, setRenderScale] = useState(vrm.renderScale || 1.0);
  const [devicePixelRatio, setDevicePixelRatio] = useState<number | 'auto'>(vrm.devicePixelRatio || 'auto');

  const [live2dScale, setLive2dScale] = useState(live2d.scale);
  const [live2dXOffset, setLive2dXOffset] = useState(live2d.xOffset);
  const [live2dYOffset, setLive2dYOffset] = useState(live2d.yOffset);
  const [vrmScale, setVrmScale] = useState(vrm.scale);
  const [vrmPosition, setVrmPosition] = useState<[number, number, number]>(vrm.position3d);

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

  const loadPreviewModel = useCallback(async (id: string) => {
    try {
      const avatar = await getAvatar(id);
      if (avatar?.data) {
        const ab = await avatar.data.arrayBuffer();
        previewDataRef.current = ab;
        setPreviewData(ab);
        setDataVersion((v) => v + 1);
      }
    } catch (error) {
      console.error('Failed to load preview model:', error);
    }
  }, []);

  useEffect(() => {
    loadAvatars();
  }, [loadAvatars]);

  useEffect(() => {
    if (currentModelId) {
      loadPreviewModel(currentModelId);
    }
  }, [currentModelId, loadPreviewModel]);

  const handleSelect = useCallback(
    async (avatar: AvatarRecord) => {
      if (type === 'live2d') {
        setLive2DModelId(avatar.id);
      } else {
        setVRMModelId(avatar.id);
      }
      await loadPreviewModel(avatar.id);
      loadAvatars();
    },
    [type, setLive2DModelId, setVRMModelId, loadPreviewModel, loadAvatars]
  );

  const handleDelete = useCallback(
    async (id: string) => {
      if (!confirm('确定要删除这个模型吗？')) return;
      try {
        await deleteAvatar(id);
        if (currentModelId === id) {
          if (type === 'live2d') setLive2DModelId(undefined);
          else setVRMModelId(undefined);
          previewDataRef.current = undefined;
          setPreviewData(undefined);
        }
        loadAvatars();
      } catch (error) {
        console.error('Failed to delete avatar:', error);
      }
    },
    [currentModelId, type, setLive2DModelId, setVRMModelId, loadAvatars]
  );

  const handleRename = useCallback(
    async (avatar: AvatarRecord) => {
      if (!editingName.trim()) return;
      try {
        await updateAvatar(avatar.id, { name: editingName.trim() });
        setEditingId(null);
        setEditingName('');
        loadAvatars();
      } catch (error) {
        console.error('Failed to rename avatar:', error);
        alert('重命名失败，请重试');
      }
    },
    [editingName, loadAvatars]
  );

  const handleTweakChange = useCallback((tc: VRMTweakConfig) => {
    setTweakConfig(tc);
    setVRMSettings({ tweak: tc });
  }, [setVRMSettings]);

  const handleAnimChange = useCallback((ac: AnimationSettings) => {
    setAnimConfig(ac);
    if (type === 'live2d') setLive2DSettings({ animation: ac });
    else setVRMSettings({ animation: ac });
  }, [type, setLive2DSettings, setVRMSettings]);

  const handleRenderScaleChange = useCallback((v: number) => {
    setRenderScale(v);
    setVRMSettings({ renderScale: v });
  }, [setVRMSettings]);

  const handleDprChange = useCallback((v: number | 'auto') => {
    setDevicePixelRatio(v);
    setVRMSettings({ devicePixelRatio: v });
  }, [setVRMSettings]);

  const handleReset = useCallback(() => {
    const defaultTweak = { ...DEFAULT_VRM_TWEAK };
    const defaultAnim = { ...DEFAULT_ANIMATION_SETTINGS };
    setTweakConfig(defaultTweak);
    setAnimConfig(defaultAnim);
    setRenderScale(1.0);
    setDevicePixelRatio('auto');
    setLive2dScale(0.3);
    setLive2dXOffset(0);
    setLive2dYOffset(0);
    setVrmScale(1.0);
    setVrmPosition([0, 0, 0]);
    if (type === 'live2d') {
      setLive2DSettings({ animation: defaultAnim, scale: 0.3, xOffset: 0, yOffset: 0 });
    } else {
      setVRMSettings({ tweak: defaultTweak, animation: defaultAnim, renderScale: 1.0, devicePixelRatio: 'auto', scale: 1.0, position3d: [0, 0, 0] });
    }
  }, [type, setLive2DSettings, setVRMSettings]);

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

  const tabs: { key: TabKey; label: string; vrmOnly?: boolean }[] = [
    { key: 'model', label: '模型' },
    { key: 'appearance', label: '外观' },
    { key: 'lipSync', label: '口型' },
    { key: 'emotion', label: '表情' },
    { key: 'animation', label: '动画' },
    { key: 'render', label: '渲染', vrmOnly: true },
  ];

  const visibleTabs = tabs.filter((t) => !t.vrmOnly || type === 'vrm');

  const tc: VRMTweakConfig = { ...DEFAULT_VRM_TWEAK, ...tweakConfig };
  const ac: AnimationSettings = { ...DEFAULT_ANIMATION_SETTINGS, ...animConfig };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="flex w-[calc(100vw-4rem)] h-[calc(100vh-4rem)] bg-[var(--color-bg-primary)] rounded-2xl shadow-2xl overflow-hidden">
        {/* Left: Preview */}
        <div className="flex-1 flex flex-col min-w-0">
          <div className="flex items-center justify-between px-5 py-3 border-b border-[var(--color-border)]">
            <h2 className="text-lg font-semibold text-[var(--color-text-primary)]">
              {type === 'live2d' ? 'Live2D' : 'VRM'} 虚拟形象配置
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
          <div className="flex-1 relative bg-[var(--color-bg-secondary)]">
            {previewData ? (
              type === 'live2d' ? (
                <Live2DViewer
                  modelPath=""
                  modelData={previewData}
                  scale={live2dScale}
                  xOffset={live2dXOffset}
                  yOffset={live2dYOffset}
                  animationConfig={animConfig}
                />
              ) : (
                <VRMViewer
                  modelPath=""
                  modelDataRef={previewDataRef}
                  dataVersion={dataVersion}
                  scale={vrmScale}
                  position={vrmPosition}
                  tweakConfig={tweakConfig}
                  animationConfig={animConfig}
                  renderScale={renderScale}
                  devicePixelRatio={devicePixelRatio}
                />
              )
            ) : (
              <div className="flex flex-col items-center justify-center h-full text-center p-8">
                <svg className="w-20 h-20 mx-auto text-[var(--color-text-tertiary)]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4" />
                </svg>
                <p className="text-[var(--color-text-secondary)] mt-4">请选择或上传模型</p>
                <p className="text-sm text-[var(--color-text-tertiary)] mt-1">在右侧"模型"标签页中管理模型</p>
              </div>
            )}
          </div>
        </div>

        {/* Right: Config Panel */}
        <div className="w-[340px] flex flex-col border-l border-[var(--color-border)] bg-[var(--color-bg-primary)]">
          <div className="flex gap-0.5 px-3 pt-3 pb-2 border-b border-[var(--color-border)] flex-wrap">
            {visibleTabs.map((tab) => (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
                className={`px-2.5 py-1 text-xs rounded-md transition-colors ${
                  activeTab === tab.key
                    ? 'bg-[var(--color-accent)] text-white'
                    : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)] hover:bg-[var(--color-bg-hover)]'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          <div className="flex-1 overflow-y-auto p-3">
            {activeTab === 'model' && (
              <div className="space-y-4">
                <div
                  className={`relative border-2 border-dashed rounded-xl p-6 text-center transition-all cursor-pointer ${
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
                      if (file.size > 50 * 1024 * 1024) {
                        alert('文件大小不能超过 50MB');
                        return;
                      }
                      setIsUploading(true);
                      try {
                        await api.uploadAvatar(file, type, file.name.replace(/\.[^.]+$/, ''), (progress) => {
                          console.log(`Upload progress: ${progress}%`);
                        });
                        loadAvatars();
                      } catch (error) {
                        console.error('Upload failed:', error);
                        alert('上传失败: ' + (error instanceof Error ? error.message : '未知错误'));
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
                      <div className="w-6 h-6 border-2 border-[var(--color-accent)] border-t-transparent rounded-full animate-spin" />
                      <p className="text-xs text-[var(--color-text-secondary)] mt-2">上传中...</p>
                    </div>
                  ) : (
                    <>
                      <svg className="w-8 h-8 mx-auto mb-2 text-[var(--color-text-tertiary)]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                      </svg>
                      <p className="text-xs text-[var(--color-text-secondary)]">点击或拖拽上传模型</p>
                      <p className="text-[10px] text-[var(--color-text-tertiary)] mt-1">
                        {type === 'live2d' ? '.model.json / .zip' : '.vrm'}，最大 50MB
                      </p>
                    </>
                  )}
                </div>

                {isLoading ? (
                  <div className="flex items-center justify-center h-24">
                    <div className="w-6 h-6 border-2 border-[var(--color-accent)] border-t-transparent rounded-full animate-spin" />
                  </div>
                ) : avatars.length === 0 ? (
                  <div className="text-center py-8">
                    <p className="text-sm text-[var(--color-text-tertiary)]">暂无模型</p>
                  </div>
                ) : (
                  <div className="space-y-2">
                    {avatars.map((avatar) => (
                      <div
                        key={avatar.id}
                        className={`p-3 rounded-lg border transition-all ${
                          currentModelId === avatar.id
                            ? 'border-[var(--color-accent)] bg-[var(--color-accent)]/10'
                            : 'border-[var(--color-border)] hover:border-[var(--color-accent)]/50'
                        }`}
                      >
                        <div className="flex items-center justify-between mb-1">
                          {editingId === avatar.id ? (
                            <input
                              type="text"
                              value={editingName}
                              onChange={(e) => setEditingName(e.target.value)}
                              onBlur={() => handleRename(avatar)}
                              onKeyDown={(e) => e.key === 'Enter' && handleRename(avatar)}
                              className="px-2 py-0.5 text-sm bg-[var(--color-bg-tertiary)] border border-[var(--color-border)] rounded flex-1 mr-2"
                              autoFocus
                            />
                          ) : (
                            <span
                              className="text-sm font-medium text-[var(--color-text-primary)] cursor-pointer hover:text-[var(--color-accent)] truncate"
                              onDoubleClick={() => {
                                setEditingId(avatar.id);
                                setEditingName(avatar.name);
                              }}
                            >
                              {avatar.name}
                            </span>
                          )}
                          {currentModelId === avatar.id && (
                            <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-[var(--color-accent)] text-white whitespace-nowrap">
                              使用中
                            </span>
                          )}
                        </div>
                        <div className="text-[10px] text-[var(--color-text-tertiary)] mb-2">
                          {formatSize(avatar.size)} · {formatDate(avatar.createdAt)}
                        </div>
                        <div className="flex gap-1.5">
                          <button
                            onClick={() => loadPreviewModel(avatar.id)}
                            className="flex-1 px-2 py-1 text-[10px] rounded bg-[var(--color-bg-tertiary)] hover:bg-[var(--color-bg-hover)] transition-colors"
                          >
                            预览
                          </button>
                          <button
                            onClick={() => handleSelect(avatar)}
                            disabled={currentModelId === avatar.id}
                            className={`flex-1 px-2 py-1 text-[10px] rounded transition-colors ${
                              currentModelId === avatar.id
                                ? 'bg-[var(--color-bg-tertiary)] text-[var(--color-text-tertiary)] cursor-not-allowed'
                                : 'bg-[var(--color-accent)] text-white hover:opacity-90'
                            }`}
                          >
                            使用
                          </button>
                          <button
                            onClick={() => handleDelete(avatar.id)}
                            className="px-2 py-1 text-[10px] rounded bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-colors"
                          >
                            删除
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {activeTab === 'appearance' && (
              <div className="space-y-3">
                {type === 'live2d' ? (
                  <>
                    <Slider label="缩放" value={live2dScale} min={0.05} max={1} step={0.01}
                      onChange={(v) => { setLive2dScale(v); setLive2DSettings({ scale: v }); }} />
                    <Slider label="X 偏移" value={live2dXOffset} min={-200} max={200} step={1}
                      onChange={(v) => { setLive2dXOffset(v); setLive2DSettings({ xOffset: v }); }} format={v => `${v.toFixed(0)}px`} />
                    <Slider label="Y 偏移" value={live2dYOffset} min={-200} max={200} step={1}
                      onChange={(v) => { setLive2dYOffset(v); setLive2DSettings({ yOffset: v }); }} format={v => `${v.toFixed(0)}px`} />
                    <Toggle label="口型同步" value={live2d.lipSync}
                      onChange={(v) => setLive2DSettings({ lipSync: v })} />
                    <Toggle label="空闲动作" value={live2d.idleMotion}
                      onChange={(v) => setLive2DSettings({ idleMotion: v })} />
                  </>
                ) : (
                  <>
                    <Slider label="缩放" value={vrmScale} min={0.1} max={3} step={0.05}
                      onChange={(v) => { setVrmScale(v); setVRMSettings({ scale: v }); }} />
                    <Slider label="X 位置" value={vrmPosition[0]} min={-5} max={5} step={0.1}
                      onChange={(v) => { const p: [number,number,number] = [v, vrmPosition[1], vrmPosition[2]]; setVrmPosition(p); setVRMSettings({ position3d: p }); }} />
                    <Slider label="Y 位置" value={vrmPosition[1]} min={-5} max={5} step={0.1}
                      onChange={(v) => { const p: [number,number,number] = [vrmPosition[0], v, vrmPosition[2]]; setVrmPosition(p); setVRMSettings({ position3d: p }); }} />
                    <Slider label="Z 位置" value={vrmPosition[2]} min={-5} max={5} step={0.1}
                      onChange={(v) => { const p: [number,number,number] = [vrmPosition[0], vrmPosition[1], v]; setVrmPosition(p); setVRMSettings({ position3d: p }); }} />
                    <Slider label="X 轴旋转" value={tc.modelRotationX} min={-Math.PI} max={Math.PI} step={0.05}
                      onChange={(v) => handleTweakChange({ ...tc, modelRotationX: v })} format={v => `${(v * 180 / Math.PI).toFixed(0)}°`} />
                    <Slider label="Y 轴旋转" value={tc.modelRotationY} min={-Math.PI} max={Math.PI} step={0.05}
                      onChange={(v) => handleTweakChange({ ...tc, modelRotationY: v })} format={v => `${(v * 180 / Math.PI).toFixed(0)}°`} />
                    <Slider label="Z 轴旋转" value={tc.modelRotationZ} min={-Math.PI} max={Math.PI} step={0.05}
                      onChange={(v) => handleTweakChange({ ...tc, modelRotationZ: v })} format={v => `${(v * 180 / Math.PI).toFixed(0)}°`} />
                    <Toggle label="口型同步" value={vrm.lipSync}
                      onChange={(v) => setVRMSettings({ lipSync: v })} />
                    <Toggle label="空闲动画" value={vrm.idleAnimation}
                      onChange={(v) => setVRMSettings({ idleAnimation: v })} />
                    <Toggle label="视线追踪" value={vrm.lookAtMouse}
                      onChange={(v) => setVRMSettings({ lookAtMouse: v })} />
                  </>
                )}
              </div>
            )}

            {activeTab === 'lipSync' && (
              <div className="space-y-3">
                <Slider label="灵敏度" value={ac.lipSyncSensitivity} min={0} max={2} step={0.1}
                  onChange={(v) => handleAnimChange({ ...ac, lipSyncSensitivity: v })} />
                <Slider label="平滑度" value={ac.lipSyncSmoothing} min={0.01} max={1} step={0.05}
                  onChange={(v) => handleAnimChange({ ...ac, lipSyncSmoothing: v })} />
                <div className="text-[var(--color-text-secondary)] text-[10px] mt-1">元音权重</div>
                <Slider label="A" value={ac.vowelWeightA} min={0} max={2} step={0.1}
                  onChange={(v) => handleAnimChange({ ...ac, vowelWeightA: v })} />
                <Slider label="I" value={ac.vowelWeightI} min={0} max={2} step={0.1}
                  onChange={(v) => handleAnimChange({ ...ac, vowelWeightI: v })} />
                <Slider label="U" value={ac.vowelWeightU} min={0} max={2} step={0.1}
                  onChange={(v) => handleAnimChange({ ...ac, vowelWeightU: v })} />
                <Slider label="E" value={ac.vowelWeightE} min={0} max={2} step={0.1}
                  onChange={(v) => handleAnimChange({ ...ac, vowelWeightE: v })} />
                <Slider label="O" value={ac.vowelWeightO} min={0} max={2} step={0.1}
                  onChange={(v) => handleAnimChange({ ...ac, vowelWeightO: v })} />
              </div>
            )}

            {activeTab === 'emotion' && (
              <div className="space-y-3">
                <Slider label="表情强度" value={ac.emotionIntensity} min={0} max={2} step={0.1}
                  onChange={(v) => handleAnimChange({ ...ac, emotionIntensity: v })} />
                <Slider label="持续时间" value={ac.emotionDuration} min={0.5} max={10} step={0.5}
                  onChange={(v) => handleAnimChange({ ...ac, emotionDuration: v })} format={v => `${v.toFixed(1)}s`} />
                <Slider label="恢复速度" value={ac.emotionRecoverSpeed} min={0.1} max={2} step={0.1}
                  onChange={(v) => handleAnimChange({ ...ac, emotionRecoverSpeed: v })} />
              </div>
            )}

            {activeTab === 'animation' && (
              <div className="space-y-3">
                {type === 'vrm' ? (
                  <>
                    <div className="text-[var(--color-text-secondary)] text-[10px]">呼吸</div>
                    <Slider label="频率" value={ac.breathFrequency} min={0.1} max={1} step={0.05}
                      onChange={(v) => handleAnimChange({ ...ac, breathFrequency: v })} />
                    <Slider label="幅度" value={ac.breathAmplitude} min={0} max={0.1} step={0.005}
                      onChange={(v) => handleAnimChange({ ...ac, breathAmplitude: v })} />
                    <div className="text-[var(--color-text-secondary)] text-[10px] mt-1">眨眼</div>
                    <Slider label="间隔" value={ac.blinkInterval} min={1} max={8} step={0.5}
                      onChange={(v) => handleAnimChange({ ...ac, blinkInterval: v })} format={v => `${v.toFixed(1)}s`} />
                    <Slider label="持续时间" value={ac.blinkDuration} min={0.05} max={0.3} step={0.01}
                      onChange={(v) => handleAnimChange({ ...ac, blinkDuration: v })} format={v => `${(v * 1000).toFixed(0)}ms`} />
                    <div className="text-[var(--color-text-secondary)] text-[10px] mt-1">跟随</div>
                    <Slider label="头部速度" value={ac.headFollowSpeed} min={0.5} max={5} step={0.1}
                      onChange={(v) => handleAnimChange({ ...ac, headFollowSpeed: v })} />
                    <Slider label="身体延迟" value={ac.bodyFollowDelay} min={0} max={1} step={0.05}
                      onChange={(v) => handleAnimChange({ ...ac, bodyFollowDelay: v })} />
                  </>
                ) : (
                  <>
                    <div className="text-[var(--color-text-secondary)] text-[10px]">动作</div>
                    <Slider label="触发概率" value={ac.motionTriggerProbability} min={0} max={1} step={0.05}
                      onChange={(v) => handleAnimChange({ ...ac, motionTriggerProbability: v })} />
                    <div className="text-[var(--color-text-secondary)] text-[10px] mt-1">视线</div>
                    <Slider label="跟随速度" value={ac.focusSpeed} min={1} max={5} step={0.1}
                      onChange={(v) => handleAnimChange({ ...ac, focusSpeed: v })} />
                  </>
                )}
              </div>
            )}

            {activeTab === 'render' && type === 'vrm' && (
              <div className="space-y-3">
                <Slider label="渲染分辨率" value={renderScale} min={0.5} max={2} step={0.1}
                  onChange={handleRenderScaleChange} format={v => `${v.toFixed(1)}x`} />
                <div className="text-[var(--color-text-secondary)] text-[10px] mt-1">设备像素比</div>
                <div className="flex gap-1.5">
                  {(['auto', 1, 1.5, 2] as const).map((v) => (
                    <button
                      key={String(v)}
                      onClick={() => handleDprChange(v)}
                      className={`flex-1 px-2 py-1.5 text-[10px] rounded transition-colors ${
                        devicePixelRatio === v
                          ? 'bg-[var(--color-accent)] text-white'
                          : 'bg-[var(--color-bg-tertiary)] text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-hover)]'
                      }`}
                    >
                      {v === 'auto' ? '自动' : `${v}x`}
                    </button>
                  ))}
                </div>
                <div className="text-[var(--color-text-secondary)] text-[10px] mt-1">相机</div>
                <Slider label="X 偏移" value={tc.camera.offsetX} min={-3} max={3} step={0.05}
                  onChange={(v) => handleTweakChange({ ...tc, camera: { ...tc.camera, offsetX: v } })} />
                <Slider label="Y 高度" value={tc.camera.offsetY} min={0} max={4} step={0.05}
                  onChange={(v) => handleTweakChange({ ...tc, camera: { ...tc.camera, offsetY: v } })} />
                <Slider label="Z 距离" value={tc.camera.offsetZ} min={0.5} max={6} step={0.1}
                  onChange={(v) => handleTweakChange({ ...tc, camera: { ...tc.camera, offsetZ: v } })} />
                <Slider label="注视点 Y" value={tc.camera.lookAtY} min={0} max={1.5} step={0.02}
                  onChange={(v) => handleTweakChange({ ...tc, camera: { ...tc.camera, lookAtY: v } })} />
                <div className="text-[var(--color-text-secondary)] text-[10px] mt-1">灯光</div>
                <Slider label="主光强度" value={tc.light.directionalIntensity} min={0} max={5} step={0.1}
                  onChange={(v) => handleTweakChange({ ...tc, light: { ...tc.light, directionalIntensity: v } })} />
                <Slider label="环境光" value={tc.light.ambientIntensity} min={0} max={3} step={0.1}
                  onChange={(v) => handleTweakChange({ ...tc, light: { ...tc.light, ambientIntensity: v } })} />
                <Slider label="补光" value={tc.light.pointIntensity} min={0} max={3} step={0.1}
                  onChange={(v) => handleTweakChange({ ...tc, light: { ...tc.light, pointIntensity: v } })} />
              </div>
            )}
          </div>

          <div className="px-3 py-2 border-t border-[var(--color-border)]">
            <button
              onClick={handleReset}
              className="w-full px-3 py-1.5 text-xs rounded bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)] border border-[var(--color-border)] transition-colors"
            >
              重置所有参数
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function Slider({
  label,
  value,
  min,
  max,
  step,
  onChange,
  format = (v) => v.toFixed(2),
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: number) => void;
  format?: (v: number) => string;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <div className="flex justify-between">
        <span className="text-xs text-[var(--color-text-secondary)]">{label}</span>
        <span className="text-[10px] text-[var(--color-text-tertiary)] tabular-nums w-12 text-right">{format(value)}</span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className="w-full h-1 rounded-full appearance-none cursor-pointer accent-[var(--color-accent)]
          [&::-webkit-slider-runnable-track]:rounded-full [&::-webkit-slider-runnable-track]:h-1
          [&::-webkit-slider-runnable-track]:bg-[var(--color-bg-secondary)]
          [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3
          [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-[var(--color-accent)]
          [&::-webkit-slider-thumb]:mt-[-4px]"
      />
    </div>
  );
}

function Toggle({
  label,
  value,
  onChange,
}: {
  label: string;
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between p-2.5 bg-[var(--color-bg-tertiary)] rounded-lg">
      <span className="text-xs">{label}</span>
      <button
        onClick={() => onChange(!value)}
        className={`w-9 h-5 rounded-full transition-colors ${
          value ? 'bg-[var(--color-accent)]' : 'bg-[var(--color-border)]'
        }`}
      >
        <div
          className={`w-3.5 h-3.5 rounded-full bg-white transition-transform ${
            value ? 'translate-x-4' : 'translate-x-0.5'
          }`}
        />
      </button>
    </div>
  );
}

export default AvatarManager;
