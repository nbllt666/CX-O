/**
 * SubTask 2.2 HTTPS 插件服务。
 *
 * 承载四个端点：
 *   GET  /health  匿名健康检查（含证书指纹，供客户端校验防中间人）
 *   GET  /tools   需认证+授权 → 返回可用工具名
 *   GET  /skills  需认证+授权 → 返回技能列表
 *   POST /call    需认证+授权+防重放 → 分发到工具执行
 *
 * 安全路径固定顺序（任一失败即返回稳定错误码，不执行任何本机动作）：
 *   1) 令牌认证（UNAUTHORIZED） → 2) 防重放（REPLAY_DETECTED/INVALID_ARGUMENT）
 *   → 3) 本地授权（NOT_AUTHORIZED） → 4) 工具分发与执行
 *
 * 端口冲突自动重试并重注册（依次递增端口）。生命周期随 Electron 启停。
 * 不依赖 electron 主进程 API（证书/依赖注入），可在 node 环境单测。
 */
import { createServer, type Server } from 'node:https';
import type { IncomingMessage, ServerResponse } from 'node:http';
import type { Authenticator } from './auth';
import { ERROR_MESSAGES, HTTP_STATUS, errorResult, messageOf, type ErrorCode, type ToolResult } from './errors';

export type ToolHandler = (params: Record<string, unknown>) => Promise<ToolResult>;

export interface PluginConfig {
  host: string;
  port: number;
  /** 端口被占用时的最大重试次数（递增端口），默认 10 */
  maxPortAttempts?: number;
  tls: { cert: string; key: string };
}

export interface SkillInfo {
  name: string;
  description: string;
  arguments: Record<string, string>;
}

export interface PluginDeps {
  authenticator: Authenticator;
  isAuthorized: () => boolean;
  /** 工具名 → 处理器 */
  tools: Record<string, ToolHandler>;
  /** 技能清单（供 /skills 返回） */
  skills: SkillInfo[];
  config: PluginConfig;
  /** 证书指纹，经 /health 暴露供客户端校验 */
  fingerprint: string;
  logger?: (line: string) => void;
}

const MAX_BODY_BYTES = 1024 * 1024; // 1 MiB 请求体上限，防滥用

export class ComputerControlHttpServer {
  private server: Server | null = null;
  private port = 0;
  private readonly logger: (line: string) => void;

  constructor(private readonly deps: PluginDeps) {
    this.logger = deps.logger ?? (() => undefined);
  }

  getPort(): number {
    return this.port;
  }

  async start(): Promise<void> {
    const { config } = this.deps;
    const maxAttempts = config.maxPortAttempts ?? 10;
    for (let attempt = 0; attempt < maxAttempts; attempt++) {
      const port = config.port + attempt;
      try {
        await this.listen(port);
        if (attempt > 0) {
          this.logger(`[computerControl] 端口 ${config.port} 被占用，已重注册到 ${this.port}`);
        }
        this.logger(`[computerControl] HTTPS 服务已启动: https://${config.host}:${this.port}`);
        return;
      } catch (err) {
        if ((err as { code?: string }).code === 'EADDRINUSE' && attempt < maxAttempts - 1) {
          continue;
        }
        throw err;
      }
    }
    throw new Error('无法绑定插件端口（全部端口被占用）');
  }

  async stop(): Promise<void> {
    const server = this.server;
    this.server = null;
    if (server) {
      await new Promise<void>((resolve) => server.close(() => resolve()));
      this.logger('[computerControl] HTTPS 服务已停止');
    }
  }

  private listen(port: number): Promise<void> {
    return new Promise((resolve, reject) => {
      const server = createServer(
        { key: this.deps.config.tls.key, cert: this.deps.config.tls.cert },
        (req, res) => {
          void this.handle(req, res);
        },
      );
      server.once('error', reject);
      server.listen(port, this.deps.config.host, () => {
        server.removeListener('error', reject);
        this.server = server;
        const addr = server.address();
        this.port = addr && typeof addr === 'object' ? addr.port : port;
        resolve();
      });
    });
  }

  // ---------------------------------------------------------------------------
  // 路由分发
  // ---------------------------------------------------------------------------
  private async handle(req: IncomingMessage, res: ServerResponse): Promise<void> {
    let url: URL;
    try {
      url = new URL(req.url ?? '/', `https://${req.headers.host ?? 'localhost'}`);
    } catch {
      return this.json(res, HTTP_STATUS.INVALID_ARGUMENT, {
        ok: false,
        error: { code: 'INVALID_ARGUMENT', message: '非法请求路径' },
      });
    }
    const pathname = url.pathname;
    try {
      if (req.method === 'GET' && pathname === '/health') {
        return this.handleHealth(res);
      }
      if (req.method === 'GET' && pathname === '/tools') {
        return this.withAuth(req, res, () => this.handleTools(res));
      }
      if (req.method === 'GET' && pathname === '/skills') {
        return this.withAuth(req, res, () => this.handleSkills(res));
      }
      if (req.method === 'POST' && pathname === '/call') {
        return this.handleCall(req, res);
      }
      return this.json(res, HTTP_STATUS.INVALID_ARGUMENT, {
        ok: false,
        error: { code: 'INVALID_ARGUMENT', message: '未知端点或方法' },
      });
    } catch (err) {
      this.logger(`[computerControl] 处理请求异常: ${messageOf(err)}`);
      return this.error(res, 'SYSTEM_ERROR', '插件内部错误');
    }
  }

  private handleHealth(res: ServerResponse): void {
    this.json(res, 200, {
      ok: true,
      status: 'ok',
      service: 'computer-control',
      fingerprint: this.deps.fingerprint,
    });
  }

  private handleTools(res: ServerResponse): void {
    this.json(res, 200, { ok: true, tools: Object.keys(this.deps.tools) });
  }

  private handleSkills(res: ServerResponse): void {
    this.json(res, 200, { ok: true, skills: this.deps.skills });
  }

  private async handleCall(req: IncomingMessage, res: ServerResponse): Promise<void> {
    const token = extractBearer(req.headers.authorization);
    const auth = this.deps.authenticator.verifyAuth(token);
    if (!auth.ok) {
      return this.error(res, 'UNAUTHORIZED', ERROR_MESSAGES.UNAUTHORIZED);
    }

    const body = await readJson(req);
    if (body === null) {
      return this.error(res, 'INVALID_ARGUMENT', '请求体必须为合法 JSON 对象');
    }

    const replay = this.deps.authenticator.verifyReplay(body.request_id);
    if (!replay.ok) {
      return this.error(res, replay.code as ErrorCode, ERROR_MESSAGES[replay.code as ErrorCode]);
    }

    if (!this.deps.isAuthorized()) {
      return this.error(res, 'NOT_AUTHORIZED', ERROR_MESSAGES.NOT_AUTHORIZED);
    }

    if (typeof body.tool !== 'string' || !(body.tool in this.deps.tools)) {
      return this.error(res, 'INVALID_ARGUMENT', '未知工具');
    }
    const args = body.arguments ?? {};
    if (typeof args !== 'object' || args === null || Array.isArray(args)) {
      return this.error(res, 'INVALID_ARGUMENT', 'arguments 必须为对象');
    }

    let result: ToolResult;
    try {
      result = await this.deps.tools[body.tool](args as Record<string, unknown>);
    } catch (err) {
      result = errorResult('SYSTEM_ERROR', `工具执行异常: ${messageOf(err)}`);
    }

    if (result.ok) {
      return this.json(res, 200, { ok: true, result: result.output });
    }
    const code = result.code as ErrorCode;
    return this.json(res, HTTP_STATUS[code] ?? 500, {
      ok: false,
      error: { code, message: result.error ?? ERROR_MESSAGES[code] },
    });
  }

  // ---------------------------------------------------------------------------
  // 工具方法
  // ---------------------------------------------------------------------------
  private withAuth(
    req: IncomingMessage,
    res: ServerResponse,
    next: () => void,
  ): void {
    const token = extractBearer(req.headers.authorization);
    const auth = this.deps.authenticator.verifyAuth(token);
    if (!auth.ok) {
      return this.error(res, 'UNAUTHORIZED', ERROR_MESSAGES.UNAUTHORIZED);
    }
    if (!this.deps.isAuthorized()) {
      return this.error(res, 'NOT_AUTHORIZED', ERROR_MESSAGES.NOT_AUTHORIZED);
    }
    next();
  }

  private json(res: ServerResponse, status: number, payload: unknown): void {
    const body = JSON.stringify(payload);
    res.writeHead(status, {
      'Content-Type': 'application/json; charset=utf-8',
      'Content-Length': Buffer.byteLength(body),
      'Cache-Control': 'no-store',
    });
    res.end(body);
  }

  private error(res: ServerResponse, code: ErrorCode, message: string): void {
    this.json(res, HTTP_STATUS[code] ?? 500, { ok: false, error: { code, message } });
  }
}

function extractBearer(header: string | undefined): string | undefined {
  if (!header) return undefined;
  const m = /^Bearer\s+(.+)$/i.exec(header.trim());
  return m ? m[1] : undefined;
}

/** 读取并解析 JSON 请求体；超限或非法返回 null */
async function readJson(req: IncomingMessage): Promise<Record<string, unknown> | null> {
  const chunks: Buffer[] = [];
  let size = 0;
  for await (const chunk of req) {
    const buf = chunk as Buffer;
    size += buf.length;
    if (size > MAX_BODY_BYTES) return null;
    chunks.push(buf);
  }
  if (chunks.length === 0) return null;
  try {
    const parsed = JSON.parse(Buffer.concat(chunks).toString('utf-8'));
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return null;
    return parsed as Record<string, unknown>;
  } catch {
    return null;
  }
}
