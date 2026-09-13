/**
 * 控制面模块出口
 * ============================================================================
 * 统一 re-export 控制面能力（服务器 / 纯路由 / SSE），供 CLI 入口与测试引用。
 * ============================================================================
 */
export {
  startControlServer,
  handleControlRoute,
  streamRuntimeLogs,
  type ControlContext,
  type ControlServerHandle,
  type ControlServerOptions,
  type ControlRouteResult,
  type ControlStatusSnapshot,
  type LogStreamOptions,
} from './server';
