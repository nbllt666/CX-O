import { describe, expect, it } from 'vitest';

import enUS from './locales/en-US.json';
import zhCN from './locales/zh-CN.json';

/**
 * i18n 语言一致性守卫（GN-004 第八轮 O-19 / O-20）。
 *
 * 背景：2026-10-01 发现 `management.autonomy.subtitle` 在 zh-CN 含"焦点"而 en-US 缺失
 * （语言不对称），且该文案**无任何自动化断言覆盖**，只能靠人工 checklist 校验；
 * 同期还清理了若干把已删除的"预算（成本告警）"能力描述为现存的词条。
 * 本文件把"语言不对称"与"已删能力词条回流"两类问题固化为可执行断言，防止静默回归。
 */

/** 已知的语言不对称例外：**当前为空**（原有的 en 独有孤儿键 `management.audioPanel.clientsOnline`
 *  已于 2026-10-02 删除——该键在 src 内零引用，补 zh 译文等于为不可见文案新增内容；
 *  删除后两语言完全对称）。若未来确实需要该键，应同时写入两份 locale。 */
const KNOWN_EN_ONLY_KEYS: string[] = [];

/** 把嵌套词条扁平化为 "a.b.c" 形式的键路径（对象视为分支，其余视为叶子）。 */
function keyPaths(node: unknown, prefix = ''): string[] {
  if (node === null || typeof node !== 'object') return prefix ? [prefix] : [];
  const paths: string[] = [];
  for (const [key, value] of Object.entries(node as Record<string, unknown>)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (value !== null && typeof value === 'object') {
      paths.push(...keyPaths(value, path));
    } else {
      paths.push(path);
    }
  }
  return paths;
}

describe('i18n 语言一致性守卫', () => {
  it('zh-CN 与 en-US 的键结构对称（已知例外显式登记）', () => {
    const zh = keyPaths(zhCN).sort();
    const en = keyPaths(enUS).sort();
    expect(en.filter((key) => !zh.includes(key))).toEqual(KNOWN_EN_ONLY_KEYS);
    expect(zh.filter((key) => !en.includes(key))).toEqual([]);
  });

  it('autonomy 副标题在两语言均声明「焦点」维度（GN-004 O-19 防回归）', () => {
    expect(zhCN.management.autonomy.subtitle).toContain('焦点');
    expect(enUS.management.autonomy.subtitle).toMatch(/focus/i);
  });

  it('词条中不含已删除的「预算 / 成本告警」能力残留', () => {
    expect(JSON.stringify(zhCN)).not.toMatch(/预算|超支/);
    expect(JSON.stringify(enUS)).not.toMatch(/budget|overspend/i);
  });
});
