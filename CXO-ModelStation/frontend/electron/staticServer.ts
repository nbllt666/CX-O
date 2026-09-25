/**
 * 前端本地静态服务（Electron 主进程内置）。
 *
 * 契约（change-id: package-modelstation-desktop-installer）：
 * - 仅监听 127.0.0.1；托管前端构建产物目录（生产 dist/）；
 * - `/api/*` 与 `/health` 反代到后端 base（默认 http://127.0.0.1:8300）；
 * - 反代必须端到端透传：multipart/form-data 上传、Range/206、大响应流式、
 *   OPTIONS 预检；后端不可达时返回 502 + 可读 JSON（不挂死）；
 * - 非文件 GET 走 SPA fallback（index.html）；
 * - 端口顺延由 ports.ts 提供（3300 → 3310）。
 *
 * 设计：仅依赖 Node 内置 http/https/fs；代理使用流管道（零缓冲），
 * 以避免破坏大文件上传/下载与音频 Range 语义。
 */
import * as fs from "node:fs";
import * as http from "node:http";
import * as https from "node:https";
import * as path from "node:path";

import { createPortProbe, isPortInUseError, pickAvailablePort } from "./ports";

export const DEFAULT_PROXY_PREFIXES = ["/api", "/health"];
export const DEFAULT_PROXY_TIMEOUT_MS = 120_000;

const MIME_TYPES: Record<string, string> = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".map": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".gif": "image/gif",
  ".ico": "image/x-icon",
  ".webp": "image/webp",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".ttf": "font/ttf",
  ".txt": "text/plain; charset=utf-8",
  ".wasm": "application/wasm",
  ".wav": "audio/wav",
  ".mp3": "audio/mpeg",
};

export interface StaticServerConfig {
  /** 前端构建产物目录（生产 dist/） */
  distDir: string;
  /** 后端 base，如 http://127.0.0.1:8300 */
  backendBaseUrl: string;
  /** 需要反代的路径前缀，默认 ['/api', '/health'] */
  proxyPrefixes?: string[];
  /** 反代超时（ms），默认 120s */
  proxyTimeoutMs?: number;
  /** 监听地址，默认 127.0.0.1（冻结契约：仅回环） */
  host?: string;
}

export interface BackendTarget {
  protocol: "http:" | "https:";
  hostname: string;
  port: number;
  hostHeader: string;
}

export interface RangeSpec {
  start: number;
  end: number;
}

/** 解析后端 base 为 http.request 目标 */
export function parseBackendTarget(baseUrl: string): BackendTarget {
  const url = new URL(baseUrl);
  const protocol: "http:" | "https:" = url.protocol === "https:" ? "https:" : "http:";
  const port = url.port ? Number(url.port) : protocol === "https:" ? 443 : 80;
  return { protocol, hostname: url.hostname, port, hostHeader: url.host };
}

/** 路径前缀匹配（'/api' 匹配 '/api' 与 '/api/xxx'，不匹配 '/apix'） */
export function matchesPrefix(pathname: string, prefix: string): boolean {
  return pathname === prefix || pathname.startsWith(prefix.endsWith("/") ? prefix : `${prefix}/`);
}

/** 单区间 Range 解析；返回 null=无/不可解析 Range，'invalid'=语法非法或越界 */
export function parseRange(header: string, size: number): RangeSpec | null | "invalid" {
  const match = /^bytes=(\d*)-(\d*)$/.exec(header.trim());
  if (!match) return "invalid";
  const [, rawStart, rawEnd] = match;
  if (rawStart === "" && rawEnd === "") return "invalid";

  let start: number;
  let end: number;
  if (rawStart === "") {
    const suffix = Number(rawEnd);
    if (!Number.isFinite(suffix) || suffix <= 0) return "invalid";
    start = Math.max(0, size - suffix);
    end = size - 1;
  } else {
    start = Number(rawStart);
    end = rawEnd === "" ? size - 1 : Number(rawEnd);
    if (!Number.isFinite(start) || !Number.isFinite(end)) return "invalid";
    if (end > size - 1) end = size - 1;
  }
  if (!Number.isFinite(size) || size <= 0) return "invalid";
  if (start > end || start >= size) return "invalid";
  return { start, end };
}

function safeDecodePath(rawUrl: string): string | null {
  const withoutQuery = rawUrl.split("?")[0];
  try {
    return decodeURIComponent(withoutQuery);
  } catch {
    return null;
  }
}

function isInside(root: string, target: string): boolean {
  return target === root || target.startsWith(root + path.sep);
}

function sendJson(res: http.ServerResponse, status: number, body: unknown): void {
  const payload = Buffer.from(JSON.stringify(body), "utf8");
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": String(payload.byteLength),
    "Cache-Control": "no-store",
  });
  res.end(payload);
}

/** 反代：流式透传请求体与响应（含状态码/全部响应头），保留 multipart 与 Range 语义 */
function handleProxy(
  req: http.IncomingMessage,
  res: http.ServerResponse,
  target: BackendTarget,
  backendBaseUrl: string,
  timeoutMs: number,
): void {
  const transport = target.protocol === "https:" ? https : http;
  const headers: http.OutgoingHttpHeaders = { ...req.headers };
  delete headers.host;
  headers.host = target.hostHeader;

  const proxyReq = transport.request(
    {
      protocol: target.protocol,
      hostname: target.hostname,
      port: target.port,
      method: req.method,
      path: req.url,
      headers,
    },
    (proxyRes) => {
      res.writeHead(proxyRes.statusCode ?? 502, proxyRes.headers as http.OutgoingHttpHeaders);
      proxyRes.pipe(res);
      proxyRes.on("error", () => res.destroy());
    },
  );

  proxyReq.setTimeout(timeoutMs, () => {
    proxyReq.destroy(new Error(`后端响应超时（>${timeoutMs}ms）`));
  });

  proxyReq.on("error", (error: Error) => {
    if (res.headersSent) {
      res.destroy();
      return;
    }
    sendJson(res, 502, {
      detail: `无法连接 ModelStation 后端（${backendBaseUrl}）：${error.message}。请确认后端已启动或修改连接地址。`,
    });
  });

  req.on("aborted", () => proxyReq.destroy());
  res.on("close", () => {
    if (!proxyReq.destroyed && !res.writableEnded) proxyReq.destroy();
  });

  req.pipe(proxyReq);
}

/** 静态托管 + SPA fallback + Range（206） */
function handleStatic(
  req: http.IncomingMessage,
  res: http.ServerResponse,
  distRoot: string,
  pathname: string,
): void {
  const relative = pathname.replace(/^\/+/, "");
  const candidate = path.resolve(distRoot, relative);
  if (!isInside(distRoot, candidate)) {
    sendJson(res, 403, { detail: "Forbidden" });
    return;
  }

  let filePath = candidate;
  try {
    if (!relative || !fs.existsSync(candidate) || !fs.statSync(candidate).isFile()) {
      filePath = path.join(distRoot, "index.html");
    }
  } catch {
    filePath = path.join(distRoot, "index.html");
  }

  let stat: fs.Stats;
  try {
    stat = fs.statSync(filePath);
    if (!stat.isFile()) throw new Error("not a file");
  } catch {
    sendJson(res, 404, { detail: "Not Found" });
    return;
  }

  const ext = path.extname(filePath).toLowerCase();
  const contentType = MIME_TYPES[ext] ?? "application/octet-stream";
  const rangeHeader = req.headers.range;
  const parsed = typeof rangeHeader === "string" ? parseRange(rangeHeader, stat.size) : null;

  if (parsed === "invalid") {
    res.writeHead(416, {
      "Content-Type": "application/json; charset=utf-8",
      "Content-Range": `bytes */${stat.size}`,
      "Accept-Ranges": "bytes",
    });
    res.end();
    return;
  }

  if (parsed) {
    res.writeHead(206, {
      "Content-Type": contentType,
      "Content-Length": String(parsed.end - parsed.start + 1),
      "Content-Range": `bytes ${parsed.start}-${parsed.end}/${stat.size}`,
      "Accept-Ranges": "bytes",
      "Cache-Control": "no-cache",
    });
    if (req.method === "HEAD") {
      res.end();
      return;
    }
    fs.createReadStream(filePath, { start: parsed.start, end: parsed.end })
      .on("error", () => res.destroy())
      .pipe(res);
    return;
  }

  res.writeHead(200, {
    "Content-Type": contentType,
    "Content-Length": String(stat.size),
    "Accept-Ranges": "bytes",
    "Cache-Control": ext === ".html" ? "no-cache" : "public, max-age=3600",
  });
  if (req.method === "HEAD") {
    res.end();
    return;
  }
  fs.createReadStream(filePath)
    .on("error", () => res.destroy())
    .pipe(res);
}

/** 创建（未监听）静态服务实例 */
export function createStaticServer(config: StaticServerConfig): http.Server {
  const distRoot = path.resolve(config.distDir);
  const prefixes = config.proxyPrefixes ?? DEFAULT_PROXY_PREFIXES;
  const timeoutMs = config.proxyTimeoutMs ?? DEFAULT_PROXY_TIMEOUT_MS;
  const target = parseBackendTarget(config.backendBaseUrl);

  return http.createServer((req, res) => {
    const rawUrl = req.url ?? "/";
    const pathname = safeDecodePath(rawUrl);
    if (pathname === null) {
      sendJson(res, 400, { detail: "Bad Request" });
      return;
    }

    if (prefixes.some((prefix) => matchesPrefix(pathname, prefix))) {
      handleProxy(req, res, target, config.backendBaseUrl, timeoutMs);
      return;
    }

    if (req.method === "GET" || req.method === "HEAD") {
      handleStatic(req, res, distRoot, pathname);
      return;
    }

    sendJson(res, 405, { detail: `Method Not Allowed: ${req.method ?? "?"} ${pathname}` });
  });
}

export interface StartStaticServerOptions extends StaticServerConfig {
  /** 首选端口，默认 3300；传 0 表示由系统分配（测试用） */
  preferredPort?: number;
  /** 顺延尝试次数，默认 11（3300..3310） */
  maxPortTries?: number;
}

export interface RunningStaticServer {
  server: http.Server;
  host: string;
  port: number;
  /** 实际监听地址，如 http://127.0.0.1:3300 */
  url: string;
}

function listenOnce(server: http.Server, host: string, port: number): Promise<number> {
  return new Promise<number>((resolve, reject) => {
    const onError = (error: Error) => {
      server.removeListener("listening", onListening);
      reject(error);
    };
    const onListening = () => {
      server.removeListener("error", onError);
      const address = server.address();
      resolve(typeof address === "object" && address ? address.port : port);
    };
    server.once("error", onError);
    server.once("listening", onListening);
    server.listen({ host, port });
  });
}

/** 启动静态服务：优先首选端口，占用则顺延（EADDRINUSE 重试），返回实际地址 */
export async function startStaticServer(
  options: StartStaticServerOptions,
): Promise<RunningStaticServer> {
  const host = options.host ?? "127.0.0.1";
  const preferredPort = options.preferredPort ?? 3300;
  const maxPortTries = options.maxPortTries ?? 11;
  const server = createStaticServer({ ...options, host });

  let actualPort: number;
  if (preferredPort === 0) {
    actualPort = await listenOnce(server, host, 0);
  } else {
    // 先用探针选出空闲端口（纯函数逻辑可单测），再实监听；实监听仍带 EADDRINUSE 顺延兜底。
    let port: number | null = null;
    try {
      port = await pickAvailablePort(preferredPort, createPortProbe(host), maxPortTries);
    } catch {
      port = null;
    }
    const candidates =
      port === null
        ? Array.from({ length: Math.max(1, maxPortTries) }, (_, i) => preferredPort + i)
        : [port, ...Array.from({ length: Math.max(1, maxPortTries) }, (_, i) => preferredPort + i)];
    let lastError: unknown = null;
    let listeningPort: number | null = null;
    for (const candidate of candidates) {
      try {
        listeningPort = await listenOnce(server, host, candidate);
        break;
      } catch (error) {
        lastError = error;
        if (!isPortInUseError(error)) throw error;
      }
    }
    if (listeningPort === null) {
      throw lastError instanceof Error
        ? lastError
        : new Error(`端口 ${preferredPort} 起连续 ${maxPortTries} 次均被占用`);
    }
    actualPort = listeningPort;
  }

  return { server, host, port: actualPort, url: `http://${host}:${actualPort}` };
}