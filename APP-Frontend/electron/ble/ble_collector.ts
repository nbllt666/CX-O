/**
 * 手环心率 BLE 采集器（主进程，@abandonware/noble）
 * ============================================================================
 * 背景（spec：前端 Electron BLE 采集）：主进程用 noble（Node BLE 库）扫描带
 * Heart Rate Service 0x180D 的设备，连接后订阅 0x2A37（Heart Rate Measurement）
 * notification 并解析 bpm，断线自动重连；扫不到 0x180D 判定为型号不支持。
 *
 * 健壮性约束：
 *  - noble 为原生模块（Windows 需 BLE 适配器 + electron-rebuild），本文件用
 *    createRequire 动态 require，加载失败时 graceful 降级为状态 unavailable，
 *    绝不影响 Electron 主流程与梦境主流程（spec：异常隔离）。
 *  - ESM 主进程加载 CJS noble：`createRequire(import.meta.url)`（package.json
 *    type=module，产物为 ESM）。
 *  - 可测试性：nobleLib 可由外部注入（单测打桩），REST 上送经 fetchImpl 注入。
 *  - 心率数据仅在本机流转：解析出 bpm 后经 onHr 回调交主进程上送，原始字节不落盘。
 *
 * 类型说明：noble 无官方 TS 类型，本文件按使用面定义最小结构化接口
 * （NobleLike/NoblePeripheral/NobleService/NobleCharacteristic），内部不再出现 any。
 *
 * 单位说明：HR 数值为有效心率（1..220 bpm），0 或 >220 视为无效样本丢弃（对齐
 * spec HeartRateSleepEstimator 的无效数据过滤口径）。
 * ============================================================================
 */
import { createRequire } from 'node:module';

/** BLE 标准 UUID（小写规范化比较用） */
export const HEART_RATE_SERVICE_UUID = '180d';
export const HEART_RATE_MEASUREMENT_CHAR_UUID = '2a37';

// ---------------------------------------------------------------------------
// noble 最小 API 面（@abandonware/noble 无官方类型，按实际使用面定义）
// ---------------------------------------------------------------------------

export interface NobleLike {
  on(event: 'discover', listener: (peripheral: NoblePeripheral) => void): unknown;
  off?(event: 'discover', listener: (peripheral: NoblePeripheral) => void): unknown;
  startScanning(
    serviceUUIDs: string[],
    allowDuplicates: boolean,
    cb?: (err?: Error | null) => void,
  ): unknown;
  stopScanning(cb?: (err?: Error | null) => void): unknown;
}

export interface NoblePeripheral {
  id: string;
  address?: string;
  advertisement?: {
    localName?: string;
    serviceUuids?: string[];
  };
  rssi?: number;
  isConnected?: boolean;
  connect(cb: (err?: Error | null) => void): unknown;
  disconnect(cb?: (err?: Error | null) => void): unknown;
  discoverServices(
    uuids: string[],
    cb: (err: Error | null, services: NobleService[]) => void,
  ): unknown;
  on(event: 'disconnect', listener: () => void): unknown;
  /** EventEmitter 同名方法（真实 noble peripheral 继承自 EventEmitter；mock 可缺省）。 */
  removeAllListeners?(event?: string): unknown;
}

export interface NobleService {
  uuid: string;
  discoverCharacteristics(
    uuids: string[],
    cb: (err: Error | null, characteristics: NobleCharacteristic[]) => void,
  ): unknown;
}

export interface NobleCharacteristic {
  uuid: string;
  subscribe(cb?: (err?: Error | null) => void): unknown;
  unsubscribe(cb?: (err?: Error | null) => void): unknown;
  notify(notify: boolean, cb?: (err?: Error | null) => void): unknown;
  on(event: 'data', listener: (data: Buffer | Uint8Array) => void): unknown;
  /** EventEmitter 同名方法（真实 noble characteristic 继承自 EventEmitter；mock 可缺省）。 */
  removeAllListeners?(event?: string): unknown;
}

// ---------------------------------------------------------------------------
// 公共类型
// ---------------------------------------------------------------------------

/** 采集器状态机 */
export type BleStatus =
  | 'idle' // 空闲（未扫描/已断开）
  | 'unavailable' // noble 原生模块不可用（graceful 降级，不崩溃）
  | 'scanning' // 扫描中
  | 'unsupported' // 扫不到 0x180D（型号不支持/未开启心率广播）
  | 'connecting' // 连接中
  | 'connected' // 已连接并订阅 HR
  | 'reconnecting' // 断线自动重连中
  | 'disconnected'; // 连接失败/已断开（无重连）

/** 扫描结果中的一台 BLE 设备 */
export interface BleDeviceInfo {
  deviceId: string;
  name: string;
  address: string;
  /** 设备指纹（name+address 确定性 hash），供配对管理与后端样本关联 */
  fingerprint: string;
  rssi: number | null;
  serviceUuids: string[];
  /** 是否带 Heart Rate Service 0x180D */
  hasHeartRate: boolean;
}

export interface BleCollectorOptions {
  /** 注入 noble 库（单测打桩用）；缺省用 createRequire 动态加载 */
  nobleLib?: unknown;
  /** 扫描超时（秒），默认 15 */
  scanTimeoutSec?: number;
  /** 设备名过滤关键字（子串匹配，忽略大小写）；空串不过滤 */
  deviceNameHint?: string;
  /** 断线重连间隔（秒），默认 30 */
  reconnectIntervalSec?: number;
  logger?: (line: string) => void;
}

export interface BleCollectorCallbacks {
  onHr?: (bpm: number) => void;
  onStatus?: (status: BleStatus, detail?: string) => void;
  onError?: (error: Error, context?: string) => void;
}

export interface BleResult {
  ok: boolean;
  status: BleStatus;
  devices?: BleDeviceInfo[];
  error?: string;
}

/**
 * 解析 BLE Heart Rate Measurement（0x2A37）数据。
 * flags 字节 bit0 决定心率格式：0=UINT8（1 字节），1=UINT16（2 字节小端）。
 */
export function parseHeartRateMeasurement(data: Uint8Array | Buffer): number {
  if (!data || data.length < 2) {
    throw new Error(`心率数据过短（${data ? data.length : 0} 字节）`);
  }
  const flags = data[0];
  if ((flags & 0x01) === 0) {
    return data[1];
  }
  if (data.length < 3) {
    throw new Error('UINT16 心率数据不足 3 字节');
  }
  return (data[1] | (data[2] << 8)) >>> 0;
}

/** 设备指纹：name+address 的确定性 FNV-1a 32 位 hash（十六进制，8 位补齐）。 */
export function makeDeviceFingerprint(name: string, address: string): string {
  const input = `${name ?? ''}|${address ?? ''}`;
  let hash = 0x811c9dc5;
  for (let i = 0; i < input.length; i++) {
    hash ^= input.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return `ble_${(hash >>> 0).toString(16).padStart(8, '0')}`;
}

export class BleHeartRateCollector {
  private readonly noble: NobleLike | null;
  private readonly nobleAvailable: boolean;
  private readonly scanTimeoutMs: number;
  private readonly deviceNameHint: string;
  private readonly reconnectMs: number;
  private readonly callbacks: BleCollectorCallbacks;
  private readonly logger: (line: string) => void;

  private state: BleStatus = 'idle';
  private readonly devices = new Map<string, BleDeviceInfo>(); // 最近一次扫描结果（跨扫描保留）
  private readonly peripherals = new Map<string, NoblePeripheral>(); // deviceId -> noble peripheral 对象
  private characteristic: NobleCharacteristic | null = null;
  private lastDeviceId: string | null = null;
  private autoReconnect = false;
  private activeFingerprint: string | null = null;
  private activeDeviceName: string | null = null;

  private scanTimer: ReturnType<typeof setTimeout> | null = null;
  private scanResolver: (() => void) | null = null;
  private scanInterrupted = false;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private discoverListener: ((peripheral: NoblePeripheral) => void) | null = null;

  constructor(options: BleCollectorOptions = {}, callbacks: BleCollectorCallbacks = {}) {
    this.scanTimeoutMs = (options.scanTimeoutSec ?? 15) * 1000;
    this.deviceNameHint = (options.deviceNameHint ?? '').trim();
    this.reconnectMs = (options.reconnectIntervalSec ?? 30) * 1000;
    this.callbacks = callbacks;
    this.logger = options.logger ?? (() => undefined);

    const injected = options.nobleLib as Partial<NobleLike> | null | undefined;
    if (injected && typeof injected.on === 'function' && typeof injected.startScanning === 'function') {
      this.noble = injected as NobleLike;
      this.nobleAvailable = true;
    } else {
      // 注入缺失或注入对象 API 不完整：退回动态 require；仍失败则 graceful 降级
      const loaded = this.tryLoadNoble();
      this.noble = loaded;
      this.nobleAvailable = loaded !== null;
      if (!loaded) {
        this.state = 'unavailable';
      }
    }
  }

  /** createRequire 动态加载 CJS noble；失败返回 null（graceful 降级，不抛异常）。 */
  private tryLoadNoble(): NobleLike | null {
    try {
      const require = createRequire(import.meta.url);
      const lib = require('@abandonware/noble') as Partial<NobleLike>;
      if (!lib || typeof lib.on !== 'function' || typeof lib.startScanning !== 'function') {
        this.logger('[ble] noble 加载成功但 API 不完整，降级为 unavailable');
        return null;
      }
      this.logger('[ble] noble 加载成功');
      return lib as NobleLike;
    } catch (err) {
      this.logger(`[ble] noble 加载失败，BLE 采集不可用（不崩溃）: ${String(err)}`);
      return null;
    }
  }

  // -------------------------------------------------------------------------
  // 对外 API
  // -------------------------------------------------------------------------

  /** 当前状态 + 活跃设备指纹/名称（供 IPC ble:status 返回）。 */
  getStatus(): { status: BleStatus; fingerprint: string | null; deviceName: string | null } {
    return {
      status: this.state,
      fingerprint: this.activeFingerprint,
      deviceName: this.activeDeviceName,
    };
  }

  getDeviceFingerprint(): string | null {
    return this.activeFingerprint;
  }

  getScannedDevices(): BleDeviceInfo[] {
    return [...this.devices.values()];
  }

  /** 扫描带 Heart Rate Service 的设备；扫描结束做能力探测（无 0x180D → unsupported）。 */
  async startScan(preserveAutoReconnect = false): Promise<BleResult> {
    if (!this.nobleAvailable || !this.noble) {
      return { ok: false, status: this.state, error: 'BLE 不可用（noble 原生模块未加载）' };
    }
    if (this.state === 'scanning') {
      return { ok: false, status: this.state, error: '正在扫描中，请稍候' };
    }
    if (this.state === 'connected' || this.state === 'connecting') {
      return { ok: false, status: this.state, error: '设备已连接，请先断开再扫描' };
    }

    // 用户发起扫描 = 接管控制权，取消自动重连与上一次扫描
    // H11: 重连流程内部的补扫（preserveAutoReconnect=true）不得关闭自动重连，
    // 否则设备从扫描结果短暂丢失时重连链被永久切断（autoReconnect 残留 false）。
    if (!preserveAutoReconnect) {
      this.autoReconnect = false;
    }
    this.clearReconnectTimer();
    this.clearScanTimer();
    // 复位打断标记：clearScanTimer() 在无待收尾扫描时也会置 scanInterrupted=true，
    // 但本次 startScan 是全新会话，复位后正常完成的扫描不应被误判为中断（否则
    // disconnect() 之后首次 startScan 即使扫描成功也会误报「扫描被 connect/disconnect 中断」）。
    this.scanInterrupted = false;

    this.devices.clear();
    this.setState('scanning', '正在扫描 BLE 设备…');
    const listener = (peripheral: NoblePeripheral) => this.handleDiscovered(peripheral);
    this.discoverListener = listener;
    this.noble.on('discover', listener);

    try {
      await this.nobleCall((cb) => this.noble?.startScanning([], true, cb));
    } catch (err) {
      this.noble.off?.('discover', listener);
      this.discoverListener = null;
      this.setState('disconnected', `启动扫描失败：${String(err)}`);
      return { ok: false, status: this.state, error: String(err) };
    }

    // 等待扫描窗口；connect/disconnect 打断时 clearScanTimer 会 resolve 该 Promise，
    // 避免扫描协程永久悬挂。
    await new Promise<void>((resolve) => {
      this.scanResolver = resolve;
      this.scanTimer = setTimeout(resolve, this.scanTimeoutMs);
    });
    this.scanTimer = null;
    this.scanResolver = null;

    // 被打断（connect/disconnect 已自行 stopScanning + removeDiscoverListener）
    // → 在这里退出，不做正常扫描收尾，否则会覆盖打断流程的状态。
    if (this.scanInterrupted) {
      this.scanInterrupted = false;
      return { ok: false, status: this.state, error: '扫描被 connect/disconnect 中断' };
    }

    if (this.noble && typeof this.noble.stopScanning === 'function') {
      try {
        await this.nobleCall((cb) => this.noble?.stopScanning(cb));
      } catch {
        // 停止扫描失败可忽略
      }
    }
    this.removeDiscoverListener();

    const all = [...this.devices.values()];
    const hrCount = all.filter((d) => d.hasHeartRate).length;
    // 能力探测：扫不到 0x180D → 型号不支持/未开启心率广播
    if (hrCount === 0) {
      this.setState('unsupported', '未发现带心率服务 0x180D 的设备（型号不支持或未开启心率广播）');
    } else {
      this.setState('idle', `扫描完成，发现 ${hrCount} 台心率设备`);
    }
    return { ok: true, status: this.state, devices: all };
  }

  /** 连接设备并订阅 0x2A37 心率通知。deviceId 须来自最近一次扫描。 */
  async connect(deviceId: string): Promise<BleResult> {
    if (!this.nobleAvailable || !this.noble) {
      return { ok: false, status: this.state, error: 'BLE 不可用（noble 原生模块未加载）' };
    }
    const device = this.devices.get(deviceId);
    const peripheral = this.peripherals.get(deviceId);
    if (!device || !peripheral) {
      return { ok: false, status: this.state, error: '设备不存在，请先扫描' };
    }
    if (this.state === 'scanning') {
      this.clearScanTimer();
      if (this.noble && typeof this.noble.stopScanning === 'function') {
        try {
          await this.nobleCall((cb) => this.noble?.stopScanning(cb));
        } catch {
          // 忽略
        }
      }
      this.removeDiscoverListener();
    }

    this.lastDeviceId = deviceId;
    this.activeFingerprint = device.fingerprint;
    this.activeDeviceName = device.name;
    this.setState('connecting', `正在连接 ${device.name || deviceId}…`);

    try {
      await this.nobleCall((cb) => peripheral.connect(cb));

      const discoverArgs = await this.nobleCall((cb) =>
        peripheral.discoverServices([HEART_RATE_SERVICE_UUID], cb),
      );
      const hrService = this.findService((discoverArgs[0] as NobleService[]) ?? []);
      if (!hrService) {
        await this.safeDisconnectPeripheral(peripheral);
        this.setState('unsupported', '设备不支持心率服务 0x180D');
        return { ok: false, status: this.state, error: '设备不支持心率服务 0x180D' };
      }

      const charArgs = await this.nobleCall((cb) =>
        hrService.discoverCharacteristics([HEART_RATE_MEASUREMENT_CHAR_UUID], cb),
      );
      const hrChar = this.findCharacteristic((charArgs[0] as NobleCharacteristic[]) ?? []);
      if (!hrChar) {
        await this.safeDisconnectPeripheral(peripheral);
        this.setState('unsupported', '设备缺少心率特征 0x2A37');
        return { ok: false, status: this.state, error: '设备缺少心率特征 0x2A37' };
      }

      // 先挂 data 监听再订阅，避免丢包；断线重连复用同一 characteristic 时
      // 必须先清理旧监听器，否则 handler 线性累积导致 HR 重复上送。
      hrChar.removeAllListeners?.('data');
      hrChar.on('data', (data: Buffer | Uint8Array) => this.handleHrData(data));
      await this.subscribeCharacteristic(hrChar);

      this.characteristic = hrChar;
      // 断线事件：驱动自动重连调度。同样先清旧监听器，避免重连链上一次断线触发多次调度。
      peripheral.removeAllListeners?.('disconnect');
      peripheral.on('disconnect', () => this.handlePeripheralDisconnect(deviceId));

      this.autoReconnect = true;
      this.setState('connected', `已连接 ${device.name || deviceId}，心率采集开始`);
      return { ok: true, status: this.state };
    } catch (err) {
      const message = String(err);
      if (this.autoReconnect) {
        // 重连流程中的失败：回到 reconnecting，由调度方续排
        this.setState('reconnecting', `连接失败：${message}`);
      } else {
        this.setState('disconnected', `连接失败：${message}`);
      }
      this.emitError(err instanceof Error ? err : new Error(message), 'connect');
      return { ok: false, status: this.state, error: message };
    }
  }

  /** 主动断开：取消自动重连、退订并断开连接。幂等。 */
  async disconnect(): Promise<BleResult> {
    this.autoReconnect = false;
    this.clearReconnectTimer();
    this.clearScanTimer();

    if (this.noble && typeof this.noble.stopScanning === 'function') {
      try {
        await this.nobleCall((cb) => this.noble?.stopScanning(cb));
      } catch {
        // 忽略
      }
    }
    this.removeDiscoverListener();

    await this.unsubscribeCharacteristic();

    const peripheral = this.peripherals.get(this.lastDeviceId ?? '');
    this.characteristic = null;
    if (peripheral) {
      await this.safeDisconnectPeripheral(peripheral);
    }

    this.setState('idle', '已断开连接');
    return { ok: true, status: this.state };
  }

  /**
   * 移除 discover 监听器并清引用。startScan 的任一终止路径（启动失败 / 正常收尾 /
   * 扫描中被 connect / disconnect 打断）都必须调用，否则监听器累积导致内存泄漏
   * 与后续扫描重复处理 discover 事件。
   */
  private removeDiscoverListener(): void {
    if (this.noble && this.discoverListener) {
      this.noble.off?.('discover', this.discoverListener);
    }
    this.discoverListener = null;
  }

  // -------------------------------------------------------------------------
  // 内部实现
  // -------------------------------------------------------------------------

  private handleDiscovered(peripheral: NoblePeripheral): void {
    if (this.state !== 'scanning') return; // 忽略扫描窗口外迟到的 discover
    if (!peripheral || typeof peripheral !== 'object') return;

    const advertisement = peripheral.advertisement ?? {};
    const serviceUuids: string[] = Array.isArray(advertisement.serviceUuids)
      ? advertisement.serviceUuids.map((u) => String(u).toLowerCase())
      : [];
    const hasHeartRate = serviceUuids.includes(HEART_RATE_SERVICE_UUID);
    const name = typeof advertisement.localName === 'string' ? advertisement.localName : '';
    const address = typeof peripheral.address === 'string' ? peripheral.address : '';
    const deviceId =
      peripheral.id !== undefined && peripheral.id !== null ? String(peripheral.id) : address || name;
    if (!deviceId) return;

    // device_name_hint 过滤（子串，忽略大小写）
    if (this.deviceNameHint && !name.toLowerCase().includes(this.deviceNameHint.toLowerCase())) {
      return;
    }

    const existing = this.devices.get(deviceId);
    const merged: BleDeviceInfo = {
      deviceId,
      name: name || existing?.name || '',
      address,
      fingerprint: makeDeviceFingerprint(name || existing?.name || '', address || deviceId),
      rssi: typeof peripheral.rssi === 'number' ? peripheral.rssi : null,
      serviceUuids,
      // 已登记过 HR 的设备不因后续广播缺 0x180D 而降级
      hasHeartRate: existing ? existing.hasHeartRate || hasHeartRate : hasHeartRate,
    };
    this.devices.set(deviceId, merged);
    this.peripherals.set(deviceId, peripheral);
  }

  private handleHrData(data: Buffer | Uint8Array): void {
    if (this.state !== 'connected') return;
    try {
      const bpm = parseHeartRateMeasurement(data);
      // 无效样本（0 或 >220）丢弃，不进入上送链
      if (bpm > 0 && bpm <= 220) {
        this.callbacks.onHr?.(bpm);
      }
    } catch (err) {
      this.emitError(err instanceof Error ? err : new Error(String(err)), 'parse-hr');
    }
  }

  private handlePeripheralDisconnect(deviceId: string): void {
    this.characteristic = null;
    if (!this.autoReconnect || this.state !== 'connected') return;
    if (deviceId !== this.lastDeviceId) return;
    this.setState('reconnecting', '连接断开，等待自动重连…');
    this.scheduleReconnect();
  }

  private scheduleReconnect(): void {
    this.clearReconnectTimer();
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      void this.reconnectOnce();
    }, this.reconnectMs);
  }

  private async reconnectOnce(): Promise<void> {
    if (this.state !== 'reconnecting' || !this.lastDeviceId || !this.autoReconnect) return;

    // 设备缓存可能已被新扫描覆盖，缺失时先补一次扫描
    if (!this.devices.has(this.lastDeviceId)) {
      // H11: 重连触发的补扫必须保留 autoReconnect（startScan 默认会关闭它）
      await this.startScan(true);
      if (!this.autoReconnect) return;
    }
    if (!this.devices.has(this.lastDeviceId)) {
      this.setState('reconnecting', '重连失败：设备未在扫描结果中');
      this.scheduleReconnect();
      return;
    }

    const result = await this.connect(this.lastDeviceId);
    if (!result.ok && this.autoReconnect) {
      this.setState('reconnecting', `重连失败：${result.error ?? ''}`);
      this.scheduleReconnect();
    }
  }

  private async subscribeCharacteristic(char: NobleCharacteristic): Promise<void> {
    // noble 提供 subscribe（通知订阅）与 notify(true) 两种入口，优先 subscribe，退化到 notify
    if (typeof char.subscribe === 'function') {
      await this.nobleCall((cb) => char.subscribe(cb));
      return;
    }
    if (typeof char.notify === 'function') {
      await this.nobleCall((cb) => char.notify(true, cb));
      return;
    }
    throw new Error('特征不支持订阅通知');
  }

  private async unsubscribeCharacteristic(): Promise<void> {
    const char = this.characteristic;
    if (!char) return;
    this.characteristic = null;
    try {
      if (typeof char.unsubscribe === 'function') {
        await this.nobleCall((cb) => char.unsubscribe(cb));
      } else if (typeof char.notify === 'function') {
        await this.nobleCall((cb) => char.notify(false, cb));
      }
    } catch {
      // 退订失败可忽略
    }
  }

  private async safeDisconnectPeripheral(peripheral: NoblePeripheral): Promise<void> {
    try {
      if (peripheral && typeof peripheral.disconnect === 'function') {
        await this.nobleCall((cb) => peripheral.disconnect(cb));
      }
    } catch {
      // 忽略
    }
  }

  private findService(services: NobleService[]): NobleService | undefined {
    return services.find((s) => String(s?.uuid ?? '').toLowerCase() === HEART_RATE_SERVICE_UUID);
  }

  private findCharacteristic(
    characteristics: NobleCharacteristic[],
  ): NobleCharacteristic | undefined {
    return characteristics.find(
      (c) => String(c?.uuid ?? '').toLowerCase() === HEART_RATE_MEASUREMENT_CHAR_UUID,
    );
  }

  /** noble 调用统一包装：兼容 callback 风格（主）与 Promise 风格（mock 兼容）。 */
  private nobleCall(
    fn: (cb: (err?: Error | null, ...args: unknown[]) => void) => unknown,
  ): Promise<unknown[]> {
    return new Promise((resolve, reject) => {
      let settled = false;
      const done = (err: Error | null, args: unknown[]): void => {
        if (settled) return;
        settled = true;
        if (err) reject(err);
        else resolve(args);
      };
      try {
        const ret = fn((err?: Error | null, ...args: unknown[]) => done(err ?? null, args));
        if (ret && typeof (ret as Promise<unknown>).then === 'function') {
          (ret as Promise<unknown>).then(() => done(null, []), (error: unknown) =>
            done(error instanceof Error ? error : new Error(String(error)), []),
          );
        }
      } catch (err) {
        done(err instanceof Error ? err : new Error(String(err)), []);
      }
    });
  }

  private setState(status: BleStatus, detail?: string): void {
    this.state = status;
    try {
      this.callbacks.onStatus?.(status, detail);
    } catch (err) {
      this.emitError(err instanceof Error ? err : new Error(String(err)), 'onStatus');
    }
  }

  private emitError(error: Error, context?: string): void {
    try {
      this.callbacks.onError?.(error, context);
    } catch {
      // 回调异常不得外泄
    }
  }

  private clearScanTimer(): void {
    if (this.scanTimer) {
      clearTimeout(this.scanTimer);
      this.scanTimer = null;
    }
    // 被打断时标记并 resolve 扫描窗口 Promise，避免 startScan 协程永久悬挂
    this.scanInterrupted = true;
    if (this.scanResolver) {
      this.scanResolver();
      this.scanResolver = null;
    }
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }
}
