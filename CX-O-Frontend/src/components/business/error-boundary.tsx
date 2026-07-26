/**
 * @file error-boundary.tsx — ErrorBoundary 业务组件重组（模块7）
 * ============================================================================
 * 模块: 模块7 业务组件重组层 — A 组系统类
 * 落点: C:\CX-O\CX-O-Frontend\src\components\business\error-boundary.tsx
 * 原组件: src/components/ErrorBoundary.tsx
 *
 * 重组策略（MODULE-7 AGENTS.md §2.4）:
 *   - 保留现有业务逻辑（getDerivedStateFromError / componentDidCatch / handleReset 不变）
 *   - UI 层换用模块6 ui-v2 基础组件（Card / Button）
 *   - 注入 Liquid Glass + data-glass + motion variants
 *   - 通过 className 消费 token，不硬编码颜色
 *
 * 跨模块导入约束（rules-0 §四 + MODULE-7 AGENTS.md §2.3）:
 *   - 仅 import 模块3 motion / 模块4 glass / 模块6 ui-v2 公开产出
 *   - 仅 import 本模块内部实现
 *   - 禁止 import 模块8/9 内部实现
 * ============================================================================
 */

import { Component, type ErrorInfo, type ReactNode } from 'react';
import { AlertCircle, RefreshCw } from 'lucide-react';
import { motion, type Variants } from 'framer-motion';
import { cn } from '@/lib/utils';
import { Card } from '@/components/ui-v2';
import { Button } from '@/components/ui-v2';
import {
  buildGlassDataAttributes,
  getComponentMotionVariants,
} from '@/components/ui-v2';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
  errorInfo: ErrorInfo | null;
}

// 入场 motion variants（基于模块6 getComponentMotionVariants 工厂，gentle spring）
const errorCardVariants: Variants = getComponentMotionVariants({
  componentName: 'Dialog',
  springKey: 'gentle',
});

/**
 * ErrorBoundary 业务组件（重组版）。
 *
 * 业务逻辑保留: getDerivedStateFromError / componentDidCatch / handleReset 原样保留。
 * UI 层重组: 容器换用 ui-v2 Card + Button，挂载 data-glass，注入 motion variants。
 */
export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = {
      hasError: false,
      error: null,
      errorInfo: null,
    };
  }

  static getDerivedStateFromError(error: Error): State {
    return {
      hasError: true,
      error,
      errorInfo: null,
    };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    this.setState({
      error,
      errorInfo,
    });
    console.error('ErrorBoundary caught an error:', error, errorInfo);
  }

  handleReset = () => {
    this.setState({
      hasError: false,
      error: null,
      errorInfo: null,
    });
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      const glassAttributes = buildGlassDataAttributes(true, 3);

      return (
        <div className="min-h-screen flex items-center justify-center bg-[var(--color-bg-primary)]">
          <motion.div
            variants={errorCardVariants}
            initial="initial"
            animate="animate"
            exit="exit"
          >
            <Card
              className={cn('max-w-md w-full p-6')}
              dataGlass={true}
              glassTier={3}
            >
              <div className="flex items-center gap-3 mb-4">
                <AlertCircle className="w-8 h-8 text-[var(--color-error)]" />
                <h1 className="text-xl font-semibold text-[var(--color-text-primary)]">
                  出错了
                </h1>
              </div>

              <div className="mb-4">
                <p className="text-[var(--color-text-secondary)] mb-2">
                  抱歉，应用程序遇到了一个错误。请尝试刷新页面。
                </p>
                {this.state.error && (
                  <div
                    className="bg-[var(--color-error-light)] border border-[var(--color-error)] rounded-[var(--radius-md)] p-3"
                    {...glassAttributes}
                  >
                    <p className="text-sm text-[var(--color-error)] font-mono break-all">
                      {this.state.error.message}
                    </p>
                  </div>
                )}
              </div>

              <div className="flex gap-3">
                <Button
                  variant="primary"
                  className="flex-1"
                  icon={<RefreshCw className="w-4 h-4" />}
                  onClick={() => window.location.reload()}
                >
                  刷新页面
                </Button>
                <Button
                  variant="secondary"
                  className="flex-1"
                  onClick={this.handleReset}
                >
                  重试
                </Button>
              </div>

              {process.env.NODE_ENV === 'development' && this.state.errorInfo && (
                <details className="mt-4">
                  <summary className="cursor-pointer text-sm text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]">
                    查看详细错误信息
                  </summary>
                  <pre className="mt-2 text-xs bg-[var(--color-bg-tertiary)] p-3 rounded-[var(--radius-md)] overflow-auto max-h-40">
                    {this.state.errorInfo.componentStack}
                  </pre>
                </details>
              )}
            </Card>
          </motion.div>
        </div>
      );
    }

    return this.props.children;
  }
}
