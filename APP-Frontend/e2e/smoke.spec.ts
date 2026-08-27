import { expect, type Page, test } from '@playwright/test';

/**
 * E2E 冒烟用例（s0402 Test2）：离线可过——不依赖真实后端。
 *
 * 行为契约锚点（src/App.tsx）：
 * - 连接门只拦管理页（#/）；桌宠窗（#/pet）与弹幕窗（#/danmaku）独立于
 *   后端连接状态正常渲染，功能降级但窗口可用。
 * - document.title 由路由前缀固定写回，与 locale 无关，是比文案更稳的
 *   路由渲染证据。
 *
 * 选择器依据（全部来自运行时 DOM 探查快照 + 真实源码结构，非猜测类名）：
 * - DanmakuToolbar.tsx：控制按钮均带 title/aria-label；i18n 实际渲染 zh-CN
 *   （探查证据：error-context.md 可达性树「暂停滚动」「清屏」「窗口置顶」，
 *   Playwright use.locale 不影响 i18next 的 zh-CN 默认解析）。断言采用
 *   双语正则，兼容未来语言环境变化。
 * - 背景不透明度滑块是弹幕窗内唯一 input[type="range"]。
 * - DanmakuList.tsx：无消息时列表层渲染 t('danmaku.empty')
 *   （zh-CN：“暂无弹幕，等待直播消息…”）。
 */

/**
 * DOM 探查辅助：设 CXO_E2E_PROBE_DOM=1 运行时打印 #root 实际 HTML 片段，
 * 用于核验上述选择器依据与真实 DOM 一致（先探查后选型器，不硬编码猜测）。
 */
async function dumpRootIfProbing(page: Page): Promise<void> {
  if (!process.env.CXO_E2E_PROBE_DOM) return;
  const html = await page.locator('#root').innerHTML();
  console.log(
    `\n[CXO_E2E_PROBE_DOM] #root innerHTML（截断 4000 字符）:\n${html.slice(0, 4000)}\n`,
  );
}

function trackPageErrors(page: Page): Error[] {
  const pageErrors: Error[] = [];
  page.on('pageerror', (error) => pageErrors.push(error));
  return pageErrors;
}

test('冒烟：根路由渲染出可见内容且无致命 JS 错误', async ({ page }) => {
  const pageErrors = trackPageErrors(page);

  await page.goto('/');

  // 断言一：#root 内出现可见元素。无后端时的合法形态链为
  // 「Checking backend connection...」检查态 → ConnectionSetup 连接门，
  // 任一形态都是根路由的正常渲染（此处不断言具体形态，避免耦合业务时机）。
  await expect(page.locator('#root > *').first()).toBeVisible();
  await expect(page.locator('#root')).not.toBeEmpty();

  // 断言二：App.tsx 对非 #/pet、#/danmaku 前缀的 hash 无条件写回管理界面标题。
  await expect(page).toHaveTitle('CXO-Pet 管理界面');

  await dumpRootIfProbing(page);

  // 断言三：收集到的致命未捕获异常为空（WS 重连失败仅产生网络级 console 错误，
  // 不构成 pageerror，属离线 Mock 场景预期行为）。
  expect(pageErrors).toEqual([]);
});

test('冒烟：弹幕窗独立于后端连接门渲染', async ({ page }) => {
  const pageErrors = trackPageErrors(page);

  await page.goto('/#/danmaku');

  // 断言一：App.tsx 对 #/danmaku 前缀 hash 无条件写回标题「CXO-Pet 弹幕」，
  // 说明弹幕窗分支（绕过连接门的 HashRouter 路由）已接管渲染。
  await expect(page).toHaveTitle('CXO-Pet 弹幕');

  // 断言二：工具条关键控件渲染——背景不透明度滑块（唯一 range 输入）。
  await expect(page.locator('#root input[type="range"]')).toBeVisible();

  // 断言三：工具条控制按钮组（aria-label 来自 i18n，当前实测渲染 zh-CN 文案，
  // 用双语正则兜底语言漂移）。
  await expect(
    page.getByRole('button', { name: /暂停滚动|Pause scroll/ }),
  ).toBeVisible();
  await expect(page.getByRole('button', { name: /^清屏$|^Clear$/ })).toBeVisible();
  await expect(
    page.getByRole('button', { name: /窗口置顶|Always on top/ }),
  ).toBeVisible();

  // 断言四：弹幕列表容器空态文案可见（无后端 → 无直播 WS 消息 → 稳定空态；
  // 数据通道缺省不影响窗口本体渲染，即“独立渲染”契约的直接证据）。
  await expect(
    page.getByText(/等待直播消息|Waiting for live messages/),
  ).toBeVisible();

  await dumpRootIfProbing(page);

  expect(pageErrors).toEqual([]);
});
