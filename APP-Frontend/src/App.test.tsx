import { describe, it, expect, beforeAll, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor, cleanup } from '@testing-library/react';
import App from './App';
import i18n from './i18n';

/**
 * App 连接检测门测试：
 * - fetch 打桩为 /health 200 时进入路由
 * - fetch reject 时渲染 ConnectionSetup
 * - 后端不可达但 #/pet / #/danmaku 路由时仍渲染对应页（连接门只拦管理界面）
 */
describe('App 连接检测门与路由骨架', () => {
  // jsdom 的 navigator.language 为 en-US，显式固定为 zh-CN 后再断言中文文案
  beforeAll(async () => {
    await i18n.changeLanguage('zh-CN');
  });

  beforeEach(() => {
    window.location.hash = '#/';
  });

  afterEach(() => {
    // vitest globals:false 下 RTL 自动 cleanup 不生效，须显式调用——
    // 否则前一用例的 HashRouter 仍挂载并监听 hashchange，污染后续用例
    cleanup();
    vi.unstubAllGlobals();
    window.location.hash = '#/';
  });

  it('后端可达时渲染管理界面占位页', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response('{"status":"ok"}', { status: 200 })),
    );
    render(<App />);
    expect(await screen.findByText('管理界面')).toBeInTheDocument();
  });

  it('后端不可达时渲染连接设置页', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('connection refused')));
    render(<App />);
    expect(await screen.findByText('连接设置')).toBeInTheDocument();
  });

  it('后端不可达但 #/pet 路由时仍渲染桌宠页（连接门不拦截）', async () => {
    window.location.hash = '#/pet';
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('connection refused')));
    render(<App />);
    // 桌宠页应直接渲染，不经过连接门；不应出现连接设置文案
    await waitFor(() => {
      expect(screen.queryByText('连接设置')).not.toBeInTheDocument();
    });
  });

  it('后端不可达但 #/danmaku 路由时仍渲染弹幕页（连接门不拦截）', async () => {
    window.location.hash = '#/danmaku';
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('connection refused')));
    render(<App />);
    await waitFor(() => {
      expect(screen.queryByText('连接设置')).not.toBeInTheDocument();
    });
  });
});
