/**
 * 标签时间线核心模块：声画同步 spec Task 1。
 *
 * 将解析后的头像标签按原始全文(rawText)中的字符偏移组织成时间线，
 * 供音频播放/字幕推进驱动标签触发。匹配基准 = 原始含标签全文(rawText)，
 * 而非 cleanText。cleanText 仅用于显示。
 *
 * 设计说明：
 * - 触发点偏移直接取 scanAvatarTagMatches 给出的「标签起点在 rawText 中的
 *   真实字符位置」：已被容错分级剥离的非法标签不产生命中点，也不会使
 *   后续标签的偏移发生位移。
 * - 由于每个匹配独立对应一个标签，多 label 排列时触发点互不干扰。
 */
import { parseAvatarTags, scanAvatarTagMatches } from './tagParser';
import type { AvatarTag } from './tagParser';

/** 一次标签命中：标签 + 其在原始全文中的起始字符偏移 */
export interface LabelHit {
  tag: AvatarTag;
  rawCharOffset: number;
}

/** 标签时间线：按 rawText 偏移组织全部标签触发点 */
export interface LabelTimeline {
  rawText: string;
  cleanText: string;
  /** 推进到指定 rawText 字符位置，返回所有尚未触发命中的标签（原顺序） */
  advanceTo(rawCharPos: number): LabelHit[];
  /** 返回仍未触发的标签列表 */
  getRemaining(): AvatarTag[];
  /** 当前已推进的字符位置 */
  currOffset: number;
  /** 重置：清空触发集与游标 */
  reset(): void;
}

export function createLabelTimeline(rawText: string): LabelTimeline {
  const { cleanText } = parseAvatarTags(rawText);

  // 按 rawText 真实匹配起点预生成有序命中列表（dropped/unknown 标签不产生命中点）
  const hits: LabelHit[] = [];
  for (const m of scanAvatarTagMatches(rawText)) {
    if (m.tag) {
      hits.push({ tag: m.tag, rawCharOffset: m.start });
    }
  }

  // 已触发标签去重集合（按标签对象引用去重）
  const triggered = new Set<AvatarTag>();
  let currOffset = 0;

  return {
    rawText,
    cleanText,
    advanceTo(rawCharPos: number): LabelHit[] {
      currOffset = rawCharPos;
      const result: LabelHit[] = [];
      for (const hit of hits) {
        if (hit.rawCharOffset < rawCharPos && !triggered.has(hit.tag)) {
          result.push(hit);
          triggered.add(hit.tag);
        }
      }
      return result;
    },
    getRemaining(): AvatarTag[] {
      return hits.filter((h) => !triggered.has(h.tag)).map((h) => h.tag);
    },
    get currOffset() {
      return currOffset;
    },
    set currOffset(value: number) {
      currOffset = value;
    },
    reset(): void {
      triggered.clear();
      currOffset = 0;
    },
  };
}