import { test, expect, type Page } from '@playwright/test';

/**
 * ACP 管理页面 E2E 测试
 *
 * 覆盖范围：
 *  - 页面加载与统计卡片渲染
 *  - 空代理状态展示
 *  - 代理列表渲染与交互
 *  - 创建代理表单流程
 *  - 编辑代理表单流程（预填值）
 *  - 切换代理状态（PATCH 契约）
 *  - 删除代理（DELETE 契约 + confirm 对话框）
 *
 * 对应闭合判据：OBS-P6-8（AcpPage 大规模重构后功能等价验证）
 */

// ---- Mock 数据 ----

const MOCK_STATS = {
  status: 'success',
  statistics: {
    total_agents: 4,
    active_agents: 2,
    total_messages: 128,
    total_conversations: 32,
    avg_response_time: 246.5,
  },
};

const MOCK_AGENTS = [
  {
    id: 'agent-e2e-001',
    name: '测试助手 Alpha',
    description: '用于 E2E 验证的主代理',
    capabilities: ['chat', 'memory'],
    status: 'active',
  },
  {
    id: 'agent-e2e-002',
    name: '归档代理 Beta',
    description: '负责记忆归档与检索',
    capabilities: ['memory', 'tool'],
    status: 'inactive',
  },
];

// ---- Mock 安装 ----

async function setupMocks(page: Page, agents = MOCK_AGENTS, stats = MOCK_STATS) {
  // 应用启动健康检查
  await page.route('**/health', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'healthy',
        version: '1.0.0-e2e-mock',
        services: { database: 'connected', llm: 'connected' },
      }),
    }),
  );

  // 应用启动配置拉取
  await page.route('**/api/config/limits', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'success', config: {} }),
    }),
  );

  // ACP 统计
  await page.route('**/api/acp/stats', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(stats),
    }),
  );

  // ACP 代理列表
  await page.route('**/api/acp/agents', (route) => {
    const method = route.request().method();
    if (method === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ agents }),
      });
    }
    if (method === 'POST') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'success' }),
      });
    }
    return route.continue();
  });

  // ACP 单个代理（PATCH/DELETE）
  await page.route('**/api/acp/agents/*', (route) => {
    const method = route.request().method();
    if (method === 'PATCH') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'success' }),
      });
    }
    if (method === 'DELETE') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'success' }),
      });
    }
    return route.continue();
  });
}

// ---- 测试用例 ----

test.describe('ACP 管理页面 E2E', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
  });

  test('页面加载并渲染标题与统计卡片', async ({ page }) => {
    await page.goto('/acp');
    await page.waitForTimeout(1500);

    // 标题
    await expect(page.locator('h1:has-text("ACP 管理")')).toBeVisible({ timeout: 10000 });
    await expect(page.locator('text=管理 AI 代理和协调协议')).toBeVisible();

    // 4 张统计卡片
    await expect(page.locator('text=总代理数')).toBeVisible();
    await expect(page.locator('text=活跃代理')).toBeVisible();
    await expect(page.locator('text=总会话数')).toBeVisible();
    await expect(page.locator('text=平均响应时间')).toBeVisible();

    // 统计数值来自 MOCK_STATS
    await expect(page.locator('text=4').first()).toBeVisible();
    await expect(page.locator('text=246.5ms')).toBeVisible();

    // 创建按钮
    await expect(page.locator('button:has-text("创建代理")')).toBeVisible();
  });

  test('空代理状态展示创建入口', async ({ page }) => {
    await setupMocks(page, [], { ...MOCK_STATS, statistics: { ...MOCK_STATS.statistics, total_agents: 0, active_agents: 0 } });
    await page.goto('/acp');
    await page.waitForTimeout(1500);

    await expect(page.locator('text=暂无代理')).toBeVisible({ timeout: 10000 });
    await expect(page.locator('button:has-text("创建第一个代理")')).toBeVisible();
  });

  test('代理列表渲染状态徽章与能力标签', async ({ page }) => {
    await page.goto('/acp');
    await page.waitForTimeout(1500);

    // 代理名称
    await expect(page.locator('text=测试助手 Alpha')).toBeVisible({ timeout: 10000 });
    await expect(page.locator('text=归档代理 Beta')).toBeVisible();

    // 状态徽章
    await expect(page.locator('text=活跃').first()).toBeVisible();
    await expect(page.locator('text=停用').first()).toBeVisible();

    // 能力标签（anime variant Badge）
    await expect(page.locator('text=chat').first()).toBeVisible();
    await expect(page.locator('text=memory').first()).toBeVisible();
    await expect(page.locator('text=tool').first()).toBeVisible();
  });

  test('创建代理表单提交调用 POST /api/acp/agents', async ({ page }) => {
    let createCalled = false;
    let capturedBody: Record<string, unknown> = {};

    await page.unroute('**/api/acp/agents');
    await page.route('**/api/acp/agents', (route) => {
      const method = route.request().method();
      if (method === 'POST') {
        createCalled = true;
        capturedBody = route.request().postDataJSON() as Record<string, unknown>;
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ status: 'success' }),
        });
      }
      if (method === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ agents: MOCK_AGENTS }),
        });
      }
      return route.continue();
    });

    await page.goto('/acp');
    await page.waitForTimeout(1500);

    await page.click('button:has-text("创建代理")');
    await page.waitForTimeout(800);

    // 表单可见
    await expect(page.locator('text=名称').first()).toBeVisible({ timeout: 5000 });
    await expect(page.locator('text=描述').first()).toBeVisible();
    await expect(page.locator('text=能力（逗号分隔）')).toBeVisible();

    // 填写表单
    await page.fill('input[required], input[type="text"]', 'E2E 新代理');
    await page.fill('textarea', '由 E2E 测试创建');

    await page.click('button[type="submit"]:has-text("创建")');
    await page.waitForTimeout(1000);

    expect(createCalled).toBe(true);
    expect(capturedBody.name).toBe('E2E 新代理');
    expect(capturedBody.description).toBe('由 E2E 测试创建');
  });

  test('编辑代理打开模态框并预填现有数据', async ({ page }) => {
    await page.goto('/acp');
    await page.waitForTimeout(1500);

    // 点击第一个代理的编辑按钮（title="编辑"）
    await page.locator('button[title="编辑"]').first().click();
    await page.waitForTimeout(800);

    // 模态框打开，预填名称
    const nameInput = page.locator('input[required], input[type="text"]').first();
    await expect(nameInput).toBeVisible({ timeout: 5000 });
    const prefilledValue = await nameInput.inputValue();
    expect(prefilledValue).toBe('测试助手 Alpha');

    // 提交按钮显示"保存"而非"创建"
    await expect(page.locator('button[type="submit"]:has-text("保存")')).toBeVisible();
  });

  test('切换代理状态调用 PATCH /api/acp/agents/:id', async ({ page }) => {
    let patchCalled = false;
    let capturedUrl = '';

    await page.route('**/api/acp/agents/*', (route) => {
      if (route.request().method() === 'PATCH') {
        patchCalled = true;
        capturedUrl = route.request().url();
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ status: 'success' }),
        });
      }
      return route.continue();
    });

    await page.goto('/acp');
    await page.waitForTimeout(1500);

    // 点击活跃代理的停用按钮（title="停用"）
    await page.locator('button[title="停用"]').first().click();
    await page.waitForTimeout(1000);

    expect(patchCalled).toBe(true);
    expect(capturedUrl).toContain('/api/acp/agents/agent-e2e-001');
  });

  test('删除代理调用 DELETE 并处理 confirm 对话框', async ({ page }) => {
    let deleteCalled = false;
    let capturedUrl = '';

    // 处理 window.confirm
    page.on('dialog', async (dialog) => {
      expect(dialog.type()).toBe('confirm');
      expect(dialog.message()).toContain('删除');
      await dialog.accept();
    });

    await page.route('**/api/acp/agents/*', (route) => {
      if (route.request().method() === 'DELETE') {
        deleteCalled = true;
        capturedUrl = route.request().url();
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ status: 'success' }),
        });
      }
      return route.continue();
    });

    await page.goto('/acp');
    await page.waitForTimeout(1500);

    await page.locator('button[title="删除"]').first().click();
    await page.waitForTimeout(1000);

    expect(deleteCalled).toBe(true);
    expect(capturedUrl).toContain('/api/acp/agents/agent-e2e-001');
  });

  test('刷新按钮触发代理列表重新拉取', async ({ page }) => {
    let fetchCount = 0;

    await page.unroute('**/api/acp/agents');
    await page.route('**/api/acp/agents', (route) => {
      if (route.request().method() === 'GET') {
        fetchCount += 1;
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ agents: MOCK_AGENTS }),
        });
      }
      return route.continue();
    });

    await page.goto('/acp');
    await page.waitForTimeout(1500);
    const initialCount = fetchCount;

    // 点击代理列表的刷新按钮（RefreshCw 图标按钮，title="刷新"）
    await page.locator('button[title="刷新"]').click();
    await page.waitForTimeout(1000);

    expect(fetchCount).toBeGreaterThan(initialCount);
  });
});
