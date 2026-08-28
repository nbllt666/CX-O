/**
 * 全局错误边界（R8-01）：根级 class 组件，包裹 <App /> 捕获子树渲染期异常，
 * 显示兜底 UI（异常文案 + 刷新按钮）替代整树白屏。
 *
 * i18n：class 组件内无法使用 useTranslation hook，直接经 i18n 实例取词
 * （i18n 已在 main.tsx import './i18n' 时初始化，此处复用同一实例）。
 */
import { Component, type ErrorInfo, type ReactNode } from 'react';
import i18n from '@/i18n';

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
}

export default class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { hasError: false };

  static getDerivedStateFromError(): Partial<ErrorBoundaryState> {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('[ErrorBoundary] uncaught render error:', error, info.componentStack);
  }

  render(): ReactNode {
    if (this.state.hasError) {
      return (
        <div className="app-surface flex min-h-screen flex-col items-center justify-center gap-4 p-6 text-center">
          <h1 className="text-lg font-semibold">{i18n.t('errorBoundary.title')}</h1>
          <p className="max-w-md text-sm text-muted-foreground">{i18n.t('errorBoundary.message')}</p>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-85"
          >
            {i18n.t('errorBoundary.reload')}
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
