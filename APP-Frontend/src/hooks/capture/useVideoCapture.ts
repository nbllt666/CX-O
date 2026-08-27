/**
 * useVideoCapture — 屏幕共享 / 摄像头采集生命周期（SubTask 4.6/4.7）。
 *
 * - 屏幕：Electron 渲染层 getDisplayMedia（主进程 setDisplayMediaRequestHandler
 *   授权首个屏幕源，见 electron/main.ts）；浏览器模式同源 API 弹系统选择器。
 * - 摄像头：getUserMedia({ video: true })。
 * - 默认关闭（captureStore 不持久化 active）；active 翻转驱动启停；
 *   关闭立即停止全部 track 并释放 video/canvas 资源。
 * - captureFrame：隐藏 video 当前帧 → canvas（最长边缩至 1280）→ JPEG dataURL，
 *   供画面帧发送链路上行。
 * - 优雅降级：mediaDevices 不可用 / 权限拒绝 → onError 提示，isCapturing 保持 false。
 */
import { useCallback, useEffect, useRef, useState } from 'react';

export type CaptureSourceKind = 'screen' | 'camera';

export interface UseVideoCaptureOptions {
  kind: CaptureSourceKind;
  /** 采集开关（captureStore.screenActive / cameraActive） */
  active: boolean;
  onError?: (kind: CaptureSourceKind) => void;
  /** 系统级停止（如浏览器「停止共享」按钮）：caller 回写 store 开关为 false */
  onEnded?: (kind: CaptureSourceKind) => void;
}

export interface UseVideoCaptureReturn {
  isCapturing: boolean;
  /** 抓取当前帧为 JPEG dataURL；未就绪/未采集时返回 null */
  captureFrame: () => string | null;
}

/** 帧最长边上限：控制 dataURL 体积，避免持续占用带宽 */
const MAX_FRAME_EDGE = 1280;
const JPEG_QUALITY = 0.7;

export function useVideoCapture({
  kind,
  active,
  onError,
  onEnded,
}: UseVideoCaptureOptions): UseVideoCaptureReturn {
  const [isCapturing, setIsCapturing] = useState(false);

  const streamRef = useRef<MediaStream | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  // 竞态防护（B2）：采集请求代际号——每次启动/停止递增，用于识别并丢弃过期的 async 结果
  const requestSeqRef = useRef(0);
  // 竞态防护（B2）：卸载标记（授权弹窗在组件卸载后才 resolve 时需丢弃结果）
  const mountedRef = useRef(true);
  const onErrorRef = useRef(onError);
  onErrorRef.current = onError;
  const onEndedRef = useRef(onEnded);
  onEndedRef.current = onEnded;

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const stopCapture = useCallback(() => {
    // 竞态防护（B2）：同步作废全部在途采集请求结果
    requestSeqRef.current += 1;
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null;
      videoRef.current = null;
    }
    setIsCapturing(false);
  }, []);

  const startCapture = useCallback(async () => {
    if (!navigator.mediaDevices) {
      onErrorRef.current?.(kind);
      return;
    }
    // 竞态防护（B2）：进入即占用新代际，await 返回后凭本代次判断结果是否仍然有效
    requestSeqRef.current += 1;
    const seq = requestSeqRef.current;
    try {
      let stream: MediaStream;
      if (kind === 'screen') {
        if (typeof navigator.mediaDevices.getDisplayMedia !== 'function') {
          onErrorRef.current?.(kind);
          return;
        }
        stream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false });
      } else {
        if (typeof navigator.mediaDevices.getUserMedia !== 'function') {
          onErrorRef.current?.(kind);
          return;
        }
        stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
      }
      // 竞态防护（B2）：授权期间已被停止/重启/卸载 → 本结果过期，释放轨道不得写入
      if (!mountedRef.current || seq !== requestSeqRef.current) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      streamRef.current = stream;

      // 系统级停止（如浏览器「停止共享」按钮）：清理并通知 caller 回写开关
      stream.getVideoTracks()[0]?.addEventListener('ended', () => {
        stopCapture();
        onEndedRef.current?.(kind);
      });

      const video = document.createElement('video');
      video.muted = true;
      video.playsInline = true;
      video.srcObject = stream;
      await video.play().catch(() => {
        // 某些环境下 play() 需用户手势，帧抓取在 readyState 就绪后仍可用
      });
      videoRef.current = video;
      setIsCapturing(true);
    } catch (e) {
      console.warn(`[useVideoCapture] ${kind} capture failed:`, e);
      // 竞态防护（B2）：仅当代际仍有效才清理并上报，过期失败不得影响新一轮/已停止的状态
      if (seq !== requestSeqRef.current) return;
      stopCapture();
      onErrorRef.current?.(kind);
    }
  }, [kind, stopCapture]);

  useEffect(() => {
    if (active) {
      void startCapture();
    } else {
      stopCapture();
    }
    return () => stopCapture();
  }, [active, startCapture, stopCapture]);

  const captureFrame = useCallback((): string | null => {
    const video = videoRef.current;
    if (!video || video.readyState < 2 || video.videoWidth === 0) return null;

    if (!canvasRef.current) {
      canvasRef.current = document.createElement('canvas');
    }
    const canvas = canvasRef.current;
    const scale = Math.min(1, MAX_FRAME_EDGE / Math.max(video.videoWidth, video.videoHeight));
    canvas.width = Math.round(video.videoWidth * scale);
    canvas.height = Math.round(video.videoHeight * scale);
    const ctx = canvas.getContext('2d');
    if (!ctx) return null;
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    try {
      return canvas.toDataURL('image/jpeg', JPEG_QUALITY);
    } catch {
      return null;
    }
  }, []);

  return { isCapturing, captureFrame };
}

export default useVideoCapture;
