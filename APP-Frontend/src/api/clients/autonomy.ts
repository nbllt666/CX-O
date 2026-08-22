/**
 * autonomy 域客户端：CX-O-Autonomy「Agent 生活」自主系统访问层。
 * 端点面对齐后端 server/api/routers/autonomy.py（挂载前缀 /api）：
 *   GET  /api/autonomy/status
 *   POST /api/autonomy/control
 *   GET  /api/autonomy/audit
 *   GET  /api/autonomy/config
 *   PUT  /api/autonomy/config
 *
 * 降级口径（对齐 tuner.ts）：
 * - 查询类（getStatus/getConfig/getAudit）失败返回 null / 空页，供 UI 降级展示；
 *   其中 getStatus 对「未启用」不抛错（后端返回 {"status": "disabled"}，HTTP 200）。
 * - 触发/变更类（control/updateConfig）抛归一化错误（normalizeError），供 UI 捕获提示。
 */
import { request, normalizeError } from '../base';
import type {
  AutonomyAuditEntry,
  AutonomyConfig,
  AutonomyControlResult,
  AutonomyStatus,
} from '../types';

/** 控制指令枚举（对齐后端 CONTROL_ACTIONS） */
export type AutonomyControlAction = 'enable' | 'disable' | 'pause' | 'resume' | 'emergency_stop';

/** 审计日志分页响应：{"items": [...], "total": int} */
export interface AutonomyAuditPage {
  items: AutonomyAuditEntry[];
  total: number;
}

export const autonomyApi = {
  /**
   * 状态快照。未启用返回 {status: "disabled"}（HTTP 200）；后端离线/网络失败返回 null，
   * 供 UI 展示错误态。
   */
  async getStatus(): Promise<AutonomyStatus | null> {
    try {
      return await request<AutonomyStatus>({ url: '/api/autonomy/status' });
    } catch {
      return null;
    }
  },

  /** 下发控制指令（enable/disable/pause/resume/emergency_stop）；失败抛归一化错误 */
  async control(action: AutonomyControlAction): Promise<AutonomyControlResult> {
    try {
      return await request<AutonomyControlResult>({
        url: '/api/autonomy/control',
        method: 'post',
        data: { action },
      });
    } catch (err) {
      throw normalizeError(err);
    }
  },

  /** 审计日志分页；后端离线返回 null（供 UI 降级为错误提示） */
  async getAudit(params?: { limit?: number; offset?: number }): Promise<AutonomyAuditPage | null> {
    try {
      return await request<AutonomyAuditPage>({
        url: '/api/autonomy/audit',
        params: { limit: params?.limit ?? 20, offset: params?.offset ?? 0 },
      });
    } catch {
      return null;
    }
  },

  /** 当前配置；未装配（404）/后端离线返回 null */
  async getConfig(): Promise<AutonomyConfig | null> {
    try {
      return await request<AutonomyConfig>({ url: '/api/autonomy/config' });
    } catch {
      return null;
    }
  },

  /** 局部更新配置并保存（非法字段后端返回 422）；失败抛归一化错误 */
  async updateConfig(partial: Partial<AutonomyConfig>): Promise<AutonomyConfig> {
    try {
      return await request<AutonomyConfig>({
        url: '/api/autonomy/config',
        method: 'put',
        data: partial,
      });
    } catch (err) {
      throw normalizeError(err);
    }
  },
};
