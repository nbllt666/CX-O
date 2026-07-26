/**
 * @file 性能 Hook（React 组件消费接口）
 *
 * 职责：为 React 组件提供性能数据消费接口，包括：
 * - usePerformance：获取监控器实例与初始快照
 * - usePerformanceAlerts：订阅性能告警
 * - usePerformanceSnapshot：定时刷新性能快照
 *
 * 契约对齐：
 * - 被所有模块通过 import { usePerformance } from '@/lib/performance/use-performance' 消费
 * - 不承载业务逻辑，仅代理 PerformanceMonitor 单例
 *
 * 跨模块导入约束：仅 import react + 本模块内部（performance-monitor.ts），禁止 import 模块1-8。
 */

import { useEffect, useMemo, useRef, useState, useCallback } from 'react';
import {
  createPerformanceMonitor,
  DEFAULT_PERFORMANCE_CONFIG,
  type PerformanceMonitor,
  type PerformanceMonitorConfig,
  type PerformanceSnapshot,
  type PerformanceAlert,
} from './performance-monitor';

/**
 * usePerformance 返回值。
 */
export interface UsePerformanceResult {
  /** 性能监控器单例 */
  readonly monitor: PerformanceMonitor;
  /** 初始性能快照 */
  readonly snapshot: PerformanceSnapshot;
  /** 当前配置 */
  readonly config: PerformanceMonitorConfig;
}

/**
 * 获取性能监控器实例与初始快照。
 *
 * 多次调用返回同一单例（PerformanceMonitor.getInstance）。
 * 不在 hook 内自动 init/destroy（监控器生命周期由 App 层管理）。
 *
 * @param config 可选配置覆盖（仅首次调用生效）
 */
export function usePerformance(
  config: PerformanceMonitorConfig = DEFAULT_PERFORMANCE_CONFIG,
): UsePerformanceResult {
  const monitor = useMemo(() => createPerformanceMonitor(config), []); // eslint-disable-line react-hooks/exhaustive-deps

  const [snapshot, setSnapshot] = useState<PerformanceSnapshot>(() => monitor.getSnapshot());

  // 配置变更时更新（不重建实例），同步刷新快照
  useEffect(() => {
    monitor.updateConfig(config);
    setSnapshot(monitor.getSnapshot());
  }, [monitor, config]);

  return { monitor, snapshot, config };
}

/**
 * usePerformanceAlerts 返回值。
 */
export interface UsePerformanceAlertsResult {
  /** 最近收到的告警列表（按时间倒序，最多 50 条） */
  readonly alerts: readonly PerformanceAlert[];
  /** 最近一条告警 */
  readonly latest: PerformanceAlert | null;
  /** 手动清空告警列表 */
  readonly clear: () => void;
}

const MAX_ALERTS = 50;

/**
 * 订阅性能告警。
 *
 * @param monitor 性能监控器实例
 * @returns 告警列表与操作接口
 */
export function usePerformanceAlerts(monitor: PerformanceMonitor): UsePerformanceAlertsResult {
  const [alerts, setAlerts] = useState<readonly PerformanceAlert[]>([]);

  const unsubscribeRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    const unsubscribe = monitor.onAlert(alert => {
      setAlerts(prev => {
        const next = [alert, ...prev];
        return next.slice(0, MAX_ALERTS);
      });
    });

    unsubscribeRef.current = unsubscribe;
    return () => {
      unsubscribe();
      unsubscribeRef.current = null;
    };
  }, [monitor]);

  const clear = useCallback(() => {
    setAlerts([]);
  }, []);

  return {
    alerts,
    latest: alerts.length > 0 ? alerts[0] : null,
    clear,
  };
}

/**
 * usePerformanceSnapshot 返回值。
 */
export interface UsePerformanceSnapshotResult {
  /** 当前快照 */
  readonly snapshot: PerformanceSnapshot;
  /** 是否正在轮询 */
  readonly polling: boolean;
}

/**
 * 定时刷新性能快照。
 *
 * @param monitor 性能监控器实例
 * @param intervalMs 刷新间隔（ms），默认 5000
 */
export function usePerformanceSnapshot(
  monitor: PerformanceMonitor,
  intervalMs: number = 5000,
): UsePerformanceSnapshotResult {
  const [snapshot, setSnapshot] = useState<PerformanceSnapshot>(() => monitor.getSnapshot());
  const [polling, setPolling] = useState(true);

  useEffect(() => {
    if (intervalMs <= 0) {
      setPolling(false);
      return;
    }

    setPolling(true);
    const timer = setInterval(() => {
      setSnapshot(monitor.getSnapshot());
    }, intervalMs);

    return () => {
      clearInterval(timer);
    };
  }, [monitor, intervalMs]);

  return { snapshot, polling };
}

/**
 * usePerformanceLifecycle 返回值。
 */
export interface UsePerformanceLifecycleResult {
  /** 监控器是否已初始化 */
  readonly initialized: boolean;
  /** 初始化监控器（注册告警回调与降级回调） */
  readonly init: (onAlert?: (alert: PerformanceAlert) => void, degradeCallback?: () => void) => void;
  /** 销毁监控器 */
  readonly destroy: () => void;
}

/**
 * 管理性能监控器生命周期（init/destroy）。
 *
 * 应在 App 根组件调用一次，负责监控器的初始化与清理。
 * 不在组件 unmount 时 destroy（单例保持全局存活），需手动调用 destroy。
 */
export function usePerformanceLifecycle(
  monitor: PerformanceMonitor,
): UsePerformanceLifecycleResult {
  const [initialized, setInitialized] = useState(false);
  const alertHandlerRef = useRef<((alert: PerformanceAlert) => void) | null>(null);
  const degradeCallbackRef = useRef<(() => void) | null>(null);

  const init = useCallback(
    (onAlert?: (alert: PerformanceAlert) => void, degradeCallback?: () => void) => {
      if (initialized) {
        return;
      }

      if (onAlert !== undefined) {
        alertHandlerRef.current = onAlert;
      }
      if (degradeCallback !== undefined) {
        degradeCallbackRef.current = degradeCallback;
        monitor.registerDegradeCallback(degradeCallback);
      }

      monitor.init(alertHandlerRef.current ?? undefined);
      setInitialized(true);
    },
    [monitor, initialized],
  );

  const destroy = useCallback(() => {
    if (!initialized) {
      return;
    }
    monitor.destroy();
    alertHandlerRef.current = null;
    degradeCallbackRef.current = null;
    setInitialized(false);
  }, [monitor, initialized]);

  // 组件 unmount 时重置单例（避免内存泄漏）
  useEffect(() => {
    return () => {
      // 注意：不调用 destroy，因为单例可能被其他组件使用
      // 仅清理本地引用
      alertHandlerRef.current = null;
      degradeCallbackRef.current = null;
    };
  }, []);

  return { initialized, init, destroy };
}
