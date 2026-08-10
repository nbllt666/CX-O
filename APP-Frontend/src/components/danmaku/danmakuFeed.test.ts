/**
 * 弹幕流纯逻辑单测：append/buffer/flush/clear 状态机与 WS 数据规整。
 * 覆盖 SubTask 5.1 的核心口径——暂停滚动时新弹幕缓存、恢复后补齐、容量截断。
 */
import { describe, it, expect } from 'vitest';
import {
  danmakuFeedReducer,
  initialDanmakuFeedState,
  toDanmakuItem,
  MAX_ITEMS,
  MAX_PENDING,
} from './danmakuFeed';
import type { DanmakuItem, DanmakuFeedState } from './danmakuFeed';

function makeItem(n: number): DanmakuItem {
  return { id: `id-${n}`, username: `user-${n}`, content: `content-${n}`, ts: n };
}

function makeState(items: number, pending: number): DanmakuFeedState {
  return {
    items: Array.from({ length: items }, (_, i) => makeItem(i)),
    pending: Array.from({ length: pending }, (_, i) => makeItem(10000 + i)),
  };
}

describe('danmakuFeedReducer', () => {
  it('append 追加到渲染队列尾部', () => {
    const s0 = makeState(1, 0);
    const s1 = danmakuFeedReducer(s0, { type: 'append', item: makeItem(99) });
    expect(s1.items.map((i) => i.id)).toEqual(['id-0', 'id-99']);
    expect(s1.pending).toEqual([]);
  });

  it('append 超出 MAX_ITEMS 时丢弃最旧', () => {
    const s0 = makeState(MAX_ITEMS, 0);
    const s1 = danmakuFeedReducer(s0, { type: 'append', item: makeItem(99999) });
    expect(s1.items).toHaveLength(MAX_ITEMS);
    expect(s1.items[0].id).toBe('id-1');
    expect(s1.items[MAX_ITEMS - 1].id).toBe('id-99999');
  });

  it('buffer 暂停期弹幕进入缓存队列，不影响渲染队列', () => {
    const s0 = makeState(2, 0);
    const s1 = danmakuFeedReducer(s0, { type: 'buffer', item: makeItem(5) });
    expect(s1.items).toHaveLength(2);
    expect(s1.pending.map((i) => i.id)).toEqual(['id-5']);
  });

  it('buffer 超出 MAX_PENDING 时丢弃最旧缓存', () => {
    const s0 = makeState(0, MAX_PENDING);
    const s1 = danmakuFeedReducer(s0, { type: 'buffer', item: makeItem(99999) });
    expect(s1.pending).toHaveLength(MAX_PENDING);
    expect(s1.pending[MAX_PENDING - 1].id).toBe('id-99999');
  });

  it('flush 将缓存按序并入渲染队列并清空缓存', () => {
    const s0 = makeState(2, 3);
    const s1 = danmakuFeedReducer(s0, { type: 'flush' });
    expect(s1.items.map((i) => i.id)).toEqual([
      'id-0',
      'id-1',
      'id-10000',
      'id-10001',
      'id-10002',
    ]);
    expect(s1.pending).toEqual([]);
  });

  it('flush 后总量超 MAX_ITEMS 时整体截断保最新', () => {
    const s0 = makeState(MAX_ITEMS, 10);
    const s1 = danmakuFeedReducer(s0, { type: 'flush' });
    expect(s1.items).toHaveLength(MAX_ITEMS);
    // 缓存全部保留在尾部，最旧的 10 条渲染弹幕被挤出
    expect(s1.items[MAX_ITEMS - 1].id).toBe('id-10009');
    expect(s1.items[0].id).toBe('id-10');
  });

  it('flush 空缓存时返回原状态引用（不触发多余渲染）', () => {
    const s0 = makeState(3, 0);
    expect(danmakuFeedReducer(s0, { type: 'flush' })).toBe(s0);
  });

  it('clear 同时清空渲染队列与缓存队列', () => {
    const s0 = makeState(5, 5);
    expect(danmakuFeedReducer(s0, { type: 'clear' })).toEqual(initialDanmakuFeedState);
  });
});

describe('toDanmakuItem', () => {
  it('规整正常弹幕', () => {
    const item = toDanmakuItem(
      { id: 'a1', content: '  hello  ', username: '  小明 ', color: '#fff' },
      1000,
      0,
    );
    expect(item).toEqual({ id: 'a1', username: '小明', content: 'hello', color: '#fff', ts: 1000 });
  });

  it('空内容与纯空白内容被丢弃', () => {
    expect(toDanmakuItem({ content: '' }, 1000, 0)).toBeNull();
    expect(toDanmakuItem({ content: '   ' }, 1000, 1)).toBeNull();
    expect(toDanmakuItem({}, 1000, 2)).toBeNull();
  });

  it('id 缺省时以时间戳+序号兜底且序号防同毫秒碰撞', () => {
    const a = toDanmakuItem({ content: 'x' }, 1000, 0);
    const b = toDanmakuItem({ content: 'y' }, 1000, 1);
    expect(a?.id).toBe('dm-1000-0');
    expect(b?.id).toBe('dm-1000-1');
    expect(a?.id).not.toBe(b?.id);
  });

  it('username 缺省/空白归一为空串（展示层负责匿名兜底）', () => {
    expect(toDanmakuItem({ content: 'x' }, 1000, 0)?.username).toBe('');
    expect(toDanmakuItem({ content: 'x', username: '  ' }, 1000, 1)?.username).toBe('');
  });

  it('color 空串归一为 undefined', () => {
    expect(toDanmakuItem({ content: 'x', color: '' }, 1000, 0)?.color).toBeUndefined();
  });
});
