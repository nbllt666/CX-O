/**
 * dream 域客户端：CX-O-Dream 梦境引擎访问层。
 * 端点面对齐后端 server/api/routers/dream.py（挂载前缀 /api）：
 *   GET    /api/dream/status
 *   POST   /api/dream/trigger
 *   GET    /api/dream/list
 *   POST   /api/dream/{id}/confirm
 *   POST   /api/dream/{id}/reject
 *   DELETE /api/dream/session/{session_id}
 *   POST   /api/dream/purge
 *   GET    /api/dream/config
 *   PUT    /api/dream/config
 *
 * 降级口径（对齐 autonomy.ts）：
 * - 查询类（getStatus/getList/getConfig）失败返回 null，供 UI 降级展示；
 *   其中 getStatus 对「未启用」不抛错（后端返回 {"status": "disabled"}，HTTP 200）。
 * - 触发/变更类（trigger/confirm/reject/purgeSession/purge/updateConfig）
 *   抛归一化错误（normalizeError），供 UI 捕获提示。
 */
import { request, normalizeError } from '../base';
import type {
  DreamConfirmResult,
  DreamConfig,
  DreamListResult,
  DreamPurgeResult,
  DreamPurgeSessionResult,
  DreamRejectResult,
  DreamStatus,
  DreamTriggerResult,
} from '../types';

export const dreamApi = {
  /**
   * 状态快照。未启用返回 {status: "disabled"}（HTTP 200）；后端离线/网络失败返回 null，
   * 供 UI 展示错误态。
   */
  async getStatus(): Promise<DreamStatus | null> {
    try {
      return await request<DreamStatus>({ url: '/api/dream/status' });
    } catch {
      return null;
    }
  },

  /** 分页列出缓冲候选（按 state/decision 过滤）；后端离线返回 null */
  async getList(params?: {
    state?: string;
    limit?: number;
    offset?: number;
  }): Promise<DreamListResult | null> {
    try {
      const query: Record<string, string | number> = {
        limit: params?.limit ?? 50,
        offset: params?.offset ?? 0,
      };
      // state 可选：仅在明确给出时携带，避免空串误过滤
      if (params?.state) {
        query.state = params.state;
      }
      return await request<DreamListResult>({ url: '/api/dream/list', params: query });
    } catch {
      return null;
    }
  },

  /** 手动触发一轮梦境会话；未启用返回 {"status": "disabled"}（HTTP 200），失败抛归一化错误 */
  async trigger(): Promise<DreamTriggerResult> {
    try {
      return await request<DreamTriggerResult>({ url: '/api/dream/trigger', method: 'post' });
    } catch (err) {
      throw normalizeError(err);
    }
  },

  /** 确认梦境候选 → 固化主库；候选不存在/未启用抛归一化错误 */
  async confirm(bufferId: number): Promise<DreamConfirmResult> {
    try {
      return await request<DreamConfirmResult>({
        url: `/api/dream/${bufferId}/confirm`,
        method: 'post',
      });
    } catch (err) {
      throw normalizeError(err);
    }
  },

  /** 否定梦境候选 → 缓冲置 rejected（不写主库）；失败抛归一化错误 */
  async reject(bufferId: number, reason?: string): Promise<DreamRejectResult> {
    try {
      return await request<DreamRejectResult>({
        url: `/api/dream/${bufferId}/reject`,
        method: 'post',
        data: { reason: reason ?? '' },
      });
    } catch (err) {
      throw normalizeError(err);
    }
  },

  /** 按会话回滚：软删该会话全部梦境记忆（红线 R5）；失败抛归一化错误 */
  async purgeSession(sessionId: string): Promise<DreamPurgeSessionResult> {
    try {
      return await request<DreamPurgeSessionResult>({
        url: `/api/dream/session/${encodeURIComponent(sessionId)}`,
        method: 'delete',
      });
    } catch (err) {
      throw normalizeError(err);
    }
  },

  /** 手动触发清除任务（超 TTL / 低重要性 / 缓冲过期）；失败抛归一化错误 */
  async purge(): Promise<DreamPurgeResult> {
    try {
      return await request<DreamPurgeResult>({ url: '/api/dream/purge', method: 'post' });
    } catch (err) {
      throw normalizeError(err);
    }
  },

  /** 当前梦境配置（独立配置模块，未启用也可读）；后端离线返回 null */
  async getConfig(): Promise<DreamConfig | null> {
    try {
      return await request<DreamConfig>({ url: '/api/dream/config' });
    } catch {
      return null;
    }
  },

  /** 局部更新配置并保存（后端深度合并 + model_validate，非法字段 422）；失败抛归一化错误 */
  async updateConfig(partial: Partial<DreamConfig>): Promise<DreamConfig> {
    try {
      return await request<DreamConfig>({
        url: '/api/dream/config',
        method: 'put',
        data: partial,
      });
    } catch (err) {
      throw normalizeError(err);
    }
  },
};
