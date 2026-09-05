/**
 * cxfc 域客户端：CXFC 插件 / 技能管理。
 * 端点面对齐 CX-O-Frontend clients/cxfc.ts。
 */
import { request } from '../base';
import type { CxfcDiscoveredPlugin, CxfcPlugin, CxfcSkill } from '../types';

// ── CXFC 数据网关类型（域专属类型按惯例定义在客户端模块内） ──

/** relay 目标条目（GET /api/cxfc/relay/targets） */
export interface CxfcRelayTarget {
  plugin_id: string;
  name: string;
  transport: string;
  active: boolean;
}

/** 记忆检索载荷（POST /api/cxfc/memory/search；agent_id 显式传入，不做隐式隔离） */
export interface CxfcMemorySearchPayload {
  query: string;
  limit?: number;
  agent_id?: string;
  [key: string]: unknown;
}

/** 记忆检索响应（对齐 MemoryManager.search_memories 结果契约的宽松视图） */
export interface CxfcMemorySearchResult {
  results?: Array<Record<string, unknown>>;
  total?: number;
  [key: string]: unknown;
}

/** 记忆写入载荷（POST /api/cxfc/memory/write；后端按 memory.schema.json 校验） */
export interface CxfcMemoryWritePayload {
  content: string;
  agent_id?: string;
  importance?: number;
  [key: string]: unknown;
}

/** 记忆写入响应 */
export interface CxfcMemoryWriteResult {
  status?: string;
  memory_id?: string;
  id?: string;
  [key: string]: unknown;
}

/** 记忆库统计（GET /api/cxfc/memory/stats） */
export interface CxfcMemoryStats {
  total_memories?: number;
  [key: string]: unknown;
}

/** 单条记忆记录（GET /api/cxfc/memory/{id}；结构以 memory.schema.json 为准） */
export type CxfcMemoryRecord = Record<string, unknown>;

/** 生理样本上报载荷（POST /api/cxfc/physio/report；隐私红线：不回传原始 HR 序列） */
export interface CxfcPhysioReportPayload {
  heart_rate?: number;
  source?: string;
  [key: string]: unknown;
}

/** 生理上报受理响应 */
export interface CxfcPhysioReportResult {
  status?: string;
  [key: string]: unknown;
}

/** 生理状态（GET /api/cxfc/physio/status；仅衍生指标） */
export type CxfcPhysioStatus = Record<string, unknown>;

/** 睡眠数据（GET /api/cxfc/physio/sleep；仅衍生指标） */
export type CxfcPhysioSleep = Record<string, unknown>;

export const cxfcApi = {
  async getCxfcPlugins(): Promise<CxfcPlugin[]> {
    const response = await request<{ plugins: CxfcPlugin[] }>({ url: '/api/cxfc/plugins' });
    return response.plugins || [];
  },

  async getCxfcSkills(): Promise<CxfcSkill[]> {
    const response = await request<{ skills: CxfcSkill[] }>({ url: '/api/cxfc/skills' });
    return response.skills || [];
  },

  connectCxfcPlugin(host: string, port: number): Promise<{ status: string; plugin_id: string }> {
    return request<{ status: string; plugin_id: string }>({
      url: '/api/cxfc/connect',
      method: 'post',
      data: { host, port },
    });
  },

  disconnectCxfcPlugin(pluginId: string): Promise<{ status: string }> {
    return request<{ status: string }>({
      url: `/api/cxfc/plugins/${encodeURIComponent(pluginId)}/disconnect`,
      method: 'post',
    });
  },

  refreshCxfcPlugin(pluginId: string): Promise<{ status: string }> {
    return request<{ status: string }>({
      url: `/api/cxfc/plugins/${encodeURIComponent(pluginId)}/refresh`,
      method: 'post',
    });
  },

  discoverCxfcPlugins(scan = false): Promise<{ remote: CxfcDiscoveredPlugin[] }> {
    return request<{ remote: CxfcDiscoveredPlugin[] }>({
      url: '/api/cxfc/discover',
      params: scan ? { scan: true } : undefined,
    });
  },

  // relay（前端转接）与 embedded（后端进程内嵌入式）扩展端点
  relayRegister(payload: {
    plugin_id?: string;
    name?: string;
    tools: Array<{ name: string; description?: string }>;
    capabilities?: string[];
    skills?: unknown[];
    token?: string;
  }): Promise<{ status: string; plugin_id: string }> {
    return request<{ status: string; plugin_id: string }>({
      url: '/api/cxfc/relay/register',
      method: 'post',
      data: payload,
    });
  },

  relayTargets(): Promise<{ targets: CxfcRelayTarget[] }> {
    return request<{ targets: CxfcRelayTarget[] }>({
      url: '/api/cxfc/relay/targets',
    });
  },

  relayResult(payload: {
    plugin_id: string;
    request_id: string;
    success: boolean;
    result?: unknown;
    error?: string;
  }): Promise<{ status: string }> {
    return request<{ status: string }>({
      url: '/api/cxfc/relay/result',
      method: 'post',
      data: payload,
    });
  },

  embeddedRegister(payload: {
    plugin_id: string;
    name?: string;
    tools: Array<{ name: string; description?: string; parameters?: object; handler?: string }>;
    capabilities?: string[];
    skills?: unknown[];
  }): Promise<{ status: string; plugin_id: string }> {
    return request<{ status: string; plugin_id: string }>({
      url: '/api/cxfc/embedded',
      method: 'post',
      data: payload,
    });
  },

  // ── CXFC 数据网关（/api/cxfc/memory/*、/api/cxfc/physio/*） ──
  // 鉴权口径对齐 admin 客户端：base.ts 请求拦截器统一注入 x-api-key
  // （localStorage cxo-admin-key，与后端网关 verify_admin_api_key 运维旁路对齐）；
  // 插件侧走 plugin_access_token（Authorization: Bearer），前端管理页测试器走管理密钥旁路。

  /** 记忆检索：POST /api/cxfc/memory/search（向量+关键词） */
  memorySearch(payload: CxfcMemorySearchPayload): Promise<CxfcMemorySearchResult> {
    return request<CxfcMemorySearchResult>({
      url: '/api/cxfc/memory/search',
      method: 'post',
      data: payload,
    });
  },

  /** 记忆写入：POST /api/cxfc/memory/write（后端按 memory.schema.json 校验） */
  memoryWrite(payload: CxfcMemoryWritePayload): Promise<CxfcMemoryWriteResult> {
    return request<CxfcMemoryWriteResult>({
      url: '/api/cxfc/memory/write',
      method: 'post',
      data: payload,
    });
  },

  /** 记忆库统计：GET /api/cxfc/memory/stats */
  memoryStats(): Promise<CxfcMemoryStats> {
    return request<CxfcMemoryStats>({ url: '/api/cxfc/memory/stats' });
  },

  /** 单条记忆详情：GET /api/cxfc/memory/{id} */
  memoryGet(id: string): Promise<CxfcMemoryRecord> {
    return request<CxfcMemoryRecord>({
      url: `/api/cxfc/memory/${encodeURIComponent(id)}`,
    });
  },

  /** 生理样本上报：POST /api/cxfc/physio/report（转发现有 PhysioSignalStore 管道） */
  physioReport(payload: CxfcPhysioReportPayload): Promise<CxfcPhysioReportResult> {
    return request<CxfcPhysioReportResult>({
      url: '/api/cxfc/physio/report',
      method: 'post',
      data: payload,
    });
  },

  /** 生理状态：GET /api/cxfc/physio/status（仅衍生指标，不含原始 HR 序列） */
  physioStatus(): Promise<CxfcPhysioStatus> {
    return request<CxfcPhysioStatus>({ url: '/api/cxfc/physio/status' });
  },

  /** 睡眠数据：GET /api/cxfc/physio/sleep（仅衍生指标） */
  physioSleep(): Promise<CxfcPhysioSleep> {
    return request<CxfcPhysioSleep>({ url: '/api/cxfc/physio/sleep' });
  },
};
