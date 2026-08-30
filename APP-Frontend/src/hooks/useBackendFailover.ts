/**
 * useBackendFailover：前端主后端集群感知故障转移 React Hook。
 *
 * 挂载时收集候选节点；随后周期探测当前后端 /health，连续失败达到阈值后触发
 * runBackendFailover() 切换到健康对等节点，成功则重载当前窗（全新 base/ws 地址重连）。
 *
 * 在 APP 根组件调用一次即可覆盖所有窗口（管理界面 / 桌宠可视化 / 弹幕窗）
 * ——它们都随 App 渲染，重载后各自按新地址重连。
 */
import { useEffect, useRef } from 'react';

import { getApiBaseUrl } from '../api/base';
import {
  FAILOVER_CONSECUTIVE,
  FAILOVER_POLL_MS,
  normalize,
  probeBackend,
  refreshCandidates,
  runBackendFailover,
} from '../lib/backendFailover';

export interface UseBackendFailoverOptions {
  /** 探测间隔（ms） */
  pollMs?: number;
  /** 连续失败多少次触发切换 */
  consecutive?: number;
  /** 切换成功后回调（在重载前触发） */
  onSwitched?: (url: string) => void;
}

export function useBackendFailover(options: UseBackendFailoverOptions = {}): void {
  const consecutiveRef = useRef(0);
  // 在途互斥：单轮探测+切换可超过 poll 间隔（探测超时叠加候选逐个探测），
  // 并发 tick 会双计数、双 reload——tick 开头若在途则直接跳过本轮
  const inFlightRef = useRef(false);
  const optionsRef = useRef(options);
  optionsRef.current = options;

  useEffect(() => {
    let cancelled = false;

    // 启动时收集候选节点（当前自己 + cluster peers + 局域网发现），
    // 保证主后端失联时能读到备选对等节点。
    void refreshCandidates().catch(() => {});

    const tick = async () => {
      if (cancelled || inFlightRef.current) return;
      inFlightRef.current = true;
      try {
        const current = normalize(getApiBaseUrl());
        const ok = await probeBackend(current);
        consecutiveRef.current = ok ? 0 : consecutiveRef.current + 1;

        if (
          !ok &&
          consecutiveRef.current >= (optionsRef.current.consecutive ?? FAILOVER_CONSECUTIVE)
        ) {
          const next = await runBackendFailover(current);
          if (next && next !== current) {
            optionsRef.current.onSwitched?.(next);
            // 切换后重载当前窗，使所有客户端以新 base/ws 地址重连
            window.location.reload();
          }
        }
      } finally {
        inFlightRef.current = false;
      }
    };

    void tick();
    const timer = setInterval(tick, options.pollMs ?? FAILOVER_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [options.pollMs, options.consecutive]);
}

export { FAILOVER_CONSECUTIVE, FAILOVER_POLL_MS };
