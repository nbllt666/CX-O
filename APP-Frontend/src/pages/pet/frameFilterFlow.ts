/**
 * 单帧筛选分流纯逻辑（spec add-vlm-frame-filter-face-match Task 5）。
 *
 * 分流语义（与 spec Requirement「前端采集分流与降级」逐条对齐）：
 * - 筛选开启时先 POST /api/vision/frame 取三态判定；
 * - forward → 发起对话（prompt 附加 face_labels 提示）；
 * - summarize / discard → 静默结束（不建气泡、不发起对话，仅复位互斥）；
 * - 筛选请求任何异常（网络失败 / 5xx）→ 回退直通对话，视觉不断流。
 *
 * 抽为纯函数 + IO 注入的目的：PetPage 挂载依赖过重（VRM/WS/Electron），
 * 分流决策表经本模块直接单测（对齐 pages/pet 纯函数测试惯例）。
 */
import type { FrameFilterResponse } from '../../api/clients/vision';

/** 帧来源（与 CaptureSourceKind / vision client source 口径一致） */
export type FrameFilterSource = 'camera' | 'screen';

/** face_labels 提示文案构造器：PetPage 注入 i18n t，单测注入 stub */
export type FaceLabelsHintBuilder = (labels: string) => string;

/**
 * forward 判定的对话 prompt 组装：基础帧 prompt + 画面人物提示。
 * face_labels 缺失 / 为空时原样返回，不追加提示。
 * 多个标签以「、」连接后交给提示构造器（如「小A、小B 在画面中」）。
 */
export function resolveFrameFilterPrompt(
  basePrompt: string,
  faceLabels: readonly string[] | undefined,
  buildLabelsHint: FaceLabelsHintBuilder,
): string {
  if (!faceLabels || faceLabels.length === 0) return basePrompt;
  return `${basePrompt}\n${buildLabelsHint(faceLabels.join('、'))}`;
}

/**
 * 筛选分流 IO 注入口：PetPage 接真实实现（visionApi / 气泡对话链），
 * 单测注入 mock 逐一验证 forward / summarize / discard / 回退四条路径。
 */
export interface FrameFilterFlowIo {
  /** 请求后端筛选判定（对应 vision client 的 filterFrame） */
  requestFilter: (
    image: string,
    agentId: string,
    source: FrameFilterSource,
    ts: string,
  ) => Promise<FrameFilterResponse>;
  /** forward：发起对话（气泡 + sendMessageStream 全链，内部自带互斥复位与错误兜底） */
  startConversation: (prompt: string, image: string) => void;
  /** summarize / discard：静默结束——仅复位互斥，不建气泡不发起对话 */
  settleSilent: () => void;
  /** 筛选请求失败（网络失败 / 5xx / 任何异常）：回退直通对话，视觉不断流 */
  fallbackToConversation: (error: unknown) => void;
}

/**
 * 帧筛选分流编排：先判定后分流。
 * - 请求失败 → fallbackToConversation（保证视觉链路不断）；
 * - 非 forward（summarize/discard）→ settleSilent；
 * - forward → startConversation（prompt = 基础帧 prompt + face_labels 提示）。
 */
export async function runFrameFilterFlow(
  image: string,
  agentId: string,
  source: FrameFilterSource,
  ts: string,
  basePrompt: string,
  buildLabelsHint: FaceLabelsHintBuilder,
  io: FrameFilterFlowIo,
): Promise<void> {
  let response: FrameFilterResponse;
  try {
    response = await io.requestFilter(image, agentId, source, ts);
  } catch (error) {
    io.fallbackToConversation(error);
    return;
  }
  if (response.action !== 'forward') {
    // summarize/discard：静默结束，不打扰（摘要已由后端沉淀，可于 /memories 查看）
    io.settleSilent();
    return;
  }
  io.startConversation(
    resolveFrameFilterPrompt(basePrompt, response.face_labels, buildLabelsHint),
    image,
  );
}
