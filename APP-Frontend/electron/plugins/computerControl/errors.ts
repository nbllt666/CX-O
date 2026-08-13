/**
 * 电脑控制插件统一错误码与工具结果契约。
 *
 * 错误码枚举、message 与 http_status 对齐
 * `public/schema/computer_control_error_codes.json`（迁移自
 * `.trae/specs/add-computer-control-cxfc/contracts/error_codes.json`），供
 * /call 响应、认证/防重放/授权与三个工具适配器共用，避免模块间异常拦截歧义。
 */
export const ErrorCodes = {
  UNAUTHORIZED: 'UNAUTHORIZED',
  NOT_AUTHORIZED: 'NOT_AUTHORIZED',
  REPLAY_DETECTED: 'REPLAY_DETECTED',
  INVALID_ARGUMENT: 'INVALID_ARGUMENT',
  EXECUTION_FAILED: 'EXECUTION_FAILED',
  TIMEOUT: 'TIMEOUT',
  SYSTEM_ERROR: 'SYSTEM_ERROR',
  PLUGIN_OFFLINE: 'PLUGIN_OFFLINE',
} as const;

export type ErrorCode = (typeof ErrorCodes)[keyof typeof ErrorCodes];

/** 每个错误码对应的 HTTP 状态（对齐契约 http_status 字段） */
export const HTTP_STATUS: Record<ErrorCode, number> = {
  UNAUTHORIZED: 401,
  NOT_AUTHORIZED: 403,
  REPLAY_DETECTED: 409,
  INVALID_ARGUMENT: 400,
  EXECUTION_FAILED: 500,
  TIMEOUT: 504,
  SYSTEM_ERROR: 500,
  PLUGIN_OFFLINE: 503,
};

/** 稳定错误信息（与契约 message 保持一致） */
export const ERROR_MESSAGES: Record<ErrorCode, string> = {
  UNAUTHORIZED: '认证失败：注册令牌缺失/错误或 TLS 证书指纹不匹配。不执行任何本机动作。',
  NOT_AUTHORIZED: '本地授权未开启（授权被撤销或尚未授权）。不执行任何本机动作。',
  REPLAY_DETECTED: '防重放拒绝：request_id 在当前时间窗内重复。不执行任何本机动作。',
  INVALID_ARGUMENT: '参数错误：工具名或参数不符合对应工具请求契约。不执行本机动作。',
  EXECUTION_FAILED: '执行失败：进程启动失败或系统权限不足。',
  TIMEOUT: '执行超时：超出 timeout_ms，已回收整个进程树并停止执行。',
  SYSTEM_ERROR: '系统失败：插件内部错误或配置缺失等系统级问题。',
  PLUGIN_OFFLINE: '插件不可用：插件未注册、已断开或 /call 端点不可达。',
};

export interface ErrorBody {
  code: ErrorCode;
  message: string;
}

/** 工具统一返回结构：ok=true 携带 output；ok=false 携带稳定错误码 + 可读信息 */
export interface ToolResult {
  ok: boolean;
  code: ErrorCode | 'OK';
  error?: string;
  output?: unknown;
}

export function okResult(output?: unknown): ToolResult {
  return { ok: true, code: 'OK', output };
}

export function errorResult(code: ErrorCode, message: string): ToolResult {
  return { ok: false, code, error: message };
}

export function messageOf(err: unknown): string {
  if (err instanceof Error) return err.message;
  return String(err);
}
