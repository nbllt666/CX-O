/**
 * vision 域客户端：主动视觉视频叙事片段上传。
 *
 * 端点：POST /api/vision/clip（已有后端，ContractTask 冻结）。
 * - multipart/form-data 字段：clip(文件) + event_type + ts + source + 可选 narrative_memory_enabled。
 * - 响应为 APIResponse 包裹：{success, data: {accepted, clip_id?, pending?}, message, ...}。
 *
 * 封装习惯对齐 chat.ts / base.ts：
 * - base URL 复用 getApiBaseUrl()（IPC > localStorage > env > 默认 http://127.0.0.1:8000）；
 * - Bearer token 从 localStorage(STORAGE_KEYS.token) 注入，与 axios 拦截器同一取值口径；
 * - 网络/HTTP 错误经 normalizeError 归一化后抛给调用方（由管线统一兜底为「未接受」）。
 *
 * 注意：FormData 的 Content-Type 由浏览器自动附带 boundary，这里不手动设置，
 * 否则后端无法解析 multipart。
 */
import { getApiBaseUrl, normalizeError, request, STORAGE_KEYS } from '../base';

export interface UploadVisionClipRequest {
  /** 已编码的片段文件（video/webm Blob） */
  blob: Blob;
  /** 触发事件类型（如 scene_change） */
  eventType: string;
  /** 事件时间戳（毫秒） */
  ts: number;
  /** 片段来源（屏幕 / 摄像头） */
  source: 'camera' | 'screen';
  /** 是否启用叙事记忆（可选，默认后端自行决定） */
  narrativeMemoryEnabled?: boolean;
}

export type UploadVisionClipResult = { accepted: boolean };

/**
 * 上传一个视觉片段到后端 /api/vision/clip。
 * - HTTP/网络错误 normalizeError 归一化后抛错（网络断连 / 5xx 等）；
 * - 响应为 APIResponse 包裹，仅解包 data.accepted 布尔位
 *   （clip_id/pending 供上层自知即可，无需强约束）。
 */
export async function uploadVisionClip(
  request: UploadVisionClipRequest,
): Promise<UploadVisionClipResult> {
  const form = new FormData();
  // 文件字段：命名 clip_<ts>.webm，供后端读取文件名
  form.append('clip', request.blob, `clip_${request.ts}.webm`);
  form.append('event_type', request.eventType);
  form.append('ts', String(request.ts));
  form.append('source', request.source);
  if (request.narrativeMemoryEnabled !== undefined) {
    form.append('narrative_memory_enabled', String(request.narrativeMemoryEnabled));
  }

  const token = localStorage.getItem(STORAGE_KEYS.token);
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  // 手动不设置 Content-Type，交由浏览器携带 multipart boundary

  const baseUrl = getApiBaseUrl();
  try {
    const res = await fetch(`${baseUrl}/api/vision/clip`, {
      method: 'POST',
      headers,
      body: form,
    });
    if (!res.ok) {
      throw new Error(`请求失败: ${res.status} ${res.statusText}`);
    }
    const body = (await res.json()) as { success?: boolean; data?: { accepted?: boolean } };
    return { accepted: Boolean(body?.data?.accepted) };
  } catch (error) {
    throw normalizeError(error);
  }
}

// ── 帧筛选（Task 5 / spec add-vlm-frame-filter-face-match，信号契约冻结） ──

/** 帧筛选三态判定：forward=转发主 LLM 对话 / summarize=仅沉淀摘要 / discard=无价值丢弃 */
export type FrameFilterAction = 'forward' | 'summarize' | 'discard';

/**
 * POST /api/vision/frame 响应（spec 信号契约，非 APIResponse 包裹，扁平结构）。
 * summary/reason/importance/degraded/face_labels 按判定结果可选；filter_active
 * 为 false 表示后端筛选开关关闭（直接 forward，零筛选开销）。
 */
export interface FrameFilterResponse {
  action: FrameFilterAction;
  summary?: string;
  reason?: string;
  importance?: 'low' | 'medium' | 'high';
  degraded?: boolean;
  face_labels?: string[];
  filter_active: boolean;
}

/**
 * 单帧筛选判定：把画面帧交给后端小 VLM 筛选层，返回 forward/summarize/discard 三态。
 * - image 为 dataURL（与 chat images 同口径）；ts 为可解析时间戳字符串，可选；
 * - 网络错误 / 非 2xx 一律抛出（normalizeError 归一化），由调用方回退直通对话；
 * - 响应为扁平信号契约（非 APIResponse 包裹），直接透传。
 */
export async function filterFrame(
  image: string,
  agentId: string,
  source: 'camera' | 'screen',
  ts?: string,
): Promise<FrameFilterResponse> {
  return request<FrameFilterResponse>({
    url: '/api/vision/frame',
    method: 'post',
    data: { image, agent_id: agentId, source, ts },
  });
}