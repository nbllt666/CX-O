/**
 * Neko 插件 LLM 工具 → CXFC 桥接核心（纯逻辑，无 electron 依赖，可单测）
 * ============================================================================
 * 背景：neko 插件只把 LLM 工具定义 POST 给 neko 主服务器（/api/tools/register，
 * 主服务器端口 48911），插件服务器本地只留 (plugin_id, tool_name)+超时。为了让
 * CX-O 后端能通过 CXFC 协议调用这些工具，需要在本机补一个「注册接收器」把
 * 定义完整捕获，并提供一个 CXFC 风格 /call 桥，把工具调用转发到插件服务器的
 * /api/llm-tools/callback/{plugin_id}/{tool}。
 *
 * 本文件提供：
 *  - ToolRegistrarStore：内存工具注册表（register/unregister/clear/list）
 *  - 注册接收器协议处理器（模拟 neko 主服务器 /api/tools/* 路由各端点）
 *  - CXFC 桥 /call 处理器（鉴权/防重放由外部完成，此处负责转发与结果映射）
 * ============================================================================
 */

/** 一条工具注册定义（对齐 neko main_server ToolRegisterRequest 语义） */
export interface ToolRegDef {
  name: string;
  description?: string;
  parameters?: Record<string, unknown>;
  callback_url?: string;
  role?: string | null;
  source?: string | null;
  timeout_seconds?: number;
  /** 由 source 标签解析出的插件 id（plugin:{id}），供 /call 转发定位 */
  plugin_id?: string;
}

/** 从 neko 的 source 标签（plugin:{id}）解析插件 id；非 plugin: 前缀返回 null */
export function parsePluginIdFromSource(source?: string | null): string | null {
  if (!source) return null;
  const m = /^plugin:(.+)$/.exec(source);
  return m ? m[1] : null;
}

/** 把工具定义映射为 CXFC 注册所需的 schema（name/description/parameters/returns） */
export function buildToolSchema(def: ToolRegDef): Record<string, unknown> {
  return {
    name: def.name,
    description: def.description ?? '',
    parameters: def.parameters ?? {},
    returns: {},
  };
}

/** 内存工具注册表（插件 → 工具定义；name 为唯一键） */
export class ToolRegistrarStore {
  private readonly tools = new Map<string, ToolRegDef>();

  /** 注册/更新；从 source 解析 plugin_id。返回受影响 role 列表（对齐 main_server 语义）。 */
  register(def: ToolRegDef): { ok: true; affected_roles: string[]; failed_roles: string[] } {
    const normalized: ToolRegDef = { ...def, plugin_id: parsePluginIdFromSource(def.source) ?? def.plugin_id };
    this.tools.set(def.name, normalized);
    return { ok: true, affected_roles: [def.role ?? 'default'], failed_roles: [] };
  }

  /** 反注册单个工具；存在则删除返回 true */
  unregister(name: string): boolean {
    return this.tools.delete(name);
  }

  /** 按 source 清空（插件下线时全量清理）；返回移除数量 */
  clearBySource(source?: string | null): number {
    if (!source) return 0;
    let removed = 0;
    for (const [name, def] of this.tools) {
      if (def.source === source) {
        this.tools.delete(name);
        removed++;
      }
    }
    return removed;
  }

  /** 由工具名取定义 */
  get(name: string): ToolRegDef | undefined {
    return this.tools.get(name);
  }

  /** 全量定义列表（按名排序，稳定） */
  list(): ToolRegDef[] {
    return [...this.tools.values()].sort((a, b) => a.name.localeCompare(b.name));
  }

  /** 供 CXFC 注册的 schema 列表 */
  listSchemas(): unknown[] {
    return this.list().map(buildToolSchema);
  }

  size(): number {
    return this.tools.size;
  }
}

// ---------------------------------------------------------------------------
// 小工具
// ---------------------------------------------------------------------------

export interface JsonBody {
  [key: string]: unknown;
}

export async function readJsonBody(req: NodeJS.ReadableStream): Promise<JsonBody | null> {
  const chunks: Buffer[] = [];
  let size = 0;
  const MAX = 1024 * 1024;
  for await (const chunk of req) {
    const b = chunk as Buffer;
    size += b.length;
    if (size > MAX) return null;
    chunks.push(b);
  }
  if (chunks.length === 0) return null;
  try {
    const parsed = JSON.parse(Buffer.concat(chunks).toString('utf-8'));
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return null;
    return parsed as JsonBody;
  } catch {
    return null;
  }
}

export function jsonPayload(data: string, status: number): { status: number; body: string; headers: Record<string, string> } {
  return {
    status,
    body: data,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      'Content-Length': String(Buffer.byteLength(data)),
      'Cache-Control': 'no-store',
    },
  };
}

// ---------------------------------------------------------------------------
// 注册接收器（模拟 neko 主服务器 /api/tools/*）——返回 {route, status, body} 交给外层写 socket
// ---------------------------------------------------------------------------

export interface RegistrationRouteResult {
  status: number;
  headers: Record<string, string>;
  body: string;
}

/** 处理注册接收器请求；返回可直接写回的结果。fetch 未用，仅保留签名一致性。 */
export function handleRegistrarRoute(
  store: ToolRegistrarStore,
  method: string,
  pathname: string,
  body: JsonBody | null,
): RegistrationRouteResult {
  const write = (status: number, obj: unknown): RegistrationRouteResult => {
    const data = JSON.stringify(obj);
    return { status, headers: jsonPayload(data, status).headers, body: data };
  };

  if (method === 'GET' && pathname === '/api/tools') {
    const tools: Record<string, Record<string, unknown>> = {};
    for (const def of store.list()) {
      tools[def.name] = {
        description: def.description ?? '',
        parameters: def.parameters ?? {},
        callback_url: def.callback_url ?? '',
        source: def.source ?? null,
        timeout_seconds: def.timeout_seconds ?? 30,
      };
    }
    return write(200, { tools });
  }

  if (method !== 'POST') {
    return write(400, { ok: false, error: 'unsupported method or path' });
  }

  if (pathname === '/api/tools/register') {
    if (!body || typeof body.name !== 'string' || !body.name) {
      return write(400, { ok: false, error: 'name required' });
    }
    const def: ToolRegDef = {
      name: body.name,
      description: typeof body.description === 'string' ? body.description : '',
      parameters: typeof body.parameters === 'object' && body.parameters ? (body.parameters as Record<string, unknown>) : {},
      callback_url: typeof body.callback_url === 'string' ? body.callback_url : '',
      role: typeof body.role === 'string' ? body.role : null,
      source: typeof body.source === 'string' ? body.source : null,
      timeout_seconds: typeof body.timeout_seconds === 'number' ? body.timeout_seconds : 30,
      plugin_id: parsePluginIdFromSource(typeof body.source === 'string' ? body.source : null) ?? undefined,
    };
    const res = store.register(def);
    return write(200, { ...res, plugin_id: def.plugin_id ?? null });
  }

  if (pathname === '/api/tools/unregister') {
    const name = body?.name;
    const removed = typeof name === 'string' && name ? store.unregister(name) : false;
    return write(200, { ok: true, removed: removed ? 1 : 0, failed_roles: [] });
  }

  if (pathname === '/api/tools/clear') {
    const source = typeof body?.source === 'string' ? body.source : null;
    const removed = store.clearBySource(source);
    return write(200, { ok: true, removed, failed_roles: [] });
  }

  return write(404, { ok: false, error: 'unknown route' });
}

// ---------------------------------------------------------------------------
// CXFC /call 转发（鉴权/防重放在外层完成；此处执行查找+转发+结果映射）
// ---------------------------------------------------------------------------

export interface CallContext {
  /** 意见：从请求体取出工具名 */
  tool?: string;
  arguments?: Record<string, unknown>;
  request_id?: string;
}

export type ToolCallResult = {
  ok: true;
  result: unknown;
} | {
  ok: false;
  code: string;
  message: string;
};

/**
 * 执行一次 CXFC 工具调用。@param pluginPort 插件服务器端口；@param fetchImpl 可注入便于测试。
 */
export async function executeNekoToolCall(
  store: ToolRegistrarStore,
  ctx: CallContext,
  options: {
    pluginPort: number;
    fetchImpl?: typeof fetch;
  },
): Promise<ToolCallResult> {
  const toolName = ctx.tool;
  const args = ctx.arguments ?? {};
  if (typeof toolName !== 'string' || !toolName) {
    return { ok: false, code: 'INVALID_ARGUMENT', message: '缺少工具名' };
  }
  const def = store.get(toolName);
  if (!def) {
    return { ok: false, code: 'INVALID_ARGUMENT', message: `未知工具：${toolName}` };
  }
  if (!def.plugin_id) {
    return { ok: false, code: 'INVALID_ARGUMENT', message: `工具 ${toolName} 缺少插件归属（source 标签）` };
  }
  if (!Number.isFinite(options.pluginPort) || options.pluginPort <= 0) {
    return { ok: false, code: 'PLUGIN_OFFLINE', message: '插件服务器端口无效' };
  }

  const fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);
  const url = `http://127.0.0.1:${options.pluginPort}/api/llm-tools/callback/${encodeURIComponent(def.plugin_id)}/${encodeURIComponent(toolName)}`;
  try {
    const resp = await fetchImpl(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: toolName, arguments: args, call_id: ctx.request_id ?? '' }),
    });
    let data: { output?: unknown; is_error?: boolean; error?: string | null } = {};
    try {
      data = (await resp.json()) as typeof data;
    } catch {
      data = { output: undefined, is_error: true, error: `非 JSON 响应 (HTTP ${resp.status})` };
    }
    if (data.is_error) {
      return { ok: false, code: 'EXECUTION_FAILED', message: data.error ?? 'neko 插件工具执行失败' };
    }
    return { ok: true, result: data.output };
  } catch (err) {
    return {
      ok: false,
      code: 'PLUGIN_OFFLINE',
      message: `转发到插件服务器失败: ${err instanceof Error ? err.message : String(err)}`,
    };
  }
}