/*
 * usePolling — 页面级轮询 Hook（统一封装，防请求风暴）。
 *
 * 硬约束（spec「后端未启动」场景）：
 * - 轮询间隔 ≥ 2s（调用方传更小值会被钳制）；
 * - 连续 3 次失败即停止轮询，显示连接错误，不发起密集重试；
 * - 组件卸载立即停止（清理定时器、丢弃 in-flight 结果）；
 * - refresh() 可手动恢复（重置失败计数并立即拉取一次）。
 */
import { useCallback, useEffect, useRef, useState } from "react";

export const DEFAULT_POLL_INTERVAL_MS = 3000;
export const MIN_POLL_INTERVAL_MS = 2000;
export const MAX_CONSECUTIVE_FAILURES = 3;

export interface UsePollingOptions {
  /** 轮询间隔毫秒数；下限 2000ms */
  intervalMs?: number;
  /** false 时暂停轮询（不清理已获取的 data） */
  enabled?: boolean;
}

export interface UsePollingResult<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  /** true = 连续失败达上限，轮询已停止（refresh 可恢复） */
  stopped: boolean;
  /** 手动刷新：重置失败计数并立即拉取一次 */
  refresh: () => void;
}

export function usePolling<T>(
  fetcher: () => Promise<T>,
  options: UsePollingOptions = {},
): UsePollingResult<T> {
  const { intervalMs: rawIntervalMs = DEFAULT_POLL_INTERVAL_MS, enabled = true } = options;
  const intervalMs = Math.max(rawIntervalMs, MIN_POLL_INTERVAL_MS);

  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [stopped, setStopped] = useState(false);
  const [refreshSignal, setRefreshSignal] = useState(0);

  // fetcher 用 ref 承载：页面以内联箭头函数传入时不触发轮询循环重启
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const refresh = useCallback(() => {
    setRefreshSignal((s) => s + 1);
  }, []);

  useEffect(() => {
    if (!enabled) {
      return;
    }

    let cancelled = false;
    let running = false;
    let failures = 0;
    let timer: number | null = null;

    const clearTimer = () => {
      if (timer !== null) {
        window.clearTimeout(timer);
        timer = null;
      }
    };

    const tick = async () => {
      if (cancelled || running) {
        return;
      }
      running = true;
      setLoading(true);
      try {
        const result = await fetcherRef.current();
        if (cancelled) return;
        failures = 0;
        setData(result);
        setError(null);
        setStopped(false);
        timer = window.setTimeout(() => void tick(), intervalMs);
      } catch (e) {
        if (cancelled) return;
        failures += 1;
        setError(e instanceof Error ? e.message : String(e));
        if (failures >= MAX_CONSECUTIVE_FAILURES) {
          // 连续失败达上限：停止轮询，避免失败请求风暴
          setStopped(true);
        } else {
          timer = window.setTimeout(() => void tick(), intervalMs);
        }
      } finally {
        running = false;
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    void tick();

    return () => {
      cancelled = true;
      clearTimer();
    };
  }, [enabled, intervalMs, refreshSignal]);

  return { data, error, loading, stopped, refresh };
}
