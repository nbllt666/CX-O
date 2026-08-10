import { describe, expect, it } from 'vitest';

import { DanmakuSpeechQueue } from './danmakuSpeechQueue';

describe('DanmakuSpeechQueue', () => {
  it('FIFO 顺序出队', () => {
    const q = new DanmakuSpeechQueue(3);
    q.enqueue({ id: '1', text: 'a' });
    q.enqueue({ id: '2', text: 'b' });
    expect(q.dequeue()?.id).toBe('1');
    expect(q.dequeue()?.id).toBe('2');
    expect(q.dequeue()).toBeUndefined();
  });

  it('超容量丢弃最旧条目并返回它', () => {
    const q = new DanmakuSpeechQueue(2);
    expect(q.enqueue({ id: '1', text: 'a' })).toBeNull();
    expect(q.enqueue({ id: '2', text: 'b' })).toBeNull();
    const dropped = q.enqueue({ id: '3', text: 'c' });
    expect(dropped?.id).toBe('1');
    expect(q.size).toBe(2);
    expect(q.dequeue()?.id).toBe('2');
    expect(q.dequeue()?.id).toBe('3');
  });

  it('clear 清空待播', () => {
    const q = new DanmakuSpeechQueue(3);
    q.enqueue({ id: '1', text: 'a' });
    q.enqueue({ id: '2', text: 'b' });
    q.clear();
    expect(q.size).toBe(0);
    expect(q.dequeue()).toBeUndefined();
  });

  it('容量下限为 1', () => {
    const q = new DanmakuSpeechQueue(0);
    q.enqueue({ id: '1', text: 'a' });
    const dropped = q.enqueue({ id: '2', text: 'b' });
    expect(dropped?.id).toBe('1');
    expect(q.size).toBe(1);
  });
});
