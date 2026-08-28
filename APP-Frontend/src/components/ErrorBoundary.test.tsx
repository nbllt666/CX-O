/**
 * ErrorBoundary 组件测试（R8-01）：
 *  - 子组件正常时直接渲染
 *  - 子组件抛错时显示兜底 UI（异常文案 + 刷新按钮），并由 componentDidCatch 记录错误
 *
 * 注：window.location.reload 为 jsdom [Unforgeable] API，无法 spy，
 * 点击行为不在单测覆盖范围（生产路径为原生 window.location.reload()）。
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import '@/i18n';
import ErrorBoundary from './ErrorBoundary';

function Bomb({ shouldThrow }: { shouldThrow: boolean }) {
  if (shouldThrow) throw new Error('boom');
  return <div data-testid="fine">ok</div>;
}

describe('ErrorBoundary', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('子组件正常时直接渲染', () => {
    render(
      <ErrorBoundary>
        <Bomb shouldThrow={false} />
      </ErrorBoundary>,
    );
    expect(screen.getByTestId('fine')).toBeInTheDocument();
  });

  it('子组件抛错时显示兜底 UI 与刷新按钮，并记录错误', () => {
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    render(
      <ErrorBoundary>
        <Bomb shouldThrow />
      </ErrorBoundary>,
    );
    expect(screen.getByText('页面出现异常')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '刷新页面' })).toBeInTheDocument();
    expect(screen.queryByTestId('fine')).not.toBeInTheDocument();
    expect(errSpy).toHaveBeenCalled();
  });
});
