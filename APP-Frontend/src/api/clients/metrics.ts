/**
 * metrics 域客户端：语音链路延迟指标（spec enhance-cxfc-admin-and-integrate-dream Task 5）。
 *
 * 数据源：GET /api/stats/voice-latency
 * 响应形状：{status, data: {summary, recent, buffer_size}}
 * - summary: 各段延迟 {asr/ttft/tts_first/e2e: {p50, p95, max, count}}（单位 ms）
 * - recent: 最近 N 轮明细
 * - buffer_size: 缓冲内已结算轮次样本数
 * 无样本时各段 p50/p95/max 为 null、count=0。
 *
 * 请求序号防陈旧覆盖：模块级递增 seq，响应返回时若 seq 已落后于最新发起的
 * 请求（期间发起了更新的请求），则该响应视为陈旧数据丢弃（返回 null），
 * 调用方据此跳过状态更新，避免慢响应覆盖新数据。
 */
import { request } from '../base';

/** 单段延迟统计（单位 ms；无样本时 p50/p95/max 为 null、count 为 0） */
export interface VoiceLatencySegmentStats {
  p50: number | null;
  p95: number | null;
  max: number | null;
  count: number;
}

/** 各段延迟汇总：asr / ttft（LLM 首 Token）/ tts_first（TTS 首帧）/ e2e（端到端） */
export interface VoiceLatencySummary {
  asr: VoiceLatencySegmentStats;
  ttft: VoiceLatencySegmentStats;
  tts_first: VoiceLatencySegmentStats;
  e2e: VoiceLatencySegmentStats;
}

/** 最近 N 轮明细（后端原始结构，前端仅透传展示，不做强约束） */
export interface VoiceLatencyRecentTurn {
  client_id?: string;
  settled_at?: string;
  segments?: Record<string, unknown>;
  events?: Record<string, unknown>;
  [key: string]: unknown;
}

/** GET /api/stats/voice-latency 的 data 载荷 */
export interface VoiceLatencyStats {
  summary: VoiceLatencySummary;
  recent: VoiceLatencyRecentTurn[];
  buffer_size: number;
}

interface VoiceLatencyEnvelope {
  status?: string;
  data: VoiceLatencyStats;
}

// 模块级请求序号：每次发起请求自增；响应 seq < 最新 seq 即为陈旧响应
let voiceLatencyReqSeq = 0;

export const metricsApi = {
  /**
   * 获取语音链路延迟统计。
   * 返回 null 表示响应为陈旧数据（期间已发起更新的请求），调用方应丢弃不做状态更新；
   * 请求失败（网络错误 / 404 / 503 等）抛出归一化 Error，由调用方静默降级。
   */
  async getVoiceLatency(): Promise<VoiceLatencyStats | null> {
    const seq = ++voiceLatencyReqSeq;
    const response = await request<VoiceLatencyEnvelope>({
      url: '/api/stats/voice-latency',
    });
    if (seq !== voiceLatencyReqSeq) {
      // 已有更新的请求在途/完成，本响应陈旧，丢弃
      return null;
    }
    return response.data;
  },
};
