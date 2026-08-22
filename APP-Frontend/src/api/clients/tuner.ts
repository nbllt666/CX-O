/**
 * tuner 域客户端：进化实验室（CXO-Tuner 自适应微调）访问层。
 * 端点面对齐后端 server/api/routers/tuner.py，挂载前缀 /api：
 *   GET  /api/v1/tuner/stats
 *   POST /api/v1/tuner/train/trigger
 *   GET  /api/v1/tuner/train/status
 *   GET  /api/v1/tuner/adapters
 *   POST /api/v1/tuner/adapters/{id}/apply
 *
 * 降级口径：Tuner 离线（后端返回 status="degraded"、503 或网络失败）时，
 * 查询类方法（getStats/listAdapters/getTrainStatus/health）返回 null/空以驱动 UI 降级；
 * 触发类方法（trigger/applyAdapter）向后端透传并抛出归一化错误（normalizeError），供 UI 捕获提示。
 */
import { request, normalizeError } from '../base';

/** 数据集统计（对齐 tuner.py stats 降级默认结构与 CXO-Tuner dataset/stats） */
export interface TunerStats {
  total: number;
  source_breakdown: Record<string, number>;
  positive_ratio: number;
  negative_ratio: number;
  anchor_count: number;
}

/** 适配器条目（CXO-Tuner /adapters 列表项，向后透传，保留未知字段） */
export interface TunerAdapter {
  id: string;
  name?: string;
  base_model?: string;
  created_at?: string;
  status?: string;
  /** 直播特化来源：base / streaming / intimate（后端返回时展示，否则省略） */
  scene?: string;
  [key: string]: unknown;
}

/** 训练任务状态（CXO-Tuner /train/status，向后透传） */
export interface TunerTrainStatus {
  job_id?: string;
  status?: string;
  /** 0-100（与后端 TrainStatus.progress 0-1 兼容，取百分比展示） */
  progress?: number;
  /**
   * Loss 历史点。优先 loss_curve（CXO-Tuner 契约口径），
   * 兼容 MVP 使用的 loss_history 旧字段。
   */
  loss_curve?: number[];
  loss_history?: number[];
  /** 显存占用：可能是格式化字符串（MVP 业态）或纯数字字节口径 */
  memory?: string;
  /** 显存占用（MB），对齐 cxo_tuner.pyi TrainStatus.memory_usage_mb */
  memory_usage_mb?: number;
  error?: string;
  [key: string]: unknown;
}

/** 删除适配器响应（对齐 CXO-Tuner delete_adapter 语义） */
export interface TunerDeleteResult {
  deleted: boolean;
}

/** 应用适配器响应（对齐 tuner.py apply 返回结构） */
export interface TunerApplyResult {
  adapter_id: string;
  applied: boolean;
  detail?: string;
  lora_enabled?: boolean;
  rollback?: { previous_llm_host?: string; previous_llm_port?: unknown };
}

interface TunerEnvelope<T> {
  status: string;
  stats?: T;
  train?: T;
  adapters?: T[];
}

export const tunerApi = {
  /**
   * 探活：Tuner 可达返回 true。以 /stats 判定（Tuner 离线时后端返回 status="degraded"），
   * 主后端不可达（网络失败）同样视为离线返回 false。不抛异常。
   */
  async health(): Promise<boolean> {
    const stats = await tunerApi.getStats();
    return stats !== null;
  },

  /** 数据集统计；Tuner 离线或网络失败返回 null（供 UI 降级展示「Tuner 未在线」） */
  async getStats(): Promise<TunerStats | null> {
    try {
      const resp = await request<TunerEnvelope<TunerStats>>({ url: '/api/v1/tuner/stats' });
      if (resp?.status === 'degraded') return null;
      return resp?.stats ?? null;
    } catch {
      return null;
    }
  },

  /** 触发 LoRA 训练；Tuner 不可达/未启用时后端返回 503，此处透传抛出归一化错误 */
  async trigger(epochs: number, sample_ratio: number): Promise<TunerTrainStatus> {
    const resp = await request<TunerEnvelope<TunerTrainStatus>>({
      url: '/api/v1/tuner/train/trigger',
      method: 'post',
      data: { epochs, sample_ratio },
    });
    return resp?.train ?? {};
  },

  /** 查询训练状态；Tuner 离线或网络失败返回 null */
  async getTrainStatus(jobId: string): Promise<TunerTrainStatus | null> {
    try {
      const resp = await request<TunerEnvelope<TunerTrainStatus>>({
        url: '/api/v1/tuner/train/status',
        params: { job_id: jobId },
      });
      return resp?.train ?? null;
    } catch {
      return null;
    }
  },

  /** 列出全部适配器；Tuner 离线时后端返回降级空列表，此处返回 null 供 UI 判定离线 */
  async listAdapters(): Promise<TunerAdapter[] | null> {
    try {
      const resp = await request<TunerEnvelope<TunerAdapter>>({
        url: '/api/v1/tuner/adapters',
      });
      if (resp?.status === 'degraded') return [];
      return resp?.adapters ?? [];
    } catch {
      return null;
    }
  },

  /** 应用适配器；Tuner/evolution 未启用时后端返回 503，透传抛出归一化错误 */
  async applyAdapter(id: string): Promise<TunerApplyResult> {
    try {
      return await request<TunerApplyResult>({
        url: `/api/v1/tuner/adapters/${encodeURIComponent(id)}/apply`,
        method: 'post',
      });
    } catch (err) {
      throw normalizeError(err);
    }
  },

  /**
   * 删除适配器产物（对齐 cxo_tuner.pyi CXOTunerAPI.delete_adapter）。
   * CX-O-SERVER 当前未代理该端点时后端返回 404，此处透传抛出归一化错误，供 UI 降级提示。
   */
  async deleteAdapter(id: string): Promise<TunerDeleteResult> {
    try {
      return await request<TunerDeleteResult>({
        url: `/api/v1/tuner/adapters/${encodeURIComponent(id)}`,
        method: 'delete',
      });
    } catch (err) {
      throw normalizeError(err);
    }
  },
};