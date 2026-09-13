/**
 * 运行时日志环形缓冲
 * ============================================================================
 * 收集 neko 运行时（插件服务器子进程 / 桥 / 编排层）的日志行：
 *  - 内存环形缓冲（容量有限，超出后淘汰最旧条目），供控制面 SSE / 状态页
 *    随时拉取最近日志（后续任务接入）；
 *  - 与可选注入的 logSink 并行推送：sink 存在时每行同时投递，sink 不存在时
 *    仅入缓冲（不丢日志）。
 * ============================================================================
 */

/** 缓冲容量（条数）；超出后淘汰最旧行 */
const LOG_BUFFER_CAPACITY = 1000;

const buffer: string[] = [];

/** 追加一行日志进环形缓冲（超容量淘汰最旧） */
export function appendRuntimeLog(line: string): void {
  buffer.push(line);
  if (buffer.length > LOG_BUFFER_CAPACITY) {
    buffer.splice(0, buffer.length - LOG_BUFFER_CAPACITY);
  }
}

/** 读取当前缓冲内的全部日志行（副本，按时间正序） */
export function getRuntimeLogLines(): string[] {
  return [...buffer];
}

/** 清空缓冲（测试或控制面需要时使用） */
export function clearRuntimeLog(): void {
  buffer.length = 0;
}
