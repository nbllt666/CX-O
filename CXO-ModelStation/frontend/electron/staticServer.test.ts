// @vitest-environment node
/**
 * 本地静态服务 + /api 反代 单测（真实 socket，覆盖 multipart / Range / 502 / 归档 SPA）。
 */
import * as fs from "node:fs";
import * as http from "node:http";
import * as os from "node:os";
import * as path from "node:path";
import type { AddressInfo } from "node:net";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  createStaticServer,
  matchesPrefix,
  parseBackendTarget,
  parseRange,
  startStaticServer,
  type RunningStaticServer,
} from "./staticServer";

const JS_BODY = "0123456789";

let tmpRoots: string[] = [];
const closers: Array<() => Promise<void>> = [];

function makeDist(): string {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "cxo-ms-static-"));
  tmpRoots.push(root);
  fs.mkdirSync(path.join(root, "assets"), { recursive: true });
  fs.writeFileSync(path.join(root, "index.html"), "<!doctype html><title>SPA</title>", "utf8");
  fs.writeFileSync(path.join(root, "assets", "app.js"), JS_BODY, "utf8");
  return root;
}

function makeUpstream(
  handler: (req: http.IncomingMessage, res: http.ServerResponse) => void,
): Promise<{ server: http.Server; port: number }> {
  const server = http.createServer(handler);
  return new Promise((resolve) => {
    server.listen({ host: "127.0.0.1", port: 0 }, () => {
      closers.push(() => closeServer(server));
      resolve({ server, port: (server.address() as AddressInfo).port });
    });
  });
}

/** Node 19+ 默认 keep-alive：先断开存量连接再 close，避免 close 等待 5s */
function closeServer(server: http.Server): Promise<void> {
  return new Promise<void>((done) => {
    server.closeAllConnections();
    server.close(() => done());
  });
}

async function startServer(
  distDir: string,
  backendBaseUrl: string,
  proxyTimeoutMs?: number,
): Promise<RunningStaticServer> {
  const handle = await startStaticServer({ distDir, backendBaseUrl, preferredPort: 0, proxyTimeoutMs });
  closers.push(() => closeServer(handle.server));
  return handle;
}

interface SimpleResponse {
  status: number;
  headers: http.IncomingHttpHeaders;
  body: Buffer;
}

function rawRequest(
  port: number,
  options: { method?: string; path: string; headers?: http.OutgoingHttpHeaders; body?: Buffer },
): Promise<SimpleResponse> {
  return new Promise((resolve, reject) => {
    const req = http.request(
      { host: "127.0.0.1", port, method: options.method ?? "GET", path: options.path, headers: options.headers },
      (res) => {
        const chunks: Buffer[] = [];
        res.on("data", (chunk: Buffer) => chunks.push(chunk));
        res.on("end", () =>
          resolve({ status: res.statusCode ?? 0, headers: res.headers, body: Buffer.concat(chunks) }),
        );
      },
    );
    req.on("error", reject);
    if (options.body) req.write(options.body);
    req.end();
  });
}

async function freeClosedPort(): Promise<number> {
  const probe = http.createServer();
  const port = await new Promise<number>((resolve) =>
    probe.listen({ host: "127.0.0.1", port: 0 }, () => resolve((probe.address() as AddressInfo).port)),
  );
  await new Promise<void>((resolve) => probe.close(() => resolve()));
  return port;
}

afterEach(async () => {
  while (closers.length > 0) {
    const close = closers.pop();
    if (close) await close();
  }
  while (tmpRoots.length > 0) {
    const root = tmpRoots.pop();
    if (root) fs.rmSync(root, { recursive: true, force: true });
  }
  tmpRoots = [];
});

beforeEach(() => {
  tmpRoots = [];
});

// ======================== 纯函数 ========================

describe("helpers", () => {
  it("matchesPrefix 按路径段匹配，不误伤同前缀路径", () => {
    expect(matchesPrefix("/api", "/api")).toBe(true);
    expect(matchesPrefix("/api/sovits-svc/models", "/api")).toBe(true);
    expect(matchesPrefix("/health", "/health")).toBe(true);
    expect(matchesPrefix("/apix", "/api")).toBe(false);
    expect(matchesPrefix("/assets/app.js", "/api")).toBe(false);
  });

  it("parseBackendTarget 解析 host/port/协议", () => {
    expect(parseBackendTarget("http://127.0.0.1:8300")).toEqual({
      protocol: "http:",
      hostname: "127.0.0.1",
      port: 8300,
      hostHeader: "127.0.0.1:8300",
    });
    expect(parseBackendTarget("https://backend.local")).toEqual({
      protocol: "https:",
      hostname: "backend.local",
      port: 443,
      hostHeader: "backend.local",
    });
  });

  it("parseRange 支持 bytes=a-b / a- / -n，越界与非法返回 invalid", () => {
    expect(parseRange("bytes=0-3", 10)).toEqual({ start: 0, end: 3 });
    expect(parseRange("bytes=4-", 10)).toEqual({ start: 4, end: 9 });
    expect(parseRange("bytes=-4", 10)).toEqual({ start: 6, end: 9 });
    expect(parseRange("bytes=0-99", 10)).toEqual({ start: 0, end: 9 });
    expect(parseRange("bytes=99-100", 10)).toBe("invalid");
    expect(parseRange("items=0-3", 10)).toBe("invalid");
    expect(parseRange("bytes=", 10)).toBe("invalid");
  });
});

// ======================== 静态托管与 SPA fallback ========================

describe("静态托管", () => {
  it("命中文件返回 200 + Content-Type + 字节数", async () => {
    const dist = makeDist();
    const handle = await startServer(dist, "http://127.0.0.1:1");
    const res = await rawRequest(handle.port, { path: "/assets/app.js" });

    expect(res.status).toBe(200);
    expect(res.headers["content-type"]).toContain("text/javascript");
    expect(res.headers["content-length"]).toBe(String(JS_BODY.length));
    expect(res.body.toString("utf8")).toBe(JS_BODY);
  });

  it("非文件 GET 走 SPA fallback（返回 index.html）", async () => {
    const dist = makeDist();
    const handle = await startServer(dist, "http://127.0.0.1:1");
    const res = await rawRequest(handle.port, { path: "/train" });

    expect(res.status).toBe(200);
    expect(res.headers["content-type"]).toContain("text/html");
    expect(res.body.toString("utf8")).toContain("SPA");
  });

  it("路径穿越被拒绝（403）", async () => {
    const dist = makeDist();
    const handle = await startServer(dist, "http://127.0.0.1:1");
    const res = await rawRequest(handle.port, { path: "/..%2f..%2fsecret.txt" });

    expect(res.status).toBe(403);
  });

  it("Range 请求静态文件返回 206 + Content-Range + 部分内容", async () => {
    const dist = makeDist();
    const handle = await startServer(dist, "http://127.0.0.1:1");
    const res = await rawRequest(handle.port, {
      path: "/assets/app.js",
      headers: { range: "bytes=0-3" },
    });

    expect(res.status).toBe(206);
    expect(res.headers["content-range"]).toBe(`bytes 0-3/${JS_BODY.length}`);
    expect(res.headers["accept-ranges"]).toBe("bytes");
    expect(res.headers["content-length"]).toBe("4");
    expect(res.body.toString("utf8")).toBe("0123");
  });

  it("越界 Range 返回 416", async () => {
    const dist = makeDist();
    const handle = await startServer(dist, "http://127.0.0.1:1");
    const res = await rawRequest(handle.port, {
      path: "/assets/app.js",
      headers: { range: "bytes=99-200" },
    });

    expect(res.status).toBe(416);
    expect(res.headers["content-range"]).toBe(`bytes */${JS_BODY.length}`);
  });

  it("非 GET/HEAD 的非代理路径返回 405", async () => {
    const dist = makeDist();
    const handle = await startServer(dist, "http://127.0.0.1:1");
    const res = await rawRequest(handle.port, { method: "POST", path: "/train" });
    expect(res.status).toBe(405);
  });
});

// ======================== /api 反代 ========================

describe("/api 反代", () => {
  it("透传方法/路径/查询串，返回后端 JSON", async () => {
    const seen: string[] = [];
    const upstream = await makeUpstream((req, res) => {
      seen.push(`${req.method} ${req.url} host=${req.headers.host}`);
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ ok: true, items: [1, 2, 3] }));
    });
    const dist = makeDist();
    const handle = await startServer(dist, `http://127.0.0.1:${upstream.port}`);

    const res = await rawRequest(handle.port, { path: "/api/sovits-svc/models?limit=5" });

    expect(res.status).toBe(200);
    expect(res.headers["content-type"]).toContain("application/json");
    expect(JSON.parse(res.body.toString("utf8"))).toEqual({ ok: true, items: [1, 2, 3] });
    expect(seen[0]).toBe(`GET /api/sovits-svc/models?limit=5 host=127.0.0.1:${upstream.port}`);
  });

  it("/health 也被反代（面板健康检查同源可用）", async () => {
    const upstream = await makeUpstream((_req, res) => {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ status: "healthy", service: "CXO-ModelStation" }));
    });
    const dist = makeDist();
    const handle = await startServer(dist, `http://127.0.0.1:${upstream.port}`);

    const res = await rawRequest(handle.port, { path: "/health" });
    expect(res.status).toBe(200);
    expect(JSON.parse(res.body.toString("utf8")).service).toBe("CXO-ModelStation");
  });

  it("multipart/form-data 上传端到端透传（boundary 与原始字节不被破坏）", async () => {
    let received = { contentType: "", length: 0, raw: "" };
    const upstream = await makeUpstream((req, res) => {
      const chunks: Buffer[] = [];
      req.on("data", (chunk: Buffer) => chunks.push(chunk));
      req.on("end", () => {
        const raw = Buffer.concat(chunks).toString("utf8");
        received = {
          contentType: String(req.headers["content-type"] ?? ""),
          length: raw.length,
          raw,
        };
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ status: "success", imported: 1 }));
      });
    });
    const dist = makeDist();
    const handle = await startServer(dist, `http://127.0.0.1:${upstream.port}`);

    const formData = new FormData();
    formData.append("speaker_name", "smoke");
    formData.append("files", new Blob([Buffer.from("audio-bytes-1234567890")], { type: "audio/wav" }), "smoke.wav");

    const response = await fetch(`http://127.0.0.1:${handle.port}/api/sovits-svc/datasets/import`, {
      method: "POST",
      body: formData,
    });
    const body = (await response.json()) as { status: string; imported: number };

    expect(response.status).toBe(200);
    expect(body).toEqual({ status: "success", imported: 1 });
    expect(received.contentType).toContain("multipart/form-data; boundary=");
    expect(received.raw).toContain('name="speaker_name"');
    expect(received.raw).toContain("smoke");
    expect(received.raw).toContain('filename="smoke.wav"');
    expect(received.raw).toContain("audio-bytes-1234567890");
  });

  it("Range 请求头与后端 206 响应（含 Content-Range）原样透传", async () => {
    let upstreamRange = "";
    const upstream = await makeUpstream((req, res) => {
      upstreamRange = String(req.headers.range ?? "");
      res.writeHead(206, {
        "Content-Type": "audio/wav",
        "Content-Range": "bytes 0-1023/8000",
        "Accept-Ranges": "bytes",
        "Content-Length": "4",
      });
      res.end("abcd");
    });
    const dist = makeDist();
    const handle = await startServer(dist, `http://127.0.0.1:${upstream.port}`);

    const res = await rawRequest(handle.port, {
      path: "/api/audio-files/audition/demo.wav",
      headers: { range: "bytes=0-1023" },
    });

    expect(upstreamRange).toBe("bytes=0-1023");
    expect(res.status).toBe(206);
    expect(res.headers["content-range"]).toBe("bytes 0-1023/8000");
    expect(res.headers["accept-ranges"]).toBe("bytes");
    expect(res.body.toString("utf8")).toBe("abcd");
  });

  it("OPTIONS 预检原样转发到后端", async () => {
    let method = "";
    const upstream = await makeUpstream((req, res) => {
      method = req.method ?? "";
      res.writeHead(200, { "Access-Control-Allow-Origin": "http://127.0.0.1:3300" });
      res.end();
    });
    const dist = makeDist();
    const handle = await startServer(dist, `http://127.0.0.1:${upstream.port}`);

    const res = await rawRequest(handle.port, { method: "OPTIONS", path: "/api/sovits-svc/train" });
    expect(method).toBe("OPTIONS");
    expect(res.status).toBe(200);
  });

  it("后端不可达：快速返回 502 + 可读 JSON（不挂死）", async () => {
    const dist = makeDist();
    const deadPort = await freeClosedPort();
    const handle = await startServer(dist, `http://127.0.0.1:${deadPort}`);

    const started = Date.now();
    const res = await rawRequest(handle.port, { path: "/api/sovits-svc/models" });
    const elapsed = Date.now() - started;

    expect(res.status).toBe(502);
    expect(res.headers["content-type"]).toContain("application/json");
    const detail = (JSON.parse(res.body.toString("utf8")) as { detail: string }).detail;
    expect(detail).toContain(`http://127.0.0.1:${deadPort}`);
    expect(elapsed).toBeLessThan(3000);
  });

  it("后端响应超时：按配置超时返回 502（不无限等待）", async () => {
    const upstream = await makeUpstream(() => {
      // 故意不响应
    });
    const dist = makeDist();
    const handle = await startServer(dist, `http://127.0.0.1:${upstream.port}`, 200);

    const started = Date.now();
    const res = await rawRequest(handle.port, { path: "/api/slow" });
    expect(res.status).toBe(502);
    expect(Date.now() - started).toBeLessThan(3000);
  });
});

// ======================== 端口顺延 ========================

describe("startStaticServer 端口", () => {
  it("首选端口被占用时顺延，返回实际端口", async () => {
    const dist = makeDist();
    const blocker = http.createServer();
    const blockedPort = await new Promise<number>((resolve) =>
      blocker.listen({ host: "127.0.0.1", port: 0 }, () => resolve((blocker.address() as AddressInfo).port)),
    );
    closers.push(() => closeServer(blocker));

    const handle = await startStaticServer({ distDir: dist, backendBaseUrl: "http://127.0.0.1:1", preferredPort: blockedPort });
    closers.push(() => closeServer(handle.server));

    expect(handle.port).toBeGreaterThan(blockedPort);
    expect(handle.url).toBe(`http://127.0.0.1:${handle.port}`);

    const res = await rawRequest(handle.port, { path: "/assets/app.js" });
    expect(res.status).toBe(200);
  });

  it("createStaticServer 仅监听回环（不暴露 0.0.0.0）", async () => {
    const dist = makeDist();
    const server = createStaticServer({ distDir: dist, backendBaseUrl: "http://127.0.0.1:1" });
    const port = await new Promise<number>((resolve) =>
      server.listen({ host: "127.0.0.1", port: 0 }, () => resolve((server.address() as AddressInfo).port)),
    );
    closers.push(() => closeServer(server));

    const res = await rawRequest(port, { path: "/assets/app.js" });
    expect(res.status).toBe(200);
    const address = server.address() as AddressInfo;
    expect(address.address).toBe("127.0.0.1");
  });
});