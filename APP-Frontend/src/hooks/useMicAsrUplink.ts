/**
 * useMicAsrUplink — 麦克风采集 → Live WebSocket ASR 上行流（SubTask 4.1/4.2/4.5）。
 *
 * 链路：getUserMedia(16kHz 单声道) → AudioContext(16kHz) → Analyser →
 *       ScriptProcessor(4096) → encodePcm16(含 micGain) → Live WS 二进制帧。
 * 协议：/ws/live 二进制帧 = 裸 Int16 PCM 小端 @16kHz mono
 *       （服务端 vad_processor 以 np.frombuffer(int16) @16000 读取）。
 *
 * 口型数据源：RAF 读取本地 Analyser 频谱，仅在服务端 VAD 判定说话中
 * （speaking=true，来自 Live WS vad_status）写入 volumeRef/vowelWeightsRef，
 * 说话结束或停止采集时归零（不说话不动嘴）。
 *
 * 增益：在 PCM 编码前应用于 float 域（encodePcm16），改动即时生效，
 * 无需重建音频图；本地口型分析取增益前信号，反映真实人声电平。
 *
 * 优雅降级：浏览器/权限不可用时调用 onError 并保持非激活，不抛异常崩溃。
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import type { MutableRefObject } from 'react';

import { useAudioPipeline } from './audio/pipeline';
import { encodePcm16 } from './audio/pcm';
import { computeVowelWeights } from './useAudioAnalyzer';
import type { VowelWeights } from './useAudioAnalyzer';

export interface UseMicAsrUplinkOptions {
  /** 麦克风开关（audioStore.micEnabled） */
  enabled: boolean;
  /** 麦克风增益 0~2（audioStore.micGain） */
  gain: number;
  /** Live WS 二进制上行（未连接时由 transport 层丢弃） */
  sendAudio: (audioData: ArrayBuffer) => void;
  /** 服务端 VAD 说话状态（Live WS vad_status 事件驱动） */
  speaking: boolean;
  /** 采集启动失败回调（权限拒绝/设备不可用/浏览器不支持） */
  onError?: (message: string) => void;
}

export interface UseMicAsrUplinkReturn {
  /** 采集流已建立并正在上行 */
  isActive: boolean;
  /** 口型音量（speaking 时实时，否则 0） */
  volumeRef: MutableRefObject<number>;
  /** 口型元音权重（speaking 时实时，否则全零） */
  vowelWeightsRef: MutableRefObject<VowelWeights>;
}

const ZERO_VOWELS: VowelWeights = { a: 0, i: 0, u: 0, e: 0, o: 0 };
/** 与 useAudioAnalyzer/useTtsLipSync 同口径的归一化参数 */
const FFT_SIZE = 256;
const NORMALIZATION_FACTOR = 100;
const VOWEL_VOLUME_THRESHOLD = 0.05;
/** 4096 采样/块 @16kHz ≈ 256ms/帧，与服务端 VAD 帧长兼容 */
const SCRIPT_BUFFER_SIZE = 4096;

export function useMicAsrUplink({
  enabled,
  gain,
  sendAudio,
  speaking,
  onError,
}: UseMicAsrUplinkOptions): UseMicAsrUplinkReturn {
  const [isActive, setIsActive] = useState(false);

  const volumeRef = useRef(0);
  const vowelWeightsRef = useRef<VowelWeights>({ ...ZERO_VOWELS });

  const mediaStreamRef = useRef<MediaStream | null>(null);
  const scriptProcessorRef = useRef<ScriptProcessorNode | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const rafRef = useRef(0);
  // 竞态防护（B1）：stopCapture 发起的 closePipeline() 的 Promise；快速开关麦克风时
  // startCapture 必须先等待其完成再重建音频图，避免建在正在关闭的 AudioContext 上。
  const closingPromiseRef = useRef<Promise<void> | null>(null);

  // getUserMedia 授权弹窗期间可能被用户关闭开关或卸载组件。此时若授权弹窗 resolve，
  // 需要能读到「最新」的 enabled/卸载状态，避免无条件重建采集上行或抛 mic-start-failed。
  const mountedRef = useRef(true);
  const enabledRef = useRef(enabled);

  // 卸载兜底：组件真正卸载后置 false，阻断 async getUserMedia 的迟到续体
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const gainRef = useRef(gain);
  gainRef.current = gain;
  const sendAudioRef = useRef(sendAudio);
  sendAudioRef.current = sendAudio;
  const speakingRef = useRef(speaking);
  speakingRef.current = speaking;
  const onErrorRef = useRef(onError);
  onErrorRef.current = onError;

  const {
    audioContextRef,
    analyserRef,
    init: initPipeline,
    close: closePipeline,
    createStreamSource,
    createScriptProcessor,
    createStreamDestination,
  } = useAudioPipeline({
    audioContextOptions: { sampleRate: 16000 },
    fftSize: FFT_SIZE,
  });

  const stopLipLoop = useCallback(() => {
    if (rafRef.current) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = 0;
    }
    volumeRef.current = 0;
    vowelWeightsRef.current = { ...ZERO_VOWELS };
  }, []);

  const startLipLoop = useCallback(() => {
    const analyser = analyserRef.current;
    if (!analyser) return;
    const dataArray = new Uint8Array(analyser.frequencyBinCount);
    const tick = () => {
      const a = analyserRef.current;
      if (!a) return;
      a.getByteFrequencyData(dataArray);
      if (speakingRef.current) {
        let sum = 0;
        for (let i = 0; i < dataArray.length; i++) sum += dataArray[i];
        const volume = Math.min(sum / dataArray.length / NORMALIZATION_FACTOR, 1);
        volumeRef.current = volume;
        vowelWeightsRef.current = computeVowelWeights(dataArray, VOWEL_VOLUME_THRESHOLD, volume);
      } else {
        volumeRef.current = 0;
        vowelWeightsRef.current = { ...ZERO_VOWELS };
      }
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
  }, [analyserRef]);

  const stopCapture = useCallback(() => {
    stopLipLoop();
    if (scriptProcessorRef.current) {
      scriptProcessorRef.current.onaudioprocess = null;
      scriptProcessorRef.current.disconnect();
      scriptProcessorRef.current = null;
    }
    if (sourceRef.current) {
      sourceRef.current.disconnect();
      sourceRef.current = null;
    }
    // 竞态防护（B1）：close() 返回 Promise 且完成后才置空 audioContextRef，
    // 记录该 Promise 供后续 startCapture await，避免重建在正在关闭的 ctx 上
    closingPromiseRef.current = closePipeline();
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach((track) => track.stop());
      mediaStreamRef.current = null;
    }
    setIsActive(false);
  }, [closePipeline, stopLipLoop]);

  const startCapture = useCallback(async () => {
    if (!navigator.mediaDevices?.getUserMedia) {
      onErrorRef.current?.('media-unavailable');
      return;
    }
    // 竞态防护（B1）：快速开关麦克风——先等上一次 close 完成，再继续重建
    const prevClose = closingPromiseRef.current;
    if (prevClose) {
      await prevClose;
      closingPromiseRef.current = null;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          sampleRate: 16000,
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      // 授权弹窗期间开关可能已关闭或组件已卸载：此时不得再重建采集上行，直接停掉轨道
      if (!mountedRef.current || !enabledRef.current) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      mediaStreamRef.current = stream;

      // 竞态防护（B1）守卫：ctx 已处于 closed 态（上一轮 close 迟到/异步 finally 未跑完）
      // 时清空 refs，让 initPipeline 走完整重建路径而非幂等早退
      const staleCtx = audioContextRef.current;
      if (staleCtx && staleCtx.state === 'closed') {
        audioContextRef.current = null;
        analyserRef.current = null;
      }

      initPipeline();
      const source = createStreamSource(stream);
      const processor = createScriptProcessor(SCRIPT_BUFFER_SIZE, 1, 1);
      const destination = createStreamDestination();
      const analyser = analyserRef.current;
      if (!source || !processor || !destination || !analyser) {
        throw new Error('audio pipeline init failed');
      }

      processor.onaudioprocess = (event) => {
        const input = event.inputBuffer.getChannelData(0);
        const pcm = encodePcm16(input, gainRef.current);
        sendAudioRef.current(pcm.buffer);
      };

      source.connect(analyser);
      analyser.connect(processor);
      processor.connect(destination);
      sourceRef.current = source;
      scriptProcessorRef.current = processor;

      // AudioContext 可能因自动播放策略处于 suspended，采集前主动恢复
      if (audioContextRef.current?.state === 'suspended') {
        void audioContextRef.current.resume();
      }

      startLipLoop();
      setIsActive(true);
    } catch (e) {
      console.error('[useMicAsrUplink] Failed to start microphone:', e);
      stopCapture();
      onErrorRef.current?.('mic-start-failed');
    }
  }, [
    initPipeline,
    createStreamSource,
    createScriptProcessor,
    createStreamDestination,
    analyserRef,
    audioContextRef,
    startLipLoop,
    stopCapture,
  ]);

  // 开关联动：enabled 翻转驱动采集启停；卸载兜底清理
  useEffect(() => {
    enabledRef.current = enabled;
    if (enabled) {
      void startCapture();
    } else {
      stopCapture();
    }
    return () => stopCapture();
  }, [enabled, startCapture, stopCapture]);

  return { isActive, volumeRef, vowelWeightsRef };
}

export default useMicAsrUplink;
