/**
 * labelTimeline 单测：标签时间线核心逻辑。
 *
 * 关键前提：匹配基准 = 原始含标签全文(rawText)，偏移均在 rawText 中计算。
 * 触发点 = 每个 tag 段起点在 rawText 中的字符偏移。
 */
import { describe, it, expect } from 'vitest';

import { createLabelTimeline, type LabelTimeline } from './labelTimeline';

describe('createLabelTimeline', () => {
  it('cleanText 为去掉标签后的纯文本', () => {
    const tl = createLabelTimeline('你好[emotion:happy]朋友[action:wave]！');
    expect(tl.rawText).toBe('你好[emotion:happy]朋友[action:wave]！');
    // "你好" + "朋友" + "！" = 你好朋友！
    expect(tl.cleanText).toBe('你好朋友！');
  });

  it('按 rawText 偏移触发标签（happy=2, wave=19）', () => {
    const tl: LabelTimeline = createLabelTimeline('你好[emotion:happy]朋友[action:wave]！');
    // 手工核对：
    //   你好=2 字符 → happy 起始偏移 2
    //   [emotion:happy]=15 字符 → 朋友 起点=2+15=17
    //   朋友=2 字符 → 17+2=19 → wave 起始偏移 19
    const firstHits = tl.advanceTo(3);
    expect(firstHits).toHaveLength(1);
    expect(firstHits[0]).toMatchObject({ rawCharOffset: 2 });
    expect(firstHits[0].tag).toEqual({ type: 'emotion', emotion: 'happy' });

    const secondHits = tl.advanceTo(20);
    expect(secondHits).toHaveLength(1);
    expect(secondHits[0]).toMatchObject({ rawCharOffset: 19 });
    expect(secondHits[0].tag).toEqual({ type: 'action', action: 'wave' });
  });

  it('advanceTo 对已触发标签去重，重复调用不返回', () => {
    const tl = createLabelTimeline('你好[emotion:happy]朋友[action:wave]！');
    // 第一次 advanceTo(3) 命中 happy
    expect(tl.advanceTo(3)).toHaveLength(1);
    // 重复调用同位置，happy 已触发 → 返回空
    expect(tl.advanceTo(3)).toEqual([]);
    // 推进更远覆盖已触发 happy，仅命中未触发的 wave
    const hits = tl.advanceTo(20);
    expect(hits).toHaveLength(1);
    expect(hits[0].tag).toEqual({ type: 'action', action: 'wave' });
  });

  it('标签开头无文本时触发点偏移为 0', () => {
    const tl = createLabelTimeline('[emotion:happy]你好');
    const hits = tl.advanceTo(1);
    expect(hits).toHaveLength(1);
    expect(hits[0]).toMatchObject({ rawCharOffset: 0 });
    expect(hits[0].tag).toEqual({ type: 'emotion', emotion: 'happy' });
  });

  it('getRemaining 返回仍未触发的标签', () => {
    const tl = createLabelTimeline('你好[emotion:happy]朋友[action:wave]！');
    expect(tl.getRemaining()).toHaveLength(2);

    tl.advanceTo(3); // 触发 happy
    const remaining = tl.getRemaining();
    expect(remaining).toHaveLength(1);
    expect(remaining[0]).toEqual({ type: 'action', action: 'wave' });
  });

  it('reset 清空触发集后重新可触发全部标签', () => {
    const tl = createLabelTimeline('你好[emotion:happy]朋友[action:wave]！');
    tl.advanceTo(20); // 触发全部
    expect(tl.getRemaining()).toHaveLength(0);

    tl.reset();
    expect(tl.getRemaining()).toHaveLength(2);
    expect(tl.currOffset).toBe(0);
    // 重置后可再次触发
    const hits = tl.advanceTo(3);
    expect(hits).toHaveLength(1);
    expect(hits[0].tag).toEqual({ type: 'emotion', emotion: 'happy' });
  });

  it('相邻标签顺序与偏移正确', () => {
    const tl = createLabelTimeline('[emotion:happy][action:wave]你好');
    // happy 起始偏移 0；[emotion:happy]=15 → wave 起始偏移 15
    const all = tl.advanceTo(100);
    expect(all).toHaveLength(2);
    expect(all[0].rawCharOffset).toBe(0);
    expect(all[1].rawCharOffset).toBe(15);
    expect(all[0].tag).toEqual({ type: 'emotion', emotion: 'happy' });
    expect(all[1].tag).toEqual({ type: 'action', action: 'wave' });
  });

  it('非法标签按原文保留为文本，不产生触发点', () => {
    const tl = createLabelTimeline('你好[emotion:rage]朋友');
    // rage 不受支持 → 回退为纯文本，无 tag 触发点
    expect(tl.advanceTo(100)).toEqual([]);
    expect(tl.cleanText).toBe('你好[emotion:rage]朋友');
  });
});