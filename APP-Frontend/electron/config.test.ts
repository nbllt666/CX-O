/**
 * 应用配置读写单元测试（Vitest）。
 * 重点验证 M-G 修复项：
 *  1) readConfig 对损坏 JSON 容错（warn 后回退 {}，触发默认配置重建），不再 rethrow；
 *  2) ENOENT 维持现状返回 {}；
 *  3) writeConfig 原子替换成功且不残留 .tmp 临时文件；
 *  4) 原子写可正常覆盖既有目标文件。
 */
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest';
import * as fs from 'node:fs';
import * as path from 'node:path';
import * as os from 'node:os';

const tmpDir = path.join(os.tmpdir(), `cxo-config-test-${process.pid}-${Date.now()}`);

vi.mock('electron', () => ({
  app: {
    getPath: (() => tmpDir) as unknown as () => string,
  },
}));

// 必须在 mock 之后导入被测模块
import { getConfig, setConfig } from './config';

describe('config 配置读写', () => {
  beforeAll(() => {
    fs.mkdirSync(tmpDir, { recursive: true });
  });

  afterAll(() => {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  });

  it('文件缺失（ENOENT）时读取返回 null，不抛异常', () => {
    expect(getConfig('backendUrl')).toBeNull();
  });

  it('setConfig/getConfig 正常往返写入', () => {
    setConfig('backendUrl', 'http://127.0.0.1:8000');
    expect(getConfig('backendUrl')).toBe('http://127.0.0.1:8000');
  });

  it('损坏 JSON 时读取容错返回默认空表（不再 rethrow），下次写入自动重建', () => {
    const configPath = path.join(tmpDir, 'config.json');
    fs.writeFileSync(configPath, '{"backendUrl": "http://trunc', 'utf-8'); // 半截 JSON
    expect(getConfig('backendUrl')).toBeNull(); // 不抛 SyntaxError

    // 下一次 setConfig 覆盖重写恢复正常
    setConfig('backendUrl', 'http://recovered:8000');
    expect(getConfig('backendUrl')).toBe('http://recovered:8000');
    const reparsed = JSON.parse(fs.readFileSync(configPath, 'utf-8')) as Record<string, string>;
    expect(reparsed.backendUrl).toBe('http://recovered:8000');
  });

  it('原子替换写入后不残留 .tmp 临时文件', () => {
    setConfig('k1', 'v1');
    setConfig('k2', 'v2'); // 第二次为覆盖已存在目标的场景
    expect(fs.existsSync(path.join(tmpDir, 'config.json.tmp'))).toBe(false);
    expect(fs.existsSync(path.join(tmpDir, 'config.json'))).toBe(true);
    expect(getConfig('k1')).toBe('v1');
    expect(getConfig('k2')).toBe('v2');
  });
});
