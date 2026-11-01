// @vitest-environment node
/**
 * 配置持久化单测（tests/config.test.ts）
 * ============================================================================
 * 覆盖 src/shared/config.ts：
 *  - 默认值自动补全（auto_init）：无配置文件 / 配置缺失键 / 类型非法时回落默认；
 *  - setConfig / getConfig / getAll 往返一致（含归一化：trim / 端口取整）；
 *  - 持久化写入 data/config.json，未传键保持磁盘原值；
 *  - 损坏 JSON 文件容错（按空配置处理并由默认值回填，随后写入可重建）；
 *  - 原子写（tmp + rename）替换后不残留 .tmp 文件。
 *
 * 通过 vi.mock 把 paths 模块重定向到 os.tmpdir 下的临时目录（mkdtemp），
 * 绝不读写真实 data/ 目录；每个用例使用独立临时目录，前后创建/清理。
 * ============================================================================
 */
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/** vi.hoisted：在 mock 工厂执行前可用的可变容器（当前临时根目录） */
const tmpRoots = vi.hoisted(() => ({ current: '' }));

/** 伪装 paths 模块：全部路径指向临时目录；getter 保证每次访问都取当前临时目录 */
vi.mock('../src/shared/paths', async () => {
  const fsMod = await import('node:fs');
  const pathMod = await import('node:path');
  return {
    get projectRoot() {
      return tmpRoots.current;
    },
    get dataDir() {
      return pathMod.join(tmpRoots.current, 'data');
    },
    get certsDir() {
      return pathMod.join(tmpRoots.current, 'data', 'certs');
    },
    get configPath() {
      return pathMod.join(tmpRoots.current, 'data', 'config.json');
    },
    ensureDataDirs: () => {
      fsMod.mkdirSync(pathMod.join(tmpRoots.current, 'data', 'certs'), { recursive: true });
    },
  };
});

type ConfigModule = typeof import('../src/shared/config');

/** 被测模块引用：beforeEach 中动态导入（此时 mock 路径已指向本轮临时目录） */
let config: ConfigModule;
/** 本轮用例的临时根目录 */
let tmpRoot: string;

/** 本文件会设置的环境变量（测试间隔离：逐用例保存/恢复） */
const ENV_KEYS = [
  'CXO_NEKO_ADAPTER_CONTROL_HOST',
  'CXO_NEKO_ADAPTER_BRIDGE_HOST',
  'CXO_NEKO_ADAPTER_BRIDGE_PUBLIC_HOST',
  'CXO_NEKO_ADAPTER_BACKEND_URL',
] as const;
const savedEnv: Record<string, string | undefined> = {};

beforeEach(async () => {
  for (const key of ENV_KEYS) {
    savedEnv[key] = process.env[key];
    delete process.env[key];
  }
  tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'cxo-config-test-'));
  tmpRoots.current = tmpRoot;
  config = await import('../src/shared/config');
});

afterEach(() => {
  for (const key of ENV_KEYS) {
    if (savedEnv[key] === undefined) delete process.env[key];
    else process.env[key] = savedEnv[key];
  }
  // 重置模块注册表：清空 config.ts 模块级状态（writing 标志）并释放 mock 引用
  vi.resetModules();
  fs.rmSync(tmpRoot, { recursive: true, force: true });
});

/** 配置文件在临时目录中的绝对路径 */
function configFilePath(): string {
  return path.join(tmpRoot, 'data', 'config.json');
}

describe('配置默认值自动补全（auto_init）', () => {
  it('无配置文件时 getAll 返回完整默认配置', () => {
    const all = config.getAll();
    expect(all).toEqual(config.DEFAULT_CONFIG);
    // 逐键锁定默认值语义（与 mergeWithDefaults 契约一致）
    expect(all).toEqual({
      python: 'python',
      sourceDir: 'C:\\N.E.K.O-main',
      port: 48916,
      backendUrl: 'http://127.0.0.1:8000',
      controlPort: 48920,
      controlHost: '127.0.0.1',
      bridgeHost: '127.0.0.1',
      bridgePublicHost: '127.0.0.1',
      autoStart: false,
    });
  });

  it('配置文件缺失键/类型非法时按默认值补全（不抛错）', () => {
    fs.mkdirSync(path.dirname(configFilePath()), { recursive: true });
    fs.writeFileSync(
      configFilePath(),
      JSON.stringify({ port: 0, backendUrl: '', autoStart: 'yes', python: null }),
      'utf-8',
    );
    const all = config.getAll();
    expect(all.port).toBe(48916); // 非法端口（0/NaN）回落默认
    expect(all.backendUrl).toBe('http://127.0.0.1:8000'); // 空字符串回落默认
    expect(all.python).toBe('python'); // 非字符串/null 回落默认
    expect(all.autoStart).toBe(false); // 严格等于 true 才生效（'yes' 不生效）
  });
});

describe('set/get 往返与持久化', () => {
  it('默认监听/通告地址均为 127.0.0.1（controlHost / bridgeHost / bridgePublicHost）', () => {
    expect(config.getConfig('controlHost')).toBe('127.0.0.1');
    expect(config.getConfig('bridgeHost')).toBe('127.0.0.1');
    expect(config.getConfig('bridgePublicHost')).toBe('127.0.0.1');
  });

  it('setConfig 可写入 controlHost / bridgeHost / bridgePublicHost，且空字符串回落默认', () => {
    const after = config.setConfig({ controlHost: ' 0.0.0.0 ', bridgeHost: '::', bridgePublicHost: ' cxo-neko-adapter ' });
    expect(after.controlHost).toBe('0.0.0.0');
    expect(after.bridgeHost).toBe('::');
    expect(after.bridgePublicHost).toBe('cxo-neko-adapter');
    // 空字符串非空才生效 → 回落默认
    config.setConfig({ controlHost: '' });
    expect(config.getConfig('controlHost')).toBe('127.0.0.1');
  });

  it('setConfig 后 getConfig/getAll 返回归一化后的值', () => {
    const after = config.setConfig({
      port: 48999.7,
      backendUrl: '  http://10.0.0.8:9000/  ',
      python: ' /usr/bin/python3 ',
      autoStart: true,
    });
    expect(after.port).toBe(48999); // 端口取整
    expect(after.backendUrl).toBe('http://10.0.0.8:9000/'); // 字符串 trim（仅去首尾空白，不剥尾斜杠）
    expect(after.python).toBe('/usr/bin/python3');
    expect(after.autoStart).toBe(true);
    expect(config.getConfig('port')).toBe(48999);
    expect(config.getConfig('backendUrl')).toBe('http://10.0.0.8:9000/');
    expect(config.getConfig('autoStart')).toBe(true);
  });

  it('setConfig 持久化到 data/config.json 且未传键保持磁盘原值', () => {
    config.setConfig({ backendUrl: 'http://a:1' });
    config.setConfig({ port: 49001 }); // 第二次只写 port
    expect(fs.existsSync(configFilePath())).toBe(true);
    const onDisk = JSON.parse(fs.readFileSync(configFilePath(), 'utf-8')) as Record<string, unknown>;
    expect(onDisk.backendUrl).toBe('http://a:1'); // 第一次写入的键仍在
    expect(onDisk.port).toBe(49001);
    expect(config.getConfig('backendUrl')).toBe('http://a:1');
  });

  it('值为 undefined 的键不覆盖磁盘原值', () => {
    config.setConfig({ port: 49003 });
    config.setConfig({ port: undefined });
    expect(config.getConfig('port')).toBe(49003);
  });

  it('非法端口写入后读取回落默认（normalize 下限 0 → 合并时回落）', () => {
    config.setConfig({ port: -5 });
    expect(config.getConfig('port')).toBe(48916);
  });
});

describe('损坏 JSON 容错与原子写', () => {
  it('损坏 JSON 文件按空配置容错（默认值补全），随后写入可重建', () => {
    fs.mkdirSync(path.dirname(configFilePath()), { recursive: true });
    // 截断/损坏的 JSON（模拟写入中途异常）
    fs.writeFileSync(configFilePath(), '{"python": "C:\\broken', 'utf-8');
    expect(() => config.getAll()).not.toThrow();
    expect(config.getAll()).toEqual(config.DEFAULT_CONFIG);
    // 触发一次正常写入即可重建合法配置文件
    config.setConfig({ port: 49004 });
    expect(config.getConfig('port')).toBe(49004);
    expect(JSON.parse(fs.readFileSync(configFilePath(), 'utf-8'))).toMatchObject({ port: 49004 });
  });

  it('原子写：tmp+rename 替换后不残留 .tmp 文件', () => {
    config.setConfig({ port: 49005 });
    config.setConfig({ backendUrl: 'http://b:2' }); // 第二次写也走 tmp+rename
    const dataDir = path.join(tmpRoot, 'data');
    const files = fs.readdirSync(dataDir);
    expect(files).toContain('config.json');
    expect(files.some((f) => f.endsWith('.tmp'))).toBe(false);
    expect(files).toContain('certs'); // ensureDataDirs 幂等创建目录结构
  });
});

describe('环境变量覆盖（容器部署）', () => {
  it('设置四个环境变量后 getAll/getConfig 取环境值', () => {
    process.env.CXO_NEKO_ADAPTER_CONTROL_HOST = '0.0.0.0';
    process.env.CXO_NEKO_ADAPTER_BRIDGE_HOST = '0.0.0.0';
    process.env.CXO_NEKO_ADAPTER_BRIDGE_PUBLIC_HOST = 'cxo-neko-adapter';
    process.env.CXO_NEKO_ADAPTER_BACKEND_URL = 'http://cxo-server:8000';

    const all = config.getAll();
    expect(all.controlHost).toBe('0.0.0.0');
    expect(all.bridgeHost).toBe('0.0.0.0');
    expect(all.bridgePublicHost).toBe('cxo-neko-adapter');
    expect(all.backendUrl).toBe('http://cxo-server:8000');
    expect(config.getConfig('controlHost')).toBe('0.0.0.0');
    expect(config.getConfig('bridgeHost')).toBe('0.0.0.0');
    expect(config.getConfig('bridgePublicHost')).toBe('cxo-neko-adapter');
  });

  it('环境值首尾空白被 trim；空白串不覆盖（回落配置文件/默认）', () => {
    process.env.CXO_NEKO_ADAPTER_CONTROL_HOST = '  0.0.0.0  ';
    process.env.CXO_NEKO_ADAPTER_BACKEND_URL = '   ';
    expect(config.getConfig('controlHost')).toBe('0.0.0.0');
    expect(config.getConfig('backendUrl')).toBe('http://127.0.0.1:8000');
  });

  it('环境覆盖优先于磁盘配置，且不把环境值写入配置文件', () => {
    config.setConfig({ controlHost: '192.168.1.10', backendUrl: 'http://disk:8000' });
    process.env.CXO_NEKO_ADAPTER_CONTROL_HOST = '0.0.0.0';
    process.env.CXO_NEKO_ADAPTER_BACKEND_URL = 'http://env:8000';
    expect(config.getConfig('controlHost')).toBe('0.0.0.0');
    expect(config.getConfig('backendUrl')).toBe('http://env:8000');
    const onDisk = JSON.parse(fs.readFileSync(configFilePath(), 'utf-8')) as Record<string, unknown>;
    expect(onDisk.controlHost).toBe('192.168.1.10');
    expect(onDisk.backendUrl).toBe('http://disk:8000');
  });
});
