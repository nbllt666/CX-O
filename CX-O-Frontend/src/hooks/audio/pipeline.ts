/**
 * useAudioPipeline — AudioContext + Analyser 生命周期管理工厂。
 *
 * 设计类比 useWSTransport：将三个音频 hook（useMicrophone / useAudioStream /
 * useAudioAnalyzer）共享的 AudioContext 构造、Analyser 配置、节点工厂、
 * close 清理逻辑抽取为公共工厂。caller 负责何时 init/close、如何连接节点、
 * 以及分析计算（RAF/setInterval/MediaRecorder）。
 *
 * 不管理：source node 的连接关系、分析循环、MediaRecorder、ScriptProcessor 回调。
 * 这些是 caller 专属逻辑，工厂只提供 AudioContext/Analyser 的生命周期。
 */
import { useRef, useCallback, useEffect } from 'react';

export interface UseAudioPipelineOptions {
  /** AudioContext 构造参数（latencyHint / sampleRate 等） */
  audioContextOptions?: AudioContextOptions;
  /** Analyser.fftSize，默认 256 */
  fftSize?: number;
  /** Analyser.smoothingTimeConstant，默认 0.8 */
  smoothingTimeConstant?: number;
}

export interface UseAudioPipelineReturn {
  audioContextRef: React.MutableRefObject<AudioContext | null>;
  analyserRef: React.MutableRefObject<AnalyserNode | null>;
  /** 创建 AudioContext + Analyser。幂等：若已初始化则为 no-op。 */
  init: () => void;
  /** 关闭 AudioContext 并清空 refs。幂等：若已关闭则为 no-op。 */
  close: () => void;
  /** 创建 MediaStreamAudioSourceNode（未 init 时返回 null） */
  createStreamSource: (stream: MediaStream) => MediaStreamAudioSourceNode | null;
  /** 创建 MediaElementAudioSourceNode（未 init 时返回 null） */
  createElementSource: (el: HTMLAudioElement) => MediaElementAudioSourceNode | null;
  /** 创建 ScriptProcessorNode（未 init 时返回 null） */
  createScriptProcessor: (
    bufferSize: number,
    inputChannels?: number,
    outputChannels?: number,
  ) => ScriptProcessorNode | null;
  /** 创建 MediaStreamAudioDestinationNode（未 init 时返回 null） */
  createStreamDestination: () => MediaStreamAudioDestinationNode | null;
}

export function useAudioPipeline(
  options: UseAudioPipelineOptions = {},
): UseAudioPipelineReturn {
  const { audioContextOptions, fftSize = 256, smoothingTimeConstant = 0.8 } = options;

  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);

  // Store options in refs so init/close and node factories have stable identity
  const optsRef = useRef({ audioContextOptions, fftSize, smoothingTimeConstant });
  optsRef.current = { audioContextOptions, fftSize, smoothingTimeConstant };

  const init = useCallback(() => {
    if (audioContextRef.current) return;

    const { audioContextOptions: ctxOpts, fftSize: fft, smoothingTimeConstant: stc } =
      optsRef.current;
    const AudioContextClass =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    const ctx = new AudioContextClass(ctxOpts);
    audioContextRef.current = ctx;

    const analyser = ctx.createAnalyser();
    analyser.fftSize = fft;
    analyser.smoothingTimeConstant = stc;
    analyserRef.current = analyser;
  }, []);

  const close = useCallback(() => {
    if (audioContextRef.current) {
      audioContextRef.current.close().catch(() => {});
      audioContextRef.current = null;
    }
    analyserRef.current = null;
  }, []);

  const createStreamSource = useCallback(
    (stream: MediaStream): MediaStreamAudioSourceNode | null => {
      return audioContextRef.current?.createMediaStreamSource(stream) ?? null;
    },
    [],
  );

  const createElementSource = useCallback(
    (el: HTMLAudioElement): MediaElementAudioSourceNode | null => {
      return audioContextRef.current?.createMediaElementSource(el) ?? null;
    },
    [],
  );

  const createScriptProcessor = useCallback(
    (
      bufferSize: number,
      inputChannels: number = 1,
      outputChannels: number = 1,
    ): ScriptProcessorNode | null => {
      return (
        audioContextRef.current?.createScriptProcessor(
          bufferSize,
          inputChannels,
          outputChannels,
        ) ?? null
      );
    },
    [],
  );

  const createStreamDestination = useCallback(
    (): MediaStreamAudioDestinationNode | null => {
      return audioContextRef.current?.createMediaStreamDestination() ?? null;
    },
    [],
  );

  useEffect(() => {
    return () => close();
  }, [close]);

  return {
    audioContextRef,
    analyserRef,
    init,
    close,
    createStreamSource,
    createElementSource,
    createScriptProcessor,
    createStreamDestination,
  };
}
