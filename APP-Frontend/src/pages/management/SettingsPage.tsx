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
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Camera,
  Link2,
  Mic,
  MonitorPlay,
  Radio,
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
import {
  DEFAULT_BACKEND_URL,
  getApiBaseUrl,
  getWsBaseUrl,
  setBackendUrl,
  setWsUrl,
  STORAGE_KEYS,
} from '@/api/base';
import { cn } from '@/lib/utils';

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
            placeholder="ws://127.0.0.1:8100"
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
      <p className="text-xs text-muted-foreground">
        {window.electronAPI
          ? t('settings.backend.electronHint')
          : t('settings.backend.browserHint')}
      </p>
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
  const frameMode = useCaptureStore((s) => s.frameMode);
  const frameIntervalSec = useCaptureStore((s) => s.frameIntervalSec);
  const setScreenActive = useCaptureStore((s) => s.setScreenActive);
  const setCameraActive = useCaptureStore((s) => s.setCameraActive);
  const setFrameMode = useCaptureStore((s) => s.setFrameMode);
  const setFrameIntervalSec = useCaptureStore((s) => s.setFrameIntervalSec);

  const modeOptions: Array<{ value: CaptureFrameMode; label: string }> = [
    { value: 'interval', label: t('settings.capture.modeInterval') },
    { value: 'manual', label: t('settings.capture.modeManual') },
  ];

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
      {renderCaptureRow(t('settings.capture.screen'), screenActive, setScreenActive)}
      {renderCaptureRow(t('settings.capture.camera'), cameraActive, setCameraActive)}
      <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <MonitorPlay className="h-3.5 w-3.5" />
        {t('settings.capture.petNote')}
      </p>
      <Row label={t('settings.capture.frameMode')}>
        <Segmented options={modeOptions} value={frameMode} onChange={setFrameMode} />
      </Row>
      {frameMode === 'interval' && (
        <SliderField
          label={t('settings.capture.intervalSec')}
          value={frameIntervalSec}
          min={MIN_FRAME_INTERVAL_SEC}
          max={MAX_FRAME_INTERVAL_SEC}
          step={1}
          format={(v) => `${v}s`}
          onChange={setFrameIntervalSec}
        />
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
      <AudioSection />
      <CaptureSection />
    </div>
  );
}
