/**
 * CXFC relay（前端转接）WS 推送处理单测（P2-T2）。
 *
 * 覆盖：
 * - handleCxfcRelayCall 成功回报（success=true + result）
 * - 执行失败 / 未识别工具（executor 返回 ok=false）→ success=false + error 回报
 * - executor 抛异常 → success=false + 错误信息回报
 * - 缺 plugin_id / request_id / tool → 不回报
 * - 回报调用本身异常 → 不向调用方抛错
 * - createElectronComputerControlExecutor：有 electronAPI 桥 → 调用 IPC；无桥 → 返回不可执行错误
 *
 * handleCxfcRelayCall 为依赖注入设计，测试不依赖真实 IPC / HTTP。
 */
import { afterEach, describe, it, expect, vi, type Mock } from 'vitest';

import {
  createElectronComputerControlExecutor,
  handleCxfcRelayCall,
  type CxfcRelayCallMessage,
  type RelayResultPayload,
  type RelayResultReporter,
  type RelayToolExecutor,
} from './cxfcRelay';

function makeReport(): Mock<RelayResultReporter> {
  return vi.fn<RelayResultReporter>(async () => {});
}

async function run(
  message: CxfcRelayCallMessage,
  executor: RelayToolExecutor,
  report: Mock<RelayResultReporter> = makeReport(),
) {
  await handleCxfcRelayCall(message, { executor, report });
  return report;
}

describe('handleCxfcRelayCall', () => {
  it('执行成功 → 回报 success=true + result', async () => {
    const report = await run(
      { type: 'cxfc_relay_call', plugin_id: 'relay_pc', request_id: 'r1', tool: 'computer_run_command', arguments: { command: 'echo hi' } },
      async () => ({ ok: true, output: { x: 1 } }),
    );
    expect(report).toHaveBeenCalledTimes(1);
    const payload = report.mock.calls[0][0] as RelayResultPayload;
    expect(payload).toMatchObject({
      plugin_id: 'relay_pc',
      request_id: 'r1',
      success: true,
      result: { x: 1 },
    });
  });

  it('执行失败 → 回报 success=false + error', async () => {
    const report = await run(
      { type: 'cxfc_relay_call', plugin_id: 'relay_pc', request_id: 'r2', tool: 'computer_keyboard_control', arguments: {} },
      async () => ({ ok: false, code: 'EXECUTION_FAILED', error: 'boom' }),
    );
    const payload = report.mock.calls[0][0] as RelayResultPayload;
    expect(payload.success).toBe(false);
    expect(payload.error).toBe('boom');
    expect(payload.result).toBeUndefined();
  });

  it('未识别工具（executor 返回 INVALID_ARGUMENT）→ 回报 success=false', async () => {
    const report = await run(
      { type: 'cxfc_relay_call', plugin_id: 'relay_pc', request_id: 'r3', tool: 'not_a_tool', arguments: {} },
      async () => ({ ok: false, code: 'INVALID_ARGUMENT', error: '未知工具' }),
    );
    const payload = report.mock.calls[0][0] as RelayResultPayload;
    expect(payload.success).toBe(false);
    expect(payload.error).toBe('未知工具');
  });

  it('executor 抛异常 → 回报 success=false + 错误信息', async () => {
    const report = await run(
      { type: 'cxfc_relay_call', plugin_id: 'relay_pc', request_id: 'r4', tool: 'computer_screen_control', arguments: {} },
      async () => {
        throw new Error('oops');
      },
    );
    const payload = report.mock.calls[0][0] as RelayResultPayload;
    expect(payload.success).toBe(false);
    expect(payload.error).toBe('oops');
  });

  it('缺 request_id → 不回报', async () => {
    const report = await run(
      { type: 'cxfc_relay_call', plugin_id: 'relay_pc', tool: 'computer_run_command', arguments: {} },
      async () => ({ ok: true, output: 1 }),
    );
    expect(report).not.toHaveBeenCalled();
  });

  it('缺 plugin_id → 不回报', async () => {
    const report = await run(
      { type: 'cxfc_relay_call', request_id: 'r5', tool: 'computer_run_command', arguments: {} },
      async () => ({ ok: true }),
    );
    expect(report).not.toHaveBeenCalled();
  });

  it('缺 tool → 不回报', async () => {
    const report = await run(
      { type: 'cxfc_relay_call', plugin_id: 'relay_pc', request_id: 'r6', arguments: {} },
      async () => ({ ok: true }),
    );
    expect(report).not.toHaveBeenCalled();
  });

  it('回报调用异常 → 不向调用方抛错', async () => {
    const report: Mock<RelayResultReporter> = vi.fn<RelayResultReporter>(async () => {
      throw new Error('report down');
    });
    await expect(
      handleCxfcRelayCall(
        { type: 'cxfc_relay_call', plugin_id: 'relay_pc', request_id: 'r7', tool: 'computer_run_command', arguments: {} },
        { executor: async () => ({ ok: true, output: 1 }), report },
      ),
    ).resolves.toBeUndefined();
  });

  // 多窗去重：后端向每个窗口广播同一条 relay call，同窗口内已见 request_id 不再执行
  it('同 request_id 二次调用 → 不执行 executor 不回报', async () => {
    const executor = vi.fn<RelayToolExecutor>(async () => ({ ok: true, output: 1 }));
    const report = makeReport();
    const message: CxfcRelayCallMessage = {
      type: 'cxfc_relay_call',
      plugin_id: 'relay_pc',
      request_id: 'dedup-dup-1',
      tool: 'computer_run_command',
      arguments: {},
    };
    await handleCxfcRelayCall(message, { executor, report });
    await handleCxfcRelayCall(message, { executor, report });
    expect(executor).toHaveBeenCalledTimes(1);
    expect(report).toHaveBeenCalledTimes(1);
  });

  it('不同 request_id → 各自正常执行', async () => {
    const executor = vi.fn<RelayToolExecutor>(async () => ({ ok: true, output: 1 }));
    const report = makeReport();
    await handleCxfcRelayCall(
      { type: 'cxfc_relay_call', plugin_id: 'relay_pc', request_id: 'dedup-a-1', tool: 'computer_run_command', arguments: {} },
      { executor, report },
    );
    await handleCxfcRelayCall(
      { type: 'cxfc_relay_call', plugin_id: 'relay_pc', request_id: 'dedup-a-2', tool: 'computer_run_command', arguments: {} },
      { executor, report },
    );
    expect(executor).toHaveBeenCalledTimes(2);
    expect(report).toHaveBeenCalledTimes(2);
  });
});

describe('createElectronComputerControlExecutor', () => {
  const originalElectronApi = window.electronAPI;

  afterEach(() => {
    if (originalElectronApi === undefined) {
      delete window.electronAPI;
    } else {
      window.electronAPI = originalElectronApi;
    }
  });

  it('有 electronAPI 桥 → 调用 callComputerControlTool(tool, args)', async () => {
    const call = vi.fn(async () => ({ ok: true, output: 'hi' }));
    window.electronAPI = { callComputerControlTool: call } as unknown as NonNullable<Window['electronAPI']>;
    const executor = createElectronComputerControlExecutor();
    const result = await executor('computer_run_command', { command: 'echo hi' });
    expect(call).toHaveBeenCalledWith('computer_run_command', { command: 'echo hi' });
    expect(result).toEqual({ ok: true, output: 'hi' });
  });

  it('无 electronAPI 桥 → 返回不可执行错误（浏览器模式）', async () => {
    delete window.electronAPI;
    const executor = createElectronComputerControlExecutor();
    const result = await executor('computer_run_command', { command: 'echo hi' });
    expect(result.ok).toBe(false);
    expect(result.code).toBe('SYSTEM_ERROR');
  });

  it('IPC 抛异常 → 返回 ok=false 不向外抛', async () => {
    window.electronAPI = {
      callComputerControlTool: async () => {
        throw new Error('ipc fail');
      },
    } as unknown as NonNullable<Window['electronAPI']>;
    const executor = createElectronComputerControlExecutor();
    const result = await executor('computer_run_command', { command: 'echo hi' });
    expect(result.ok).toBe(false);
    expect(result.error).toContain('ipc fail');
  });
});
