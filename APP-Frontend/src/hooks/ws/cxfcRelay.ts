/**
 * CXFC relay（前端转接）WS 推送处理（P2-T2）。
 *
 * 后端经 WS 广播 {type:"cxfc_relay_call", plugin_id, tool, arguments, request_id, token}，
 * 前端收到后在本地执行对应工具（电脑控制执行器，经 Electron 主进程 IPC），完成后经
 * HTTP POST /api/cxfc/relay/result 回报 {request_id, plugin_id, success, result/error}；
 * 未识别工具 / 执行异常 → success=false 回报 error。
 *
 * 本模块为纯函数依赖注入设计（executor / report 可替换），便于单测覆盖处理与回报链路，
 * 不依赖 React / WebSocket 传输层。
 */
import { cxfcApi } from '../../api/clients/cxfc';

export interface CxfcRelayCallMessage {
  type: 'cxfc_relay_call';
  plugin_id?: string;
  tool?: string;
  arguments?: Record<string, unknown>;
  request_id?: string;
  token?: string;
}

/** 工具执行结果（对齐电脑控制插件 ToolResult 契约；relay 侧不依赖具体错误码）。 */
export interface RelayToolOutcome {
  ok: boolean;
  code?: string;
  error?: string;
  output?: unknown;
}

export type RelayToolExecutor = (
  tool: string,
  args: Record<string, unknown>,
) => Promise<RelayToolOutcome>;

export interface RelayResultPayload {
  plugin_id: string;
  request_id: string;
  success: boolean;
  result?: unknown;
  error?: string;
}

export type RelayResultReporter = (payload: RelayResultPayload) => unknown;

// ── 多窗 request_id 去重 ──
// 后端会向每个已连接窗口广播同一条 cxfc_relay_call：多开桌宠/管理窗场景下同一
// request_id 会被多个窗口各自执行并重复回报（如同一命令被执行 N 次）。此处以模块级
// 已见集合去重：同一窗口内已处理过的 request_id 直接丢弃（不执行不回报）。
const MAX_SEEN_REQUEST_IDS = 256;
const seenRequestIds = new Set<string>();

/** 登记新 request_id；容量超限时淘汰最早登记者（Set 保持插入序，首个即最早）。 */
function rememberRequestId(requestId: string): void {
  if (seenRequestIds.size >= MAX_SEEN_REQUEST_IDS) {
    const oldest = seenRequestIds.values().next().value;
    if (oldest !== undefined) {
      seenRequestIds.delete(oldest);
    }
  }
  seenRequestIds.add(requestId);
}

/** Electron 主进程电脑控制执行器；浏览器模式（无 electronAPI 桥接）返回不可执行错误。 */
export function createElectronComputerControlExecutor(): RelayToolExecutor {
  return async (tool, args) => {
    const api = window.electronAPI;
    if (!api || typeof api.callComputerControlTool !== 'function') {
      return {
        ok: false,
        code: 'SYSTEM_ERROR',
        error: '电脑控制执行器不可用（非 Electron 环境或未桥接）',
      };
    }
    try {
      return await api.callComputerControlTool(tool, args);
    } catch (err) {
      return {
        ok: false,
        code: 'SYSTEM_ERROR',
        error: err instanceof Error ? err.message : String(err),
      };
    }
  };
}

/**
 * 处理一条 cxfc_relay_call 消息：本地执行工具并回报结果。
 *
 * - 执行成功（executor.ok=true）→ success=true + result
 * - 执行失败 / 未识别工具 / 抛异常 → success=false + error（取 error || code）
 * - 缺 plugin_id / request_id / tool 无法执行或回报 → 静默跳过（打印警告）；
 *   缺 request_id 的消息不参与去重（保持既有跳过语义，直接走原逻辑）
 * - 已见 request_id（多窗重复广播）→ 直接 return，不执行不回报
 * - 回报调用本身异常不向 WS 路由抛错（避免污染消息处理）
 */
export async function handleCxfcRelayCall(
  message: CxfcRelayCallMessage,
  deps: { executor: RelayToolExecutor; report: RelayResultReporter },
): Promise<void> {
  const { plugin_id, request_id, tool } = message;
  if (!plugin_id || !request_id || !tool) {
    console.warn('[cxfc_relay_call] 消息缺少 plugin_id/request_id/tool，跳过:', message);
    return;
  }

  // 多窗去重：同一 request_id 只执行一次；重复推送静默丢弃（不执行不回报）
  if (seenRequestIds.has(request_id)) {
    return;
  }
  rememberRequestId(request_id);

  let success = false;
  let result: unknown;
  let error: string | undefined;

  try {
    const outcome = await deps.executor(tool, message.arguments ?? {});
    if (outcome.ok) {
      success = true;
      result = outcome.output;
    } else {
      error = outcome.error || outcome.code || '工具执行失败';
    }
  } catch (err) {
    error = err instanceof Error ? err.message : String(err);
  }

  try {
    await deps.report({ plugin_id, request_id, success, result, error });
  } catch (err) {
    console.error('[cxfc_relay_call] 回报结果失败:', err);
  }
}

/**
 * 便捷装配：默认 Electron 执行器 + 既有 cxfcApi.relayResult 回报。
 *
 * 惰性单例：executor 每次调用动态读 window.electronAPI、report 为纯转发，
 * 两者均无闭包状态，可跨消息复用；每条 relay 消息重建一套 deps 纯属浪费。
 */
let defaultRelayDeps: {
  executor: RelayToolExecutor;
  report: RelayResultReporter;
} | null = null;

export function createDefaultRelayDeps(): {
  executor: RelayToolExecutor;
  report: RelayResultReporter;
} {
  if (!defaultRelayDeps) {
    defaultRelayDeps = {
      executor: createElectronComputerControlExecutor(),
      report: (payload: RelayResultPayload) => cxfcApi.relayResult(payload),
    };
  }
  return defaultRelayDeps;
}
