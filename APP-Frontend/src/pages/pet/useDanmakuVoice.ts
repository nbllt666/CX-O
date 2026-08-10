/**
 * useDanmakuVoice — 弹幕语音播报（SubTask 4.4）。
 *
 * 链路：Live WS danmaku 事件 →（开关开）→ 播报队列 → POST /api/tts {text}
 *       → 二进制音频 decodeAudioData → source → analyser → gain(ttsVolume) → destination
 *       → RAF 读 analyser 频谱写 volumeRef/vowelWeightsRef 驱动口型。
 *
 * 协议决策：本地触发（前端拿到弹幕文本直接调 /api/tts），与参考前端
 * audio 客户端 textToSpeech 端点一致；不经 Live WS 额外消息。
 *
 * 队列：FIFO 容量 3，超限丢弃最旧（danmakuSpeechQueue）。
 * 开关关闭：立即清空待播队列并打断当前播报。
 * 优雅降级：/api/tts 失败（网络/合成错误）跳过该条继续下一条，不崩溃。
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import type { MutableRefObject } from 'react';

import { audioApi } from '../../api/clients/audio';
import type { LiveDanmakuData } from '../../hooks/useLiveWebSocket';
import { computeVowelWeights } from '../../hooks/useAudioAnalyzer';
import type { VowelWeights } from '../../hooks/useAudioAnalyzer';
import { DanmakuSpeechQueue } from './danmakuSpeechQueue';

export interface UseDanmakuVoiceOptions {
  /** 弹幕语音播报开关（audioStore.danmakuVoiceEnabled） */
  enabled: boolean;
  /** 播放音量 0~1（audioStore.ttsVolume，与对话 TTS 同一音量口径） */
  volume: number;
  /** 弹幕 → 播报文本（默认 "昵称: 内容"） */
  formatText?: (data: LiveDanmakuData) => string;
  /** 单条开始播报时回调（PetPage 用来落气泡） */
  onSpeakStart?: (text: string) => void;
}

export interface UseDanmakuVoiceReturn {
  /** Live WS onDanmaku 入口：开关开时入队 */
  notifyDanmaku: (data: LiveDanmakuData) => void;
  /** 正在播报 */
  isPlaying: boolean;
  volumeRef: MutableRefObject<number>;
  vowelWeightsRef: MutableRefObject<VowelWeights>;
}

const ZERO_VOWELS: VowelWeights = { a: 0, i: 0, u: 0, e: 0, o: 0 };
const FFT_SIZE = 256;
const NORMALIZATION_FACTOR = 100;
const VOWEL_VOLUME_THRESHOLD = 0.05;

function defaultFormat(data: LiveDanmakuData): string {
  const name = data.username?.trim();
  return name ? `${name}: ${data.content}` : data.content;
}

export function useDanmakuVoice({
  enabled,
  volume,
  formatText,
  onSpeakStart,
}: UseDanmakuVoiceOptions): UseDanmakuVoiceReturn {
  const [isPlaying, setIsPlaying] = useState(false);

  const volumeRef = useRef(0);
  const vowelWeightsRef = useRef<VowelWeights>({ ...ZERO_VOWELS });

  const queueRef = useRef(new DanmakuSpeechQueue());
  const ctxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const gainNodeRef = useRef<GainNode | null>(null);
  const activeSourceRef = useRef<AudioBufferSourceNode | null>(null);
  const speakingRef = useRef(false);
  const rafRef = useRef(0);

  const enabledRef = useRef(enabled);
  enabledRef.current = enabled;
  const volumeStoreRef = useRef(volume);
  volumeStoreRef.current = volume;
  const formatTextRef = useRef(formatText);
  formatTextRef.current = formatText;
  const onSpeakStartRef = useRef(onSpeakStart);
  onSpeakStartRef.current = onSpeakStart;

  const stopLipLoop = useCallback(() => {
    if (rafRef.current) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = 0;
    }
    volumeRef.current = 0;
    vowelWeightsRef.current = { ...ZERO_VOWELS };
  }, []);

  const startLipLoop = useCallback(() => {
    if (rafRef.current) return;
    const dataArray = new Uint8Array(FFT_SIZE / 2);
    const tick = () => {
      const analyser = analyserRef.current;
      if (analyser && speakingRef.current) {
        analyser.getByteFrequencyData(dataArray);
        let sum = 0;
        for (let i = 0; i < dataArray.length; i++) sum += dataArray[i];
        const v = Math.min(sum / dataArray.length / NORMALIZATION_FACTOR, 1);
        volumeRef.current = v;
        vowelWeightsRef.current = computeVowelWeights(dataArray, VOWEL_VOLUME_THRESHOLD, v);
      } else {
        volumeRef.current = 0;
        vowelWeightsRef.current = { ...ZERO_VOWELS };
      }
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
  }, []);

  const ensureGraph = useCallback((): AudioContext => {
    if (!ctxRef.current || ctxRef.current.state === 'closed') {
      const ctx = new AudioContext();
      const analyser = ctx.createAnalyser();
      analyser.fftSize = FFT_SIZE;
      analyser.smoothingTimeConstant = 0.8;
      const gainNode = ctx.createGain();
      gainNode.gain.value = volumeStoreRef.current;
      analyser.connect(gainNode);
      gainNode.connect(ctx.destination);
      ctxRef.current = ctx;
      analyserRef.current = analyser;
      gainNodeRef.current = gainNode;
    }
    if (ctxRef.current.state === 'suspended') {
      void ctxRef.current.resume();
    }
    return ctxRef.current;
  }, []);

  // 音量实时生效（增益节点在 analyser 下游，不影响口型分析）
  useEffect(() => {
    if (gainNodeRef.current) {
      gainNodeRef.current.gain.value = volume;
    }
  }, [volume]);

  const playNext = useCallback(async () => {
    if (speakingRef.current) return;
    const item = queueRef.current.dequeue();
    if (!item) {
      setIsPlaying(false);
      return;
    }
    speakingRef.current = true;
    setIsPlaying(true);
    try {
      const blob = await audioApi.textToSpeech(item.text);
      const arrayBuffer = await blob.arrayBuffer();
      const ctx = ensureGraph();
      const audioBuffer = await ctx.decodeAudioData(arrayBuffer);
      // 等待合成期间开关被关闭：丢弃本次播报
      if (!enabledRef.current) {
        speakingRef.current = false;
        setIsPlaying(false);
        return;
      }
      onSpeakStartRef.current?.(item.text);
      const source = ctx.createBufferSource();
      source.buffer = audioBuffer;
      source.connect(analyserRef.current!);
      activeSourceRef.current = source;
      startLipLoop();
      source.onended = () => {
        activeSourceRef.current = null;
        speakingRef.current = false;
        void playNext();
      };
      source.start();
    } catch (e) {
      // 合成/网络失败：跳过该条继续下一条
      console.warn('[useDanmakuVoice] TTS failed, skip item:', e);
      speakingRef.current = false;
      void playNext();
    }
  }, [ensureGraph, startLipLoop]);

  const notifyDanmaku = useCallback(
    (data: LiveDanmakuData) => {
      if (!enabledRef.current) return;
      const text = (formatTextRef.current ?? defaultFormat)(data).trim();
      if (!text) return;
      queueRef.current.enqueue({ id: data.id, text });
      void playNext();
    },
    [playNext],
  );

  // 开关关闭：立即清空待播 + 打断当前播报 + 口型归零
  useEffect(() => {
    if (!enabled) {
      queueRef.current.clear();
      if (activeSourceRef.current) {
        try {
          activeSourceRef.current.stop();
        } catch {
          // 源可能已自然结束
        }
        activeSourceRef.current = null;
      }
      speakingRef.current = false;
      setIsPlaying(false);
      stopLipLoop();
    }
  }, [enabled, stopLipLoop]);

  // 卸载：释放音频资源
  useEffect(() => {
    return () => {
      stopLipLoop();
      if (activeSourceRef.current) {
        try {
          activeSourceRef.current.stop();
        } catch {
          /* 已结束 */
        }
      }
      if (ctxRef.current && ctxRef.current.state !== 'closed') {
        void ctxRef.current.close();
      }
      ctxRef.current = null;
      analyserRef.current = null;
      gainNodeRef.current = null;
    };
  }, [stopLipLoop]);

  return { notifyDanmaku, isPlaying, volumeRef, vowelWeightsRef };
}

export default useDanmakuVoice;
