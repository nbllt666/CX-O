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

/**
 * AnalyserNode mock — supports fftSize, smoothingTimeConstant, frequencyBinCount,
 * getByteFrequencyData, getByteTimeDomainData, connect/disconnect.
 * Tests can call setFrequencyData([...]) to control what getByteFrequencyData reports.
 */
export class MockAnalyserNode {
  fftSize: number = 2048;
  smoothingTimeConstant: number = 0.8;
  minDecibels: number = -100;
  maxDecibels: number = -30;
  connectedTo: unknown[] = [];
  disconnected = false;
  private _frequencyData: Uint8Array = new Uint8Array(1024);
  private _timeDomainData: Uint8Array = new Uint8Array(2048);

  get frequencyBinCount(): number {
    return this.fftSize / 2;
  }

  connect(dest: unknown): unknown {
    this.connectedTo.push(dest);
    return dest;
  }

  disconnect(): void {
    this.disconnected = true;
    this.connectedTo = [];
  }

  getByteFrequencyData(array: Uint8Array): void {
    const len = Math.min(array.length, this._frequencyData.length);
    for (let i = 0; i < len; i++) array[i] = this._frequencyData[i];
  }

  getByteTimeDomainData(array: Uint8Array): void {
    const len = Math.min(array.length, this._timeDomainData.length);
    for (let i = 0; i < len; i++) array[i] = this._timeDomainData[i];
  }

  setFrequencyData(data: number[] | Uint8Array): void {
    this._frequencyData = data instanceof Uint8Array ? data : new Uint8Array(data);
  }
}

export class MockMediaStreamAudioSourceNode {
  stream: MediaStream;
  connectedTo: unknown[] = [];
  disconnected = false;
  constructor(stream: MediaStream) {
    this.stream = stream;
  }
  connect(dest: unknown): unknown {
    this.connectedTo.push(dest);
    return dest;
  }
  disconnect(): void {
    this.disconnected = true;
    this.connectedTo = [];
  }
}

export class MockMediaElementAudioSourceNode {
  mediaElement: HTMLAudioElement;
  connectedTo: unknown[] = [];
  disconnected = false;
  constructor(mediaElement: HTMLAudioElement) {
    this.mediaElement = mediaElement;
  }
  connect(dest: unknown): unknown {
    this.connectedTo.push(dest);
    return dest;
  }
  disconnect(): void {
    this.disconnected = true;
    this.connectedTo = [];
  }
}

/**
 * ScriptProcessorNode mock — supports onaudioprocess callback, connect/disconnect,
 * and a triggerAudioProcess() test helper to fire onaudioprocess with custom input.
 */
export class MockScriptProcessorNode {
  bufferSize: number;
  onaudioprocess: ((event: { inputBuffer: MockAudioBuffer; outputBuffer: MockAudioBuffer }) => void) | null = null;
  connectedTo: unknown[] = [];
  disconnected = false;
  private _inputBuffer: MockAudioBuffer;
  private _outputBuffer: MockAudioBuffer;

  constructor(bufferSize: number, sampleRate: number = 44100) {
    this.bufferSize = bufferSize;
    const makeBuffer = (): MockAudioBuffer => ({
      length: bufferSize,
      duration: bufferSize / sampleRate,
      numberOfChannels: 1,
      sampleRate,
      getChannelData: () => new Float32Array(bufferSize),
    });
    this._inputBuffer = makeBuffer();
    this._outputBuffer = makeBuffer();
  }

  connect(dest: unknown): unknown {
    this.connectedTo.push(dest);
    return dest;
  }

  disconnect(): void {
    this.disconnected = true;
    this.connectedTo = [];
  }

  triggerAudioProcess(inputData?: Float32Array): void {
    if (inputData) {
      this._inputBuffer = {
        ...this._inputBuffer,
        getChannelData: () => inputData,
      };
    }
    this.onaudioprocess?.({ inputBuffer: this._inputBuffer, outputBuffer: this._outputBuffer });
  }
}

/**
 * MediaStreamAudioDestinationNode mock — exposes a stream with stoppable tracks
 * for MediaRecorder and cleanup.
 */
export class MockMediaStreamAudioDestinationNode {
  stream: MediaStream;
  connectedTo: unknown[] = [];
  disconnected = false;
  constructor() {
    const stop = (): void => {};
    this.stream = {
      getTracks: () => [{ stop, kind: 'audio' }],
      getAudioTracks: () => [{ stop, kind: 'audio' }],
      getVideoTracks: () => [],
    } as unknown as MediaStream;
  }
  connect(dest: unknown): unknown {
    this.connectedTo.push(dest);
    return dest;
  }
  disconnect(): void {
    this.disconnected = true;
    this.connectedTo = [];
  }
}

/**
 * MediaRecorder mock — captures start/stop state and lets tests fire ondataavailable.
 */
export class MockMediaRecorder {
  static instances: MockMediaRecorder[] = [];
  static LAST: MockMediaRecorder | null = null;

  stream: MediaStream;
  mimeType: string;
  state: 'inactive' | 'recording' | 'paused' = 'inactive';
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onerror: ((event: unknown) => void) | null = null;
  onstop: (() => void) | null = null;

  constructor(stream: MediaStream, options?: { mimeType?: string }) {
    this.stream = stream;
    this.mimeType = options?.mimeType ?? 'audio/webm;codecs=opus';
    MockMediaRecorder.instances.push(this);
    MockMediaRecorder.LAST = this;
  }

  start(timeslice?: number): void {
    this.state = 'recording';
    void timeslice;
  }

  stop(): void {
    this.state = 'inactive';
    this.onstop?.();
  }

  pause(): void {
    this.state = 'paused';
  }

  resume(): void {
    this.state = 'recording';
  }

  triggerDataAvailable(data: Blob): void {
    this.ondataavailable?.({ data });
  }

  static reset(): void {
    MockMediaRecorder.instances = [];
    MockMediaRecorder.LAST = null;
  }
}

export class MockAudioContext {
  static instances: MockAudioContext[] = [];
  static LAST: MockAudioContext | null = null;

  currentTime = 0;
  state: 'running' | 'suspended' | 'closed' = 'running';
  destination: unknown = {};
  sampleRate: number = 44100;
  decodedCount = 0;
  sourcesCreated = 0;
  analysersCreated = 0;
  streamSourcesCreated = 0;
  elementSourcesCreated = 0;
  scriptProcessorsCreated = 0;
  streamDestinationsCreated = 0;
  /** Constructor options captured for test assertions (e.g., latencyHint / sampleRate). */
  ctorOptions: Record<string, unknown> = {};
  closed = false;
  /** Last created nodes — test helpers for triggering events. */
  lastAnalyser: MockAnalyserNode | null = null;
  lastScriptProcessor: MockScriptProcessorNode | null = null;

  constructor(options?: AudioContextOptions) {
    if (options) {
      this.ctorOptions = options as Record<string, unknown>;
      if (typeof options.sampleRate === 'number') {
        this.sampleRate = options.sampleRate;
      }
    }
    MockAudioContext.instances.push(this);
    MockAudioContext.LAST = this;
  }

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

  createAnalyser(): MockAnalyserNode {
    this.analysersCreated++;
    const node = new MockAnalyserNode();
    this.lastAnalyser = node;
    return node;
  }

  createMediaStreamSource(stream: MediaStream): MockMediaStreamAudioSourceNode {
    this.streamSourcesCreated++;
    return new MockMediaStreamAudioSourceNode(stream);
  }

  createMediaElementSource(audioElement: HTMLAudioElement): MockMediaElementAudioSourceNode {
    this.elementSourcesCreated++;
    return new MockMediaElementAudioSourceNode(audioElement);
  }

  createScriptProcessor(bufferSize: number, _inputChannels: number, _outputChannels: number): MockScriptProcessorNode {
    this.scriptProcessorsCreated++;
    const node = new MockScriptProcessorNode(bufferSize, this.sampleRate);
    this.lastScriptProcessor = node;
    return node;
  }

  createMediaStreamDestination(): MockMediaStreamAudioDestinationNode {
    this.streamDestinationsCreated++;
    return new MockMediaStreamAudioDestinationNode();
  }

  resume(): Promise<void> {
    this.state = 'running';
    return Promise.resolve();
  }

  close(): Promise<void> {
    this.state = 'closed';
    this.closed = true;
    return Promise.resolve();
  }

  static reset(): void {
    MockAudioContext.instances = [];
    MockAudioContext.LAST = null;
  }
}

/**
 * Mock MediaStream returned by navigator.mediaDevices.getUserMedia.
 * Tracks tracks-stopped for cleanup assertions.
 */
export class MockMediaStream {
  tracks: { stop: () => void; kind: string; enabled: boolean; readyState: 'live' | 'ended' }[];
  active = true;
  id = 'mock-stream';

  constructor(trackCount = 1) {
    this.tracks = Array.from({ length: trackCount }, () => ({
      stop: (): void => {
        this.tracks.forEach((t) => (t.readyState = 'ended'));
        this.active = false;
      },
      kind: 'audio',
      enabled: true,
      readyState: 'live' as const,
    }));
  }

  getTracks(): { stop: () => void; kind: string; enabled: boolean; readyState: 'live' | 'ended' }[] {
    return this.tracks;
  }

  getAudioTracks() {
    return this.tracks.filter((t) => t.kind === 'audio');
  }

  getVideoTracks() {
    return this.tracks.filter((t) => t.kind === 'video');
  }
}

export function installWebSocketMocks(): void {
  globalThis.WebSocket = MockWebSocket as unknown as typeof WebSocket;
  globalThis.AudioContext = MockAudioContext as unknown as typeof AudioContext;
  (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext =
    MockAudioContext as unknown as typeof AudioContext;
  globalThis.MediaRecorder = MockMediaRecorder as unknown as typeof MediaRecorder;

  // navigator.mediaDevices.getUserMedia mock — returns a MockMediaStream.
  if (!navigator.mediaDevices) {
    Object.defineProperty(navigator, 'mediaDevices', {
      value: {
        getUserMedia: (): Promise<MediaStream> =>
          Promise.resolve(new MockMediaStream() as unknown as MediaStream),
      },
      writable: true,
    });
  } else {
    navigator.mediaDevices.getUserMedia = (): Promise<MediaStream> =>
      Promise.resolve(new MockMediaStream() as unknown as MediaStream);
  }
}

export function resetWebSocketMocks(): void {
  MockWebSocket.reset();
  MockAudioContext.reset();
  MockMediaRecorder.reset();
}
