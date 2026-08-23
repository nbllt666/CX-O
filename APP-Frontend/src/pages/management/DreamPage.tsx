/**
 * 梦境日志页（DreamPage）
 *
 * CX-O-Dream 梦境引擎控制台：
 * - 顶部状态卡片：待命中/梦境生成中/清除已调度/未启用徽章 + 上次会话 + 会话统计
 * - 操作区：手动触发 / 手动清除
 * - 梦境候选列表：按会话分组，卡片展示内容 / lucidity_score / decision / 关联素材，
 *   含确认 / 否定（按 id）与按会话清除（红线 R5）
 * - 配置编辑区：含 enabled 开关与主要参数，保存调 updateConfig 后刷新
 * - 生理信号区块：手环心率 BLE 配对（扫描/连接/断开/解除）、状态徽章
 *   （未启用/未配对/已连接/采集失败/断线重连中）、physio 配置编辑、一键清除基线
 *
 * 数据全部来自 dreamApi / physioApi / window.ble。降级口径（对齐 AutonomyPage）：
 * - getStatus 返回 null（后端离线）→ 全页错误态 + 重试
 * - getStatus 返回 {status:"disabled"}（未启用）→ 状态卡「未启用」徽章 + 引导提示
 * - config / list 独立容错，失败不影响主状态展示
 * - window.ble 缺失（非 Electron 浏览器模式）→ 生理信号区块显示「不可用」提示，
 *   配置编辑与一键清除仍可用（走后端 REST）
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  AlertTriangle,
  Ban,
  Bluetooth,
  Check,
  HeartPulse,
  Moon,
  Play,
  RefreshCw,
  Save,
  Smartphone,
  Trash2,
  WifiOff,
  X,
} from 'lucide-react';
import { dreamApi } from '@/api/clients/dream';
import { physioApi } from '@/api/clients/physio';
import type {
  DreamBufferEntry,
  DreamConfig,
  DreamStats,
  DreamStatus,
  DreamStatusActive,
  PhysioConfig,
  PhysioDevice,
  PhysioStatus,
  PhysioStatusActive,
} from '@/api/types';
import { cn } from '@/lib/utils';

const EMPTY_STATS: DreamStats = {
  sessions: 0,
  generated: 0,
  approved: 0,
  rejected: 0,
  purges: 0,
};

/** 忙碌动作标记：用于禁用对应按钮，避免重复提交 */
type DreamBusyAction =
  | 'trigger'
  | 'purge'
  | 'confirm'
  | 'reject'
  | 'clear-session'
  | 'save-config';

/** 生理信号区块忙碌动作标记（独立于梦境操作，避免互相干扰） */
type PhysioBusyAction =
  | 'scan'
  | 'connect'
  | 'disconnect'
  | 'forget'
  | 'save-config'
  | 'clear';

function isActiveStatus(s: DreamStatus | null): s is DreamStatusActive {
  return !!s && s.status !== 'disabled';
}

function isPhysioActive(s: PhysioStatus | null): s is PhysioStatusActive {
  return !!s && s.status !== 'disabled';
}

/** BLE 状态快照（对齐 electron.d.ts BleStatus） */
type BleInfoSnapshot = {
  status: BleStatus;
  fingerprint: string | null;
  deviceName: string | null;
};

/** 文本输入字段 */
function TextField({
  label,
  value,
  onChange,
  testId,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  testId?: string;
}) {
  return (
    <label className="flex flex-col gap-1 text-xs">
      <span className="text-muted-foreground">{label}</span>
      <input
        data-testid={testId}
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-lg border border-[var(--glass-border)] bg-transparent px-2 py-1 text-xs outline-none focus:border-primary/50"
      />
    </label>
  );
}

/** 数字输入字段 */
function NumberField({
  label,
  value,
  onChange,
  step,
  testId,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  step?: number;
  testId?: string;
}) {
  return (
    <label className="flex flex-col gap-1 text-xs">
      <span className="text-muted-foreground">{label}</span>
      <input
        data-testid={testId}
        type="number"
        value={Number.isFinite(value) ? String(value) : ''}
        onChange={(e) => onChange(e.target.value === '' ? 0 : Number(e.target.value))}
        step={step}
        className="rounded-lg border border-[var(--glass-border)] bg-transparent px-2 py-1 text-xs outline-none focus:border-primary/50"
      />
    </label>
  );
}

/** 布尔开关字段 */
function CheckboxField({
  label,
  checked,
  onChange,
  testId,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  testId?: string;
}) {
  return (
    <label className="flex items-center gap-2 text-xs text-muted-foreground">
      <input
        data-testid={testId}
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4 accent-pink-500"
      />
      {label}
    </label>
  );
}

export default function DreamPage() {
  const { t } = useTranslation();
  const [status, setStatus] = useState<DreamStatus | null>(null);
  const [items, setItems] = useState<DreamBufferEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [listError, setListError] = useState(false);
  const [actionError, setActionError] = useState(false);
  const [busyAction, setBusyAction] = useState<DreamBusyAction | null>(null);
  const [draft, setDraft] = useState<DreamConfig | null>(null);
  const [saved, setSaved] = useState(false);
  // 配置草稿同步标记：仅初始加载与保存成功后从服务端回填，用户编辑不被刷新覆盖
  const draftSyncedRef = useRef(false);
  // ── 生理信号（physio）状态 ──
  const [physioStatus, setPhysioStatus] = useState<PhysioStatus | null>(null);
  const [physioConfig, setPhysioConfig] = useState<PhysioConfig | null>(null);
  const [physioDraft, setPhysioDraft] = useState<PhysioConfig | null>(null);
  const physioDraftSyncedRef = useRef(false);
  const [pairedDevices, setPairedDevices] = useState<PhysioDevice[]>([]);
  const [scannedDevices, setScannedDevices] = useState<BleDeviceInfo[]>([]);
  const [bleInfo, setBleInfo] = useState<BleInfoSnapshot | null>(null);
  const [bleError, setBleError] = useState<string | null>(null);
  const [physioBusy, setPhysioBusy] = useState<PhysioBusyAction | null>(null);
  const [physioActionError, setPhysioActionError] = useState(false);
  const [physioSaved, setPhysioSaved] = useState(false);

  const active = isActiveStatus(status);
  const bleAvailable = typeof window !== 'undefined' && !!window.ble;
  const physioActive = isPhysioActive(physioStatus);

  const fetchStatusAndConfig = useCallback(async () => {
    const [statusData, configData] = await Promise.all([
      dreamApi.getStatus(),
      dreamApi.getConfig().catch(() => null),
    ]);
    setStatus(statusData);
    if (configData && !draftSyncedRef.current) {
      setDraft(configData);
      draftSyncedRef.current = true;
    }
    return statusData;
  }, []);

  /** 刷新 BLE 采集器状态（window.ble.getStatus；非 Electron 下直接跳过） */
  const refreshBleStatus = useCallback(async () => {
    if (!window.ble) return;
    try {
      setBleInfo(await window.ble.getStatus());
    } catch (error) {
      console.error('BLE status failed:', error);
    }
  }, []);

  /** 刷新生理信号后端数据（status/config/devices）；getStatus 为 null（后端离线）时上层转全页错误态 */
  const refreshPhysio = useCallback(async () => {
    const [statusData, configData, devicesData] = await Promise.all([
      physioApi.getStatus(),
      physioApi.getConfig().catch(() => null),
      physioApi.getDevices().catch(() => null),
    ]);
    setPhysioStatus(statusData);
    if (configData) {
      setPhysioConfig(configData);
      if (!physioDraftSyncedRef.current) {
        setPhysioDraft(configData);
        physioDraftSyncedRef.current = true;
      }
    }
    if (devicesData) {
      setPairedDevices(devicesData.devices);
    }
    return statusData;
  }, []);

  const loadList = useCallback(async () => {
    const page = await dreamApi.getList();
    if (page === null) {
      setListError(true);
      return;
    }
    setListError(false);
    setItems(page.items);
    setTotal(page.total);
  }, []);

  const load = useCallback(async () => {
    setIsLoading(true);
    setLoadError(false);
    setActionError(false);
    setSaved(false);
    try {
      const statusData = await fetchStatusAndConfig();
      if (statusData === null) {
        // 后端离线：getStatus 返回 null → 全页错误态
        setLoadError(true);
      }
      const physioStatusData = await refreshPhysio();
      if (physioStatusData === null) {
        // 后端离线（生理信号端点不可达）→ 全页错误态 + 重试（对齐既有 loadError 模式）
        setLoadError(true);
      }
      await refreshBleStatus();
      await loadList();
    } catch (error) {
      console.error('Dream load failed:', error);
      setLoadError(true);
    } finally {
      setIsLoading(false);
    }
  }, [fetchStatusAndConfig, refreshPhysio, refreshBleStatus, loadList]);

  // 订阅主进程 BLE 状态推送（断线重连中等状态即时回显徽章）；非 Electron 下跳过
  useEffect(() => {
    if (!window.ble) return;
    const unsubscribe = window.ble.onStatus((status) => {
      setBleInfo((prev) => ({
        status,
        fingerprint: prev?.fingerprint ?? null,
        deviceName: prev?.deviceName ?? null,
      }));
    });
    return unsubscribe;
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  /** 通用操作包装：执行 → 刷新状态/列表，失败置 actionError */
  const handleAction = async (action: DreamBusyAction, fn: () => Promise<unknown>) => {
    if (busyAction) return;
    setBusyAction(action);
    setActionError(false);
    try {
      await fn();
      await fetchStatusAndConfig();
      await loadList();
    } catch (error) {
      console.error('Dream action failed:', error);
      setActionError(true);
    } finally {
      setBusyAction(null);
    }
  };

  const handleReject = (id: number) => {
    if (!window.confirm(t('management.dream.rejectConfirm'))) return;
    void handleAction('reject', () => dreamApi.reject(id));
  };

  const handleClearSession = (sessionId: string) => {
    if (!window.confirm(t('management.dream.clearSessionConfirm'))) return;
    void handleAction('clear-session', () => dreamApi.purgeSession(sessionId));
  };

  const updateDraft = (patch: Partial<DreamConfig>) => {
    setDraft((prev) => (prev ? { ...prev, ...patch } : prev));
    setSaved(false);
  };

  const updateSchedule = (patch: Partial<DreamConfig['schedule']>) => {
    setDraft((prev) => (prev ? { ...prev, schedule: { ...prev.schedule, ...patch } } : prev));
    setSaved(false);
  };

  const handleSaveConfig = async () => {
    if (!draft || busyAction) return;
    setBusyAction('save-config');
    setActionError(false);
    setSaved(false);
    try {
      const next = await dreamApi.updateConfig(draft);
      setDraft(next);
      setSaved(true);
      await fetchStatusAndConfig();
      await loadList();
    } catch (error) {
      console.error('Dream config save failed:', error);
      setActionError(true);
    } finally {
      setBusyAction(null);
    }
  };

  // ── 生理信号（physio）操作 ──

  const updatePhysioDraft = (patch: Partial<PhysioConfig>) => {
    setPhysioDraft((prev) => (prev ? { ...prev, ...patch } : prev));
    setPhysioSaved(false);
  };

  const handleScan = async () => {
    if (!window.ble || physioBusy) return;
    setPhysioBusy('scan');
    setPhysioActionError(false);
    setBleError(null);
    try {
      const result = await window.ble.scan();
      setScannedDevices(result.devices ?? []);
      setBleInfo((prev) => ({
        status: result.status,
        fingerprint: prev?.fingerprint ?? null,
        deviceName: prev?.deviceName ?? null,
      }));
      if (!result.ok) {
        setBleError(result.error ?? t('management.dream.physio.unsupportedHint'));
      }
    } catch (error) {
      console.error('BLE scan failed:', error);
      setPhysioActionError(true);
    } finally {
      setPhysioBusy(null);
    }
  };

  const handleConnect = async (device: BleDeviceInfo) => {
    if (!window.ble || physioBusy) return;
    setPhysioBusy('connect');
    setPhysioActionError(false);
    setBleError(null);
    try {
      const result = await window.ble.connect(device.deviceId);
      setBleInfo((prev) => ({
        status: result.status,
        fingerprint: prev?.fingerprint ?? null,
        deviceName: prev?.deviceName ?? null,
      }));
      if (result.ok) {
        // 持久化配对：连接后 device_fingerprint 写入配置（尽力而为，失败仅记录）
        await physioApi
          .updateConfig({
            device_fingerprint: device.fingerprint,
            device_name_hint: device.name || physioConfig?.device_name_hint || '',
          })
          .catch((err) => console.error('持久化配对失败（尽力而为）:', err));
        await refreshPhysio();
      } else if (result.error) {
        setBleError(result.error);
      }
    } catch (error) {
      console.error('BLE connect failed:', error);
      setPhysioActionError(true);
    } finally {
      setPhysioBusy(null);
    }
  };

  const handleDisconnect = async () => {
    if (!window.ble || physioBusy) return;
    setPhysioBusy('disconnect');
    setPhysioActionError(false);
    setBleError(null);
    try {
      const result = await window.ble.disconnect();
      setBleInfo((prev) => ({
        status: result.status,
        fingerprint: prev?.fingerprint ?? null,
        deviceName: prev?.deviceName ?? null,
      }));
      if (!result.ok && result.error) {
        setBleError(result.error);
      }
    } catch (error) {
      console.error('BLE disconnect failed:', error);
      setPhysioActionError(true);
    } finally {
      setPhysioBusy(null);
    }
  };

  const handleForget = async (device: PhysioDevice) => {
    if (physioBusy) return;
    if (!window.confirm(t('management.dream.physio.forgetConfirm'))) return;
    setPhysioBusy('forget');
    setPhysioActionError(false);
    setBleError(null);
    try {
      // forget 必须传真实指纹 id（GET /physio/devices 返回；脱敏 fingerprint 必 404）
      await physioApi.forgetDevice(device.id ?? device.fingerprint);
      await refreshPhysio();
    } catch (error) {
      console.error('Physio forget failed:', error);
      setPhysioActionError(true);
    } finally {
      setPhysioBusy(null);
    }
  };

  const handleSavePhysioConfig = async () => {
    if (!physioDraft || physioBusy) return;
    setPhysioBusy('save-config');
    setPhysioActionError(false);
    setPhysioSaved(false);
    try {
      const next = await physioApi.updateConfig({
        ...physioDraft,
        // 草稿加载早于配对写入时，保留后端已持久化的指纹，避免覆盖配对
        device_fingerprint:
          physioDraft.device_fingerprint ?? physioConfig?.device_fingerprint ?? null,
        store_raw_hr: false, // 隐私红线 R6：原始心率强制不落盘
      });
      setPhysioDraft(next);
      setPhysioSaved(true);
      await refreshPhysio();
    } catch (error) {
      console.error('Physio config save failed:', error);
      setPhysioActionError(true);
    } finally {
      setPhysioBusy(null);
    }
  };

  const handleClearBaseline = () => {
    if (!window.confirm(t('management.dream.physio.clearConfirm'))) return;
    void (async () => {
      setPhysioBusy('clear');
      setPhysioActionError(false);
      try {
        await physioApi.clear();
        await refreshPhysio();
      } catch (error) {
        console.error('Physio clear failed:', error);
        setPhysioActionError(true);
      } finally {
        setPhysioBusy(null);
      }
    })();
  };

  /** 已配对设备：后端 /devices 直接返回 {name, fingerprint(脱敏), id(真实指纹)}，
   *  forget 使用真实 id，无需再按扫描结果还原指纹（Task 6 修复后移除旧 workaround，
   *  渲染处直接使用 pairedDevices 状态） */

  /** 生理信号状态徽章（未启用/不可用/未配对/扫描中/连接中/已连接/断线重连中/采集失败） */
  const physioBadge = (() => {
    if (!physioActive) {
      return { key: 'disabled', cls: 'bg-[rgba(255,255,255,0.08)] text-muted-foreground' };
    }
    if (!bleAvailable) {
      return { key: 'unavailable', cls: 'bg-[rgba(255,255,255,0.08)] text-muted-foreground' };
    }
    switch (bleInfo?.status) {
      case 'connected':
        return { key: 'connected', cls: 'bg-emerald-500/15 text-emerald-400' };
      case 'reconnecting':
        return { key: 'reconnecting', cls: 'bg-amber-500/15 text-amber-400' };
      case 'unsupported':
      case 'unavailable':
        return { key: 'failed', cls: 'bg-red-500/15 text-red-400' };
      case 'scanning':
        return { key: 'scanning', cls: 'bg-sky-500/15 text-sky-400' };
      case 'connecting':
        return { key: 'connecting', cls: 'bg-sky-500/15 text-sky-400' };
      case 'idle':
      case 'disconnected':
      default:
        return { key: 'notPaired', cls: 'bg-[rgba(255,255,255,0.08)] text-muted-foreground' };
    }
  })();

  /** 已启用时的估计器状态（未启用/离线为 null；独立变量避免 JSX 内窄化丢失） */
  const physioEstimator = isPhysioActive(physioStatus) ? physioStatus.estimator : null;

  const statusMeta = (() => {
    if (!active) {
      return { badgeKey: 'disabled', badgeCls: 'bg-[rgba(255,255,255,0.08)] text-muted-foreground' };
    }
    switch (status.status) {
      case 'idle':
        return { badgeKey: 'idle', badgeCls: 'bg-emerald-500/15 text-emerald-400' };
      case 'dreaming':
        return { badgeKey: 'dreaming', badgeCls: 'bg-sky-500/15 text-sky-400' };
      case 'purge_scheduled':
        return { badgeKey: 'purgeScheduled', badgeCls: 'bg-amber-500/15 text-amber-400' };
      default:
        return { badgeKey: 'disabled', badgeCls: 'bg-[rgba(255,255,255,0.08)] text-muted-foreground' };
    }
  })();

  const decisionMeta = (decision: DreamBufferEntry['decision']) => {
    switch (decision) {
      case 'pending':
        return { cls: 'bg-amber-500/15 text-amber-400' };
      case 'approved':
        return { cls: 'bg-emerald-500/15 text-emerald-400' };
      case 'rejected':
        return { cls: 'bg-[rgba(255,255,255,0.08)] text-muted-foreground' };
      default:
        return { cls: 'bg-[rgba(255,255,255,0.08)] text-muted-foreground' };
    }
  };

  const stats = active ? (status.stats ?? EMPTY_STATS) : EMPTY_STATS;

  /** 按梦境会话分组（保留候选的 created_at 倒序语义） */
  const sessionGroups = useMemo(() => {
    const map = new Map<string, DreamBufferEntry[]>();
    for (const item of items) {
      const sid = item.dream_session_id || 'unknown';
      const list = map.get(sid);
      if (list) {
        list.push(item);
      } else {
        map.set(sid, [item]);
      }
    }
    return Array.from(map.entries());
  }, [items]);

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div className="flex items-center justify-between gap-4">
        <p className="text-sm text-muted-foreground">{t('management.dream.subtitle')}</p>
        <button
          type="button"
          onClick={() => void load()}
          aria-label={t('management.dream.refresh')}
          className="flex shrink-0 items-center gap-1.5 rounded-lg border border-[var(--glass-border)] px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.06)]"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          {t('management.dream.refresh')}
        </button>
      </div>

      {isLoading ? (
        <div className="glass-panel p-8 text-center text-sm text-muted-foreground">
          {t('common.loading')}
        </div>
      ) : loadError ? (
        <div className="glass-panel space-y-3 p-8 text-center">
          <AlertTriangle className="mx-auto h-8 w-8 text-red-400" />
          <p className="text-sm text-red-400">{t('management.common.loadFailed')}</p>
          <button
            type="button"
            onClick={() => void load()}
            className="rounded-lg border border-[var(--glass-border)] px-4 py-1.5 text-xs transition-colors hover:bg-[rgba(255,255,255,0.06)]"
          >
            {t('management.common.retry')}
          </button>
        </div>
      ) : (
        <>
          {/* ── 状态卡片 ── */}
          <div className="glass-panel space-y-4 p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <Moon className="h-4 w-4 text-primary" />
                <h3 className="text-sm font-semibold">{t('management.dream.statusTitle')}</h3>
                <span
                  className={cn('rounded px-2 py-0.5 text-[10px] font-medium', statusMeta.badgeCls)}
                >
                  {t(`management.dream.statusBadge.${statusMeta.badgeKey}`)}
                </span>
              </div>
            </div>

            {active ? (
              <>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  <div className="rounded-lg bg-[rgba(255,255,255,0.04)] p-3">
                    <p className="text-[10px] text-muted-foreground">
                      {t('management.dream.lastSessionAt')}
                    </p>
                    <p className="mt-0.5 truncate text-sm font-medium">
                      {status.last_session_at
                        ? new Date(status.last_session_at).toLocaleString()
                        : t('management.dream.emptyValue')}
                    </p>
                  </div>
                  <div className="rounded-lg bg-[rgba(255,255,255,0.04)] p-3">
                    <p className="text-[10px] text-muted-foreground">
                      {t('management.dream.statSessions')}
                    </p>
                    <p className="mt-0.5 text-sm font-medium tabular-nums">{stats.sessions}</p>
                  </div>
                  <div className="rounded-lg bg-[rgba(255,255,255,0.04)] p-3">
                    <p className="text-[10px] text-muted-foreground">
                      {t('management.dream.statGenerated')}
                    </p>
                    <p className="mt-0.5 text-sm font-medium tabular-nums">{stats.generated}</p>
                  </div>
                  <div className="rounded-lg bg-[rgba(255,255,255,0.04)] p-3">
                    <p className="text-[10px] text-muted-foreground">
                      {t('management.dream.statPurges')}
                    </p>
                    <p className="mt-0.5 text-sm font-medium tabular-nums">{stats.purges}</p>
                  </div>
                </div>
              </>
            ) : (
              <div className="flex items-center gap-3 rounded-lg bg-[rgba(255,255,255,0.04)] p-4">
                <Ban className="h-5 w-5 shrink-0 text-muted-foreground" />
                <div className="min-w-0">
                  <p className="text-sm font-medium">{t('management.dream.disabledTitle')}</p>
                  <p className="text-xs text-muted-foreground">
                    {t('management.dream.disabledHint')}
                  </p>
                </div>
              </div>
            )}
          </div>

          {/* ── 操作区（仅启用时） ── */}
          {active && (
            <div className="glass-panel space-y-3 p-4">
              <h3 className="text-sm font-semibold">{t('management.dream.operationsTitle')}</h3>
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={() => void handleAction('trigger', () => dreamApi.trigger())}
                  disabled={!!busyAction}
                  className="flex items-center gap-1.5 rounded-lg border border-[var(--glass-border)] px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.06)] disabled:opacity-50"
                >
                  <Play className="h-3.5 w-3.5" />
                  {t('management.dream.trigger')}
                </button>
                <button
                  type="button"
                  onClick={() => void handleAction('purge', () => dreamApi.purge())}
                  disabled={!!busyAction}
                  className="flex items-center gap-1.5 rounded-lg border border-[var(--glass-border)] px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.06)] disabled:opacity-50"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                  {t('management.dream.purge')}
                </button>
              </div>
              {actionError && (
                <p className="text-xs text-red-400">{t('management.dream.actionFailed')}</p>
              )}
            </div>
          )}

          {/* ── 梦境候选列表（仅启用时） ── */}
          {active && (
            <div className="glass-panel space-y-3 p-4">
              <div className="flex items-center justify-between gap-2">
                <h3 className="text-sm font-semibold">{t('management.dream.listTitle')}</h3>
                <span className="text-[10px] text-muted-foreground">
                  {t('management.dream.listTotal', { count: total })}
                </span>
              </div>

              {listError ? (
                <p className="py-6 text-center text-xs text-red-400">
                  {t('management.dream.listLoadFailed')}
                </p>
              ) : sessionGroups.length === 0 ? (
                <p className="py-6 text-center text-sm text-muted-foreground">
                  {t('management.dream.listEmpty')}
                </p>
              ) : (
                <div className="space-y-4">
                  {sessionGroups.map(([sessionId, entries]) => (
                    <div key={sessionId} className="rounded-lg bg-[rgba(255,255,255,0.04)] p-3">
                      <div className="mb-2 flex items-center justify-between gap-2">
                        <p className="text-[10px] text-muted-foreground">
                          {t('management.dream.sessionTitle')} · {sessionId}
                        </p>
                        <button
                          type="button"
                          onClick={() => void handleClearSession(sessionId)}
                          disabled={!!busyAction}
                          className="flex items-center gap-1 rounded border border-[var(--glass-border)] px-2 py-1 text-[10px] text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.06)] disabled:opacity-50"
                        >
                          <Trash2 className="h-3 w-3" />
                          {t('management.dream.clearSession')}
                        </button>
                      </div>
                      <div className="space-y-2">
                        {entries.map((item) => {
                          const meta = decisionMeta(item.decision);
                          return (
                            <div
                              key={item.id}
                              className="rounded-lg border border-[var(--glass-border)]/60 p-3"
                            >
                              <p className="text-sm leading-relaxed">{item.candidate_content}</p>
                              <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-muted-foreground">
                                <span
                                  className={cn(
                                    'rounded px-1.5 py-0.5 font-medium',
                                    meta.cls,
                                  )}
                                >
                                  {t(`management.dream.decision.${item.decision}`)}
                                </span>
                                <span className="tabular-nums">
                                  {t('management.dream.lucidity')}:{' '}
                                  {Math.round((item.lucidity_score ?? 0) * 100)}%
                                </span>
                                <span>
                                  {t('management.dream.associatedMemories')}:{' '}
                                  {item.associated_memories?.length ?? 0}
                                </span>
                                <span>
                                  {t('management.dream.associatedEntities')}:{' '}
                                  {item.associated_entities?.length ?? 0}
                                </span>
                              </div>
                              {item.decision === 'pending' && (
                                <div className="mt-2 flex gap-2">
                                  <button
                                    type="button"
                                    onClick={() =>
                                      void handleAction('confirm', () =>
                                        dreamApi.confirm(item.id),
                                      )
                                    }
                                    disabled={!!busyAction}
                                    className="flex items-center gap-1 rounded-lg bg-emerald-500/15 px-2.5 py-1 text-[10px] font-medium text-emerald-400 transition-colors hover:bg-emerald-500/25 disabled:opacity-50"
                                  >
                                    <Check className="h-3 w-3" />
                                    {t('management.dream.confirm')}
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() => void handleReject(item.id)}
                                    disabled={!!busyAction}
                                    className="flex items-center gap-1 rounded-lg bg-red-500/15 px-2.5 py-1 text-[10px] font-medium text-red-400 transition-colors hover:bg-red-500/25 disabled:opacity-50"
                                  >
                                    <X className="h-3 w-3" />
                                    {t('management.dream.reject')}
                                  </button>
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* ── 配置编辑区 ── */}
          <div className="glass-panel space-y-3 p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-semibold">{t('management.dream.configTitle')}</h3>
              <div className="flex items-center gap-2">
                {saved && <span className="text-[10px] text-emerald-400">{t('management.dream.saved')}</span>}
                <button
                  type="button"
                  onClick={() => void handleSaveConfig()}
                  disabled={!draft || !!busyAction}
                  className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-85 disabled:opacity-50"
                >
                  <Save className="h-3.5 w-3.5" />
                  {t('management.dream.save')}
                </button>
              </div>
            </div>

            {!draft ? (
              <p className="text-xs text-muted-foreground">{t('management.dream.configLoadFailed')}</p>
            ) : (
              <div className="space-y-3">
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  <CheckboxField
                    label={t('management.dream.field.enabled')}
                    checked={draft.enabled}
                    onChange={(v) => updateDraft({ enabled: v })}
                    testId="dream-config-enabled"
                  />
                  <TextField
                    label={t('management.dream.field.model')}
                    value={draft.model}
                    onChange={(v) => updateDraft({ model: v })}
                  />
                  <NumberField
                    label={t('management.dream.field.dreamTemperature')}
                    value={draft.dream_temperature}
                    step={0.1}
                    onChange={(v) => updateDraft({ dream_temperature: v })}
                  />
                  <NumberField
                    label={t('management.dream.field.candidatesPerSession')}
                    value={draft.candidates_per_session}
                    step={1}
                    onChange={(v) => updateDraft({ candidates_per_session: v })}
                  />
                  <NumberField
                    label={t('management.dream.field.materialWindowDays')}
                    value={draft.material_window_days}
                    step={1}
                    onChange={(v) => updateDraft({ material_window_days: v })}
                  />
                  <NumberField
                    label={t('management.dream.field.maxMaterialItems')}
                    value={draft.max_material_items}
                    step={1}
                    onChange={(v) => updateDraft({ max_material_items: v })}
                  />
                  <NumberField
                    label={t('management.dream.field.minLucidity')}
                    value={draft.min_lucidity}
                    step={0.1}
                    onChange={(v) => updateDraft({ min_lucidity: v })}
                  />
                  <NumberField
                    label={t('management.dream.field.dreamTtlHours')}
                    value={draft.dream_ttl_hours}
                    step={1}
                    onChange={(v) => updateDraft({ dream_ttl_hours: v })}
                  />
                  <NumberField
                    label={t('management.dream.field.purgeThreshold')}
                    value={draft.purge_threshold}
                    step={0.1}
                    onChange={(v) => updateDraft({ purge_threshold: v })}
                  />
                  <NumberField
                    label={t('management.dream.field.confirmedImportance')}
                    value={draft.confirmed_importance}
                    step={0.1}
                    onChange={(v) => updateDraft({ confirmed_importance: v })}
                  />
                  <CheckboxField
                    label={t('management.dream.field.surfaceOnWake')}
                    checked={draft.surface_on_wake}
                    onChange={(v) => updateDraft({ surface_on_wake: v })}
                  />
                  <NumberField
                    label={t('management.dream.field.surfaceProbability')}
                    value={draft.surface_probability}
                    step={0.1}
                    onChange={(v) => updateDraft({ surface_probability: v })}
                  />
                  <NumberField
                    label={t('management.dream.field.maxSurfacePerDay')}
                    value={draft.max_surface_per_day}
                    step={1}
                    onChange={(v) => updateDraft({ max_surface_per_day: v })}
                  />
                  <TextField
                    label={t('management.dream.field.wakeTime')}
                    value={draft.schedule.wake_time}
                    onChange={(v) => updateSchedule({ wake_time: v })}
                  />
                  <TextField
                    label={t('management.dream.field.sleepTime')}
                    value={draft.schedule.sleep_time}
                    onChange={(v) => updateSchedule({ sleep_time: v })}
                  />
                </div>
                {actionError && (
                  <p className="text-xs text-red-400">{t('management.dream.actionFailed')}</p>
                )}
              </div>
            )}
          </div>

          {/* ── 生理信号区块（手环心率 BLE + SleepSensor 融合） ── */}
          <div className="glass-panel space-y-3 p-4">
            <div className="flex items-center gap-2">
              <HeartPulse className="h-4 w-4 text-primary" />
              <h3 className="text-sm font-semibold">{t('management.dream.physio.title')}</h3>
              <span className={cn('rounded px-2 py-0.5 text-[10px] font-medium', physioBadge.cls)}>
                {t(`management.dream.physio.badge.${physioBadge.key}`)}
              </span>
            </div>

            {physioActionError && (
              <p className="text-xs text-red-400">{t('management.dream.physio.actionFailed')}</p>
            )}

            {!physioActive && (
              <div className="flex items-center gap-3 rounded-lg bg-[rgba(255,255,255,0.04)] p-4">
                <Ban className="h-5 w-5 shrink-0 text-muted-foreground" />
                <div className="min-w-0">
                  <p className="text-sm font-medium">{t('management.dream.physio.disabledTitle')}</p>
                  <p className="text-xs text-muted-foreground">
                    {t('management.dream.physio.disabledHint')}
                  </p>
                </div>
              </div>
            )}

            {!bleAvailable && (
              <div className="flex items-center gap-3 rounded-lg bg-[rgba(255,255,255,0.04)] p-4">
                <Smartphone className="h-5 w-5 shrink-0 text-muted-foreground" />
                <p className="text-xs text-muted-foreground">
                  {t('management.dream.physio.bleUnavailable')}
                </p>
              </div>
            )}

            {physioActive && bleAvailable && (
              <div className="space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-xs text-muted-foreground">
                    {t('management.dream.physio.pairingTitle')}
                  </p>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => void handleScan()}
                      disabled={!!physioBusy}
                      className="flex items-center gap-1.5 rounded-lg border border-[var(--glass-border)] px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.06)] disabled:opacity-50"
                    >
                      <Bluetooth className="h-3.5 w-3.5" />
                      {t('management.dream.physio.scan')}
                    </button>
                    {(bleInfo?.status === 'connected' || bleInfo?.status === 'reconnecting') && (
                      <button
                        type="button"
                        onClick={() => void handleDisconnect()}
                        disabled={!!physioBusy}
                        className="flex items-center gap-1.5 rounded-lg border border-[var(--glass-border)] px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.06)] disabled:opacity-50"
                      >
                        <WifiOff className="h-3.5 w-3.5" />
                        {t('management.dream.physio.disconnect')}
                      </button>
                    )}
                  </div>
                </div>

                {bleError && <p className="text-xs text-amber-400">{bleError}</p>}

                {scannedDevices.length > 0 && (
                  <div className="rounded-lg bg-[rgba(255,255,255,0.04)] p-3">
                    <p className="mb-2 text-[10px] text-muted-foreground">
                      {t('management.dream.physio.scannedTitle')}（{scannedDevices.length}）
                    </p>
                    <ul className="space-y-1">
                      {scannedDevices.map((device) => (
                        <li
                          key={device.deviceId}
                          className="flex items-center justify-between gap-2 text-xs"
                        >
                          <span className="min-w-0 truncate">
                            {device.name || device.address || device.deviceId}
                            {device.hasHeartRate && (
                              <span className="ml-1.5 rounded bg-emerald-500/15 px-1 py-0.5 text-[10px] text-emerald-400">
                                {t('management.dream.physio.deviceHeartRate')}
                              </span>
                            )}
                          </span>
                          <button
                            type="button"
                            onClick={() => void handleConnect(device)}
                            disabled={!!physioBusy}
                            className="shrink-0 rounded-lg bg-sky-500/15 px-2.5 py-1 text-[10px] font-medium text-sky-400 transition-colors hover:bg-sky-500/25 disabled:opacity-50"
                          >
                            {t('management.dream.physio.connect')}
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {pairedDevices.length > 0 && (
                  <div className="rounded-lg bg-[rgba(255,255,255,0.04)] p-3">
                    <p className="mb-2 text-[10px] text-muted-foreground">
                      {t('management.dream.physio.pairedTitle')}
                    </p>
                    <ul className="space-y-1">
                      {pairedDevices.map((device) => (
                        <li
                          key={device.id ?? device.fingerprint}
                          className="flex items-center justify-between gap-2 text-xs"
                        >
                          <span className="min-w-0 truncate">
                            {device.name || device.fingerprint}
                          </span>
                          <button
                            type="button"
                            onClick={() => void handleForget(device)}
                            disabled={!!physioBusy}
                            className="shrink-0 rounded-lg bg-red-500/15 px-2.5 py-1 text-[10px] font-medium text-red-400 transition-colors hover:bg-red-500/25 disabled:opacity-50"
                          >
                            {t('management.dream.physio.forget')}
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {physioEstimator &&
                  (physioEstimator.hr_sleep_confidence !== undefined ||
                    physioEstimator.base_hr !== undefined) && (
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                      {physioEstimator.hr_sleep_confidence !== undefined && (
                        <div className="rounded-lg bg-[rgba(255,255,255,0.04)] p-3">
                          <p className="text-[10px] text-muted-foreground">
                            {t('management.dream.physio.hrSleepConfidence')}
                          </p>
                          <p className="mt-0.5 text-sm font-medium tabular-nums">
                            {Math.round(physioEstimator.hr_sleep_confidence * 100)}%
                          </p>
                        </div>
                      )}
                      {physioEstimator.base_hr !== undefined && (
                        <div className="rounded-lg bg-[rgba(255,255,255,0.04)] p-3">
                          <p className="text-[10px] text-muted-foreground">
                            {t('management.dream.physio.baseHr')}
                          </p>
                          <p className="mt-0.5 text-sm font-medium tabular-nums">
                            {physioEstimator.base_hr} bpm
                          </p>
                        </div>
                      )}
                      {physioEstimator.window_size !== undefined && (
                        <div className="rounded-lg bg-[rgba(255,255,255,0.04)] p-3">
                          <p className="text-[10px] text-muted-foreground">
                            {t('management.dream.physio.windowSize')}
                          </p>
                          <p className="mt-0.5 text-sm font-medium tabular-nums">
                            {physioEstimator.window_size}
                          </p>
                        </div>
                      )}
                    </div>
                  )}
              </div>
            )}

            <div className="space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-xs text-muted-foreground">
                  {t('management.dream.physio.configTitle')}
                </p>
                <div className="flex items-center gap-2">
                  {physioSaved && (
                    <span className="text-[10px] text-emerald-400">
                      {t('management.dream.physio.saved')}
                    </span>
                  )}
                  <button
                    type="button"
                    onClick={() => void handleSavePhysioConfig()}
                    disabled={!physioDraft || !!physioBusy}
                    className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-85 disabled:opacity-50"
                  >
                    <Save className="h-3.5 w-3.5" />
                    {t('management.dream.physio.save')}
                  </button>
                  <button
                    type="button"
                    onClick={handleClearBaseline}
                    disabled={!!physioBusy}
                    className="flex items-center gap-1.5 rounded-lg border border-red-500/30 px-3 py-1.5 text-xs text-red-400 transition-colors hover:bg-red-500/10 disabled:opacity-50"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                    {t('management.dream.physio.clearBaseline')}
                  </button>
                </div>
              </div>

              {!physioDraft ? (
                <p className="text-xs text-muted-foreground">
                  {t('management.dream.physio.configLoadFailed')}
                </p>
              ) : (
                <div className="space-y-3">
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                    <CheckboxField
                      label={t('management.dream.physio.field.enabled')}
                      checked={physioDraft.enabled}
                      onChange={(v) => updatePhysioDraft({ enabled: v })}
                      testId="physio-config-enabled"
                    />
                    <TextField
                      label={t('management.dream.physio.field.deviceNameHint')}
                      value={physioDraft.device_name_hint}
                      onChange={(v) => updatePhysioDraft({ device_name_hint: v })}
                    />
                    <NumberField
                      label={t('management.dream.physio.field.scanTimeoutSec')}
                      value={physioDraft.scan_timeout_sec}
                      step={1}
                      onChange={(v) => updatePhysioDraft({ scan_timeout_sec: v })}
                    />
                    <NumberField
                      label={t('management.dream.physio.field.reconnectIntervalSec')}
                      value={physioDraft.reconnect_interval_sec}
                      step={1}
                      onChange={(v) => updatePhysioDraft({ reconnect_interval_sec: v })}
                    />
                    <NumberField
                      label={t('management.dream.physio.field.baseDropRatio')}
                      value={physioDraft.base_drop_ratio}
                      step={0.01}
                      onChange={(v) => updatePhysioDraft({ base_drop_ratio: v })}
                    />
                    <NumberField
                      label={t('management.dream.physio.field.baseDropConfirmMin')}
                      value={physioDraft.base_drop_confirm_min}
                      step={1}
                      onChange={(v) => updatePhysioDraft({ base_drop_confirm_min: v })}
                    />
                    <NumberField
                      label={t('management.dream.physio.field.hrStabilityThreshold')}
                      value={physioDraft.hr_stability_threshold}
                      step={0.5}
                      onChange={(v) => updatePhysioDraft({ hr_stability_threshold: v })}
                    />
                    <CheckboxField
                      label={t('management.dream.physio.field.baseHrLearning')}
                      checked={physioDraft.base_hr_learning}
                      onChange={(v) => updatePhysioDraft({ base_hr_learning: v })}
                    />
                  </div>
                  <p className="text-[10px] text-muted-foreground">
                    {t('management.dream.physio.storeRawHrNote')}
                  </p>
                  {physioActionError && (
                    <p className="text-xs text-red-400">
                      {t('management.dream.physio.actionFailed')}
                    </p>
                  )}
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
