/**
 * 电脑控制插件装配与生命周期（主进程使用）。
 *
 * 负责：
 * - 持久化注册令牌（首次运行生成随机 256-bit 令牌）与 host/port 配置
 * - 装配授权状态代理、认证器、TLS 证书、三个工具适配器与 HTTPS 服务
 * - 提供面向 electron 主进程的 start/stop 与 IPC 查询/授权读写入口
 *
 * 本文件依赖 electron（app.getPath），仅由 electron/main.ts 导入；单测针对底层
 * 模块（authorization/auth/tls/screen/keyboard/runCommand/httpServer）。
 */
import { app } from 'electron';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { randomBytes } from 'node:crypto';
import { AuthorizationStore, type AuthorizationPersistence } from './authorization';
import { Authenticator } from './auth';
import { ensureCertificate } from './tls';
import { ComputerControlHttpServer, type PluginConfig, type SkillInfo, type ToolHandler } from './httpServer';
import { ERROR_MESSAGES, errorResult, messageOf, type ToolResult } from './errors';
import { createScreenTool } from './screen';
import { createKeyboardTool } from './keyboard';
import { createRunCommandTool } from './runCommand';
import { NativeScreenDriver, NativeKeyboardDriver } from './nativeDrivers';

export interface ComputerControlOptions {
  host?: string;
  port?: number;
  /** 是否允许本机真实输入驱动（关闭时工具返回 SYSTEM_ERROR，便于无 GUI 环境） */
  enableNativeDrivers?: boolean;
}

interface PluginFileConfig {
  token: string;
  host: string;
  port: number;
}

const PLUGIN_DIR = 'plugins/computerControl';

function pluginDir(): string {
  return path.join(app.getPath('userData'), PLUGIN_DIR);
}

/** 读取或创建插件级配置文件（含随机注册令牌），令牌只存于主进程 userData */
function loadOrCreatePluginConfig(opts: ComputerControlOptions): PluginFileConfig {
  const dir = pluginDir();
  fs.mkdirSync(dir, { recursive: true });
  const configPath = path.join(dir, 'config.json');
  if (fs.existsSync(configPath)) {
    try {
      const parsed = JSON.parse(fs.readFileSync(configPath, 'utf-8')) as Partial<PluginFileConfig>;
      if (typeof parsed.token === 'string' && parsed.token.length > 0) {
        return {
          token: parsed.token,
          host: opts.host ?? parsed.host ?? '127.0.0.1',
          port: opts.port ?? parsed.port ?? 8443,
        };
      }
    } catch {
      // 配置损坏则重新生成
    }
  }
  const config: PluginFileConfig = {
    token: randomBytes(32).toString('hex'),
    host: opts.host ?? '127.0.0.1',
    port: opts.port ?? 8443,
  };
  fs.writeFileSync(configPath, JSON.stringify(config, null, 2), { encoding: 'utf-8', mode: 0o600 });
  return config;
}

function filePersistence(): AuthorizationPersistence {
  const filePath = path.join(pluginDir(), 'authorization.json');
  return {
    load(): boolean | null {
      try {
        const parsed = JSON.parse(fs.readFileSync(filePath, 'utf-8')) as { authorized?: boolean };
        return typeof parsed.authorized === 'boolean' ? parsed.authorized : null;
      } catch {
        return null;
      }
    },
    save(value: boolean): void {
      fs.mkdirSync(path.dirname(filePath), { recursive: true });
      fs.writeFileSync(filePath, JSON.stringify({ authorized: value }), { encoding: 'utf-8' });
    },
  };
}

export interface ComputerControlPlugin {
  server: ComputerControlHttpServer;
  authorization: AuthorizationStore;
  token: string;
  start(): Promise<void>;
  stop(): Promise<void>;
  getPort(): number;
  getFingerprint(): string;
  /** B-1：返回 TLS 自签名证书 PEM 原文，供注册载荷上报给后端做 TOFU 首次信任 */
  getTlsCertPem(): string;
  /**
   * P2-T2 relay 推送路径：进程内调用工具（与 /call HTTP 端点同源分发，共用同一批 ToolHandler，
   * 但绕过 HTTP 认证/防重放——由 IPC 调用方（main.ts）承担授权校验）。
   */
  callTool(tool: string, params: Record<string, unknown>): Promise<ToolResult>;
}

export function createComputerControlPlugin(opts: ComputerControlOptions = {}): ComputerControlPlugin {
  const config = loadOrCreatePluginConfig(opts);
  const tls = ensureCertificate(pluginDir());

  const authorization = new AuthorizationStore(filePersistence(), false);
  const authenticator = new Authenticator({ token: config.token });

  const tools: Record<string, ToolHandler> = {};
  if (opts.enableNativeDrivers !== false) {
    tools.computer_screen_control = createScreenTool(new NativeScreenDriver());
    tools.computer_keyboard_control = createKeyboardTool(new NativeKeyboardDriver());
  } else {
    tools.computer_screen_control = async () => ({ ok: false, code: 'SYSTEM_ERROR', error: '本机驱动未启用' });
    tools.computer_keyboard_control = async () => ({ ok: false, code: 'SYSTEM_ERROR', error: '本机驱动未启用' });
  }
  tools.computer_run_command = createRunCommandTool();

  const skills: SkillInfo[] = [
    {
      name: 'computer_screen_control',
      description: '屏幕控制：capture/click/move/scroll',
      arguments: { action: 'string', x: 'number', y: 'number', delta: 'number', button: 'string' },
    },
    {
      name: 'computer_keyboard_control',
      description: '键盘控制：type/key/press/hotkey',
      arguments: { action: 'string', text: 'string', key: 'string', modifiers: 'string[]' },
    },
    {
      name: 'computer_run_command',
      description: '运行指令：结构化 command+args+cwd+timeout_ms+env 白名单',
      arguments: { command: 'string', args: 'string[]', cwd: 'string', timeout_ms: 'number', env: 'object' },
    },
  ];

  const serverConfig: PluginConfig = {
    host: config.host,
    port: config.port,
    tls: { cert: tls.cert, key: tls.key },
  };

  const server = new ComputerControlHttpServer({
    authenticator,
    isAuthorized: () => authorization.isAuthorized(),
    tools,
    skills,
    config: serverConfig,
    fingerprint: tls.fingerprint,
    logger: (line) => console.log(line),
  });

  return {
    server,
    authorization,
    token: config.token,
    async start(): Promise<void> {
      await server.start();
    },
    async stop(): Promise<void> {
      await server.stop();
    },
    getPort(): number {
      return server.getPort();
    },
    getFingerprint(): string {
      return tls.fingerprint;
    },
    getTlsCertPem(): string {
      return tls.cert;
    },
    async callTool(tool, params) {
      const handler = tools[tool];
      if (!handler) {
        return errorResult('INVALID_ARGUMENT', '未知工具');
      }
      try {
        return await handler(params);
      } catch (err) {
        return errorResult('SYSTEM_ERROR', `工具执行异常: ${messageOf(err)}`);
      }
    },
  };
}

// ---------------------------------------------------------------------------
// 主进程单例 + 面向 electron IPC 的查询/写入入口
// ---------------------------------------------------------------------------
let currentPlugin: ComputerControlPlugin | null = null;

export async function startComputerControlPlugin(
  opts: ComputerControlOptions = {},
): Promise<ComputerControlPlugin> {
  if (currentPlugin) return currentPlugin;
  currentPlugin = createComputerControlPlugin(opts);
  await currentPlugin.start();
  return currentPlugin;
}

export async function stopComputerControlPlugin(): Promise<void> {
  if (!currentPlugin) return;
  await currentPlugin.stop();
  currentPlugin = null;
}

export function getPluginInfo(): {
  running: boolean;
  port: number | null;
  fingerprint: string | null;
  authorized: boolean;
} {
  if (!currentPlugin) {
    return { running: false, port: null, fingerprint: null, authorized: false };
  }
  return {
    running: true,
    port: currentPlugin.getPort(),
    fingerprint: currentPlugin.getFingerprint(),
    authorized: currentPlugin.authorization.isAuthorized(),
  };
}

export function getComputerControlAuthorization(): boolean {
  return currentPlugin?.authorization.isAuthorized() ?? false;
}

export function setComputerControlAuthorization(value: boolean): boolean {
  if (!currentPlugin) return false;
  currentPlugin.authorization.setAuthorized(value);
  return currentPlugin.authorization.isAuthorized();
}

/**
 * P2-T2 relay 推送路径：经主进程进程内调用电脑控制工具。
 * 插件未启动（未注册）时返回 PLUGIN_OFFLINE 稳定错误码，不执行任何本机动作；
 * 授权校验由 IPC 调用方（electron/main.ts）承担，与 /call HTTP 端点授权语义一致。
 */
export async function callComputerControlTool(
  tool: string,
  params: Record<string, unknown>,
): Promise<ToolResult> {
  if (!currentPlugin) {
    return errorResult('PLUGIN_OFFLINE', ERROR_MESSAGES.PLUGIN_OFFLINE);
  }
  return currentPlugin.callTool(tool, params ?? {});
}
