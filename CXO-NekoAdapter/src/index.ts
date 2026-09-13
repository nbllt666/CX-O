/**
 * CXO-NekoAdapter CLI 入口
 * ============================================================================
 * 职责：解析 CLI 参数（--port 覆盖控制面端口，仅本次运行生效）→ 启动控制面
 * HTTP 服务器 → 保持进程存活（server.listen 本身持活，无需额外定时器）。
 *
 * 退出语义：SIGINT/SIGTERM 优雅退出——尽力 stopNekoRuntime（3s 超时兜底）→
 * close 控制面 → process.exit(0)。Electron before-quit 场景会先 POST /stop 再
 * 杀进程，因此信号处理必须快速退出，不得悬挂。
 * ============================================================================
 */
import * as fs from 'node:fs';
import * as path from 'node:path';
import { projectRoot } from './shared/paths';
import { startControlServer } from './control';
import { stopNekoRuntime } from './launcher/launcher';

/** 从 package.json 读取版本号（读取失败回落 0.0.0） */
function readVersion(): string {
  try {
    const pkg = JSON.parse(fs.readFileSync(path.join(projectRoot, 'package.json'), 'utf-8')) as { version?: unknown };
    return typeof pkg.version === 'string' ? pkg.version : '0.0.0';
  } catch {
    return '0.0.0';
  }
}

/** 解析 --port <n>；缺失返回 undefined，非法值抛错（1-65535 整数） */
function parseCliPort(argv: string[]): number | undefined {
  const idx = argv.indexOf('--port');
  if (idx === -1) return undefined;
  const raw = argv[idx + 1];
  const n = Number(raw);
  if (raw === undefined || !Number.isInteger(n) || n <= 0 || n > 65535) {
    throw new Error(`--port 参数无效：${raw ?? '（缺失）'}（需 1-65535 的整数）`);
  }
  return n;
}

async function main(): Promise<void> {
  // 版本行（机器可读）
  console.log(`[adapter] CXO-NekoAdapter v${readVersion()}`);

  let cliPort: number | undefined;
  try {
    cliPort = parseCliPort(process.argv);
  } catch (err) {
    console.error(`[adapter] ${err instanceof Error ? err.message : String(err)}`);
    process.exit(1);
  }

  const handle = await startControlServer(cliPort !== undefined ? { port: cliPort } : undefined);

  // 优雅退出：幂等防重入；硬兜底 3s 后强制退出，杜绝悬挂
  let shuttingDown = false;
  const shutdown = (signal: string): void => {
    if (shuttingDown) return;
    shuttingDown = true;
    console.log(`[adapter] 收到 ${signal}，退出中...`);
    const hardExit = setTimeout(() => process.exit(0), 3000);
    void (async () => {
      // 1) 尽力停运行时（含 python 子进程与桥），3s 超时兜底
      try {
        await Promise.race([stopNekoRuntime(), new Promise((r) => setTimeout(r, 3000))]);
      } catch {
        /* 尽力而为 */
      }
      // 2) 关闭控制面（销毁 SSE 等全部连接）
      try {
        await Promise.race([handle.close(), new Promise((r) => setTimeout(r, 1000))]);
      } catch {
        /* 尽力而为 */
      }
      clearTimeout(hardExit);
      process.exit(0);
    })();
  };
  process.on('SIGINT', () => shutdown('SIGINT'));
  process.on('SIGTERM', () => shutdown('SIGTERM'));
}

void main().catch((err) => {
  console.error(`[adapter] 启动失败: ${err instanceof Error ? err.message : String(err)}`);
  process.exit(1);
});
