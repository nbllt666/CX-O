/**
 * WebSocket + AudioContext 测试替身。
 *
 * 设计目标：
 * - 在 vitest/jsdom 中替换全局 `WebSocket` 与 `AudioContext`，
 *   让 useWebSocket / useLiveWebSocket 跑真实代码路径而不依赖网络。
 * - 暴露静态 `instances` / `LAST` / `reset` 让测试可定位最近一次连接、
 *   主动触发 onopen/onmessage/onclose/onerror 事件，并断言 sentMessages。
 *
 * 不模拟重连退避的真实定时器——测试用 vi.useFakeTimers 推进。
 */

type Listener<E = Event> = (ev: E) => void;

export type MockWsSent = string | ArrayBuffer | Blob;

export class MockWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  static instances: MockWebSocket[] = [];
  static LAST: MockWebSocket | null = null;

  url: string;
  binaryType: 'arraybuffer' | 'blob' = 'arraybuffer';
  readyState: number = MockWebSocket.CONNECTING;

  onopen: Listener | null = null;
  onclose: Listener<CloseEvent> | null = null;
  onerror: Listener | null = null;
  onmessage: Listener<MessageEvent> | null = null;

  sentMessages: MockWsSent[] = [];
  closed = false;

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
    MockWebSocket.LAST = this;
  }

  send(data: MockWsSent): void {
    this.sentMessages.push(data);
  }

  close(): void {
    this.readyState = MockWebSocket.CLOSED;
    this.closed = true;
  }

  triggerOpen(): void {
    this.readyState = MockWebSocket.OPEN;
    this.onopen?.(new Event('open'));
  }

  triggerMessage(data: unknown, isArrayBuffer = false): void {
    let payload: string | ArrayBuffer;
    if (isArrayBuffer) {
      payload = data as ArrayBuffer;
    } else if (typeof data === 'string') {
      payload = data;
    } else {
      payload = JSON.stringify(data);
    }
    this.onmessage?.({ data: payload } as MessageEvent);
  }

  triggerClose(code = 1000, reason = ''): void {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.(new CloseEvent('close', { code, reason, wasClean: true }));
  }

  triggerError(): void {
    this.onerror?.(new Event('error'));
  }

  lastSentAsString(): string {
    const last = this.sentMessages[this.sentMessages.length - 1];
    return typeof last === 'string' ? last : '';
  }

  lastSentAsJson<T = unknown>(): T {
    return JSON.parse(this.lastSentAsString()) as T;
  }

  static reset(): void {
    MockWebSocket.instances = [];
    MockWebSocket.LAST = null;
  }
}

interface MockAudioBuffer {
  length: number;
  duration: number;
  numberOfChannels: number;
  sampleRate: number;
  getChannelData: (channel: number) => Float32Array;
}

class MockAudioBufferSourceNode {
  buffer: MockAudioBuffer | null = null;
  onended: (() => void) | null = null;
  connected = false;
  started = false;
  startWhen = 0;

  connect(_dest: unknown): void {
    this.connected = true;
  }

  start(when: number = 0): void {
    this.started = true;
    this.startWhen = when;
  }

  stop(): void {
    if (this.onended) this.onended();
  }
}

export class MockAudioContext {
  currentTime = 0;
  state: 'running' | 'suspended' | 'closed' = 'running';
  destination: unknown = {};
  decodedCount = 0;
  sourcesCreated = 0;

  decodeAudioData(_buf: ArrayBuffer): Promise<MockAudioBuffer> {
    this.decodedCount++;
    const length = 4800;
    const buffer: MockAudioBuffer = {
      length,
      duration: 0.2,
      numberOfChannels: 1,
      sampleRate: 24000,
      getChannelData: () => new Float32Array(length),
    };
    return Promise.resolve(buffer);
  }

  createBuffer(channels: number, length: number, sampleRate: number): MockAudioBuffer {
    return {
      length,
      duration: length / sampleRate,
      numberOfChannels: channels,
      sampleRate,
      getChannelData: () => new Float32Array(length),
    };
  }

  createBufferSource(): MockAudioBufferSourceNode {
    this.sourcesCreated++;
    return new MockAudioBufferSourceNode();
  }

  resume(): Promise<void> {
    this.state = 'running';
    return Promise.resolve();
  }

  close(): Promise<void> {
    this.state = 'closed';
    return Promise.resolve();
  }
}

export function installWebSocketMocks(): void {
  globalThis.WebSocket = MockWebSocket as unknown as typeof WebSocket;
  globalThis.AudioContext = MockAudioContext as unknown as typeof AudioContext;
}

export function resetWebSocketMocks(): void {
  MockWebSocket.reset();
}
