/**
 * 前端主后端集群感知故障转移（哨兵集群自动切换）。
 *
 * 让前端在"当前后端失联"时，自动从候选对等节点（cluster peers + 局域网发现 +
 * 本地缓存）挑一个健康可达的后端并切换 base/ws 地址，随后重载当前窗以全新地址重连。
 * 这样桌宠可视化/管理界面/弹幕窗都能无缝转到接管节点（active 优先）。
 *
 * 设计要点：
 * - 候选集持久化到 localStorage（`cxo-backend-candidates`），保证 A 死后仍可用 B/C。
 * - 冷启动即 `/health` 探测；连续失败阈值后触发切换。
 * - 切换带冷却（`SWITCH_COOLDOWN_MS`）防止 A/B 震荡导致重载循环。
 * - 纯函数便于单测；React 侧封装见 `src/hooks/useBackendFailover.ts`。
 */
import {
  getApiBaseUrl,
  httpToWsUrl,
  setBackendUrl,
  setWsUrl,
} from '../api/base';

const CANDIDATES_KEY = 'cxo-backend-candidates';
const SWITCH_KEY = 'cxo-backend-last-switch';

export const PROBE_TIMEOUT_MS = 2500;
export const STATE_TIMEOUT_MS = 2500;
export const SWITCH_COOLDOWN_MS = 10000;
export const FAILOVER_POLL_MS = 8000;
export const FAILOVER_CONSECUTIVE = 2;

/** 切换成功时 window 派发的自定义事件 */
export const BACKEND_SWITCHED_EVENT = 'backend:switched';

export interface SwitchedDetail {
  /** 切换到的后端 base URL */
  url: string;
}

/** 归一化 base URL：去掉末尾斜杠，保证比较一致 */
export function normalize(url: string): string {
  return (url || '').replace(/\/+$/, '');
}

/** 自带超时的 fetch：不依赖 AbortSignal.timeout，兼容测试与旧运行时 */
export function fetchJson<T>(url: string, timeoutMs = PROBE_TIMEOUT_MS): Promise<T | null> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  return fetch(url, { method: 'GET', signal: ctrl.signal })
    .then((res) => {
      if (!res.ok) return null;
      return res.json() as Promise<T>;
    })
    .catch(() => null)
    .finally(() => clearTimeout(timer));
}

/** 只探测可达性，不解析 body */
export async function probeBackend(url: string, timeoutMs = PROBE_TIMEOUT_MS): Promise<boolean> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`${normalize(url)}/health`, { method: 'GET', signal: ctrl.signal });
    return res.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

/** 读取某节点的集群角色（active/standby/candidate）；不可达或集群未启用返回 null */
export async function readClusterRole(url: string, timeoutMs = STATE_TIMEOUT_MS): Promise<string | null> {
  const data = await fetchJson<{ state?: { role?: string; enabled?: boolean } }>(
    `${normalize(url)}/api/cluster/state`,
    timeoutMs,
  );
  const state = data?.state;
  if (state && typeof state.role === 'string') {
    return state.role;
  }
  return state?.enabled === true ? 'unknown' : null;
}

/** 读取某节点配置的对等节点端点列表 */
export async function fetchClusterPeers(url: string, timeoutMs = STATE_TIMEOUT_MS): Promise<string[]> {
  const data = await fetchJson<{ state?: { peers?: string[] } }>(
    `${normalize(url)}/api/cluster/state`,
    timeoutMs,
  );
  const peers = data?.state?.peers;
  return Array.isArray(peers) ? peers.map(normalize).filter(Boolean) : [];
}

/** 局域网发现到的其他 CX-O 后端 */
export async function fetchDiscoveryBackends(url: string, timeoutMs = STATE_TIMEOUT_MS): Promise<string[]> {
  const data = await fetchJson<{ backends?: Array<{ url?: string }> }>(
    `${normalize(url)}/api/discovery/backends`,
    timeoutMs,
  );
  const backends = data?.backends;
  if (!Array.isArray(backends)) return [];
  return backends.map((b) => normalize(b?.url || '')).filter(Boolean);
}

// ---- 候选集持久化 ----

export function readCandidates(): string[] {
  try {
    const raw = localStorage.getItem(CANDIDATES_KEY);
    if (!raw) return [];
    const arr = JSON.parse(raw);
    return Array.isArray(arr) ? arr.map(normalize).filter(Boolean) : [];
  } catch {
    return [];
  }
}

export function writeCandidates(urls: string[]): void {
  try {
    const uniq = [...new Set(urls.map(normalize).filter(Boolean))];
    localStorage.setItem(CANDIDATES_KEY, JSON.stringify(uniq));
  } catch {
    /* 持久化失败不影响切换判定 */
  }
}

function readLastSwitch(): { url: string; at: number } | null {
  try {
    const raw = localStorage.getItem(SWITCH_KEY);
    if (!raw) return null;
    const o = JSON.parse(raw);
    if (!o || !o.url) return null;
    return { url: normalize(o.url), at: Number(o.at) || 0 };
  } catch {
    return null;
  }
}

function writeLastSwitch(url: string): void {
  try {
    localStorage.setItem(SWITCH_KEY, JSON.stringify({ url: normalize(url), at: Date.now() }));
  } catch {
    /* 忽略 */
  }
}

/**
 * 从当前后端收集候选节点（自己 + cluster peers + 局域网发现），并更新持久化候选集。
 * 应在连接可用时（启动 / 每次切换后）调用。
 */
export async function refreshCandidates(current = normalize(getApiBaseUrl())): Promise<string[]> {
  const pool = new Set<string>([current]);
  readCandidates().forEach((u) => pool.add(u));
  const [peers, discovered] = await Promise.allSettled([
    fetchClusterPeers(current),
    fetchDiscoveryBackends(current),
  ]);
  if (peers.status === 'fulfilled') peers.value.forEach((u) => pool.add(u));
  if (discovered.status === 'fulfilled') discovered.value.forEach((u) => pool.add(u));
  const list = [...pool];
  writeCandidates(list);
  return list;
}

/**
 * 主后端故障转移主流程。
 * - 当前仍可达 → 返回 null（不做切换）。
 * - 当前不可达 → 探测候选（排除当前），选健康者；优先 role==='active'。
 * - 切换成功 → 更新 base/ws 地址、写候选集、派发 BACKEND_SWITCHED_EVENT，返回新 URL。
 *
 * @param current 当前 base URL（缺省取 getApiBaseUrl()）
 */
export async function runBackendFailover(
  current = normalize(getApiBaseUrl()),
): Promise<string | null> {
  // 当前仍可用：无需切换
  if (await probeBackend(current)) return null;

  // 冷却：刚切换到的 url 在冷却期内不反复切换，避免 A/B 震荡
  const last = readLastSwitch();
  if (last && last.url === current && Date.now() - last.at < SWITCH_COOLDOWN_MS) {
    return null;
  }

  const candidates = readCandidates().filter((u) => u && u !== current);
  if (candidates.length === 0) return null;

  const healthy: string[] = [];
  for (const url of candidates) {
    if (await probeBackend(url)) {
      healthy.push(url);
    }
  }
  if (healthy.length === 0) return null;

  const roles = await Promise.all(
    healthy.map(async (url) => ({ url, role: await readClusterRole(url) })),
  );
  const active = roles.find((r) => r.role === 'active');
  const target = (active ?? roles[0]).url;

  if (normalize(target) === current) return null;

  setBackendUrl(normalize(target));
  // 主后端故障转移时 WS 必须跟随新节点（覆盖可能存在的旧显式 ws 覆盖）
  setWsUrl(httpToWsUrl(normalize(target)));
  writeCandidates([normalize(target), ...candidates]);
  writeLastSwitch(normalize(target));

  window.dispatchEvent(
    new CustomEvent<SwitchedDetail>(BACKEND_SWITCHED_EVENT, { detail: { url: normalize(target) } }),
  );
  return normalize(target);
}

export const backendFailoverInternals = {
  CANDIDATES_KEY,
  SWITCH_KEY,
  readLastSwitch,
  writeLastSwitch,
};