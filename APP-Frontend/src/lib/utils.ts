import { clsx } from 'clsx';
import type { ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

/** 合并 className（clsx 条件拼接 + tailwind-merge 冲突消解） */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
