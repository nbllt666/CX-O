/**
 * 前端 Electron 启动配置（电脑控制规格 Task 5）
 * ============================================================================
 * 仅负责前端 Electron 的自启动与管理员权限启动，**不负责启动/停止后端进程**：
 *  - 自启动：Windows 登录项机制（app.setLoginItemSettings），持久化 auto_start
 *  - 管理员权限启动：遵循 Windows UAC（不绕过系统安全确认），持久化 run_as_admin
 *  - 提权仅在应用启动时经 applyStartupOnLaunch 请求（启动配置语义）：触发提权
 *    relaunch 后调用方必须让当前实例受控退出（让出单实例锁，否则新提权实例
 *    拿锁失败直接退出）；用户拒绝 UAC 时无新实例，应用随之结束，可手动重开
 *
 * 浏览器模式（npm run dev:browser）不加载本模块：渲染层仅在 window.electronAPI
 * 存在时才调用 startup IPC，缺失时设置项显示不可用。
 *
 * 配置键沿用 config.ts 的字符串键值约定，布尔以 'true'/'false' 字符串持久化到
 * userData/config.json（对齐既有 config:get/set-backend-url 模式）。
 * ============================================================================
 */
import { app } from 'electron';
import { execFileSync, spawn } from 'node:child_process';
import { getConfig, setConfig } from './config';

const AUTO_START_KEY = 'auto_start';
const RUN_AS_ADMIN_KEY = 'run_as_admin';

/**
 * 提权 relaunch 哨兵环境变量：随提权子进程传递（经 PowerShell Start-Process 继承）。
 * 新实例启动时检测到该哨兵即视为"提权链路实例"，即使 isRunningAsAdmin 探测
 * （net session）因故不可靠也不再 relaunch，防止 UAC 判定失效时无限循环拉起。
 */
const ELEVATED_RELAUNCH_ENV = 'CXO_ELEVATED_RELAUNCH';

/** 当前实例是否由提权 relaunch 链路拉起（哨兵环境变量命中） */
function isElevatedRelaunchChild(): boolean {
  return process.env[ELEVATED_RELAUNCH_ENV] === '1';
}

export interface StartupSettings {
  /** 当前平台是否支持启动配置（仅 Windows） */
  supported: boolean;
  /** 持久化的前端自启动开关 */
  autoStart: boolean;
  /** 持久化的管理员权限启动开关 */
  runAsAdmin: boolean;
  /** 当前进程是否实际以管理员权限运行（false 且 runAsAdmin=true → 设置未生效） */
  isAdmin: boolean;
}

function readBool(key: string): boolean {
  return getConfig(key) === 'true';
}

/** 启动配置仅支持 Windows（Electron 登录项与 UAC 均以 Windows 语义为准） */
export function isSupportedPlatform(): boolean {
  return process.platform === 'win32';
}

/**
 * 当前进程是否以管理员权限运行。
 * Windows 下 `net session` 仅管理员可成功（返回码 0），非管理员报错。
 */
export function isRunningAsAdmin(): boolean {
  if (process.platform !== 'win32') return false;
  try {
    execFileSync('net', ['session'], { stdio: 'ignore', timeout: 3000 });
    return true;
  } catch {
    return false;
  }
}

/** 读取启动配置当前状态（供渲染层初始化与刷新） */
export function getStartupSettings(): StartupSettings {
  return {
    supported: isSupportedPlatform(),
    autoStart: readBool(AUTO_START_KEY),
    runAsAdmin: readBool(RUN_AS_ADMIN_KEY),
    isAdmin: isRunningAsAdmin(),
  };
}

/** 查询系统登录项的实际自启动状态（与持久化开关相互印证） */
export function getEffectiveAutoStart(): boolean {
  if (!isSupportedPlatform()) return false;
  try {
    return app.getLoginItemSettings().openAtLogin;
  } catch (err) {
    console.error('[startup] 读取系统登录项失败:', err);
    return false;
  }
}

/**
 * 设置前端自启动（Windows 登录项机制）。
 * 持久化 auto_start 并同步系统登录项；失败时回滚持久化并返回 false。
 */
export function setAutoStart(enabled: boolean): boolean {
  const value = !!enabled;
  if (!isSupportedPlatform()) return false;
  setConfig(AUTO_START_KEY, String(value));
  try {
    app.setLoginItemSettings({ openAtLogin: value });
    return true;
  } catch (err) {
    console.error('[startup] 设置自启动失败:', err);
    // 系统登录项更新失败时回滚配置，避免持久化状态与实际不符
    setConfig(AUTO_START_KEY, String(!value));
    return false;
  }
}

/**
 * 设置管理员权限启动。
 * 仅持久化 run_as_admin（启动配置语义，提权在下次启动时经 applyStartupOnLaunch
 * 请求 UAC）。关闭时仅持久化，无法在运行中取消已提权实例。
 */
export function setRunAsAdmin(enabled: boolean): boolean {
  const value = !!enabled;
  setConfig(RUN_AS_ADMIN_KEY, String(value));
  return true;
}

/**
 * 通过 runas verb 请求管理员权限（触发 Windows UAC 提示）。
 * 用户接受 → 启动一个提权实例（携带 CXO_ELEVATED_RELAUNCH=1 哨兵，经 PowerShell
 * 环境块继承到新实例）；用户拒绝 → 命令失败，无新实例产生。
 * 注意：本函数不退出当前实例——调用方收到"需要提权重启"信号后负责受控退出，
 * 让出单实例锁给新提权实例。
 */
function relaunchElevated(): void {
  try {
    const exe = process.execPath;
    // PowerShell 单引号字符串中 '' 表示字面单引号：逐项转义后以逗号分隔数组传给
    // -ArgumentList，避免参数含单引号/空格时破坏命令解析（原实现把整串包进一对
    // 单引号，任一参数含引号即破坏命令并可能注入额外 PS 语句）。
    const psQuote = (s: string): string => `'${String(s ?? '').replace(/'/g, "''")}'`;
    const argList = process.argv
      .slice(1)
      .map(psQuote)
      .join(', ');
    const command = `Start-Process -FilePath ${psQuote(exe)} -ArgumentList ${argList} -Verb RunAs`;
    const child = spawn('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', command], {
      stdio: 'ignore',
      detached: true,
      // 哨兵经 PowerShell → Start-Process 环境块继承传递给提权子实例
      env: { ...process.env, [ELEVATED_RELAUNCH_ENV]: '1' },
    });
    // L级修复：补 error 监听——子进程无法创建（如 PowerShell 缺失/ENOENT）时
    // emit 'error' 且无监听器会直接抛 uncaught exception 打断主流程。
    child.on('error', (err) => {
      console.error('[startup] 提权 PowerShell 进程启动失败:', err.message);
    });
    child.unref();
  } catch (err) {
    console.error('[startup] 请求管理员权限失败:', err);
  }
}

/**
 * 应用启动时调用：若持久化 run_as_admin=true 且当前未提权，则请求 UAC 提权 relaunch。
 * 返回 true = 已触发提权请求，调用方必须受控退出当前实例（让出单实例锁，否则新
 * 提权实例拿锁失败直接退出）；返回 false = 无需提权，正常继续启动。
 * 哨兵子实例（CXO_ELEVATED_RELAUNCH=1）即使提权探测不可靠也不再 relaunch，防死循环。
 */
export function applyStartupOnLaunch(): boolean {
  if (!isSupportedPlatform()) return false;
  if (!readBool(RUN_AS_ADMIN_KEY)) return false;
  // 哨兵优先于提权探测：提权链路实例不再发起 relaunch（防 UAC 判定失效时死循环）
  if (isElevatedRelaunchChild()) return false;
  if (isRunningAsAdmin()) return false;
  relaunchElevated();
  return true;
}
