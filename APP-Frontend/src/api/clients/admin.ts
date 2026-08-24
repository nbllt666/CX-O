/**
 * admin 域客户端：CX-A 管理面访问层。
 * 端点面对齐后端 server（挂载前缀 /api）：
 *   GET  /api/admin/manifest
 *   GET  /api/admin/status
 *   POST /api/admin/control
 *   POST /api/admin/batch
 *   GET  /api/admin/audit?limit=&offset=
 *
 * 降级口径（对齐 autonomy.ts）：
 * - 查询类（fetchStatus/fetchAudit）失败返回 null / 空页，供 UI 降级展示。
 * - fetchManifest 为「启用网关」：admin 未启用（manifest 拉取 503/失败）或后端离线时
 *   同样抛归一化错误（normalizeError），由 UI 区分「离线全页错误态」与「未启用徽章」。
 * - 触发类（postControl/postBatch）抛归一化错误（normalizeError），供 UI 捕获提示。
 */
import { request, normalizeError } from '../base';

/** 集群信息块（manifest/status/cluster 共享结构） */
export interface AdminClusterInfo {
  enabled: boolean;
  node_id: string;
  role: string;
  epoch?: number;
  peers?: string[];
  [key: string]: unknown;
}

/** 自描述清单（GET /api/admin/manifest） */
export interface AdminManifest {
  instance_id: string;
  node_name: string;
  capabilities?: Record<string, boolean>;
  control_actions?: string[];
  agents?: unknown[];
  plugins?: unknown[];
  models?: string[];
  cluster?: AdminClusterInfo;
  endpoints?: Record<string, unknown>;
  [key: string]: unknown;
}

/** 实例状态快照（GET /api/admin/status） */
export interface AdminStatus {
  models?: unknown[];
  capabilities?: Record<string, boolean>;
  cluster?: AdminClusterInfo;
  [key: string]: unknown;
}

/** 单条控制指令载荷（POST /api/admin/control） */
export interface AdminControlPayload {
  action: string;
  target: string;
  agent_id?: string;
  request_id?: string;
  params?: Record<string, unknown>;
}

/** 单条控制指令响应 */
export interface AdminControlResult {
  status: string;
  [key: string]: unknown;
}

/** 批量步骤之一（POST /api/admin/batch） */
export interface AdminBatchStep {
  target: string;
  action: string;
  agent_id?: string;
  params?: Record<string, unknown>;
}

/** 批量控制载荷（POST /api/admin/batch） */
export interface AdminBatchPayload {
  request_id?: string;
  mode?: string;
  stop_on_error?: boolean;
  steps: AdminBatchStep[];
}

/** 批量控制响应 */
export interface AdminBatchResult {
  [key: string]: unknown;
}

/** 管理审计日志条目（GET /api/admin/audit） */
export interface AdminAuditEntry {
  id: string;
  timestamp: string;
  actor: string;
  level: string;
  action: string;
  target?: string;
  summary?: string;
  [key: string]: unknown;
}

/** 管理审计日志分页响应：{"items": [...], "total": int} */
export interface AdminAuditPage {
  items: AdminAuditEntry[];
  total?: number;
}

export const adminApi = {
  /**
   * 自描述清单。admin 未启用（manifest 拉取 503/失败）或后端离线时抛出归一化错误，
   * 由 UI 按错误类型区分「后端离线全页错误态」与「未启用徽章」。
   */
  async fetchManifest(): Promise<AdminManifest> {
    try {
      return await request<AdminManifest>({ url: '/api/admin/manifest' });
    } catch (err) {
      throw normalizeError(err);
    }
  },

  /** 实例状态快照（{models,capabilities,cluster}）；后端离线返回 null */
  async fetchStatus(): Promise<AdminStatus | null> {
    try {
      return await request<AdminStatus>({ url: '/api/admin/status' });
    } catch {
      return null;
    }
  },

  /** 下发单条控制指令（action+target）；失败抛归一化错误 */
  async postControl(payload: AdminControlPayload): Promise<AdminControlResult> {
    try {
      return await request<AdminControlResult>({
        url: '/api/admin/control',
        method: 'post',
        data: payload,
      });
    } catch (err) {
      throw normalizeError(err);
    }
  },

  /** 批量控制指令；失败抛归一化错误 */
  async postBatch(payload: AdminBatchPayload): Promise<AdminBatchResult> {
    try {
      return await request<AdminBatchResult>({
        url: '/api/admin/batch',
        method: 'post',
        data: payload,
      });
    } catch (err) {
      throw normalizeError(err);
    }
  },

  /** 管理审计日志分页；后端离线返回 null（供 UI 降级为错误提示） */
  async fetchAudit(params?: { limit?: number; offset?: number }): Promise<AdminAuditPage | null> {
    try {
      return await request<AdminAuditPage>({
        url: '/api/admin/audit',
        params: { limit: params?.limit ?? 20, offset: params?.offset ?? 0 },
      });
    } catch {
      return null;
    }
  },
};