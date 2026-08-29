/**
 * 设置页（SubTask 6.5）：虚拟形象 / 直播 / 后端地址 / 音频 / 视觉采集 五区块。
 *
 * 边界（tasks.md 执行期约束，stores 接口冻结只消费）：
 * - 头像参数读写 settingsStore（setAvatarType / setLive2DSettings / setVRMSettings），改动即时生效；
 * - 直播区块查询 healthApi.getLiveClientStatus() 并可断开弹幕客户端；
 * - 后端地址显示当前生效地址，保存时先探测 /health，成功后经 setBackendUrl/setWsUrl 持久化
 *   （Electron 走主进程 IPC，浏览器回退 localStorage）；
 * - 音频区块读写 audioStore（micEnabled / ttsVolume / micGain / danmakuVoiceEnabled）；
 * - 视觉采集区块显示 captureStore 会话态（screenActive / cameraActive）并持久化帧节奏
 *   （frameMode / frameIntervalSec）；实际采集由桌宠窗执行（settings.capture.petNote 提示）。
 * 主题/语言切换在 ManagementLayout 顶栏，本页不重复。
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Activity,
  Bot,
  Camera,
  Database,
  KeyRound,
  Link2,
  Mic,
  MonitorPlay,
  Plug,
  Radio,
  RefreshCw,
  Rocket,
  Search,
  Server,
  Share2,
  Sparkles,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { useSettingsStore } from '@/store/settingsStore';
import type { AvatarType } from '@/store/settingsStore';
import { useAudioStore } from '@/store/audioStore';
import {
  MAX_FRAME_INTERVAL_SEC,
  MIN_FRAME_INTERVAL_SEC,
  useCaptureStore,
} from '@/store/captureStore';
import type { CaptureFrameMode } from '@/store/captureStore';
import { healthApi } from '@/api/clients/health';
import { configApi } from '@/api/clients/config';
import { tunerApi } from '@/api/clients/tuner';
import type { TunerAdapter, TunerStats, TunerTrainStatus } from '@/api/clients/tuner';
import { discoveryApi } from '@/api/clients/discovery';
import type { DiscoveredBackend } from '@/api/clients/discovery';
import { subscribeConfigChanged } from '@/lib/configEvents';
import { serviceApi } from '@/api/clients/service';
import { graphApi } from '@/api/clients/graph';
import { cxfcApi } from '@/api/clients/cxfc';
import type { CxfcPlugin, CxfcSkill } from '@/api/types';
import {
  DEFAULT_BACKEND_URL,
  getApiBaseUrl,
  getWsBaseUrl,
  setBackendUrl,
  setWsUrl,
  STORAGE_KEYS,
} from '@/api/base';
import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui-v2';
import { isElectron } from '@/lib/isElectron';
import { DEFAULT_VRM_MODEL_PATH, pickModelFile } from '@/lib/vrmModelSource';

// ── 通用小部件 ──

function Section(props: {
  icon: LucideIcon;
  title: string;
  desc: string;
  children: React.ReactNode;
}) {
  const Icon = props.icon;
  return (
    <section className="glass-panel p-5">
      <h2 className="mb-1 flex items-center gap-2 text-base font-semibold">
        <Icon className="h-4 w-4 text-primary" />
        {props.title}
      </h2>
      <p className="mb-4 text-xs text-muted-foreground">{props.desc}</p>
      <div className="space-y-2">{props.children}</div>
    </section>
  );
}

function Row(props: { label: string; desc?: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.04)] px-3 py-2">
      <div className="min-w-0">
        <p className="text-sm">{props.label}</p>
        {props.desc && <p className="text-xs text-muted-foreground">{props.desc}</p>}
      </div>
      <div className="flex shrink-0 items-center gap-2">{props.children}</div>
    </div>
  );
}

function Toggle(props: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={props.checked}
      aria-label={props.label}
      onClick={() => props.onChange(!props.checked)}
      className={cn(
        'relative h-6 w-11 rounded-full transition-colors duration-fast',
        props.checked ? 'bg-primary' : 'bg-[rgba(255,255,255,0.12)]',
      )}
    >
      <span
        className={cn(
          'absolute top-0.5 h-5 w-5 rounded-full bg-white transition-all duration-fast',
          props.checked ? 'left-[1.375rem]' : 'left-0.5',
        )}
      />
    </button>
  );
}

function SliderField(props: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  format: (v: number) => string;
  onChange: (v: number) => void;
}) {
  return (
    <Row label={props.label}>
      <input
        type="range"
        aria-label={props.label}
        min={props.min}
        max={props.max}
        step={props.step}
        value={props.value}
        onChange={(e) => props.onChange(Number(e.target.value))}
        className="w-40 accent-primary"
      />
      <span className="w-12 text-right text-xs tabular-nums text-muted-foreground">
        {props.format(props.value)}
      </span>
    </Row>
  );
}

function NumberField(props: {
  label: string;
  value: number;
  step?: number;
  onChange: (v: number) => void;
}) {
  return (
    <Row label={props.label}>
      <input
        type="number"
        aria-label={props.label}
        value={props.value}
        step={props.step ?? 1}
        onChange={(e) => {
          const v = Number(e.target.value);
          props.onChange(Number.isNaN(v) ? 0 : v);
        }}
        className="w-24 rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-2 py-1 text-right text-sm tabular-nums focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
      />
    </Row>
  );
}

function Segmented<T extends string>(props: {
  options: Array<{ value: T; label: string }>;
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div className="flex overflow-hidden rounded-lg border border-[var(--glass-border)]">
      {props.options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          onClick={() => props.onChange(opt.value)}
          className={cn(
            'px-3 py-1.5 text-xs transition-colors duration-fast',
            props.value === opt.value
              ? 'bg-primary/20 font-medium text-primary'
              : 'text-muted-foreground hover:bg-[rgba(255,255,255,0.06)]',
          )}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

// ── 通用小部件（新配置区块追加） ──

function TextField(props: {
  label: string;
  value: string;
  type?: string;
  placeholder?: string;
  onChange: (v: string) => void;
}) {
  return (
    <Row label={props.label}>
      <input
        type={props.type ?? 'text'}
        aria-label={props.label}
        value={props.value}
        placeholder={props.placeholder}
        onChange={(e) => props.onChange(e.target.value)}
        className="w-60 rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-2 py-1 text-sm placeholder:text-[rgba(255,255,255,0.3)] focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
      />
    </Row>
  );
}

function SelectField(props: {
  label: string;
  value: string;
  options: Array<{ value: string; label: string }>;
  onChange: (v: string) => void;
}) {
  return (
    <Row label={props.label}>
      <select
        aria-label={props.label}
        value={props.value}
        onChange={(e) => props.onChange(e.target.value)}
        className="w-44 rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-2 py-1 text-sm focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
      >
        {props.options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </Row>
  );
}

function TextAreaField(props: { value: string }) {
  return (
    <pre className="h-44 overflow-auto whitespace-pre-wrap rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.04)] p-3 font-mono text-xs text-muted-foreground">
      {props.value}
    </pre>
  );
}

function SaveControl(props: {
  onSave: () => Promise<void>;
  disabled: boolean;
  saveLabel: string;
  savedLabel: string;
  savingLabel: string;
  errorLabel: string;
  backendOffLabel: string;
}) {
  const [status, setStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  // 2s 复位定时器：新点击前先清除旧 timer，组件卸载时也清除，避免对已卸载组件 setState
  const resetTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    return () => {
      if (resetTimerRef.current !== null) {
        clearTimeout(resetTimerRef.current);
        resetTimerRef.current = null;
      }
    };
  }, []);
  const handleClick = async () => {
    if (resetTimerRef.current !== null) {
      clearTimeout(resetTimerRef.current);
      resetTimerRef.current = null;
    }
    setStatus('saving');
    try {
      await props.onSave();
      setStatus('saved');
    } catch {
      setStatus('error');
    }
    resetTimerRef.current = setTimeout(() => {
      resetTimerRef.current = null;
      setStatus('idle');
    }, 2000);
  };
  return (
    <div className="flex items-center gap-2 pt-1">
      <button
        type="button"
        disabled={props.disabled || status === 'saving'}
        onClick={() => void handleClick()}
        className="rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-85 disabled:opacity-50"
      >
        {status === 'saving'
          ? props.savingLabel
          : status === 'saved'
            ? props.savedLabel
            : props.saveLabel}
      </button>
      {props.disabled && (
        <span className="text-xs text-amber-400">{props.backendOffLabel}</span>
      )}
      {status === 'error' && <span className="text-xs text-red-400">{props.errorLabel}</span>}
    </div>
  );
}

/** 后端运行探测：getHealth 探活，8s 轮询。 */
function useBackendRunning() {
  const [isRunning, setIsRunning] = useState(false);
  const refresh = useCallback(async () => {
    try {
      await healthApi.getHealth();
      setIsRunning(true);
    } catch {
      setIsRunning(false);
    }
  }, []);
  useEffect(() => {
    void refresh();
    const id = setInterval(() => void refresh(), 8000);
    return () => clearInterval(id);
  }, [refresh]);
  return { isRunning, refresh };
}

// ── 区块 1：虚拟形象 ──

function AvatarSection() {
  const { t } = useTranslation();
  const avatarType = useSettingsStore((s) => s.avatarType);
  const live2d = useSettingsStore((s) => s.live2d);
  const vrm = useSettingsStore((s) => s.vrm);
  const setAvatarType = useSettingsStore((s) => s.setAvatarType);
  const setLive2DSettings = useSettingsStore((s) => s.setLive2DSettings);
  const setVRMSettings = useSettingsStore((s) => s.setVRMSettings);

  const typeOptions: Array<{ value: AvatarType; label: string }> = [
    { value: 'none', label: t('settings.avatar.typeNone') },
    { value: 'live2d', label: t('settings.avatar.typeLive2d') },
    { value: 'vrm', label: t('settings.avatar.typeVrm') },
  ];

  const setPosition3d = (axis: 0 | 1 | 2) => (v: number) => {
    const next: [number, number, number] = [...vrm.position3d];
    next[axis] = v;
    setVRMSettings({ position3d: next });
  };

  // VRM 模型文件：桌面模式经系统对话框选本地 .vrm；浏览器模式隐藏 file input（临时 blob URL）。
  // 选中的本地路径持久化到 settingsStore，VRMViewer 经 IPC 读取加载；"恢复默认"回到打包内默认模型。
  const vrmFileInputRef = useRef<HTMLInputElement>(null);
  const handlePickVrmModel = async () => {
    if (isElectron()) {
      const filePath = await pickModelFile();
      if (filePath) setVRMSettings({ modelPath: filePath });
    } else {
      vrmFileInputRef.current?.click();
    }
  };
  const handleVrmFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    // 替换前释放旧值：旧值为浏览器上传的临时 blob URL 时先 revoke，避免反复选择造成泄漏
    if (vrm.modelPath.startsWith('blob:')) URL.revokeObjectURL(vrm.modelPath);
    setVRMSettings({ modelPath: URL.createObjectURL(file) });
    e.target.value = '';
  };
  const handleResetVrmModel = () => {
    setVRMSettings({ modelPath: DEFAULT_VRM_MODEL_PATH });
  };
  const vrmModelName = vrm.modelPath.split(/[\\/]/).pop() || vrm.modelPath;

  return (
    <Section
      icon={Sparkles}
      title={t('settings.avatar.sectionTitle')}
      desc={t('settings.avatar.sectionDesc')}
    >
      <Row label={t('settings.avatar.typeLabel')}>
        <Segmented options={typeOptions} value={avatarType} onChange={setAvatarType} />
      </Row>

      {avatarType === 'live2d' && (
        <div className="space-y-2 rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.02)] p-3">
          <h3 className="text-xs font-medium text-muted-foreground">
            {t('settings.avatar.live2dTitle')}
          </h3>
          <SliderField
            label={t('settings.avatar.scale')}
            value={live2d.scale}
            min={0.1}
            max={2}
            step={0.05}
            format={(v) => `${Math.round(v * 100)}%`}
            onChange={(v) => setLive2DSettings({ scale: v })}
          />
          <NumberField
            label={t('settings.avatar.xOffset')}
            value={live2d.xOffset}
            onChange={(v) => setLive2DSettings({ xOffset: v })}
          />
          <NumberField
            label={t('settings.avatar.yOffset')}
            value={live2d.yOffset}
            onChange={(v) => setLive2DSettings({ yOffset: v })}
          />
          <Row label={t('settings.avatar.idleMotion')}>
            <Toggle
              label={t('settings.avatar.idleMotion')}
              checked={live2d.idleMotion}
              onChange={(v) => setLive2DSettings({ idleMotion: v })}
            />
          </Row>
          <Row label={t('settings.avatar.lipSync')}>
            <Toggle
              label={t('settings.avatar.lipSync')}
              checked={live2d.lipSync}
              onChange={(v) => setLive2DSettings({ lipSync: v })}
            />
          </Row>
        </div>
      )}

      {avatarType === 'vrm' && (
        <div className="space-y-2 rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.02)] p-3">
          <h3 className="text-xs font-medium text-muted-foreground">
            {t('settings.avatar.vrmTitle')}
          </h3>
          <Row label={t('settings.avatar.model')} desc={vrmModelName}>
            <button
              type="button"
              onClick={() => void handlePickVrmModel()}
              className="rounded-lg border border-primary/30 bg-primary/10 px-2.5 py-1 text-xs text-primary transition-opacity hover:opacity-85"
            >
              {t('settings.avatar.chooseModel')}
            </button>
            <button
              type="button"
              onClick={handleResetVrmModel}
              className="rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.04)] px-2.5 py-1 text-xs text-muted-foreground transition-opacity hover:opacity-85"
            >
              {t('settings.avatar.resetModel')}
            </button>
            <input
              ref={vrmFileInputRef}
              type="file"
              accept=".vrm"
              className="hidden"
              onChange={handleVrmFileChange}
            />
          </Row>
          <SliderField
            label={t('settings.avatar.scale')}
            value={vrm.scale}
            min={0.2}
            max={3}
            step={0.1}
            format={(v) => `${Math.round(v * 100)}%`}
            onChange={(v) => setVRMSettings({ scale: v })}
          />
          <SliderField
            label={t('settings.avatar.renderScale')}
            value={vrm.renderScale}
            min={0.5}
            max={2}
            step={0.1}
            format={(v) => `${Math.round(v * 100)}%`}
            onChange={(v) => setVRMSettings({ renderScale: v })}
          />
          <NumberField label={t('settings.avatar.posX')} value={vrm.position3d[0]} step={0.1} onChange={setPosition3d(0)} />
          <NumberField label={t('settings.avatar.posY')} value={vrm.position3d[1]} step={0.1} onChange={setPosition3d(1)} />
          <NumberField label={t('settings.avatar.posZ')} value={vrm.position3d[2]} step={0.1} onChange={setPosition3d(2)} />
          <Row label={t('settings.avatar.lookAtMouse')}>
            <Toggle
              label={t('settings.avatar.lookAtMouse')}
              checked={vrm.lookAtMouse}
              onChange={(v) => setVRMSettings({ lookAtMouse: v })}
            />
          </Row>
          <Row label={t('settings.avatar.idleAnimation')}>
            <Toggle
              label={t('settings.avatar.idleAnimation')}
              checked={vrm.idleAnimation}
              onChange={(v) => setVRMSettings({ idleAnimation: v })}
            />
          </Row>
        </div>
      )}
    </Section>
  );
}

// ── 区块 2：直播 ──

interface LiveClientInfo {
  connected: boolean;
  clientId?: string;
}

function LiveSection() {
  const { t } = useTranslation();
  const [info, setInfo] = useState<LiveClientInfo | null>(null);
  const [queryFailed, setQueryFailed] = useState(false);
  const [disconnectFailed, setDisconnectFailed] = useState(false);

  const refresh = useCallback(async () => {
    setQueryFailed(false);
    try {
      // 冻结的接口签名声明为 { status: string }，实际后端可能附带 connected/client_id
      const raw = (await healthApi.getLiveClientStatus()) as unknown as {
        status?: string;
        connected?: boolean;
        client_id?: string;
      };
      setInfo({
        connected: raw.connected ?? raw.status === 'connected',
        clientId: raw.client_id,
      });
    } catch {
      setInfo(null);
      setQueryFailed(true);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleDisconnect = async () => {
    if (!info?.clientId) return;
    setDisconnectFailed(false);
    try {
      await healthApi.disconnectLiveClient(info.clientId);
      await refresh();
    } catch {
      setDisconnectFailed(true);
    }
  };

  return (
    <Section
      icon={Radio}
      title={t('settings.live.sectionTitle')}
      desc={t('settings.live.sectionDesc')}
    >
      <Row label={t('settings.live.status')}>
        {queryFailed ? (
          <span className="text-xs text-red-400">{t('settings.live.checkFailed')}</span>
        ) : (
          <span
            className={cn(
              'flex items-center gap-1.5 text-xs font-medium',
              info?.connected ? 'text-emerald-400' : 'text-muted-foreground',
            )}
          >
            <span
              className={cn(
                'h-1.5 w-1.5 rounded-full',
                info?.connected ? 'bg-emerald-400' : 'bg-[rgba(255,255,255,0.3)]',
              )}
            />
            {info?.connected
              ? t('settings.live.connected')
              : t('settings.live.disconnected')}
          </span>
        )}
        {info?.connected && info.clientId && (
          <button
            type="button"
            onClick={() => void handleDisconnect()}
            className="rounded-lg border border-red-500/30 bg-red-500/10 px-2.5 py-1 text-xs text-red-400 transition-opacity hover:opacity-85"
          >
            {t('settings.live.disconnect')}
          </button>
        )}
      </Row>
      {disconnectFailed && (
        <p className="text-xs text-red-400">{t('settings.live.disconnectFailed')}</p>
      )}
    </Section>
  );
}

// ── 区块 3：后端地址 ──

function BackendSection() {
  const { t } = useTranslation();
  const [urlInput, setUrlInput] = useState(() => getApiBaseUrl());
  const [wsInput, setWsInput] = useState(() => localStorage.getItem(STORAGE_KEYS.wsUrl) || '');
  const [effectiveUrl, setEffectiveUrl] = useState(() => getApiBaseUrl());
  const [effectiveWs, setEffectiveWs] = useState(() => getWsBaseUrl());
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [discovering, setDiscovering] = useState(false);
  const [discovered, setDiscovered] = useState<DiscoveredBackend[]>([]);
  const [selectedBackendUrl, setSelectedBackendUrl] = useState<string>('');
  const [discoverError, setDiscoverError] = useState<string | null>(null);

  /** 取当前生效端口的端口号（无显式端口时回退默认 8000） */
  const currentPort = ((): number => {
    try {
      return Number(new URL(getApiBaseUrl()).port) || 8000;
    } catch {
      return 8000;
    }
  })();

  const handleDiscover = async () => {
    setDiscovering(true);
    setDiscoverError(null);
    setDiscovered([]);
    try {
      const res = await discoveryApi.discover(currentPort);
      setDiscovered(res.backends);
      setSelectedBackendUrl(res.backends[0]?.url ?? '');
    } catch (err) {
      setDiscoverError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setDiscovering(false);
    }
  };

  const handleConnect = async (backend: DiscoveredBackend) => {
    setSaving(true);
    setResult(null);
    try {
      const response = await fetch(`${backend.url}/health`, {
        method: 'GET',
        signal: AbortSignal.timeout(5000),
      });
      if (response.ok) {
        setBackendUrl(backend.url);
        setWsInput('');
        setUrlInput(backend.url);
        setEffectiveUrl(getApiBaseUrl());
        setEffectiveWs(getWsBaseUrl());
        setDiscovered([]);
        setResult({ ok: true, message: t('settings.backend.saveOk') });
      } else {
        setResult({
          ok: false,
          message: t('settings.backend.serverError', { status: response.status }),
        });
      }
    } catch (err) {
      setResult({
        ok: false,
        message: t('settings.backend.saveFailed', {
          message: err instanceof Error ? err.message : 'Unknown error',
        }),
      });
    } finally {
      setSaving(false);
    }
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    const url = urlInput.trim();
    if (!url) return;
    setSaving(true);
    setResult(null);
    try {
      const response = await fetch(`${url}/health`, {
        method: 'GET',
        signal: AbortSignal.timeout(5000),
      });
      if (response.ok) {
        setBackendUrl(url);
        const ws = wsInput.trim();
        if (ws) setWsUrl(ws);
        setEffectiveUrl(getApiBaseUrl());
        setEffectiveWs(getWsBaseUrl());
        setResult({ ok: true, message: t('settings.backend.saveOk') });
      } else {
        setResult({
          ok: false,
          message: t('settings.backend.serverError', { status: response.status }),
        });
      }
    } catch (err) {
      setResult({
        ok: false,
        message: t('settings.backend.saveFailed', {
          message: err instanceof Error ? err.message : 'Unknown error',
        }),
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Section
      icon={Link2}
      title={t('settings.backend.sectionTitle')}
      desc={t('settings.backend.sectionDesc')}
    >
      <form onSubmit={(e) => void handleSave(e)} className="space-y-2">
        <div className="rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.04)] px-3 py-2">
          <p className="mb-1 text-sm">{t('settings.backend.urlLabel')}</p>
          <p className="mb-2 font-mono text-xs text-muted-foreground">
            {effectiveUrl} · WS {effectiveWs}
          </p>
          <input
            type="url"
            aria-label={t('settings.backend.urlLabel')}
            value={urlInput}
            onChange={(e) => setUrlInput(e.target.value)}
            placeholder={DEFAULT_BACKEND_URL}
            className="w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-1.5 text-sm focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
            required
          />
          <input
            type="text"
            aria-label={t('settings.backend.wsLabel')}
            value={wsInput}
            onChange={(e) => setWsInput(e.target.value)}
            placeholder="ws://127.0.0.1:8000"
            className="mt-2 w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-1.5 text-sm focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
          />
          <p className="mt-1 text-xs text-muted-foreground">{t('settings.backend.wsHint')}</p>
          <div className="mt-2 flex items-center gap-2">
            <button
              type="submit"
              disabled={saving}
              className="rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-85 disabled:opacity-50"
            >
              {saving ? t('settings.backend.saving') : t('settings.backend.save')}
            </button>
            {result && (
              <span className={cn('text-xs', result.ok ? 'text-emerald-400' : 'text-red-400')}>
                {result.message}
              </span>
            )}
          </div>
        </div>
      </form>
      <div className="mt-2 flex items-center gap-2">
        <button
          type="button"
          onClick={() => void handleDiscover()}
          disabled={discovering}
          className="flex items-center gap-1.5 rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.04)] px-3 py-1.5 text-xs text-muted-foreground transition-opacity hover:opacity-85 disabled:opacity-50"
        >
          <Search className="h-3.5 w-3.5" />
          {discovering ? t('settings.backend.discovering') : t('settings.backend.discover')}
        </button>
        {discoverError && (
          <span className="text-xs text-red-400">{t('settings.backend.discoverFailed')}</span>
        )}
      </div>
      {discovered.length > 0 && (
        <div className="mt-2 rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.04)] p-2">
          <label className="mb-1 block text-xs text-muted-foreground">
            {t('settings.backend.discoverResult', { count: discovered.length })}
          </label>
          <div className="flex items-center gap-2">
            <select
              aria-label={t('settings.backend.discoverResult', { count: discovered.length })}
              value={selectedBackendUrl}
              onChange={(e) => setSelectedBackendUrl(e.target.value)}
              className="min-w-0 flex-1 rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-2 py-1.5 font-mono text-xs text-muted-foreground focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
            >
              {discovered.map((b) => (
                <option key={b.url} value={b.url}>
                  {b.url}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={() => {
                const backend = discovered.find((b) => b.url === selectedBackendUrl);
                if (backend) void handleConnect(backend);
              }}
              disabled={saving || !selectedBackendUrl}
              className="shrink-0 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-85 disabled:opacity-50"
            >
              {saving ? t('settings.backend.saving') : t('settings.backend.connect')}
            </button>
          </div>
        </div>
      )}
      <p className="text-xs text-muted-foreground">
        {window.electronAPI
          ? t('settings.backend.electronHint')
          : t('settings.backend.browserHint')}
      </p>
    </Section>
  );
}

// ── 区块 3.5：管理密钥 ──
// 管理面 x-api-key 录入（仅设置项，不做管理面板）：保存写 localStorage
// （key 常量取自 base.ts STORAGE_KEYS.adminKey），base.ts 请求拦截器检测到已配置时
// 自动为鉴权端点注入 x-api-key 头。输入框 type=password 且不回显已存值，仅展示配置状态徽标。

function AdminKeySection() {
  const { t } = useTranslation();
  const [configured, setConfigured] = useState(
    () => !!localStorage.getItem(STORAGE_KEYS.adminKey),
  );
  const [input, setInput] = useState('');

  const handleSave = () => {
    const key = input.trim();
    if (!key) return;
    localStorage.setItem(STORAGE_KEYS.adminKey, key);
    setInput('');
    setConfigured(true);
  };

  const handleClear = () => {
    localStorage.removeItem(STORAGE_KEYS.adminKey);
    setInput('');
    setConfigured(false);
  };

  return (
    <Section
      icon={KeyRound}
      title={t('settings.adminKey.sectionTitle')}
      desc={t('settings.adminKey.sectionDesc')}
    >
      <Row label={t('settings.adminKey.statusLabel')}>
        <span
          className={cn(
            'rounded-full px-2 py-0.5 text-[10px] font-medium',
            configured
              ? 'bg-emerald-500/15 text-emerald-400'
              : 'bg-[rgba(255,255,255,0.1)] text-muted-foreground',
          )}
        >
          {configured ? t('settings.adminKey.configured') : t('settings.adminKey.notConfigured')}
        </span>
      </Row>
      <div className="rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.04)] px-3 py-2">
        <input
          type="password"
          aria-label={t('settings.adminKey.inputLabel')}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={t('settings.adminKey.inputPlaceholder')}
          autoComplete="off"
          className="w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-1.5 text-sm focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
        />
        <div className="mt-2 flex items-center gap-2">
          <button
            type="button"
            disabled={!input.trim()}
            onClick={handleSave}
            className="rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-85 disabled:opacity-50"
          >
            {t('settings.adminKey.save')}
          </button>
          <button
            type="button"
            disabled={!configured}
            onClick={handleClear}
            className="rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.04)] px-3 py-1.5 text-xs text-muted-foreground transition-opacity hover:opacity-85 disabled:opacity-50"
          >
            {t('settings.adminKey.clear')}
          </button>
        </div>
      </div>
      <p className="text-xs text-muted-foreground">{t('settings.adminKey.hint')}</p>
    </Section>
  );
}

// ── 区块 4：音频 ──

function AudioSection() {
  const { t } = useTranslation();
  const micEnabled = useAudioStore((s) => s.micEnabled);
  const ttsVolume = useAudioStore((s) => s.ttsVolume);
  const micGain = useAudioStore((s) => s.micGain);
  const danmakuVoiceEnabled = useAudioStore((s) => s.danmakuVoiceEnabled);
  const setMicEnabled = useAudioStore((s) => s.setMicEnabled);
  const setTtsVolume = useAudioStore((s) => s.setTtsVolume);
  const setMicGain = useAudioStore((s) => s.setMicGain);
  const setDanmakuVoiceEnabled = useAudioStore((s) => s.setDanmakuVoiceEnabled);

  return (
    <Section
      icon={Mic}
      title={t('settings.audio.sectionTitle')}
      desc={t('settings.audio.sectionDesc')}
    >
      <Row label={t('settings.audio.mic')} desc={t('settings.audio.micDesc')}>
        <Toggle label={t('settings.audio.mic')} checked={micEnabled} onChange={setMicEnabled} />
      </Row>
      <SliderField
        label={t('settings.audio.ttsVolume')}
        value={ttsVolume}
        min={0}
        max={1}
        step={0.05}
        format={(v) => `${Math.round(v * 100)}%`}
        onChange={setTtsVolume}
      />
      <SliderField
        label={t('settings.audio.micGain')}
        value={micGain}
        min={0}
        max={2}
        step={0.05}
        format={(v) => `${v.toFixed(2)}x`}
        onChange={setMicGain}
      />
      <Row label={t('settings.audio.danmakuVoice')} desc={t('settings.audio.danmakuVoiceDesc')}>
        <Toggle
          label={t('settings.audio.danmakuVoice')}
          checked={danmakuVoiceEnabled}
          onChange={setDanmakuVoiceEnabled}
        />
      </Row>
    </Section>
  );
}

// ── 区块 5：视觉采集 ──

function CaptureSection() {
  const { t } = useTranslation();
  const screenActive = useCaptureStore((s) => s.screenActive);
  const cameraActive = useCaptureStore((s) => s.cameraActive);
  const visionEnabled = useCaptureStore((s) => s.visionEnabled);
  const videoModeEnabled = useCaptureStore((s) => s.videoModeEnabled);
  const frameMode = useCaptureStore((s) => s.frameMode);
  const frameIntervalSec = useCaptureStore((s) => s.frameIntervalSec);
  const setScreenActive = useCaptureStore((s) => s.setScreenActive);
  const setCameraActive = useCaptureStore((s) => s.setCameraActive);
  const setVisionEnabled = useCaptureStore((s) => s.setVisionEnabled);
  const setVideoModeEnabled = useCaptureStore((s) => s.setVideoModeEnabled);
  const setFrameMode = useCaptureStore((s) => s.setFrameMode);
  const setFrameIntervalSec = useCaptureStore((s) => s.setFrameIntervalSec);

  const modeOptions: Array<{ value: CaptureFrameMode; label: string }> = [
    { value: 'interval', label: t('settings.capture.modeInterval') },
    { value: 'adaptive', label: t('settings.capture.modeAdaptive') },
    { value: 'manual', label: t('settings.capture.modeManual') },
  ];

  // 视频模式开启时，尽力而为地把 vision_enhanced.enabled 同步到后端；
  // 单向同步（关闭不回写 false）、失败静默，不弹错不阻塞 UI。
  const syncVideoModeBackend = async (enabled: boolean) => {
    if (!enabled) return;
    try {
      await configApi.updateConfig('vision_enhanced', { enabled: true });
    } catch {
      // 尽力而为：后端不可达/写入失败时忽略，不影响本地开关状态
    }
  };

  // 本地先写入 store，再异步 best-effort 同步后端
  const handleVideoModeChange = (v: boolean) => {
    setVideoModeEnabled(v);
    void syncVideoModeBackend(v);
  };

  const renderCaptureRow = (
    label: string,
    active: boolean,
    setActive: (v: boolean) => void,
  ) => (
    <Row label={label}>
      <span
        className={cn(
          'flex items-center gap-1.5 text-xs font-medium',
          active ? 'text-emerald-400' : 'text-muted-foreground',
        )}
      >
        <span
          className={cn(
            'h-1.5 w-1.5 rounded-full',
            active ? 'bg-emerald-400' : 'bg-[rgba(255,255,255,0.3)]',
          )}
        />
        {active ? t('settings.capture.active') : t('settings.capture.inactive')}
      </span>
      <button
        type="button"
        onClick={() => setActive(!active)}
        className={cn(
          'rounded-lg border px-2.5 py-1 text-xs transition-opacity hover:opacity-85',
          active
            ? 'border-red-500/30 bg-red-500/10 text-red-400'
            : 'border-primary/30 bg-primary/10 text-primary',
        )}
      >
        {active ? t('settings.capture.turnOff') : t('settings.capture.turnOn')}
      </button>
    </Row>
  );

  return (
    <Section
      icon={Camera}
      title={t('settings.capture.sectionTitle')}
      desc={t('settings.capture.sectionDesc')}
    >
      {renderCaptureRow(t('settings.capture.visionMaster'), visionEnabled, setVisionEnabled)}
      <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <MonitorPlay className="h-3.5 w-3.5" />
        {t('settings.capture.visionMasterDesc')}
      </p>
      {renderCaptureRow(t('settings.capture.videoMode'), videoModeEnabled, handleVideoModeChange)}
      <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <MonitorPlay className="h-3.5 w-3.5" />
        {t('settings.capture.videoModeDesc')}
      </p>
      {renderCaptureRow(t('settings.capture.screen'), screenActive, setScreenActive)}
      {renderCaptureRow(t('settings.capture.camera'), cameraActive, setCameraActive)}
      <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <MonitorPlay className="h-3.5 w-3.5" />
        {t('settings.capture.petNote')}
      </p>
      <Row label={t('settings.capture.frameMode')}>
        <Segmented options={modeOptions} value={frameMode} onChange={setFrameMode} />
      </Row>
      {frameMode === 'interval' || frameMode === 'adaptive' ? (
        <SliderField
          label={t('settings.capture.intervalSec')}
          value={frameIntervalSec}
          min={MIN_FRAME_INTERVAL_SEC}
          max={MAX_FRAME_INTERVAL_SEC}
          step={1}
          format={(v) => `${v}s`}
          onChange={setFrameIntervalSec}
        />
      ) : null}
    </Section>
  );
}

// ── 区块 6：语言模型（LlmCard 对齐） ──

interface ModelEntry {
  provider: string;
  host: string;
  model: string;
  apiKey: string;
  enabled: boolean;
}

interface LlmModelsConfig {
  main: ModelEntry;
  summary: ModelEntry;
  memory: ModelEntry;
}

interface LlmParamsConfig {
  temperature: number;
  maxTokens: number;
  topP: number;
  timeout: number;
}

/** 后端 GET /api/config llm 节的 model 形状（api_key 为 snake_case） */
interface LlmModelResponse {
  provider?: string;
  model?: string;
  host?: string;
  api_key?: string;
}

/** 后端 GET /api/config llm 节返回形状 */
interface LlmConfigResponse {
  models?: { main?: LlmModelResponse; summary?: LlmModelResponse; memory?: LlmModelResponse };
  defaults?: { summary?: string; memory?: string };
  params?: Partial<LlmParamsConfig>;
}

const DEFAULT_MODEL_ENTRY: ModelEntry = {
  provider: 'ollama',
  host: 'http://localhost:11434',
  model: 'qwen3:latest',
  apiKey: '',
  enabled: false,
};

const DEFAULT_LLM_MODELS: LlmModelsConfig = {
  main: { ...DEFAULT_MODEL_ENTRY, enabled: true },
  summary: { ...DEFAULT_MODEL_ENTRY },
  memory: { ...DEFAULT_MODEL_ENTRY },
};

// 对齐后端 ModelConfig 默认（maxTokens 0 表示不限）
const DEFAULT_LLM_PARAMS: LlmParamsConfig = {
  temperature: 0.7,
  maxTokens: 0,
  topP: 0.9,
  timeout: 60,
};

const PROVIDER_OPTIONS = [
  { value: 'ollama', label: 'Ollama (本地)' },
  { value: 'vllm', label: 'vLLM' },
  { value: 'openai', label: 'OpenAI' },
];

function ModelFields(props: {
  title: string;
  desc?: string;
  entry: ModelEntry;
  showEnabled: boolean;
  onChange: (entry: ModelEntry) => void;
}) {
  const { t } = useTranslation();
  const set = (patch: Partial<ModelEntry>) => props.onChange({ ...props.entry, ...patch });
  return (
    <div className="space-y-2 rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.02)] p-3">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-medium">{props.title}</h3>
          {props.desc && <p className="text-xs text-muted-foreground">{props.desc}</p>}
        </div>
        {props.showEnabled && (
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground">{t('settings.llm.enabled')}</span>
            <Toggle
              label={t('settings.llm.enabled')}
              checked={props.entry.enabled}
              onChange={(v) => set({ enabled: v })}
            />
          </div>
        )}
      </div>
      <SelectField
        label={t('settings.llm.provider')}
        value={props.entry.provider}
        options={PROVIDER_OPTIONS}
        onChange={(v) => set({ provider: v })}
      />
      <TextField
        label={t('settings.llm.model')}
        value={props.entry.model}
        onChange={(v) => set({ model: v })}
      />
      <TextField
        label={t('settings.llm.host')}
        value={props.entry.host}
        onChange={(v) => set({ host: v })}
      />
      <TextField
        label={t('settings.llm.apiKey')}
        type="password"
        value={props.entry.apiKey}
        onChange={(v) => set({ apiKey: v })}
      />
    </div>
  );
}

/** 后端 model 节（api_key snake_case）映射为表单 ModelEntry，缺省字段保持原值 */
function toModelEntry(prev: ModelEntry, raw: LlmModelResponse | undefined): ModelEntry {
  if (!raw) return prev;
  return {
    ...prev,
    provider: raw.provider ?? prev.provider,
    model: raw.model ?? prev.model,
    host: raw.host ?? prev.host,
    apiKey: raw.api_key ?? prev.apiKey,
  };
}

/** 表单 ModelEntry → 后端 PUT 载荷（仅契约字段，api_key snake_case） */
function toModelPayload(entry: ModelEntry): LlmModelResponse {
  return {
    provider: entry.provider,
    host: entry.host,
    model: entry.model,
    api_key: entry.apiKey,
  };
}

function LlmSection() {
  const { t } = useTranslation();
  const { isRunning } = useBackendRunning();
  const [models, setModels] = useState<LlmModelsConfig>(DEFAULT_LLM_MODELS);
  const [params, setParams] = useState<LlmParamsConfig>(DEFAULT_LLM_PARAMS);
  // temperature 上限消费后端 limits（未加载时回退 2）
  const temperatureMax = useSettingsStore((s) => s.limits?.temperature_max) ?? 2;
  const fetchLimits = useSettingsStore((s) => s.fetchLimits);

  const loadConfig = useCallback(async () => {
    try {
      const data = await configApi.getConfig();
      const llm = (data as { config?: { llm?: LlmConfigResponse } }).config?.llm;
      if (llm) {
        const { models: respModels, defaults, params: respParams } = llm;
        setModels((prev) => ({
          main: toModelEntry(prev.main, respModels?.main),
          summary: {
            ...toModelEntry(prev.summary, respModels?.summary),
            enabled:
              defaults?.summary === undefined
                ? prev.summary.enabled
                : defaults.summary === 'summary',
          },
          memory: {
            ...toModelEntry(prev.memory, respModels?.memory),
            enabled:
              defaults?.memory === undefined
                ? prev.memory.enabled
                : defaults.memory === 'memory',
          },
        }));
        if (respParams) {
          setParams((prev) => ({
            temperature: respParams.temperature ?? prev.temperature,
            maxTokens: respParams.maxTokens ?? prev.maxTokens,
            topP: respParams.topP ?? prev.topP,
            timeout: respParams.timeout ?? prev.timeout,
          }));
        }
      }
    } catch {
      /* 后端不可达时保持当前表单 */
    }
  }, []);

  useEffect(() => {
    if (!isRunning) return;
    void loadConfig();
  }, [isRunning, loadConfig]);

  // 配置热更新：LLM 节保存后即时刷新表单（需重启的节不刷新，等待页面重载）
  useEffect(() => {
    const unsubscribe = subscribeConfigChanged(({ section, requiresRestart }) => {
      if (section === 'llm' && !requiresRestart && isRunning) void loadConfig();
    });
    return unsubscribe;
  }, [isRunning, loadConfig]);

  // limits 未加载时补拉一次（App 启动链路可能因后端离线而漏拉，失败静默回退默认上限）
  useEffect(() => {
    if (!useSettingsStore.getState().limits) void fetchLimits();
  }, [fetchLimits]);

  const handleSave = async () => {
    await configApi.updateConfig('llm', {
      models: {
        main: toModelPayload(models.main),
        summary: toModelPayload(models.summary),
        memory: toModelPayload(models.memory),
      },
      model_defaults: {
        summary: models.summary.enabled ? 'summary' : 'main',
        memory: models.memory.enabled ? 'memory' : 'main',
      },
      llm_params: params,
    });
  };

  return (
    <Section
      icon={Bot}
      title={t('settings.llm.sectionTitle')}
      desc={t('settings.llm.sectionDesc')}
    >
      <ModelFields
        title={t('settings.llm.mainTitle')}
        desc={t('settings.llm.mainDesc')}
        entry={models.main}
        showEnabled={false}
        onChange={(e) => setModels((p) => ({ ...p, main: e }))}
      />
      <ModelFields
        title={t('settings.llm.summaryTitle')}
        desc={t('settings.llm.summaryDesc')}
        entry={models.summary}
        showEnabled
        onChange={(e) => setModels((p) => ({ ...p, summary: e }))}
      />
      <ModelFields
        title={t('settings.llm.memoryTitle')}
        desc={t('settings.llm.memoryDesc')}
        entry={models.memory}
        showEnabled
        onChange={(e) => setModels((p) => ({ ...p, memory: e }))}
      />
      <div className="space-y-2 rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.02)] p-3">
        <h3 className="text-sm font-medium">{t('settings.llm.paramsTitle')}</h3>
        <SliderField
          label={t('settings.llm.temperature')}
          value={params.temperature}
          min={0}
          max={temperatureMax}
          step={0.05}
          format={(v) => v.toFixed(2)}
          onChange={(v) => setParams((p) => ({ ...p, temperature: v }))}
        />
        <NumberField
          label={t('settings.llm.maxTokens')}
          value={params.maxTokens}
          step={100}
          onChange={(v) => setParams((p) => ({ ...p, maxTokens: v }))}
        />
        <SliderField
          label={t('settings.llm.topP')}
          value={params.topP}
          min={0}
          max={1}
          step={0.01}
          format={(v) => v.toFixed(2)}
          onChange={(v) => setParams((p) => ({ ...p, topP: v }))}
        />
        <NumberField
          label={t('settings.llm.timeout')}
          value={params.timeout}
          step={5}
          onChange={(v) => setParams((p) => ({ ...p, timeout: v }))}
        />
      </div>
      <SaveControl
        onSave={handleSave}
        disabled={!isRunning}
        saveLabel={t('settings.llm.save')}
        savedLabel={t('settings.llm.saved')}
        savingLabel={t('settings.llm.saving')}
        errorLabel={t('settings.saveError')}
        backendOffLabel={t('settings.backendOff')}
      />
    </Section>
  );
}

// ── 区块 6.5：进化实验室（CXO-Tuner 自适应微调） ──

const TRAIN_POLL_MS = 3000;

/**
 * 自动裁判可用性。CX-O-SERVER 当前未代理 POST /api/v1/judge/build（无对应出口路由），
 * 故该入口禁用并注明；后续后端提供等价端点时改为 true 并接入触发逻辑。
 */
const JUDGE_AVAILABLE = false;

function EvolutionSection() {
  const { t } = useTranslation();
  const { isRunning } = useBackendRunning();
  const [tunerOnline, setTunerOnline] = useState(false);
  const [stats, setStats] = useState<TunerStats | null>(null);
  const [adapters, setAdapters] = useState<TunerAdapter[]>([]);
  const [epochs, setEpochs] = useState(1);
  const [sampleRatio, setSampleRatio] = useState(1);
  const [train, setTrain] = useState<TunerTrainStatus | null>(null);
  const [trainOffline, setTrainOffline] = useState(false);
  const [triggering, setTriggering] = useState(false);
  const [applyingId, setApplyingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  /** 应用成功的适配器 id 集合，用于展示「已应用」反馈 */
  const [appliedIds, setAppliedIds] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const jobIdRef = useRef<string>('');

  const load = useCallback(async () => {
    try {
      const [s, ads] = await Promise.all([tunerApi.getStats(), tunerApi.listAdapters()]);
      setStats(s);
      setTunerOnline(s !== null);
      setAdapters(ads ?? []);
    } catch {
      setTunerOnline(false);
    }
  }, []);

  useEffect(() => {
    if (!isRunning) {
      setTunerOnline(false);
      return;
    }
    void load();
  }, [isRunning, load]);

  // 配置热更新：进化实验室配置变更后即时刷新 stats / adapters（卸载时清理订阅）
  useEffect(() => {
    if (!isRunning) return;
    const unsubscribe = subscribeConfigChanged(({ section }) => {
      if (section === 'evolution') void load();
    });
    return unsubscribe;
  }, [isRunning, load]);

  const pollTrain = useCallback(async () => {
    const jobId = jobIdRef.current;
    if (!jobId) return;
    const status = await tunerApi.getTrainStatus(jobId);
    if (status) {
      setTrain(status);
      setTrainOffline(false);
    } else {
      // 轮询失败 / 后端离线：不覆写既有状态，置离线降级标记
      setTrainOffline(true);
    }
  }, []);

  // 训练进行中轮询
  useEffect(() => {
    if (!train?.job_id || train.status === 'completed' || train.status === 'failed') return;
    const id = setInterval(() => void pollTrain(), TRAIN_POLL_MS);
    return () => clearInterval(id);
  }, [train?.job_id, train?.status, pollTrain]);

  const handleTrigger = async () => {
    setTriggering(true);
    setError(null);
    try {
      const result = await tunerApi.trigger(epochs, sampleRatio);
      const jobId = result.job_id ?? '';
      jobIdRef.current = jobId;
      setTrain(result);
      setTrainOffline(false);
      setAppliedIds(new Set());
      if (jobId) void pollTrain();
    } catch (err) {
      setError(err instanceof Error ? err.message : t('settings.evolution.triggerFailed'));
    } finally {
      setTriggering(false);
    }
  };

  const handleApply = async (id: string) => {
    setApplyingId(id);
    setError(null);
    try {
      const result = await tunerApi.applyAdapter(id);
      if (result.applied) {
        setAppliedIds((prev) => new Set(prev).add(id));
      } else {
        setError(t('settings.evolution.applyFailed'));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t('settings.evolution.applyFailed'));
    } finally {
      setApplyingId(null);
    }
  };

  const handleDelete = async (id: string) => {
    setDeletingId(id);
    setError(null);
    try {
      const result = await tunerApi.deleteAdapter(id);
      if (!result.deleted) {
        setError(t('settings.evolution.deleteFailed'));
        return;
      }
      // 删除成功：刷新列表，并清理该适配器的「已应用」标记
      setAppliedIds((prev) => {
        if (!prev.has(id)) return prev;
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
      // 删除后重取适配器列表
      try {
        const ads = await tunerApi.listAdapters();
        setAdapters(ads ?? []);
      } catch {
        /* 刷新失败时保留原列表，下次 load 收敛 */
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t('settings.evolution.deleteFailed'));
    } finally {
      setDeletingId(null);
    }
  };

  // Loss 曲线：优先 loss_curve（CXO-Tuner 契约口径），回退 MVP 使用的 loss_history；
  // 两者皆缺失（或非数值）时降级为文本展示。
  const rawLoss = train?.loss_curve !== undefined ? train.loss_curve : train?.loss_history;
  const lossHistory = Array.isArray(rawLoss)
    ? rawLoss.filter((v): v is number => typeof v === 'number' && Number.isFinite(v))
    : [];
  const maxLoss = lossHistory.length ? Math.max(...lossHistory) : 0;
  const progress = Math.round(train?.progress ?? 0);

  // 显存占用展示：优先格式化字符串，否则回退 memory_usage_mb（MB）
  const memoryText =
    typeof train?.memory === 'string' && train.memory.trim() !== ''
      ? train.memory
      : train?.memory_usage_mb !== undefined && train.memory_usage_mb !== null
        ? `${train.memory_usage_mb} MB`
        : '';

  /** 直播特化来源映射：base / streaming / intimate，无 scene 时返回 null */
  const sceneLabel = (scene?: string): string | null => {
    if (!scene) return null;
    switch (scene) {
      case 'base':
        return t('settings.evolution.sceneBase');
      case 'streaming':
        return t('settings.evolution.sceneStreaming');
      case 'intimate':
        return t('settings.evolution.sceneIntimate');
      default:
        return scene;
    }
  };

  return (
    <Section
      icon={Sparkles}
      title={t('settings.evolution.sectionTitle')}
      desc={t('settings.evolution.sectionDesc')}
    >
      {!isRunning || !tunerOnline ? (
        <>
          <Row label={t('settings.evolution.status')}>
            <span className="flex items-center gap-1.5 text-xs font-medium text-amber-400">
              <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
              {t('settings.evolution.tunerOffline')}
            </span>
          </Row>
          <p className="text-xs text-muted-foreground">{t('settings.evolution.tunerOfflineDesc')}</p>
        </>
      ) : (
        <>
          {/* 数据集统计 */}
          <div className="space-y-2 rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.02)] p-3">
            <h3 className="text-sm font-medium text-muted-foreground">{t('settings.evolution.dataset')}</h3>
            <Row label={t('settings.evolution.total')}>
              <span className="text-xs tabular-nums text-muted-foreground">{stats?.total ?? 0}</span>
            </Row>
            <Row label={t('settings.evolution.positiveRatio')}>
              <span className="text-xs tabular-nums text-emerald-400">
                {((stats?.positive_ratio ?? 0) * 100).toFixed(1)}%
              </span>
            </Row>
            <Row label={t('settings.evolution.negativeRatio')}>
              <span className="text-xs tabular-nums text-red-400">
                {((stats?.negative_ratio ?? 0) * 100).toFixed(1)}%
              </span>
            </Row>
            <Row label={t('settings.evolution.anchorCount')}>
              <span className="text-xs tabular-nums text-muted-foreground">{stats?.anchor_count ?? 0}</span>
            </Row>
            {stats && Object.keys(stats.source_breakdown).length > 0 && (
              <Row label={t('settings.evolution.sourceBreakdown')}>
                <span className="text-xs text-muted-foreground">
                  {Object.entries(stats.source_breakdown)
                    .map(([k, v]) => `${k}: ${v}`)
                    .join(' · ')}
                </span>
              </Row>
            )}
          </div>

          {/* 训练触发 */}
          <div className="space-y-2 rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.02)] p-3">
            <h3 className="text-sm font-medium text-muted-foreground">{t('settings.evolution.trainTitle')}</h3>
            <NumberField
              label={t('settings.evolution.epochs')}
              value={epochs}
              step={1}
              onChange={(v) => setEpochs(Math.max(0, Math.round(v)))}
            />
            <SliderField
              label={t('settings.evolution.sampleRatio')}
              value={sampleRatio}
              min={0}
              max={1}
              step={0.05}
              format={(v) => `${Math.round(v * 100)}%`}
              onChange={setSampleRatio}
            />
            <div className="flex items-center gap-2 pt-1">
              <button
                type="button"
                disabled={triggering}
                onClick={() => void handleTrigger()}
                className="rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-85 disabled:opacity-50"
              >
                {triggering ? t('settings.evolution.triggering') : t('settings.evolution.trigger')}
              </button>
            </div>
            {error && <p className="text-xs text-red-400">{error}</p>}
          </div>

          {/* 训练状态 */}
          <div className="space-y-2 rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.02)] p-3">
            <h3 className="text-sm font-medium text-muted-foreground">{t('settings.evolution.trainStatus')}</h3>
            {!train ? (
              <p className="text-xs text-muted-foreground">{t('settings.evolution.noStatus')}</p>
            ) : (
              <>
                <Row label={t('settings.evolution.jobStatus')}>
                  <Badge
                    variant={
                      train.status === 'completed'
                        ? 'success'
                        : train.status === 'failed'
                          ? 'error'
                          : 'anime'
                    }
                    size="sm"
                  >
                    {train.status ?? '-'}
                  </Badge>
                </Row>
                <Row label={t('settings.evolution.progress')}>
                  <div className="flex w-40 items-center gap-2">
                    <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-[rgba(255,255,255,0.1)]">
                      <div
                        className="h-full rounded-full bg-primary transition-all duration-fast"
                        style={{ width: `${Math.min(100, progress)}%` }}
                      />
                    </div>
                    <span className="w-9 text-right text-xs tabular-nums text-muted-foreground">{progress}%</span>
                  </div>
                </Row>
                {memoryText && (
                  <Row label={t('settings.evolution.memory')}>
                    <span className="text-xs text-muted-foreground">{memoryText}</span>
                  </Row>
                )}
                {lossHistory.length > 0 ? (
                  <Row label={t('settings.evolution.loss')}>
                    <div className="flex h-10 items-end gap-0.5">
                      {lossHistory.slice(-24).map((v, i) => (
                        <div
                          key={`${i}-${v}`}
                          className="w-2 rounded-sm bg-[rgba(255,183,225,0.6)]"
                          style={{ height: maxLoss > 0 ? `${Math.max(8, (v / maxLoss) * 100)}%` : '8%' }}
                        />
                      ))}
                    </div>
                  </Row>
                ) : (
                  <Row label={t('settings.evolution.loss')}>
                    <span className="text-xs text-muted-foreground">{t('settings.evolution.noLoss')}</span>
                  </Row>
                )}
                {trainOffline && (
                  <p className="text-xs text-amber-400">{t('settings.evolution.trainPollFailed')}</p>
                )}
                {train.error && <p className="text-xs text-red-400">{train.error}</p>}
              </>
            )}
          </div>

          {/* 适配器列表 */}
          <div className="space-y-2 rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.02)] p-3">
            <h3 className="text-sm font-medium text-muted-foreground">{t('settings.evolution.adaptersTitle')}</h3>
            {adapters.length === 0 ? (
              <p className="py-2 text-center text-xs text-muted-foreground">
                {t('settings.evolution.noAdapters')}
              </p>
            ) : (
              adapters.map((adapter) => {
                const scene = sceneLabel(adapter.scene);
                const applied = appliedIds.has(adapter.id);
                // 训练时间：优先 created_at，解析失败回退展示原文
                let trainingTime: string | null = null;
                if (adapter.created_at) {
                  const parsed = new Date(adapter.created_at);
                  trainingTime = Number.isNaN(parsed.getTime())
                    ? adapter.created_at
                    : parsed.toLocaleString();
                }
                return (
                  <div
                    key={adapter.id}
                    className="rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.02)] px-3 py-2"
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex min-w-0 items-center gap-2">
                        <p className="truncate text-sm">{adapter.name || adapter.id}</p>
                        {scene && (
                          <span className="shrink-0 rounded-full bg-[rgba(255,183,225,0.18)] px-2 py-0.5 text-[10px] font-medium text-[var(--color-primary)]">
                            {scene}
                          </span>
                        )}
                      </div>
                      <div className="flex shrink-0 items-center gap-2">
                        {applied && (
                          <span className="text-xs text-emerald-400">
                            {t('settings.evolution.applied')}
                          </span>
                        )}
                        <button
                          type="button"
                          disabled={applyingId === adapter.id}
                          onClick={() => void handleApply(adapter.id)}
                          className="rounded-lg border border-primary/30 bg-primary/10 px-2.5 py-1 text-xs text-primary transition-opacity hover:opacity-85 disabled:opacity-50"
                        >
                          {applyingId === adapter.id
                            ? t('settings.evolution.applying')
                            : t('settings.evolution.apply')}
                        </button>
                        <button
                          type="button"
                          disabled={deletingId === adapter.id}
                          onClick={() => void handleDelete(adapter.id)}
                          aria-label={t('settings.evolution.delete', { name: adapter.name || adapter.id })}
                          className="rounded-lg border border-red-500/30 bg-red-500/10 px-2.5 py-1 text-xs text-red-400 transition-opacity hover:opacity-85 disabled:opacity-50"
                        >
                          {deletingId === adapter.id
                            ? t('settings.evolution.deleting')
                            : t('settings.evolution.delete')}
                        </button>
                      </div>
                    </div>
                    {(adapter.base_model || trainingTime) && (
                      <p className="mt-1 text-xs text-muted-foreground">
                        {adapter.base_model && <span className="font-mono">{adapter.base_model}</span>}
                        {adapter.base_model && trainingTime && <span> · </span>}
                        {trainingTime && (
                          <>
                            {t('settings.evolution.trainingTime')}：{trainingTime}
                          </>
                        )}
                      </p>
                    )}
                  </div>
                );
              })
            )}
          </div>

          {/* 自动裁判：从历史对话构建 DPO 偏好数据。
              当前 CX-O-SERVER 未代理 /judge/build，入口禁用并注明不可用原因。 */}
          <div className="space-y-2 rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.02)] p-3 opacity-80">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-medium text-muted-foreground">{t('settings.evolution.judgeTitle')}</h3>
              <Badge variant="default" size="sm">
                {t('settings.evolution.judgeUnavailable')}
              </Badge>
            </div>
            <p className="text-xs text-muted-foreground">{t('settings.evolution.judgeDesc')}</p>
            {!JUDGE_AVAILABLE && (
              <p className="text-xs text-amber-400">{t('settings.evolution.judgeUnavailableDesc')}</p>
            )}
          </div>
        </>
      )}
    </Section>
  );
}

// ── 区块 7：向量存储（VectorCard 对齐） ──

interface VectorConfigState {
  backend: string;
  vectorSize: number;
  weaviateHost: string;
  weaviatePort: number;
  embeddingProvider: string;
  embeddingModel: string;
  embeddingApiBase: string;
  embeddingApiKey: string;
}

/** 后端 GET /api/config vector 节返回形状（snake_case） */
interface VectorConfigResponse {
  backend?: string;
  vector_size?: number;
  weaviate_host?: string;
  weaviate_port?: number;
  embedding_provider?: string;
  embedding_model?: string;
  embedding_api_base?: string;
  embedding_api_key?: string;
}

// 对齐后端 WeaviateConfig 默认
const DEFAULT_VECTOR_CONFIG: VectorConfigState = {
  backend: 'weaviate',
  vectorSize: 1024,
  weaviateHost: 'localhost',
  weaviatePort: 8080,
  embeddingProvider: 'ollama',
  embeddingModel: 'nomic-embed-text',
  embeddingApiBase: '',
  embeddingApiKey: '',
};

const VECTOR_BACKEND_OPTIONS = [
  { value: 'weaviate', label: 'Weaviate (独立服务)' },
  { value: 'weaviate_embedded', label: 'Weaviate Embedded (内置)' },
];

const EMBEDDING_PROVIDER_OPTIONS = [
  { value: 'ollama', label: 'Ollama' },
  { value: 'sentence-transformers', label: 'Sentence Transformers' },
  { value: 'vllm', label: 'vLLM (OpenAI 兼容)' },
];

function VectorSection() {
  const { t } = useTranslation();
  const { isRunning } = useBackendRunning();
  const [config, setConfig] = useState<VectorConfigState>(DEFAULT_VECTOR_CONFIG);

  const loadConfig = useCallback(async () => {
    try {
      const data = await configApi.getConfig();
      const vec = (data as { config?: { vector?: VectorConfigResponse } }).config?.vector;
      if (vec) {
        setConfig((prev) => ({
          ...prev,
          backend: vec.backend ?? prev.backend,
          vectorSize: vec.vector_size ?? prev.vectorSize,
          weaviateHost: vec.weaviate_host ?? prev.weaviateHost,
          weaviatePort: vec.weaviate_port ?? prev.weaviatePort,
          embeddingProvider: vec.embedding_provider ?? prev.embeddingProvider,
          embeddingModel: vec.embedding_model ?? prev.embeddingModel,
          embeddingApiBase: vec.embedding_api_base ?? prev.embeddingApiBase,
          embeddingApiKey: vec.embedding_api_key ?? prev.embeddingApiKey,
        }));
      }
    } catch {
      /* 后端不可达时保持当前表单 */
    }
  }, []);

  useEffect(() => {
    if (!isRunning) return;
    void loadConfig();
  }, [isRunning, loadConfig]);

  // 配置热更新：Vector 节保存后即时刷新表单（需重启的节不刷新，等待页面重载）
  useEffect(() => {
    const unsubscribe = subscribeConfigChanged(({ section, requiresRestart }) => {
      if (section === 'vector' && !requiresRestart && isRunning) void loadConfig();
    });
    return unsubscribe;
  }, [isRunning, loadConfig]);

  const set = (patch: Partial<VectorConfigState>) => setConfig((prev) => ({ ...prev, ...patch }));

  const handleSave = async () => {
    await configApi.updateConfig('vector', {
      backend: config.backend,
      vector_size: config.vectorSize,
      weaviate_host: config.weaviateHost,
      weaviate_port: config.weaviatePort,
      embedding_provider: config.embeddingProvider,
      embedding_model: config.embeddingModel,
      embedding_api_base: config.embeddingApiBase,
      embedding_api_key: config.embeddingApiKey,
    });
  };

  return (
    <Section
      icon={Database}
      title={t('settings.vector.sectionTitle')}
      desc={t('settings.vector.sectionDesc')}
    >
      <SelectField
        label={t('settings.vector.backend')}
        value={config.backend}
        options={VECTOR_BACKEND_OPTIONS}
        onChange={(v) => set({ backend: v })}
      />
      <SelectField
        label={t('settings.vector.vectorSize')}
        value={String(config.vectorSize)}
        options={[
          { value: '384', label: '384' },
          { value: '768', label: '768' },
          { value: '1024', label: '1024' },
          { value: '1536', label: '1536' },
        ]}
        onChange={(v) => set({ vectorSize: Number(v) })}
      />
      {config.backend === 'weaviate' && (
        <>
          <TextField
            label={t('settings.vector.weaviateHost')}
            value={config.weaviateHost}
            onChange={(v) => set({ weaviateHost: v })}
          />
          <NumberField
            label={t('settings.vector.weaviatePort')}
            value={config.weaviatePort}
            onChange={(v) => set({ weaviatePort: v })}
          />
        </>
      )}
      <SelectField
        label={t('settings.vector.embeddingProvider')}
        value={config.embeddingProvider}
        options={EMBEDDING_PROVIDER_OPTIONS}
        onChange={(v) => set({ embeddingProvider: v })}
      />
      <TextField
        label={t('settings.vector.embeddingModel')}
        value={config.embeddingModel}
        onChange={(v) => set({ embeddingModel: v })}
      />
      {config.embeddingProvider === 'vllm' && (
        <>
          <TextField
            label={t('settings.vector.embeddingApiBase')}
            value={config.embeddingApiBase}
            onChange={(v) => set({ embeddingApiBase: v })}
          />
          <TextField
            label={t('settings.vector.embeddingApiKey')}
            type="password"
            value={config.embeddingApiKey}
            onChange={(v) => set({ embeddingApiKey: v })}
          />
        </>
      )}
      <SaveControl
        onSave={handleSave}
        disabled={!isRunning}
        saveLabel={t('settings.vector.save')}
        savedLabel={t('settings.vector.saved')}
        savingLabel={t('settings.vector.saving')}
        errorLabel={t('settings.saveError')}
        backendOffLabel={t('settings.backendOff')}
      />
    </Section>
  );
}

// ── 区块 8：图数据库（GraphCard 对齐） ──

interface GraphConfigState {
  graph_enabled: boolean;
}

// 对齐后端默认
const DEFAULT_GRAPH_CONFIG: GraphConfigState = {
  graph_enabled: true,
};

interface GraphHealthState {
  overall?: string;
  database?: string;
  semantic?: string;
}

function GraphSection() {
  const { t } = useTranslation();
  const { isRunning } = useBackendRunning();
  const [config, setConfig] = useState<GraphConfigState>(DEFAULT_GRAPH_CONFIG);
  const [health, setHealth] = useState<GraphHealthState | null>(null);
  const [stats, setStats] = useState<{ node_count: number; edge_count: number } | null>(null);

  const loadStats = useCallback(async () => {
    try {
      const [h, s] = await Promise.all([
        graphApi.getGraphHealthV2(),
        graphApi.getGraphStatsV2(),
      ]);
      setHealth(h);
      setStats({ node_count: s.node_count, edge_count: s.edge_count });
    } catch {
      setHealth(null);
      setStats(null);
    }
  }, []);

  useEffect(() => {
    if (!isRunning) return;
    let cancelled = false;
    (async () => {
      try {
        const data = await configApi.getGraphConfig();
        const cfg = (data as { config?: Partial<GraphConfigState> }).config;
        if (cfg && !cancelled) {
          setConfig((prev) => ({
            graph_enabled: cfg.graph_enabled ?? prev.graph_enabled,
          }));
        }
      } catch {
        /* 后端不可达时保持默认 */
      }
      if (!cancelled) void loadStats();
    })();
    return () => {
      cancelled = true;
    };
  }, [isRunning, loadStats]);

  const set = (patch: Partial<GraphConfigState>) => setConfig((prev) => ({ ...prev, ...patch }));

  const handleSave = async () => {
    await configApi.updateConfig('graph', { graph_enabled: config.graph_enabled });
    void loadStats();
  };

  const connected = health?.overall === 'healthy';
  const graphEnabled = config.graph_enabled;

  return (
    <Section
      icon={Share2}
      title={t('settings.graph.sectionTitle')}
      desc={t('settings.graph.sectionDesc')}
    >
      <Row label={t('settings.graph.enabled')}>
        <Toggle
          label={t('settings.graph.enabled')}
          checked={graphEnabled}
          onChange={(v) => set({ graph_enabled: v })}
        />
      </Row>

      <div className="space-y-2 rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.02)] p-3">
        <div className="flex items-center justify-between">
          <h3 className="flex items-center gap-1.5 text-sm font-medium text-muted-foreground">
            <Activity className="h-3.5 w-3.5" />
            {t('settings.graph.healthTitle')}
          </h3>
          <button
            type="button"
            onClick={() => void loadStats()}
            className="flex items-center gap-1 rounded-lg border border-primary/30 bg-primary/10 px-2 py-1 text-xs text-primary transition-opacity hover:opacity-85"
          >
            <RefreshCw className="h-3 w-3" />
            {t('settings.graph.refresh')}
          </button>
        </div>
        <Row label={t('settings.graph.status')}>
          <span
            className={cn(
              'flex items-center gap-1.5 text-xs font-medium',
              connected ? 'text-emerald-400' : graphEnabled ? 'text-red-400' : 'text-muted-foreground',
            )}
          >
            <span
              className={cn(
                'h-1.5 w-1.5 rounded-full',
                connected ? 'bg-emerald-400' : graphEnabled ? 'bg-red-400' : 'bg-[rgba(255,255,255,0.3)]',
              )}
            />
            {connected
              ? t('settings.graph.connected')
              : graphEnabled
                ? t('settings.graph.disconnected')
                : t('settings.graph.notEnabled')}
          </span>
        </Row>
        {health && (
          <>
            <Row label={t('settings.graph.database')}>
              <span className="text-xs text-muted-foreground">{health.database ?? 'unknown'}</span>
            </Row>
            <Row label={t('settings.graph.semantic')}>
              <span className="text-xs text-muted-foreground">{health.semantic ?? 'unknown'}</span>
            </Row>
          </>
        )}
        <Row label={t('settings.graph.nodes')}>
          <span className="text-xs tabular-nums text-muted-foreground">{stats?.node_count ?? 0}</span>
        </Row>
        <Row label={t('settings.graph.edges')}>
          <span className="text-xs tabular-nums text-muted-foreground">{stats?.edge_count ?? 0}</span>
        </Row>
      </div>

      <SaveControl
        onSave={handleSave}
        disabled={!isRunning}
        saveLabel={t('settings.graph.save')}
        savedLabel={t('settings.graph.saved')}
        savingLabel={t('settings.graph.saving')}
        errorLabel={t('settings.saveError')}
        backendOffLabel={t('settings.backendOff')}
      />
    </Section>
  );
}

// ── 区块 9：后端服务（ServiceCard 对齐） ──

function ServiceSection() {
  const { t } = useTranslation();
  const { isRunning, refresh } = useBackendRunning();
  const [processing, setProcessing] = useState(false);
  const [logs, setLogs] = useState('');

  const loadLogs = useCallback(async () => {
    try {
      const data = await serviceApi.getServiceLogs(50);
      setLogs(data.logs || t('settings.service.noLogs'));
    } catch {
      setLogs(t('settings.service.loadLogsFailed'));
    }
  }, [t]);

  useEffect(() => {
    if (isRunning) void loadLogs();
    else setLogs(t('settings.service.noLogs'));
  }, [isRunning, loadLogs, t]);

  const run = async (fn: () => Promise<unknown>) => {
    setProcessing(true);
    try {
      await fn();
      await refresh();
      if (isRunning) void loadLogs();
    } finally {
      setProcessing(false);
    }
  };

  let port: string | undefined;
  try {
    port = new URL(getApiBaseUrl()).port;
  } catch {
    port = undefined;
  }

  return (
    <Section
      icon={Server}
      title={t('settings.service.sectionTitle')}
      desc={t('settings.service.sectionDesc')}
    >
      <Row label={t('settings.service.status')}>
        <span
          className={cn(
            'flex items-center gap-1.5 text-xs font-medium',
            isRunning ? 'text-emerald-400' : 'text-muted-foreground',
          )}
        >
          <span
            className={cn('h-1.5 w-1.5 rounded-full', isRunning ? 'bg-emerald-400' : 'bg-[rgba(255,255,255,0.3)]')}
          />
          {isRunning ? t('settings.service.running') : t('settings.service.stopped')}
        </span>
      </Row>
      <Row label={t('settings.service.port')}>
        <span className="font-mono text-xs text-muted-foreground">{port ?? '-'}</span>
      </Row>
      <Row label={t('settings.service.manage')}>
        <div className="flex items-center gap-2">
          {isRunning ? (
            <>
              <button
                type="button"
                disabled={processing}
                onClick={() => void run(() => serviceApi.restartService())}
                className="rounded-lg border border-primary/30 bg-primary/10 px-2.5 py-1 text-xs text-primary transition-opacity hover:opacity-85 disabled:opacity-50"
              >
                {t('settings.service.restart')}
              </button>
              <button
                type="button"
                disabled={processing}
                onClick={() => void run(() => serviceApi.stopService())}
                className="rounded-lg border border-red-500/30 bg-red-500/10 px-2.5 py-1 text-xs text-red-400 transition-opacity hover:opacity-85 disabled:opacity-50"
              >
                {t('settings.service.stop')}
              </button>
            </>
          ) : (
            <button
              type="button"
              disabled={processing}
              onClick={() => void run(() => serviceApi.startService())}
              className="rounded-lg bg-primary px-2.5 py-1 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-85 disabled:opacity-50"
            >
              {t('settings.service.start')}
            </button>
          )}
        </div>
      </Row>
      <div className="space-y-1">
        <h3 className="text-sm font-medium text-muted-foreground">{t('settings.service.logs')}</h3>
        <TextAreaField value={logs} />
      </div>
    </Section>
  );
}

// ── 区块 10：CXFC 插件（PluginCard 对齐） ──

function PluginSection() {
  const { t } = useTranslation();
  const [plugins, setPlugins] = useState<CxfcPlugin[]>([]);
  const [skills, setSkills] = useState<CxfcSkill[]>([]);
  const [showConnect, setShowConnect] = useState(false);
  const [connectHost, setConnectHost] = useState('localhost');
  const [connectPort, setConnectPort] = useState(8081);

  const load = useCallback(async () => {
    try {
      const [p, s] = await Promise.all([cxfcApi.getCxfcPlugins(), cxfcApi.getCxfcSkills()]);
      setPlugins(p);
      setSkills(s);
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleScan = async () => {
    try {
      const result = await cxfcApi.discoverCxfcPlugins(true);
      const count = result.remote?.length ?? 0;
      window.alert(
        count > 0 ? t('settings.plugin.scanResult', { count }) : t('settings.plugin.scanNone'),
      );
      void load();
    } catch {
      /* ignore */
    }
  };

  const handleConnect = async () => {
    try {
      await cxfcApi.connectCxfcPlugin(connectHost, connectPort);
      setShowConnect(false);
      void load();
    } catch {
      window.alert(t('settings.plugin.connectFailed'));
    }
  };

  const handleDisconnect = async (id: string) => {
    try {
      await cxfcApi.disconnectCxfcPlugin(id);
      void load();
    } catch {
      /* ignore */
    }
  };

  const handleRefresh = async (id: string) => {
    try {
      await cxfcApi.refreshCxfcPlugin(id);
      void load();
    } catch {
      /* ignore */
    }
  };

  return (
    <Section
      icon={Plug}
      title={t('settings.plugin.sectionTitle')}
      desc={t('settings.plugin.sectionDesc')}
    >
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => void handleScan()}
          className="rounded-lg border border-primary/30 bg-primary/10 px-2.5 py-1 text-xs text-primary transition-opacity hover:opacity-85"
        >
          {t('settings.plugin.scan')}
        </button>
        <button
          type="button"
          onClick={() => setShowConnect(true)}
          className="rounded-lg bg-primary px-2.5 py-1 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-85"
        >
          {t('settings.plugin.connect')}
        </button>
      </div>

      {plugins.length === 0 ? (
        <p className="py-4 text-center text-xs text-muted-foreground">
          {t('settings.plugin.noPlugins')}
        </p>
      ) : (
        <div className="space-y-2">
          {plugins.map((plugin) => {
            const connected = plugin.status === 'connected';
            return (
              <div
                key={plugin.plugin_id}
                className="rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.02)] p-3"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">{plugin.name || plugin.plugin_id}</span>
                    <span
                      className={cn(
                        'rounded-full px-2 py-0.5 text-[10px] font-medium',
                        connected ? 'bg-emerald-500/15 text-emerald-400' : 'bg-red-500/15 text-red-400',
                      )}
                    >
                      {connected
                        ? t('settings.plugin.connected')
                        : t('settings.plugin.disconnected')}
                    </span>
                  </div>
                  <div className="flex items-center gap-1">
                    <button
                      type="button"
                      onClick={() => void handleRefresh(plugin.plugin_id)}
                      className="rounded-lg border border-[var(--glass-border)] px-2 py-0.5 text-xs text-muted-foreground transition-opacity hover:opacity-85"
                    >
                      {t('settings.plugin.refresh')}
                    </button>
                    <button
                      type="button"
                      onClick={() => void handleDisconnect(plugin.plugin_id)}
                      className="rounded-lg border border-red-500/30 bg-red-500/10 px-2 py-0.5 text-xs text-red-400 transition-opacity hover:opacity-85"
                    >
                      {t('settings.plugin.disconnect')}
                    </button>
                  </div>
                </div>
                <p className="mt-1 font-mono text-xs text-muted-foreground">
                  {plugin.host}:{plugin.port} · {t('settings.plugin.tools', { count: plugin.tools.length })} ·{' '}
                  {t('settings.plugin.skills', { count: plugin.skills.length })}
                </p>
              </div>
            );
          })}
        </div>
      )}

      {skills.length > 0 && (
        <div className="space-y-1">
          <h3 className="text-sm font-medium text-muted-foreground">{t('settings.plugin.skillsTitle')}</h3>
          <div className="space-y-1">
            {skills.map((skill) => (
              <div
                key={`${skill.source_plugin_id}:${skill.name}`}
                className="rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.02)] p-2"
              >
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium">{skill.name}</span>
                  <span className="text-xs text-muted-foreground">
                    {t('settings.plugin.fromPlugin', { plugin: skill.source_plugin_id })}
                  </span>
                </div>
                {skill.description && (
                  <p className="mt-0.5 text-xs text-muted-foreground">{skill.description}</p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {showConnect && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
          role="dialog"
          aria-modal="true"
        >
          <div className="glass-panel w-80 p-4">
            <h3 className="mb-3 text-base font-semibold">{t('settings.plugin.connectDialogTitle')}</h3>
            <div className="space-y-2">
              <TextField label={t('settings.plugin.host')} value={connectHost} onChange={setConnectHost} />
              <NumberField label={t('settings.plugin.port')} value={connectPort} onChange={setConnectPort} />
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setShowConnect(false)}
                className="rounded-lg border border-[var(--glass-border)] px-3 py-1.5 text-xs text-muted-foreground transition-opacity hover:opacity-85"
              >
                {t('settings.plugin.cancel')}
              </button>
              <button
                type="button"
                onClick={() => void handleConnect()}
                className="rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-85"
              >
                {t('settings.plugin.connectBtn')}
              </button>
            </div>
          </div>
        </div>
      )}
    </Section>
  );
}

// ── 区块 11：前端启动设置（Task 5） ──
// 自启动 / 管理员权限启动，仅作用于前端 Electron，不负责启动/停止后端进程。
// 浏览器模式（window.electronAPI 缺失）下显示不可用且不调用 Electron API。

interface StartupState {
  supported: boolean;
  autoStart: boolean;
  runAsAdmin: boolean;
  isAdmin: boolean;
}

const DESKTOP_UNAVAILABLE: StartupState = {
  supported: false,
  autoStart: false,
  runAsAdmin: false,
  isAdmin: false,
};

function StartupSection() {
  const { t } = useTranslation();
  // 浏览器模式下 window.electronAPI 为 undefined，桌面模式经 preload 暴露
  const isDesktop = !!window.electronAPI;
  const [state, setState] = useState<StartupState>(DESKTOP_UNAVAILABLE);
  const [loaded, setLoaded] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  // 桌面模式挂载时读取启动配置
  useEffect(() => {
    if (!isDesktop || !window.electronAPI) return;
    let cancelled = false;
    void window.electronAPI
      .getStartupSettings()
      .then((s) => {
        if (!cancelled) {
          setState(s);
          setLoaded(true);
        }
      })
      .catch(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [isDesktop]);

  const handleToggle = async (key: 'autoStart' | 'runAsAdmin', value: boolean) => {
    if (!isDesktop || !window.electronAPI || pending) return;
    setPending(true);
    setNotice(null);
    try {
      if (key === 'autoStart') {
        const next = await window.electronAPI.setAutoStart(value);
        setState(next);
        setNotice(null);
      } else {
        const next = await window.electronAPI.setRunAsAdmin(value);
        setState(next);
        // 开启但当前未提权 → 提示重启生效；或曾开启但未提权 → 提示未生效
        if (next.runAsAdmin && !next.isAdmin) {
          setNotice(value ? t('settings.startup.pendingRestart') : t('settings.startup.notEffective'));
        } else {
          setNotice(null);
        }
      }
    } catch {
      setNotice(t('settings.saveError'));
    } finally {
      setPending(false);
    }
  };

  // 管理员权限已开启但当前未以管理员运行 → 设置未生效提示
  const adminNotEffective = state.runAsAdmin && !state.isAdmin;

  return (
    <Section
      icon={Rocket}
      title={t('settings.startup.sectionTitle')}
      desc={t('settings.startup.sectionDesc')}
    >
      {!isDesktop && (
        <p className="text-xs text-amber-400">{t('settings.startup.browserUnavailable')}</p>
      )}
      <Row label={t('settings.startup.autoStart')} desc={t('settings.startup.autoStartDesc')}>
        <Toggle
          label={t('settings.startup.autoStart')}
          checked={state.autoStart}
          onChange={(v) => void handleToggle('autoStart', v)}
        />
      </Row>
      <Row label={t('settings.startup.runAsAdmin')} desc={t('settings.startup.runAsAdminDesc')}>
        <Toggle
          label={t('settings.startup.runAsAdmin')}
          checked={state.runAsAdmin}
          onChange={(v) => void handleToggle('runAsAdmin', v)}
        />
      </Row>
      {isDesktop && adminNotEffective && !notice && (
        <p className="text-xs text-amber-400">{t('settings.startup.notEffective')}</p>
      )}
      {notice && <p className="text-xs text-amber-400">{notice}</p>}
      {isDesktop && !loaded && !pending && (
        <p className="text-xs text-muted-foreground">{t('settings.backend.saving')}</p>
      )}
    </Section>
  );
}

export default function SettingsPage() {
  const { t } = useTranslation();
  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <p className="text-sm text-muted-foreground">{t('settings.subtitle')}</p>
      <AvatarSection />
      <LiveSection />
      <BackendSection />
      <AdminKeySection />
      <AudioSection />
      <CaptureSection />
      <LlmSection />
      <EvolutionSection />
      <VectorSection />
      <GraphSection />
      <ServiceSection />
      <PluginSection />
      <StartupSection />
    </div>
  );
}
