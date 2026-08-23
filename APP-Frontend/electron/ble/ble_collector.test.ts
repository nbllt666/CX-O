// @vitest-environment node
/**
 * BleHeartRateCollector / PhysioUploader mock 单测（noble 打桩，无真实 BLE）。
 * 覆盖：扫描 0x180D 过滤 + name hint、能力探测降级、连接订阅 0x2A37 解析 HR、
 * 断线重连调度、手动断开取消重连、noble 加载失败 graceful 降级、
 * HR 上送 ≤1Hz 节流 + 后端离线丢弃 + 系统静默 ≥30s 周期上送。
 */
import { EventEmitter } from 'node:events';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  BleHeartRateCollector,
  parseHeartRateMeasurement,
  makeDeviceFingerprint,
  type BleResult,
  type NobleCharacteristic,
  type NobleLike,
  type NobleService,
} from './ble_collector';
import { PhysioUploader } from './uploader';

// ---------------------------------------------------------------------------
// noble 打桩
// ---------------------------------------------------------------------------

/** 最小 noble 替身：EventEmitter（discover）+ startScanning/stopScanning */
class MockNoble extends EventEmitter implements NobleLike {
  startScanningCalls = 0;
  stopScanningCalls = 0;

  startScanning(
    _serviceUUIDs: string[],
    _allowDuplicates: boolean,
    cb?: (err?: Error | null) => void,
  ): unknown {
    this.startScanningCalls += 1;
    cb?.(null);
    return Promise.resolve('ok');
  }

  stopScanning(cb?: (err?: Error | null) => void): unknown {
    this.stopScanningCalls += 1;
    cb?.(null);
    return Promise.resolve();
  }
}

/** 0x2A37 特征替身；emitData 触发已注册的 data 监听 */
interface MockChar extends NobleCharacteristic {
  emitData: (data: Buffer | Uint8Array) => void;
  subscribe: ReturnType<typeof vi.fn>;
  unsubscribe: ReturnType<typeof vi.fn>;
  notify: ReturnType<typeof vi.fn>;
}

function makeCharacteristic(): MockChar {
  const dataHandlers: Array<(data: Buffer | Uint8Array) => void> = [];
  const char: MockChar = {
    uuid: '2a37',
    subscribe: vi.fn((cb?: (err?: Error | null) => void) => {
      cb?.(null);
      return Promise.resolve();
    }),
    unsubscribe: vi.fn((cb?: (err?: Error | null) => void) => {
      cb?.(null);
      return Promise.resolve();
    }),
    notify: vi.fn((_notify: boolean, cb?: (err?: Error | null) => void) => {
      cb?.(null);
      return Promise.resolve();
    }),
    on: vi.fn((event: string, handler: (data: Buffer | Uint8Array) => void) => {
      if (event === 'data') dataHandlers.push(handler);
    }),
    emitData: (data: Buffer | Uint8Array) => dataHandlers.forEach((h) => h(data)),
  };
  return char;
}

/** peripheral 替身：内含共享的 0x180D service 与 0x2A37 characteristic 引用。 */
interface MockPeripheral {
  id: string;
  address: string;
  advertisement: { localName: string; serviceUuids: string[] };
  rssi: number;
  isConnected: boolean;
  service: MockService;
  characteristic: MockChar;
  connect: ReturnType<typeof vi.fn>;
  disconnect: ReturnType<typeof vi.fn>;
  discoverServices: ReturnType<typeof vi.fn>;
  on: ReturnType<typeof vi.fn>;
  emitDisconnect: () => void;
}

interface MockService extends NobleService {
  discoverCharacteristics: ReturnType<typeof vi.fn>;
}

function makePeripheral(overrides: Partial<MockPeripheral> = {}): MockPeripheral {
  const characteristic = makeCharacteristic();
  const service: MockService = {
    uuid: '180d',
    discoverCharacteristics: vi.fn(
      (_uuids: string[], cb: (err: Error | null, chars: NobleCharacteristic[]) => void) => {
        cb(null, [characteristic]);
        return Promise.resolve();
      },
    ),
  };
  const disconnectHandlers: Array<() => void> = [];
  const periph: MockPeripheral = {
    id: 'dev-1',
    address: 'aa:bb:cc:dd:ee:ff',
    advertisement: { localName: 'PulseBand', serviceUuids: ['180d'] },
    rssi: -48,
    isConnected: false,
    service,
    characteristic,
    connect: vi.fn((cb?: (err?: Error | null) => void) => {
      periph.isConnected = true;
      cb?.(null);
      return Promise.resolve();
    }),
    disconnect: vi.fn((cb?: (err?: Error | null) => void) => {
      periph.isConnected = false;
      cb?.(null);
      return Promise.resolve();
    }),
    discoverServices: vi.fn(
      (_uuids: string[], cb: (err: Error | null, svcs: NobleService[]) => void) => {
        cb(null, [service]);
        return Promise.resolve();
      },
    ),
    on: vi.fn((event: string, handler: () => void) => {
      if (event === 'disconnect') disconnectHandlers.push(handler);
    }),
    emitDisconnect: () => disconnectHandlers.forEach((h) => h()),
    ...overrides,
  };
  return periph;
}

/** 驱动一次完整扫描：collector 挂好 discover 监听后发出设备，再推进扫描超时。 */
async function runScan(
  collector: BleHeartRateCollector,
  noble: MockNoble,
  peripherals: MockPeripheral[],
  scanTimeoutMs = 20,
): Promise<BleResult> {
  const p = collector.startScan();
  peripherals.forEach((periph) => noble.emit('discover', periph));
  await vi.advanceTimersByTimeAsync(scanTimeoutMs + 5);
  return p;
}

function makeFetchMock(
  handler: (url: string, init?: RequestInit) => Promise<Response>,
): { fetchImpl: typeof fetch; calls: Array<{ url: string; method?: string; body?: string }> } {
  const calls: Array<{ url: string; method?: string; body?: string }> = [];
  const fetchImpl = ((url: string, init?: RequestInit) => {
    const u = String(url);
    calls.push({ url: u, method: init?.method, body: init?.body as string | undefined });
    return handler(u, init);
  }) as typeof fetch;
  return { fetchImpl, calls };
}

function jsonResponse(status: number, data: unknown): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } }),
  );
}

describe('parseHeartRateMeasurement', () => {
  it('UINT8 格式解析（flags=0）', () => {
    expect(parseHeartRateMeasurement(new Uint8Array([0x00, 0x4b]))).toBe(75);
  });
  it('UINT16 格式解析（flags=0x01，小端）', () => {
    expect(parseHeartRateMeasurement(new Uint8Array([0x01, 0x50, 0x00]))).toBe(80);
    expect(parseHeartRateMeasurement(new Uint8Array([0x01, 0x01, 0x01]))).toBe(257);
  });
  it('数据过短抛错', () => {
    expect(() => parseHeartRateMeasurement(new Uint8Array([0x00]))).toThrow();
    expect(() => parseHeartRateMeasurement(new Uint8Array([0x01, 0x00]))).toThrow();
  });
});

describe('makeDeviceFingerprint', () => {
  it('确定性且区分 name+address 组合', () => {
    const a = makeDeviceFingerprint('PulseBand', 'aa:bb:cc:dd:ee:ff');
    const b = makeDeviceFingerprint('PulseBand', 'aa:bb:cc:dd:ee:ff');
    const c = makeDeviceFingerprint('PulseBand2', 'aa:bb:cc:dd:ee:ff');
    expect(a).toBe(b);
    expect(a).not.toBe(c);
    expect(a).toMatch(/^ble_[0-9a-f]{8}$/);
  });
});

describe('BleHeartRateCollector', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('扫描：标记带 0x180D 的设备并返回列表，按 device_name_hint 过滤', async () => {
    const noble = new MockNoble();
    const collector = new BleHeartRateCollector(
      { nobleLib: noble, scanTimeoutSec: 0.02, deviceNameHint: 'pulse' },
      { onStatus: () => undefined },
    );
    const hrPeriph = makePeripheral();
    const nonHrPeriph = makePeripheral({
      id: 'dev-2',
      address: '11:22:33:44:55:66',
      advertisement: { localName: 'OtherTag', serviceUuids: ['feee'] },
    });
    const hintedPeriph = makePeripheral({
      id: 'dev-3',
      address: 'aa:aa:aa:aa:aa:aa',
      advertisement: { localName: 'PulseBand-2', serviceUuids: ['180d'] },
    });
    // name hint='pulse'：OtherTag 被过滤；PulseBand-2 保留
    const result = await runScan(collector, noble, [hrPeriph, nonHrPeriph, hintedPeriph]);
    expect(result.ok).toBe(true);
    expect(result.devices?.length).toBe(2);
    const hr = result.devices?.find((d) => d.deviceId === 'dev-1');
    expect(hr?.hasHeartRate).toBe(true);
    expect(hr?.name).toBe('PulseBand');
    expect(noble.startScanningCalls).toBe(1);
    expect(noble.stopScanningCalls).toBe(1);
    expect(collector.getStatus().status).toBe('idle');
  });

  it('能力探测：扫不到 0x180D → 状态 unsupported', async () => {
    const noble = new MockNoble();
    const statuses: string[] = [];
    const collector = new BleHeartRateCollector(
      { nobleLib: noble, scanTimeoutSec: 0.02 },
      { onStatus: (s) => statuses.push(s) },
    );
    const nonHrPeriph = makePeripheral({
      advertisement: { localName: 'Speaker', serviceUuids: ['feee'] },
    });
    const result = await runScan(collector, noble, [nonHrPeriph]);
    expect(result.ok).toBe(true);
    expect(collector.getStatus().status).toBe('unsupported');
    expect(statuses).toContain('unsupported');
  });

  it('连接：订阅 0x2A37 并把 HR 解析结果经 onHr 回传（无效样本丢弃）', async () => {
    const noble = new MockNoble();
    const hrValues: number[] = [];
    const collector = new BleHeartRateCollector(
      { nobleLib: noble, scanTimeoutSec: 0.02 },
      { onHr: (bpm) => hrValues.push(bpm), onStatus: () => undefined },
    );
    const periph = makePeripheral();
    await runScan(collector, noble, [periph]);

    const connectResult = await collector.connect('dev-1');
    expect(connectResult.ok).toBe(true);
    expect(connectResult.status).toBe('connected');
    expect(collector.getStatus().status).toBe('connected');
    expect(collector.getDeviceFingerprint()).toBe(
      makeDeviceFingerprint('PulseBand', 'aa:bb:cc:dd:ee:ff'),
    );

    // 已订阅 0x2A37
    const char = periph.characteristic;
    expect(char.subscribe).toHaveBeenCalled();

    char.emitData(new Uint8Array([0x00, 0x4b])); // 75 bpm
    char.emitData(new Uint8Array([0x00, 0x00])); // 无效（0）→ 丢弃
    char.emitData(new Uint8Array([0x00, 0xdc])); // 220 有效
    char.emitData(new Uint8Array([0x00, 0xdd])); // 221 无效 → 丢弃
    expect(hrValues).toEqual([75, 220]);
  });

  it('断线重连：disconnect 事件进入 reconnecting，间隔后自动重连成功', async () => {
    const noble = new MockNoble();
    const statuses: string[] = [];
    const collector = new BleHeartRateCollector(
      { nobleLib: noble, scanTimeoutSec: 0.02, reconnectIntervalSec: 30 },
      { onStatus: (s) => statuses.push(s) },
    );
    const periph = makePeripheral();
    await runScan(collector, noble, [periph]);
    const connectResult = await collector.connect('dev-1');
    expect(connectResult.ok).toBe(true);

    // 触发 noble peripheral 的 disconnect 事件
    periph.emitDisconnect();
    expect(collector.getStatus().status).toBe('reconnecting');
    expect(statuses).toContain('reconnecting');

    // 推进重连间隔 → 自动重连
    await vi.advanceTimersByTimeAsync(30_000 + 10);
    expect(periph.connect).toHaveBeenCalledTimes(2);
    expect(collector.getStatus().status).toBe('connected');
  });

  it('手动 disconnect 取消自动重连，不再续排', async () => {
    const noble = new MockNoble();
    const collector = new BleHeartRateCollector(
      { nobleLib: noble, scanTimeoutSec: 0.02, reconnectIntervalSec: 30 },
      { onStatus: () => undefined },
    );
    const periph = makePeripheral();
    await runScan(collector, noble, [periph]);
    await collector.connect('dev-1');
    const connectCallsAfterConnect = periph.connect.mock.calls.length;

    await collector.disconnect();
    expect(collector.getStatus().status).toBe('idle');
    // 手动断开后触发 disconnect 事件，不应重连
    periph.emitDisconnect();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(periph.connect.mock.calls.length).toBe(connectCallsAfterConnect);
    expect(collector.getStatus().status).toBe('idle');
  });

  it('noble 加载失败 graceful 降级：状态 unavailable，API 不崩溃', async () => {
    // 注入 API 不完整的对象 → 与动态 require 失败同路径，确定性降级
    const collector = new BleHeartRateCollector({ nobleLib: {} });
    expect(collector.getStatus().status).toBe('unavailable');
    const scan = await collector.startScan();
    expect(scan.ok).toBe(false);
    expect(scan.error).toContain('不可用');
    const connect = await collector.connect('dev-1');
    expect(connect.ok).toBe(false);
  });
});

describe('PhysioUploader', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('HR 上送 ≤1Hz 节流：窗口内丢弃，窗口外放行', async () => {
    const { fetchImpl, calls } = makeFetchMock(async () => jsonResponse(200, { ok: true }));
    const uploader = new PhysioUploader({
      backendUrl: 'http://127.0.0.1:8000/',
      hrThrottleMs: 1000,
      fetchImpl,
    });
    const sample = () => ({ bpm: 72, ts: Math.floor(Date.now() / 1000), device_fingerprint: 'ble_abcd1234' });

    expect(await uploader.reportHr(sample())).toBe(true); // 首发
    expect(await uploader.reportHr(sample())).toBe(false); // 节流丢弃
    await vi.advanceTimersByTimeAsync(1000);
    expect(await uploader.reportHr(sample())).toBe(true); // 窗口外放行

    const hrCalls = calls.filter((c) => c.url.endsWith('/api/physio/hr'));
    expect(hrCalls.length).toBe(2);
    const firstBody = JSON.parse(hrCalls[0].body ?? '{}');
    expect(firstBody).toMatchObject({ bpm: 72, device_fingerprint: 'ble_abcd1234' });
    expect(firstBody.ts).toBeTypeOf('number');
  });

  it('后端离线：丢弃当前样本不积压，不抛异常', async () => {
    const { fetchImpl, calls } = makeFetchMock(async () => {
      throw new Error('ECONNREFUSED');
    });
    const uploader = new PhysioUploader({
      backendUrl: 'http://127.0.0.1:8000',
      hrThrottleMs: 1000,
      fetchImpl,
      logger: () => undefined,
    });
    expect(await uploader.reportHr({ bpm: 72, ts: Math.floor(Date.now() / 1000), device_fingerprint: 'f' })).toBe(false);
    await vi.advanceTimersByTimeAsync(1000);
    expect(await uploader.reportHr({ bpm: 71, ts: Math.floor(Date.now() / 1000), device_fingerprint: 'f' })).toBe(false);
    expect(calls.length).toBe(2); // 每次尝试一次，无积压缓冲
  });

  it('系统静默周期上送：≥30s 间隔，载荷 {system_idle_sec, user_active}', async () => {
    const { fetchImpl, calls } = makeFetchMock(async (url) => {
      if (url.endsWith('/api/physio/state')) return jsonResponse(200, { ok: true });
      return jsonResponse(404, {});
    });
    const uploader = new PhysioUploader({
      backendUrl: 'http://127.0.0.1:8000',
      idleIntervalMs: 30000,
      fetchImpl,
    });
    let idle = 10;
    uploader.startIdleReport(() => ({ system_idle_sec: idle, user_active: idle < 60 }));
    expect(calls.filter((c) => c.url.endsWith('/api/physio/state')).length).toBe(1); // 首次立即

    idle = 120;
    await vi.advanceTimersByTimeAsync(30000);
    const stateCalls = calls.filter((c) => c.url.endsWith('/api/physio/state'));
    expect(stateCalls.length).toBe(2);
    const body = JSON.parse(stateCalls[1].body ?? '{}');
    expect(body).toMatchObject({ system_idle_sec: 120, user_active: false });

    uploader.stop();
    await vi.advanceTimersByTimeAsync(120000);
    expect(calls.filter((c) => c.url.endsWith('/api/physio/state')).length).toBe(2);
  });
});
