/**
 * @file connection-setup.tsx — ConnectionSetup 业务组件重组（模块7）
 * ============================================================================
 * 模块: 模块7 业务组件重组层 — A 组图管理类
 * 落点: C:\CX-O\CX-O-Frontend\src\components\business\connection-setup.tsx
 * 原组件: src/components/ConnectionSetup.tsx
 *
 * 重组策略（MODULE-7 AGENTS.md §2.4）:
 *   - 保留现有业务逻辑（useState / useEffect / checkConnection / handleSubmit / localStorage 不变）
 *   - UI 层换用模块6 ui-v2 基础组件（Card / Input / Button）
 *   - 注入 Liquid Glass + data-glass + motion variants
 *   - 通过 className 消费 token，不硬编码颜色
 *
 * 跨模块导入约束（rules-0 §四 + MODULE-7 AGENTS.md §2.3）:
 *   - 仅 import 模块6 ui-v2 公开产出
 *   - 仅 import 共享基础设施（@/api/client）
 *   - 禁止 import 模块8/9 内部实现
 * ============================================================================
 */

import { useState, useEffect } from 'react';
import { motion, type Variants } from 'framer-motion';
import { cn } from '@/lib/utils';
import { setCachedBackendUrl, setCachedWsUrl } from '@/api/client';
import { Card, Input, Button } from '@/components/ui-v2';
import {
  buildGlassDataAttributes,
  getComponentMotionVariants,
} from '@/components/ui-v2';

interface ConnectionSetupProps {
  onConnected: () => void;
}

// 入场 motion variants（基于模块6 getComponentMotionVariants 工厂，gentle spring）
const setupVariants: Variants = getComponentMotionVariants({
  componentName: 'Dialog',
  springKey: 'gentle',
});

export function ConnectionSetup({ onConnected }: ConnectionSetupProps) {
  const [backendUrl, setBackendUrl] = useState(() => {
    return localStorage.getItem('cxhms-backend-url') || 'http://127.0.0.1:8000';
  });
  const [wsUrl, setWsUrl] = useState(() => {
    return localStorage.getItem('cxhms-ws-url') || 'ws://127.0.0.1:8000';
  });
  const [isChecking, setIsChecking] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    checkConnection();
     
  }, []);

  const checkConnection = async () => {
    setIsChecking(true);
    setError('');

    try {
      const response = await fetch(`${backendUrl}/health`, {
        method: 'GET',
        signal: AbortSignal.timeout(5000),
      });

      if (response.ok) {
        setCachedBackendUrl(backendUrl);
        setCachedWsUrl(wsUrl);
        onConnected();
      } else {
        setError(`服务器返回错误: ${response.status}`);
      }
    } catch (e) {
      setError(`无法连接到后端服务: ${e instanceof Error ? e.message : '未知错误'}`);
    } finally {
      setIsChecking(false);
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    checkConnection();
  };

  const glassAttributes = buildGlassDataAttributes(true, 3);

  return (
    <div className="min-h-screen flex items-center justify-center bg-[var(--color-bg-primary)]">
      <motion.div
        variants={setupVariants}
        initial="initial"
        animate="animate"
        exit="exit"
      >
        <Card className={cn('w-full max-w-md p-8')} dataGlass glassTier={3}>
          <div className="text-center mb-6">
            <h1 className="text-2xl font-bold mb-2 text-[var(--color-text-primary)]">连接设置</h1>
            <p className="text-sm text-[var(--color-text-secondary)]">
              请输入后端服务地址
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4" {...glassAttributes}>
            <div>
              <label className="block text-sm font-medium mb-2 text-[var(--color-text-secondary)]">
                后端地址
              </label>
              <Input
                type="url"
                value={backendUrl}
                onChange={(e) => setBackendUrl(e.target.value)}
                placeholder="http://127.0.0.1:8000"
                required
              />
            </div>

            <div>
              <label className="block text-sm font-medium mb-2 text-[var(--color-text-secondary)]">
                WebSocket 地址
              </label>
              <Input
                type="url"
                value={wsUrl}
                onChange={(e) => setWsUrl(e.target.value)}
                placeholder="ws://127.0.0.1:8000"
                required
              />
            </div>

            {error && (
              <div className="p-3 rounded-[var(--radius-md)] bg-[var(--color-error-light)] border border-[var(--color-error)] text-[var(--color-error)] text-sm">
                {error}
              </div>
            )}

            <Button
              type="submit"
              variant="primary"
              className="w-full"
              disabled={isChecking}
              loading={isChecking}
            >
              {isChecking ? '连接中...' : '连接'}
            </Button>
          </form>

          <div className="mt-6 p-4 rounded-[var(--radius-md)] bg-[var(--color-bg-tertiary)] text-xs text-[var(--color-text-secondary)]">
            <p className="font-medium mb-2">默认配置:</p>
            <ul className="space-y-1">
              <li>• 后端地址: http://127.0.0.1:8000</li>
              <li>• WebSocket: ws://127.0.0.1:8000</li>
            </ul>
          </div>
        </Card>
      </motion.div>
    </div>
  );
}
