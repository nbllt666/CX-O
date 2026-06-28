import { useState, useRef, useCallback, useEffect } from 'react';

export interface UseMicrophoneOptions {
  /** 额外的音频约束（如 deviceId、echoCancellation 等） */
  constraints?: MediaTrackConstraints;
  /** 录音数据回调 */
  onDataAvailable?: (data: ArrayBuffer) => void;
  /** 麦克风开启前的异步回调，可用于设备枚举/AEC 探测等；返回值将合并到 constraints */
  onBeforeStart?: () => Promise<MediaTrackConstraints | void>;
  /** 额外的音频节点工厂，返回的节点会被插入 source → ... → analyser → dest 链路 */
  createExtraNodes?: (
    ctx: AudioContext,
    source: MediaStreamAudioSourceNode,
  ) => {
    /** 最后一个连接到 analyser 的节点（默认为 source） */
    lastNode: AudioNode;
    /** 需要连接到 ctx.destination 的输出节点（可选） */
    outputNode?: AudioNode;
  };
}

export interface UseMicrophoneReturn {
  isEnabled: boolean;
  currentLevel: number;
  toggle: () => Promise<void>;
  cleanup: () => void;
  audioContextRef: React.MutableRefObject<AudioContext | null>;
  analyserRef: React.MutableRefObject<AnalyserNode | null>;
}

export function useMicrophone(options: UseMicrophoneOptions = {}): UseMicrophoneReturn {
  const { constraints = {}, onDataAvailable, onBeforeStart, createExtraNodes } = options;

  const [isEnabled, setIsEnabled] = useState(false);
  const [currentLevel, setCurrentLevel] = useState(0);

  const streamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const rafRef = useRef<number>(0);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);

  const cleanup = useCallback(() => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
      mediaRecorderRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    if (audioContextRef.current) {
      audioContextRef.current.close().catch(() => {});
      audioContextRef.current = null;
    }
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    setCurrentLevel(0);
  }, []);

  const startMonitoring = useCallback(() => {
    if (!analyserRef.current) return;
    const dataArray = new Uint8Array(analyserRef.current.frequencyBinCount);
    const updateLevel = () => {
      if (analyserRef.current) {
        analyserRef.current.getByteFrequencyData(dataArray);
        const avg = dataArray.reduce((a, b) => a + b, 0) / dataArray.length;
        setCurrentLevel(Math.min(avg / 128, 1));
      }
      rafRef.current = requestAnimationFrame(updateLevel);
    };
    updateLevel();
  }, []);

  const toggle = useCallback(async () => {
    if (isEnabled) {
      cleanup();
      setIsEnabled(false);
      return;
    }

    try {
      // 允许调用方在开启前执行设备枚举/AEC 探测等，并动态调整约束
      const extraConstraints = (await onBeforeStart?.()) ?? {};
      const mergedConstraints: MediaTrackConstraints = {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
        ...constraints,
        ...extraConstraints,
      };

      const stream = await navigator.mediaDevices.getUserMedia({
        audio: mergedConstraints,
      });
      streamRef.current = stream;

      const ctx = new AudioContext({ latencyHint: 'interactive' });
      audioContextRef.current = ctx;

      const source = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0.8;
      analyserRef.current = analyser;

      const dest = ctx.createMediaStreamDestination();

      // 允许调用方插入额外音频节点（如增益节点）
      if (createExtraNodes) {
        const { lastNode, outputNode } = createExtraNodes(ctx, source);
        lastNode.connect(analyser);
        if (outputNode) {
          analyser.connect(outputNode);
          outputNode.connect(ctx.destination);
        }
      } else {
        source.connect(analyser);
      }

      analyser.connect(dest);

      const processor = new MediaRecorder(dest.stream, { mimeType: 'audio/webm;codecs=opus' });
      mediaRecorderRef.current = processor;
      processor.ondataavailable = (e) => {
        if (e.data.size > 0 && onDataAvailable) {
          e.data.arrayBuffer().then((buf) => onDataAvailable(buf)).catch(console.error);
        }
      };
      processor.start(100);

      startMonitoring();
      setIsEnabled(true);
    } catch (e) {
      console.error('[useMicrophone] Failed to start microphone:', e);
      setIsEnabled(false);
    }
  }, [isEnabled, constraints, onDataAvailable, onBeforeStart, createExtraNodes, cleanup, startMonitoring]);

  // 组件卸载时自动清理
  useEffect(() => {
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      cleanup();
    };
  }, [cleanup]);

  return {
    isEnabled,
    currentLevel,
    toggle,
    cleanup,
    audioContextRef,
    analyserRef,
  };
}
