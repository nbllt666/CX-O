import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest';
import * as fs from 'node:fs';
import * as path from 'node:path';
import * as os from 'node:os';

// 用临时目录代替真实 userData，隔离单测写入
const tmpDir = os.tmpdir() + path.sep + 'cxo-store-test-' + process.pid + '-' + Date.now();

vi.mock('electron', () => ({
  app: {
    getPath: (() => tmpDir) as unknown as () => string,
  },
}));

// 必须在 mock 之后导入被测模块
import { loadStore, saveStore } from './store';

describe('store 槽位名校验（防路径穿越）', () => {
  beforeAll(() => {
    fs.mkdirSync(tmpDir, { recursive: true });
  });

  afterAll(() => {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  });

  it('合法名可正常保存与读取', () => {
    saveStore('app_config', JSON.stringify({ a: 1 }));
    expect(JSON.parse(loadStore('app_config')!)).toEqual({ a: 1 });
  });

  it('保存使用 `../` 的槽位名被拒绝（抛错，不落盘）', () => {
    expect(() => saveStore('../../escape', '{}')).toThrow();
  });

  it('保存含路径分隔符的槽位名被拒绝', () => {
    expect(() => saveStore('a\\b', '{}')).toThrow();
  });

  it('加载非法槽位名返回默认 null，不读外部文件', () => {
    // 写入一个真实文件到 store 目录外部，确认非法名不会命中它
    const outside = path.join(tmpDir, '..', 'escape-target.json');
    fs.writeFileSync(outside, 'SHOULD_NOT_READ');
    try {
      expect(loadStore('../escape-target')).toBeNull();
    } finally {
      fs.rmSync(outside, { force: true });
    }
  });

  it('加载不存在的槽位名返回 null（合法名缺失）', () => {
    expect(loadStore('no_such_key')).toBeNull();
  });
});