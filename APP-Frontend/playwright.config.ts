import { defineConfig } from '@playwright/test';

/**
 * 最小化 Playwright E2E 冒烟基建（s0402 Test2 承载）。
 *
 * 口径：
 * - 端口必须与 vite.config.ts 的 DEV_PORT 一致（当前固定 3100，strictPort）。
 * - workers=1：桌面应用三窗共享持久化全局状态（localStorage/zustand persist、
 *   electronStorage 内存缓存、data-theme），并发会产生跨页面串扰，故全程单 worker 串行。
 * - webServer 用 npm run dev 与日常开发口径完全一致（ELECTRON=true）；
 *   reuseExistingServer 允许复用人工已起的 dev server，测试结束不误杀外部进程。
 */
const DEV_PORT = 3100;

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  outputDir: './test-results',

  use: {
    baseURL: `http://localhost:${DEV_PORT}`,
    // 钉住语言环境保证浏览器侧确定性；注意 i18n 实际默认解析 zh-CN，
    // 与此设置无关（用例内文案断言均已按双语处理）
    locale: 'en-US',
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },

  projects: [{ name: 'chromium', use: { browserName: 'chromium' } }],

  webServer: {
    command: 'npm run dev',
    url: `http://localhost:${DEV_PORT}`,
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
