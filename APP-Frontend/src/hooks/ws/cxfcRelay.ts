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
 * - 缺 plugin_id / request_id / tool 无法执行或回报 → 静默跳过（打印警告）
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

/** 便捷装配：默认 Electron 执行器 + 既有 cxfcApi.relayResult 回报。 */
export function createDefaultRelayDeps() {
  return {
    executor: createElectronComputerControlExecutor(),
    report: (payload: RelayResultPayload) => cxfcApi.relayResult(payload),
  };
}
