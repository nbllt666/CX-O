/**
 * neko 兼容层纯函数单测（Vitest）
 */
import { describe, expect, it } from 'vitest';
import { normalizePluginList, pluginUiUrl, setNekoPort } from './neko';

describe('normalizePluginList', () => {
  it('透传数组形态', () => {
    const list = normalizePluginList([
      { id: 'a', name: 'A', description: 'x' },
      { id: 'b', name: 'B' },
    ]);
    expect(list).toHaveLength(2);
    expect(list[0].id).toBe('a');
  });

  it('归一化 { plugins: [...] } 形态', () => {
    const list = normalizePluginList({ plugins: [{ id: 'a' }], length: 1 });
    expect(list).toHaveLength(1);
    expect(list[0].id).toBe('a');
  });

  it('兜底 { id: {...} } 字典形态', () => {
    const list = normalizePluginList({ alpha: { name: 'Alpha' }, beta: { version: '1.0' } });
    expect(list).toHaveLength(2);
    expect(list.some((p) => p.id === 'alpha' && p.name === 'Alpha')).toBe(true);
  });

  it('空/非法输入返回空数组', () => {
    expect(normalizePluginList(null)).toEqual([]);
    expect(normalizePluginList(undefined)).toEqual([]);
    expect(normalizePluginList('x')).toEqual([]);
  });
});

describe('pluginUiUrl', () => {
  it('拼接插件 UI 地址并在端口缺失时抛错', () => {
    setNekoPort(48916);
    expect(pluginUiUrl(null, '/plugin/foo/ui/')).toBe('http://127.0.0.1:48916/plugin/foo/ui/');
    expect(pluginUiUrl(null, 'plugin/foo/ui/')).toBe('http://127.0.0.1:48916/plugin/foo/ui/');
    setNekoPort(null);
    expect(() => pluginUiUrl(null, '/plugin/foo/ui/')).toThrow();
  });
});