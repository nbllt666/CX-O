import { describe, it, expect } from 'vitest';
import {
  MANAGEMENT_ROUTES,
  RESERVED_TOP_LEVEL_PATHS,
  findRouteByPathname,
  validateRouteRegistry,
} from './routes';
import type { ManagementRouteEntry } from './routes';

/**
 * 路由登记表契约测试（Task 6.1）：
 * - 冻结登记表自身必须通过结构校验
 * - 校验器能识别各类违规（重复 path / 非法命名 / 占用顶层路由 / 错误命名空间 / 缺字段）
 * - findRouteByPathname 反查语义
 */
describe('管理界面路由登记表契约', () => {
  it('冻结登记表通过结构校验（零违规）', () => {
    expect(validateRouteRegistry()).toEqual([]);
  });

  it('第一批页面登记完整：仪表盘/对话/记忆/归档/设置（前 5 条保持冻结顺序）', () => {
    // 第一批顺序不可变；第二批（Task 7）只允许末尾追加
    expect(MANAGEMENT_ROUTES.map((r) => r.path).slice(0, 5)).toEqual([
      '',
      'chat',
      'memories',
      'archive',
      'settings',
    ]);
  });

  it('第二批页面末尾追加：代理/ACP（7.1）+ 插件/工具（7.2）+ 记忆代理/向量（7.3）', () => {
    const paths = MANAGEMENT_ROUTES.map((r) => r.path);
    expect(paths[5]).toBe('agents');
    expect(paths[6]).toBe('acp');
    expect(paths[7]).toBe('plugins');
    expect(paths[8]).toBe('tools');
    expect(paths[9]).toBe('memory-agent');
    expect(paths[10]).toBe('vector');
    expect(findRouteByPathname('/agents')?.titleKey).toBe('management.nav.agents');
    expect(findRouteByPathname('/acp')?.titleKey).toBe('management.nav.acp');
    expect(findRouteByPathname('/plugins')?.titleKey).toBe('management.nav.plugins');
    expect(findRouteByPathname('/tools')?.titleKey).toBe('management.nav.tools');
    expect(findRouteByPathname('/memory-agent')?.titleKey).toBe('management.nav.memoryAgent');
    expect(findRouteByPathname('/vector')?.titleKey).toBe('management.nav.vector');
  });

  it('7.4 音频三页 + Task 8 直播六页末尾追加，titleKey 均位于 management.nav.*', () => {
    const paths = MANAGEMENT_ROUTES.map((r) => r.path);
    // 7.4：音频面板/音频测试/音频工作站（index 11-13）
    expect(paths[11]).toBe('audio-panel');
    expect(paths[12]).toBe('audio-test');
    expect(paths[13]).toBe('audio-workstation');
    // Task 8：直播控制台/直播分屏/四类浏览器源（index 14-19）
    expect(paths[14]).toBe('live-console');
    expect(paths[15]).toBe('live-overlay');
    expect(paths[16]).toBe('avatar-source');
    expect(paths[17]).toBe('danmaku-source');
    expect(paths[18]).toBe('subtitle-source');
    expect(paths[19]).toBe('audio-source');

    const expectations: Record<string, string> = {
      '/audio-panel': 'management.nav.audioPanel',
      '/audio-test': 'management.nav.audioTest',
      '/audio-workstation': 'management.nav.audioWorkstation',
      '/live-console': 'management.nav.liveConsole',
      '/live-overlay': 'management.nav.liveOverlay',
      '/avatar-source': 'management.nav.avatarSource',
      '/danmaku-source': 'management.nav.danmakuSource',
      '/subtitle-source': 'management.nav.subtitleSource',
      '/audio-source': 'management.nav.audioSource',
    };
    for (const [path, titleKey] of Object.entries(expectations)) {
      expect(findRouteByPathname(path)?.titleKey).toBe(titleKey);
    }
  });

  it('首条为 index 首页，全部条目四字段齐备', () => {
    expect(MANAGEMENT_ROUTES[0].path).toBe('');
    for (const entry of MANAGEMENT_ROUTES) {
      expect(entry.titleKey.startsWith('management.nav.')).toBe(true);
      expect(entry.icon).toBeTruthy();
      expect(entry.Component).toBeTruthy();
    }
  });

  it('校验器识别：重复 path', () => {
    const dup: ManagementRouteEntry[] = [
      ...MANAGEMENT_ROUTES,
      { ...MANAGEMENT_ROUTES[1] },
    ];
    expect(validateRouteRegistry(dup).some((v) => v.includes('重复登记'))).toBe(true);
  });

  it('校验器识别：多层路径 / 非小写连字符 / 大写', () => {
    const bad: ManagementRouteEntry[] = [
      ...MANAGEMENT_ROUTES,
      { ...MANAGEMENT_ROUTES[1], path: 'audio/panel' },
      { ...MANAGEMENT_ROUTES[1], path: 'AudioPanel' },
    ];
    const violations = validateRouteRegistry(bad);
    expect(violations.some((v) => v.includes('只允许单层相对路径'))).toBe(true);
    expect(violations.some((v) => v.includes('小写连字符'))).toBe(true);
  });

  it('校验器识别：占用独立窗顶层路由 /pet、/danmaku', () => {
    const bad: ManagementRouteEntry[] = [
      ...MANAGEMENT_ROUTES,
      { ...MANAGEMENT_ROUTES[1], path: 'pet' },
    ];
    expect(validateRouteRegistry(bad).some((v) => v.includes('独立窗顶层路由'))).toBe(true);
    expect(RESERVED_TOP_LEVEL_PATHS).toContain('/pet');
    expect(RESERVED_TOP_LEVEL_PATHS).toContain('/danmaku');
  });

  it('校验器识别：titleKey 不在 management.nav.* 命名空间', () => {
    const bad: ManagementRouteEntry[] = [
      ...MANAGEMENT_ROUTES,
      { ...MANAGEMENT_ROUTES[1], path: 'agents', titleKey: 'agents.title' },
    ];
    expect(validateRouteRegistry(bad).some((v) => v.includes('management.nav.*'))).toBe(true);
  });

  it('校验器识别：首页缺失或首条非 index', () => {
    expect(validateRouteRegistry([]).length).toBeGreaterThan(0);
    const noIndex: ManagementRouteEntry[] = [MANAGEMENT_ROUTES[1]];
    expect(validateRouteRegistry(noIndex).some((v) => v.includes('首页'))).toBe(true);
  });

  it('findRouteByPathname：正查与反查一致，未登记返回 undefined', () => {
    expect(findRouteByPathname('/')?.path).toBe('');
    expect(findRouteByPathname('/chat')?.path).toBe('chat');
    expect(findRouteByPathname('/settings')?.titleKey).toBe('management.nav.settings');
    expect(findRouteByPathname('/not-registered')).toBeUndefined();
  });
});
