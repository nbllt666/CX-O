/**
 * SubTask 2.6 运行指令适配器（computer_run_command）。
 *
 * 安全要点：
 * - 使用结构化参数（command + args[] + cwd + timeout_ms + env 白名单）经 child_process
 *   启动，绝不把未校验输入拼接到 shell 字符串（不传 shell，避免注入）。
 * - 超时（默认 30000ms）后回收整个进程树：Windows 用 taskkill /T /F，其余平台 kill 负
 *   PID（进程组）。
 * - 输出截断（默认上限 65536 字节/流），防无界内存。
 * - 敏感输出脱敏：redact_patterns 正则对 stdout/stderr 做替换。
 * - env 仅合并调用方显式提供的键（白名单语义），不暴露宿主完整环境。
 *
 * spawnFn 可注入以便单测（模拟启动失败 / 免真实进程）。
 */
import { spawn, type ChildProcess, type SpawnOptionsWithoutStdio } from 'node:child_process';
import { errorResult, messageOf, okResult, type ToolResult } from './errors';

export interface RunCommandParams {
  command: string;
  args?: string[];
  cwd?: string;
  timeout_ms?: number;
  env?: Record<string, string>;
}

export interface RunCommandOptions {
  spawnFn?: typeof spawn;
  defaultTimeoutMs?: number;
  maxOutputBytes?: number;
  redactPatterns?: RegExp[];
  maxArgs?: number;
}

const DEFAULT_TIMEOUT_MS = 30_000;
const DEFAULT_MAX_OUTPUT_BYTES = 65_536;
const DEFAULT_MAX_ARGS = 64;

/**
 * O-3：默认生效的敏感输出脱敏模式。匹配常见密码/密钥/令牌赋值与
 * Authorization 头，使「敏感输出脱敏」在默认配置（未显式传入
 * redactPatterns）下即成立。可被调用方显式覆盖（含传空数组禁用）。
 */
const DEFAULT_REDACT_PATTERNS: RegExp[] = [
  /(passwd|password|pass|pwd|secret|apikey|api_key|token|access_token|auth_token|private_key)\s*[=:]\s*[^\s,;]+/gi,
  /(?:authorization|proxy-authorization)\s*:\s*Bearer\s+[^\s,;]+/gi,
  /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/gi,
];

export function createRunCommandTool(options: RunCommandOptions = {}): ToolHandler {
  const spawnFn = options.spawnFn ?? spawn;
  const defaultTimeout = options.defaultTimeoutMs ?? DEFAULT_TIMEOUT_MS;
  const maxOutput = options.maxOutputBytes ?? DEFAULT_MAX_OUTPUT_BYTES;
  const redactPatterns = options.redactPatterns ?? DEFAULT_REDACT_PATTERNS;
  const maxArgs = options.maxArgs ?? DEFAULT_MAX_ARGS;

  return async (params: Record<string, unknown>): Promise<ToolResult> => {
    const command = params.command;
    if (typeof command !== 'string' || command.trim().length === 0) {
      return errorResult('INVALID_ARGUMENT', 'command 必填且为非空字符串');
    }

    let args: string[] = [];
    if (params.args !== undefined) {
      if (!Array.isArray(params.args) || params.args.length > maxArgs) {
        return errorResult('INVALID_ARGUMENT', `args 必须为字符串数组（上限 ${maxArgs} 项）`);
      }
      if (params.args.some((a) => typeof a !== 'string')) {
        return errorResult('INVALID_ARGUMENT', 'args 必须为字符串数组');
      }
      args = params.args as string[];
    }

    let cwd: string | undefined;
    if (params.cwd !== undefined) {
      if (typeof params.cwd !== 'string') {
        return errorResult('INVALID_ARGUMENT', 'cwd 必须为字符串');
      }
      cwd = params.cwd;
    }

    let timeout = defaultTimeout;
    if (params.timeout_ms !== undefined) {
      if (typeof params.timeout_ms !== 'number' || !Number.isFinite(params.timeout_ms) || params.timeout_ms < 0) {
        return errorResult('INVALID_ARGUMENT', 'timeout_ms 必须为非负有限数字');
      }
      timeout = params.timeout_ms;
    }

    let env: Record<string, string> | undefined;
    if (params.env !== undefined) {
      if (
        typeof params.env !== 'object' ||
        params.env === null ||
        Array.isArray(params.env) ||
        Object.values(params.env).some((v) => typeof v !== 'string')
      ) {
        return errorResult('INVALID_ARGUMENT', 'env 必须为字符串键值对象');
      }
      env = params.env as Record<string, string>;
    }

    return runProcess(spawnFn, {
      command: command.trim(),
      args,
      cwd,
      timeout,
      env,
      maxOutput,
      redactPatterns,
    });
  };
}

type ToolHandler = (params: Record<string, unknown>) => Promise<ToolResult>;

interface RunProcessArgs {
  command: string;
  args: string[];
  cwd: string | undefined;
  timeout: number;
  env: Record<string, string> | undefined;
  maxOutput: number;
  redactPatterns: RegExp[];
}

function runProcess(
  spawnFn: typeof spawn,
  opts: RunProcessArgs,
): Promise<ToolResult> {
  return new Promise<ToolResult>((resolve) => {
    const spawnOpts: SpawnOptionsWithoutStdio = {
      cwd: opts.cwd,
      windowsHide: true,
      // O-2：仅透传调用方显式声明的 env 白名单键，不展开宿主完整 process.env。
      // 未传入 env 时显式注入空对象，避免 spawn 默认继承宿主完整环境，
      // 与「仅白名单内声明变量才注入」的契约一致——绝不把 process.env 全量拼进子进程。
      env: opts.env ?? {},
    };

    let child: ChildProcess;
    try {
      child = spawnFn(opts.command, opts.args, spawnOpts);
    } catch (err) {
      resolve(errorResult('EXECUTION_FAILED', `进程启动失败: ${messageOf(err)}`));
      return;
    }

    let stdout = '';
    let stderr = '';
    let stdoutTruncated = false;
    let stderrTruncated = false;
    let timedOut = false;
    let settled = false;

    const finish = (result: ToolResult): void => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(result);
    };

    const timer = setTimeout(() => {
      timedOut = true;
      killProcessTree(child);
      const output = {
        timed_out: true,
        exit_code: null as number | null,
        stdout,
        stderr,
        truncated: stdoutTruncated || stderrTruncated,
        error: '执行超时，已回收进程树',
      };
      finish({ ok: false, code: 'TIMEOUT', error: '执行超时，已回收整个进程树', output });
    }, opts.timeout);
    // 避免 timeout=0 时挂起计时器（node 环境 fine）
    if (typeof timer.unref === 'function') timer.unref();

    const append = (buf: Buffer, sink: string, isTruncated: boolean): { sink: string; isTruncated: boolean } => {
      if (sink.length >= opts.maxOutput) {
        return { sink, isTruncated: true };
      }
      const text = buf.toString('utf-8');
      if (sink.length + text.length > opts.maxOutput) {
        return { sink: sink + text.slice(0, opts.maxOutput - sink.length), isTruncated: true };
      }
      return { sink: sink + text, isTruncated };
    };

    child.stdout?.on('data', (chunk: Buffer) => {
      const r = append(chunk, stdout, stdoutTruncated);
      stdout = r.sink;
      stdoutTruncated = r.isTruncated;
    });
    child.stderr?.on('data', (chunk: Buffer) => {
      const r = append(chunk, stderr, stderrTruncated);
      stderr = r.sink;
      stderrTruncated = r.isTruncated;
    });

    child.on('error', (err) => {
      finish(errorResult('EXECUTION_FAILED', `进程执行失败: ${messageOf(err)}`));
    });

    child.on('close', (exitCode, signal) => {
      if (timedOut) return; // 已在超时分支 resolve
      if (signal) {
        finish(errorResult('EXECUTION_FAILED', `进程被信号终止: ${signal}`));
        return;
      }
      const redact = (text: string): string =>
        opts.redactPatterns.reduce((acc, re) => acc.replace(re, '***'), text);
      finish(
        okResult({
          exit_code: exitCode ?? 1,
          stdout: redact(stdout),
          stderr: redact(stderr),
          timed_out: false,
          truncated: stdoutTruncated || stderrTruncated,
          error: null,
        }),
      );
    });
  });
}

function killProcessTree(child: ChildProcess): void {
  if (!child.pid) return;
  if (process.platform === 'win32') {
    // /T 递归终止子进程，/F 强制终止，避免等待
    try {
      spawn('taskkill', ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true });
    } catch {
      /* 尽力而为 */
    }
  } else {
    // 负 PID 表示整个进程组
    try {
      process.kill(-child.pid, 'SIGKILL');
    } catch {
      try {
        child.kill('SIGKILL');
      } catch {
        /* 尽力而为 */
      }
    }
  }
}
