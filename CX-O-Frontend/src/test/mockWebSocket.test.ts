/**
 * MockWebSocket / MockAudioContext 自身的行为锁定测试。
 *
 * 目的：
 * - 防止重构 mockWebSocket.ts 时静默破坏 hook 测试基础
 * - 验证全局安装已生效（globalThis.WebSocket / AudioContext 指向 mock）
 * - 验证静态常量与原生 WebSocket 一致（hook 代码依赖 WebSocket.OPEN 等常量）
 * - 验证事件触发器与 sentMessages 收集正确
 * - 验证 MockAudioContext 的 AudioBuffer mock 支持插值采样
 *
 * 不测试 hook 行为本身——那是 useWebSocket.test.ts / useLiveWebSocket.test.ts 的职责。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  MockWebSocket,
  MockAudioContext,
  MockAnalyserNode,
  MockMediaStreamAudioSourceNode,
  MockMediaElementAudioSourceNode,
  MockScriptProcessorNode,
  MockMediaStreamAudioDestinationNode,
  MockMediaRecorder,
  MockMediaStream,
} from './mockWebSocket';

describe('MockWebSocket', () => {
  beforeEach(() => MockWebSocket.reset());

  it('globalThis.WebSocket is installed as MockWebSocket', () => {
    expect(globalThis.WebSocket).toBe(MockWebSocket);
  });

  it('static constants match native WebSocket values', () => {
    expect(MockWebSocket.CONNECTING).toBe(0);
    expect(MockWebSocket.OPEN).toBe(1);
    expect(MockWebSocket.CLOSING).toBe(2);
    expect(MockWebSocket.CLOSED).toBe(3);
  });

  it('constructor records instance and sets url', () => {
    const ws = new MockWebSocket('ws://test/x');
    expect(ws.url).toBe('ws://test/x');
    expect(ws.readyState).toBe(MockWebSocket.CONNECTING);
    expect(MockWebSocket.instances).toContain(ws);
    expect(MockWebSocket.LAST).toBe(ws);
  });

  it('send() records messages in sentMessages', () => {
    const ws = new MockWebSocket('ws://test');
    ws.send('hello');
    ws.send(JSON.stringify({ a: 1 }));
    const buf = new ArrayBuffer(4);
    ws.send(buf);

    expect(ws.sentMessages).toHaveLength(3);
    expect(ws.sentMessages[0]).toBe('hello');
    expect(ws.sentMessages[2]).toBe(buf);
  });

  it('lastSentAsString / lastSentAsJson parse last sent message', () => {
    const ws = new MockWebSocket('ws://test');
    ws.send(JSON.stringify({ type: 'config', data: { x: 1 } }));
    expect(ws.lastSentAsString()).toBe('{"type":"config","data":{"x":1}}');
    expect(ws.lastSentAsJson<{ type: string; data: { x: number } }>()).toEqual({
      type: 'config',
      data: { x: 1 },
    });
  });

  it('lastSentAsString returns empty when last sent is ArrayBuffer', () => {
    const ws = new MockWebSocket('ws://test');
    ws.send(new ArrayBuffer(8));
    expect(ws.lastSentAsString()).toBe('');
  });

  it('triggerOpen sets readyState and invokes onopen', () => {
    const ws = new MockWebSocket('ws://test');
    const opened = vi.fn();
    ws.onopen = opened;
    expect(ws.readyState).toBe(MockWebSocket.CONNECTING);

    ws.triggerOpen();
    expect(opened).toHaveBeenCalledTimes(1);
    expect(ws.readyState).toBe(MockWebSocket.OPEN);
  });

  it('triggerMessage JSON-serializes objects and invokes onmessage', () => {
    const ws = new MockWebSocket('ws://test');
    const handler = vi.fn();
    ws.onmessage = handler;

    ws.triggerMessage({ type: 'pong' });
    expect(handler).toHaveBeenCalledTimes(1);
    expect(handler.mock.calls[0][0].data).toBe('{"type":"pong"}');
  });

  it('triggerMessage passes raw string through unchanged', () => {
    const ws = new MockWebSocket('ws://test');
    const handler = vi.fn();
    ws.onmessage = handler;

    ws.triggerMessage('raw-string');
    expect(handler.mock.calls[0][0].data).toBe('raw-string');
  });

  it('triggerMessage can pass ArrayBuffer when isArrayBuffer=true', () => {
    const ws = new MockWebSocket('ws://test');
    const handler = vi.fn();
    ws.onmessage = handler;

    const buf = new ArrayBuffer(16);
    ws.triggerMessage(buf, true);
    expect(handler.mock.calls[0][0].data).toBe(buf);
  });

  it('triggerClose sets readyState and invokes onclose with code/reason', () => {
    const ws = new MockWebSocket('ws://test');
    const closed = vi.fn();
    ws.onclose = closed;

    ws.triggerClose(1006, 'abnormal');
    expect(ws.readyState).toBe(MockWebSocket.CLOSED);
    expect(closed).toHaveBeenCalledTimes(1);
    expect(closed.mock.calls[0][0].code).toBe(1006);
    expect(closed.mock.calls[0][0].reason).toBe('abnormal');
  });

  it('triggerError invokes onerror', () => {
    const ws = new MockWebSocket('ws://test');
    const errored = vi.fn();
    ws.onerror = errored;

    ws.triggerError();
    expect(errored).toHaveBeenCalledTimes(1);
  });

  it('close() marks closed and sets readyState', () => {
    const ws = new MockWebSocket('ws://test');
    ws.triggerOpen();
    expect(ws.readyState).toBe(MockWebSocket.OPEN);

    ws.close();
    expect(ws.closed).toBe(true);
    expect(ws.readyState).toBe(MockWebSocket.CLOSED);
  });

  it('binaryType defaults to arraybuffer', () => {
    const ws = new MockWebSocket('ws://test');
    expect(ws.binaryType).toBe('arraybuffer');
  });

  it('reset() clears instances and LAST', () => {
    new MockWebSocket('ws://1');
    new MockWebSocket('ws://2');
    expect(MockWebSocket.instances).toHaveLength(2);

    MockWebSocket.reset();
    expect(MockWebSocket.instances).toHaveLength(0);
    expect(MockWebSocket.LAST).toBeNull();
  });
});

describe('MockAudioContext', () => {
  it('globalThis.AudioContext is installed as MockAudioContext', () => {
    expect(globalThis.AudioContext).toBe(MockAudioContext);
  });

  it('decodeAudioData returns a Promise<AudioBuffer>', async () => {
    const ctx = new MockAudioContext();
    const buf = await ctx.decodeAudioData(new ArrayBuffer(8));
    expect(buf).toBeDefined();
    expect(typeof buf.duration).toBe('number');
    expect(typeof buf.getChannelData).toBe('function');
  });

  it('createBuffer returns AudioBuffer with channel data', () => {
    const ctx = new MockAudioContext();
    const buf = ctx.createBuffer(1, 4800, 24000);
    expect(buf.numberOfChannels).toBe(1);
    expect(buf.length).toBe(4800);
    expect(buf.sampleRate).toBe(24000);
    expect(buf.getChannelData(0)).toBeInstanceOf(Float32Array);
  });

  it('createBufferSource returns source with connect/start/stop/onended', () => {
    const ctx = new MockAudioContext();
    const source = ctx.createBufferSource();
    expect(typeof source.connect).toBe('function');
    expect(typeof source.start).toBe('function');
    expect(typeof source.stop).toBe('function');
    expect(source.onended).toBeNull();
    expect(source.buffer).toBeNull();
  });

  it('resume sets state to running', async () => {
    const ctx = new MockAudioContext();
    ctx.state = 'suspended';
    await ctx.resume();
    expect(ctx.state).toBe('running');
  });

  it('close sets state to closed', async () => {
    const ctx = new MockAudioContext();
    await ctx.close();
    expect(ctx.state).toBe('closed');
  });

  it('currentTime starts at 0 and is mutable', () => {
    const ctx = new MockAudioContext();
    expect(ctx.currentTime).toBe(0);
    ctx.currentTime = 1.5;
    expect(ctx.currentTime).toBe(1.5);
  });

  it('source.onended fires when stop() is called (used by interrupt)', () => {
    const ctx = new MockAudioContext();
    const source = ctx.createBufferSource();
    const ended = vi.fn();
    source.onended = ended;

    source.stop();
    expect(ended).toHaveBeenCalledTimes(1);
  });
});

describe('MockAudioContext extensions (M6)', () => {
  beforeEach(() => MockAudioContext.reset());

  it('constructor captures options for assertions', () => {
    const ctx = new MockAudioContext({ latencyHint: 'interactive' });
    expect(ctx.ctorOptions).toEqual({ latencyHint: 'interactive' });
  });

  it('constructor captures sampleRate option and applies to context', () => {
    const ctx = new MockAudioContext({ sampleRate: 16000 });
    expect(ctx.sampleRate).toBe(16000);
  });

  it('static instances and LAST track created contexts', () => {
    expect(MockAudioContext.instances).toHaveLength(0);
    expect(MockAudioContext.LAST).toBeNull();
    const a = new MockAudioContext();
    const b = new MockAudioContext();
    expect(MockAudioContext.instances).toEqual([a, b]);
    expect(MockAudioContext.LAST).toBe(b);
  });

  it('reset clears instances and LAST', () => {
    new MockAudioContext();
    MockAudioContext.reset();
    expect(MockAudioContext.instances).toHaveLength(0);
    expect(MockAudioContext.LAST).toBeNull();
  });

  it('createAnalyser returns MockAnalyserNode and increments counter', () => {
    const ctx = new MockAudioContext();
    const analyser = ctx.createAnalyser();
    expect(analyser).toBeInstanceOf(MockAnalyserNode);
    expect(ctx.analysersCreated).toBe(1);
  });

  it('createMediaStreamSource returns source bound to stream', () => {
    const ctx = new MockAudioContext();
    const stream = new MockMediaStream() as unknown as MediaStream;
    const source = ctx.createMediaStreamSource(stream);
    expect(source).toBeInstanceOf(MockMediaStreamAudioSourceNode);
    expect(source.stream).toBe(stream);
    expect(ctx.streamSourcesCreated).toBe(1);
  });

  it('createMediaElementSource returns source bound to element', () => {
    const ctx = new MockAudioContext();
    const el = document.createElement('audio');
    const source = ctx.createMediaElementSource(el);
    expect(source).toBeInstanceOf(MockMediaElementAudioSourceNode);
    expect(source.mediaElement).toBe(el);
    expect(ctx.elementSourcesCreated).toBe(1);
  });

  it('createScriptProcessor returns processor with bufferSize', () => {
    const ctx = new MockAudioContext({ sampleRate: 16000 });
    const proc = ctx.createScriptProcessor(4096, 1, 1);
    expect(proc).toBeInstanceOf(MockScriptProcessorNode);
    expect(proc.bufferSize).toBe(4096);
    expect(ctx.scriptProcessorsCreated).toBe(1);
  });

  it('createMediaStreamDestination returns node with stream', () => {
    const ctx = new MockAudioContext();
    const dest = ctx.createMediaStreamDestination();
    expect(dest).toBeInstanceOf(MockMediaStreamAudioDestinationNode);
    expect(dest.stream).toBeDefined();
    expect(dest.stream.getTracks()).toHaveLength(1);
    expect(ctx.streamDestinationsCreated).toBe(1);
  });

  it('close sets closed flag', async () => {
    const ctx = new MockAudioContext();
    expect(ctx.closed).toBe(false);
    await ctx.close();
    expect(ctx.closed).toBe(true);
    expect(ctx.state).toBe('closed');
  });
});

describe('MockAnalyserNode', () => {
  it('frequencyBinCount is fftSize / 2', () => {
    const analyser = new MockAnalyserNode();
    analyser.fftSize = 256;
    expect(analyser.frequencyBinCount).toBe(128);
    analyser.fftSize = 512;
    expect(analyser.frequencyBinCount).toBe(256);
  });

  it('getByteFrequencyData fills provided array from internal data', () => {
    const analyser = new MockAnalyserNode();
    analyser.fftSize = 256;
    analyser.setFrequencyData([10, 20, 30, 40]);
    const array = new Uint8Array(4);
    analyser.getByteFrequencyData(array);
    expect(Array.from(array)).toEqual([10, 20, 30, 40]);
  });

  it('getByteFrequencyData does not overflow when array is larger than internal data', () => {
    const analyser = new MockAnalyserNode();
    analyser.setFrequencyData([1, 2]);
    const array = new Uint8Array(5);
    analyser.getByteFrequencyData(array);
    expect(array[0]).toBe(1);
    expect(array[1]).toBe(2);
  });

  it('connect tracks destination and disconnect resets', () => {
    const analyser = new MockAnalyserNode();
    const dest = { name: 'dest' };
    analyser.connect(dest);
    expect(analyser.connectedTo).toContain(dest);
    analyser.disconnect();
    expect(analyser.disconnected).toBe(true);
    expect(analyser.connectedTo).toHaveLength(0);
  });
});

describe('MockScriptProcessorNode', () => {
  it('triggerAudioProcess fires onaudioprocess with input buffer', () => {
    const proc = new MockScriptProcessorNode(4096, 16000);
    const handler = vi.fn();
    proc.onaudioprocess = handler;
    proc.triggerAudioProcess();
    expect(handler).toHaveBeenCalledTimes(1);
    expect(handler.mock.calls[0][0].inputBuffer).toBeDefined();
    expect(handler.mock.calls[0][0].outputBuffer).toBeDefined();
    expect(typeof handler.mock.calls[0][0].inputBuffer.getChannelData).toBe('function');
  });

  it('triggerAudioProcess injects custom input data', () => {
    const proc = new MockScriptProcessorNode(4096, 16000);
    const received: Float32Array[] = [];
    proc.onaudioprocess = (event) => {
      received.push(event.inputBuffer.getChannelData(0));
    };
    const customData = new Float32Array([0.1, 0.2, 0.3]);
    proc.triggerAudioProcess(customData);
    expect(received[0]).toBe(customData);
  });

  it('connect/disconnect tracks destinations', () => {
    const proc = new MockScriptProcessorNode(4096, 16000);
    const dest = { name: 'dest' };
    proc.connect(dest);
    expect(proc.connectedTo).toContain(dest);
    proc.disconnect();
    expect(proc.disconnected).toBe(true);
  });
});

describe('MockMediaRecorder', () => {
  beforeEach(() => MockMediaRecorder.reset());

  it('constructor records instance and captures mimeType', () => {
    const stream = new MockMediaStream() as unknown as MediaStream;
    const rec = new MockMediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' });
    expect(MockMediaRecorder.instances).toContain(rec);
    expect(MockMediaRecorder.LAST).toBe(rec);
    expect(rec.mimeType).toBe('audio/webm;codecs=opus');
    expect(rec.state).toBe('inactive');
  });

  it('start sets state to recording', () => {
    const rec = new MockMediaRecorder(new MockMediaStream() as unknown as MediaStream);
    rec.start(100);
    expect(rec.state).toBe('recording');
  });

  it('stop sets state to inactive and fires onstop', () => {
    const rec = new MockMediaRecorder(new MockMediaStream() as unknown as MediaStream);
    const stopHandler = vi.fn();
    rec.onstop = stopHandler;
    rec.start();
    rec.stop();
    expect(rec.state).toBe('inactive');
    expect(stopHandler).toHaveBeenCalledTimes(1);
  });

  it('triggerDataAvailable fires ondataavailable with data', () => {
    const rec = new MockMediaRecorder(new MockMediaStream() as unknown as MediaStream);
    const handler = vi.fn();
    rec.ondataavailable = handler;
    const blob = new Blob([new Uint8Array([1, 2, 3])]);
    rec.triggerDataAvailable(blob);
    expect(handler).toHaveBeenCalledTimes(1);
    expect(handler.mock.calls[0][0].data).toBe(blob);
  });

  it('reset clears instances and LAST', () => {
    new MockMediaRecorder(new MockMediaStream() as unknown as MediaStream);
    MockMediaRecorder.reset();
    expect(MockMediaRecorder.instances).toHaveLength(0);
    expect(MockMediaRecorder.LAST).toBeNull();
  });
});

describe('MockMediaStream', () => {
  it('getTracks returns tracks with stop', () => {
    const stream = new MockMediaStream(2);
    expect(stream.getTracks()).toHaveLength(2);
    expect(typeof stream.getTracks()[0].stop).toBe('function');
    expect(stream.active).toBe(true);
  });

  it('stop on one track marks stream inactive', () => {
    const stream = new MockMediaStream(1);
    stream.getTracks()[0].stop();
    expect(stream.active).toBe(false);
  });

  it('getAudioTracks returns audio-kind tracks', () => {
    const stream = new MockMediaStream(2);
    expect(stream.getAudioTracks()).toHaveLength(2);
    expect(stream.getVideoTracks()).toHaveLength(0);
  });
});
