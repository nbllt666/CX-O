/**
 * 端口选择（前端本地站点）。
 *
 * 契约：首选 127.0.0.1:3300；被占用则在 3300..3310 区间顺延，返回实际端口。
 * 纯函数 + 可注入探针，便于单测。
 */
import * as net from "node:net";

export const DEFAULT_PORT = 3300;
export const DEFAULT_PORT_MAX_TRIES = 11; // 3300..3310（含首尾）

/** 第 attempt 次（0-based）候选端口 */
export function nextCandidatePort(preferred: number, attempt: number): number {
  return preferred + attempt;
}

/** 候选端口序列（含首选，最多 maxTries 个） */
export function candidatePorts(preferred: number, maxTries: number): number[] {
  const total = Math.max(1, maxTries);
  return Array.from({ length: total }, (_, index) => nextCandidatePort(preferred, index));
}

/**
 * 依次探测候选端口，返回第一个「空闲」端口。
 * probe(port) 返回 true 表示可绑定（空闲）。全部占用时抛出可读错误。
 */
export async function pickAvailablePort(
  preferred: number,
  probe: (port: number) => Promise<boolean>,
  maxTries: number = DEFAULT_PORT_MAX_TRIES,
): Promise<number> {
  const ports = candidatePorts(preferred, maxTries);
  for (const port of ports) {
    if (await probe(port)) return port;
  }
  throw new Error(
    `端口 ${ports[0]}-${ports[ports.length - 1]} 均被占用，无法启动前端本地站点。` +
      `请释放端口或修改首选端口。`,
  );
}

/** 真实探针：尝试在 127.0.0.1:port 上 listen，成功即空闲（随即关闭）。 */
export function createPortProbe(host = "127.0.0.1"): (port: number) => Promise<boolean> {
  return (port: number) =>
    new Promise<boolean>((resolve) => {
      const probeServer = net.createServer();
      probeServer.unref();
      probeServer.once("error", () => resolve(false));
      probeServer.once("listening", () => {
        probeServer.close(() => resolve(true));
      });
      probeServer.listen({ host, port, exclusive: true });
    });
}

export function isPortInUseError(error: unknown): boolean {
  return typeof error === "object" && error !== null && (error as { code?: string }).code === "EADDRINUSE";
}