import { clsx } from 'clsx';
import type { ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

/** 合并 className（clsx 条件拼接 + tailwind-merge 冲突消解） */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/** 进程内单调递增计数：为同毫秒内的多次调用消解 id 冲突 */
let monotonicIdCounter = 0;

/**
 * 单调消息 id 助手：`${prefix}${Date.now()}-${counter++}`。
 *
 * 裸 `Date.now()` 拼接在同毫秒内多次调用（如同一次批处理连落两条气泡）时会产生
 * 重复 id，导致按 id 增删/就地更新的消息列表错乱；计数器后缀保证进程内永不重复。
 */
export function nextMessageId(prefix: string): string {
  monotonicIdCounter += 1;
  return `${prefix}${Date.now()}-${monotonicIdCounter}`;
}
