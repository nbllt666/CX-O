import { describe, expect, it } from 'vitest';
import {
  applyStreamEvent,
  createAssistantMessage,
  createUserMessage,
  finalizeStreamMessage,
  normalizeStreamChunk,
} from './chatStream';
import type { ChatMsg } from './chatStream';

/** 构造 [user, assistant(占位)] 基础列表 */
function baseMessages(): ChatMsg[] {
  return [createUserMessage('u-1', '你好'), createAssistantMessage('a-1')];
}

describe('chatStream 流式事件归约', () => {
  it('content 事件逐块追加到末条 assistant 消息', () => {
    let msgs = baseMessages();
    msgs = applyStreamEvent(msgs, 'a-1', { type: 'content', content: '你' });
    msgs = applyStreamEvent(msgs, 'a-1', { type: 'content', content: '好呀' });
    expect(msgs[1].content).toBe('你好呀');
    expect(msgs[0].content).toBe('你好');
  });

  it('assistantId 不匹配时原样返回（防串台）', () => {
    const msgs = baseMessages();
    const next = applyStreamEvent(msgs, 'a-x', { type: 'content', content: 'abc' });
    expect(next).toBe(msgs);
    expect(next[1].content).toBe('');
  });

  it('thinking 事件累积思考过程', () => {
    let msgs = baseMessages();
    msgs = applyStreamEvent(msgs, 'a-1', { type: 'thinking', content: '先想' });
    msgs = applyStreamEvent(msgs, 'a-1', { type: 'thinking', content: '再想' });
    expect(msgs[1].thinking).toBe('先想再想');
  });

  it('tool_call → tool_start → tool_result 驱动工具状态机', () => {
    let msgs = baseMessages();
    msgs = applyStreamEvent(msgs, 'a-1', {
      type: 'tool_call',
      tool_call: { id: 't1', function: { name: 'search' } },
    });
    expect(msgs[1].toolCalls).toHaveLength(1);
    expect(msgs[1].toolCalls?.[0]).toMatchObject({ name: 'search', status: 'pending' });

    msgs = applyStreamEvent(msgs, 'a-1', { type: 'tool_start', tool_name: 'search' });
    expect(msgs[1].toolCalls?.[0].status).toBe('executing');

    msgs = applyStreamEvent(msgs, 'a-1', { type: 'tool_result', tool_name: 'search', result: {} });
    expect(msgs[1].toolCalls?.[0].status).toBe('completed');
  });

  it('tool_start 仅推进 pending 态（completed 不回退）', () => {
    let msgs = baseMessages();
    msgs = applyStreamEvent(msgs, 'a-1', { type: 'tool_call', tool_call: { name: 'search' } });
    msgs = applyStreamEvent(msgs, 'a-1', { type: 'tool_result', tool_name: 'search' });
    msgs = applyStreamEvent(msgs, 'a-1', { type: 'tool_start', tool_name: 'search' });
    expect(msgs[1].toolCalls?.[0].status).toBe('completed');
  });

  it('error 事件覆盖正文并标记错误态', () => {
    let msgs = baseMessages();
    msgs = applyStreamEvent(msgs, 'a-1', { type: 'error', error: '出错了：x' });
    expect(msgs[1].isError).toBe(true);
    expect(msgs[1].content).toBe('出错了：x');
  });

  it('未知事件类型不动消息体', () => {
    const msgs = baseMessages();
    expect(applyStreamEvent(msgs, 'a-1', { type: 'pong' })).toBe(msgs);
  });

  it('finalize：正文为空时以兜底文案填充，非空时保留', () => {
    let msgs = baseMessages();
    msgs = finalizeStreamMessage(msgs, 'a-1', '响应已完成');
    expect(msgs[1].content).toBe('响应已完成');

    let msgs2 = baseMessages();
    msgs2 = applyStreamEvent(msgs2, 'a-1', { type: 'content', content: '正文' });
    msgs2 = finalizeStreamMessage(msgs2, 'a-1', '响应已完成');
    expect(msgs2[1].content).toBe('正文');
  });

  it('normalizeStreamChunk 归一化 SSE 帧（含对象形态 error）', () => {
    const evt = normalizeStreamChunk({
      type: 'error',
      error: { code: 'E', message: 'boom' },
    });
    expect(evt).toMatchObject({ type: 'error', error: 'boom' });

    const content = normalizeStreamChunk({ type: 'content', content: 'hi' });
    expect(content).toMatchObject({ type: 'content', content: 'hi' });

    const malformed = normalizeStreamChunk({ content: 42 });
    expect(malformed.type).toBe('');
    expect(malformed.content).toBeUndefined();
  });
});
