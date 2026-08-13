// @vitest-environment node
/**
 * SubTask 2.6 运行指令适配器单测。
 * 覆盖：成功、超时回收、参数错误、启动失败（注入 spawnFn）、脱敏、截断。
 * 使用真实 child_process 或 mock 替身，绝不拼接 shell 字符串。
 */
import { describe, it, expect } from 'vitest';
import { EventEmitter } from 'node:events';
import { createRunCommandTool } from './runCommand';

describe('computer_run_command', () => {
  it('成功执行并返回 exit_code/stdout', async () => {
    const tool = createRunCommandTool();
    const res = await tool({ command: 'node', args: ['-e', 'process.stdout.write("hi")'] });
    expect(res.ok).toBe(true);
    expect(res.output).toMatchObject({ exit_code: 0, stdout: 'hi', timed_out: false, truncated: false, error: null });
  });

  it('结构化解耦：command+args 数组执行，不拼 shell', async () => {
    const tool = createRunCommandTool();
    // 若把 args 拼到 shell，这一串会被解释为多命令；数组方式则作为字面量参数
    const res = await tool({
      command: 'node',
      args: ['-e', 'process.stdout.write(String(1 + 1))'],
    });
    expect(res.output).toMatchObject({ stdout: '2', exit_code: 0 });
  });

  it('缺 command → INVALID_ARGUMENT', async () => {
    const tool = createRunCommandTool();
    expect((await tool({})).code).toBe('INVALID_ARGUMENT');
    expect((await tool({ command: '   ' })).code).toBe('INVALID_ARGUMENT');
  });

  it('args 非字符串数组 → INVALID_ARGUMENT', async () => {
    const tool = createRunCommandTool();
    expect((await tool({ command: 'node', args: [1, 2] })).code).toBe('INVALID_ARGUMENT');
    expect((await tool({ command: 'node', args: 'x' })).code).toBe('INVALID_ARGUMENT');
  });

  it('timeout_ms 非法 → INVALID_ARGUMENT', async () => {
    const tool = createRunCommandTool();
    expect((await tool({ command: 'node', timeout_ms: -1 })).code).toBe('INVALID_ARGUMENT');
    expect((await tool({ command: 'node', timeout_ms: 'fast' })).code).toBe('INVALID_ARGUMENT');
  });

  it('超时后返回 TIMEOUT 并回收进程树', async () => {
    const tool = createRunCommandTool({ defaultTimeoutMs: 50 });
    const res = await tool({ command: 'node', args: ['-e', 'setTimeout(()=>{},10000)'] });
    expect(res.ok).toBe(false);
    expect(res.code).toBe('TIMEOUT');
    expect(res.output).toMatchObject({ timed_out: true });
  });

  it('敏感输出按 redact_patterns 脱敏', async () => {
    const tool = createRunCommandTool({ redactPatterns: [/apiKey=[A-Za-z0-9]+/g] });
    const res = await tool({
      command: 'node',
      args: ['-e', 'process.stdout.write("apiKey=SECRET123 hello")'],
    });
    const out = res.output as { stdout: string };
    // redact_patterns 整体替换命中段（含键名），敏感值不泄漏
    expect(out.stdout).toBe('*** hello');
    expect(out.stdout).not.toContain('SECRET123');
  });

  it('O-3：默认配置下敏感输出脱敏生效（密码/令牌/Authorization 头）', async () => {
    const tool = createRunCommandTool();
    const res = await tool({
      command: 'node',
      args: ['-e', 'process.stdout.write("token=SECRET123 and Authorization: Bearer abcdef")'],
    });
    const out = res.output as { stdout: string };
    // 默认内置脱敏模式命中令牌赋值与 Authorization 头
    expect(out.stdout).not.toContain('SECRET123');
    expect(out.stdout).not.toContain('Bearer abcdef');
    expect(out.stdout).toContain('***');
  });

  it('O-2：env 仅透传白名单键，不展开 process.env', async () => {
    let captured: { env?: Record<string, string> } | undefined;
    const spawnFn = ((_cmd: string, _args: string[], opts: { env?: Record<string, string> }) => {
      captured = opts;
      const child = new EventEmitter() as EventEmitter & { pid?: number; kill?: () => void };
      (child as { pid?: number }).pid = 999;
      (child as { kill?: () => void }).kill = () => undefined;
      setImmediate(() => child.emit('close', 0, null));
      return child;
    }) as never;

    const tool = createRunCommandTool({ spawnFn });
    await tool({ command: 'echo', env: { FOO: 'bar' } });

    // 仅注入显式声明的白名单键，绝不展开宿主完整环境
    expect(captured!.env).toEqual({ FOO: 'bar' });
    expect(captured!.env).not.toHaveProperty('PATH');
    expect(captured!.env).not.toHaveProperty('Path');
  });

  it('O-2：未传入 env 时不注入任何额外变量', async () => {
    let captured: { env?: Record<string, string> } | undefined;
    const spawnFn = ((_cmd: string, _args: string[], opts: { env?: Record<string, string> }) => {
      captured = opts;
      const child = new EventEmitter() as EventEmitter & { pid?: number; kill?: () => void };
      (child as { pid?: number }).pid = 999;
      (child as { kill?: () => void }).kill = () => undefined;
      setImmediate(() => child.emit('close', 0, null));
      return child;
    }) as never;

    const tool = createRunCommandTool({ spawnFn });
    await tool({ command: 'echo' });

    // 未显式声明 env 时注入空环境（不继承宿主 process.env，不展开）
    expect(captured!.env).toEqual({});
  });

  it('输出超过上限时截断并标记 truncated', async () => {
    const tool = createRunCommandTool({ maxOutputBytes: 10 });
    const res = await tool({
      command: 'node',
      args: ['-e', 'process.stdout.write("x".repeat(100))'],
    });
    expect(res.ok).toBe(true);
    const out = res.output as { truncated: boolean; stdout: string };
    expect(out.truncated).toBe(true);
    expect(out.stdout.length).toBeLessThanOrEqual(10);
  });

  it('spawn 抛错（启动失败）→ EXECUTION_FAILED', async () => {
    const tool = createRunCommandTool({
      spawnFn: (() => {
        throw new Error('ENOENT');
      }) as never,
    });
    const res = await tool({ command: 'no-such-bin' });
    expect(res.code).toBe('EXECUTION_FAILED');
  });

  it('spawn 后触发 error 事件 → EXECUTION_FAILED', async () => {
    let child: EventEmitter;
    const tool = createRunCommandTool({
      spawnFn: (() => {
        const c = new EventEmitter() as EventEmitter & { pid?: number; kill?: () => void };
        (c as { pid?: number }).pid = 123;
        (c as { kill?: () => void }).kill = () => undefined;
        child = c;
        return c;
      }) as never,
    });
    const p = tool({ command: 'node' });
    setImmediate(() => {
      child!.emit('error', new Error('spawn failed'));
    });
    const res = await p;
    expect(res.code).toBe('EXECUTION_FAILED');
  });
});
