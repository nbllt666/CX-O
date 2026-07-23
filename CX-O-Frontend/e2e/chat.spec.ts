import { test, expect, type Page } from '@playwright/test';

async function setupChatMocks(page: Page) {
  await page.route('**/health', (route) => {
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'healthy',
        version: '1.0.0-e2e-mock',
        services: { database: 'connected', llm: 'connected' },
      }),
    });
  });

  await page.route('**/api/live/client/status', (route) => {
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ connected: false }),
    });
  });

  await page.route('**/api/config/limits', (route) => {
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'success', config: { max_chat_images: 20 } }),
    });
  });

  await page.route('**/api/agents', (route) => {
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'success',
        agents: [
          {
            id: 'default',
            name: 'Default Agent',
            description: 'Test agent',
            system_prompt: '',
            model: 'gpt-4',
            temperature: 0.7,
            max_tokens: 2000,
            use_memory: false,
            use_tools: false,
            memory_scene: '',
          },
        ],
        total: 1,
      }),
    });
  });

  await page.route('**/api/chat/history/**', (route) => {
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'success',
        messages: [
          {
            id: 'msg-1',
            role: 'user',
            content: 'Hello from history',
            timestamp: new Date().toISOString(),
          },
          {
            id: 'msg-2',
            role: 'assistant',
            content: 'Hi! This is a mocked historical reply.',
            timestamp: new Date().toISOString(),
          },
        ],
      }),
    });
  });

  await page.route('**/api/danmaku/config', (route) => {
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'success',
        config: {
          websocket: { endpoint: '/ws/live', max_connections: 100 },
          sources: {
            bilibili: { enabled: false, websocket_url: '' },
            rdf: { enabled: false, websocket_url: '' },
          },
        },
      }),
    });
  });
}

function buildSseStream(): string {
  const lines = [
    'data: {"type":"start","message_id":"stream-1"}',
    'data: {"type":"partial","content":"Mocked "}',
    'data: {"type":"partial","content":"streaming "}',
    'data: {"type":"partial","content":"reply"}',
    'data: {"type":"done","message_id":"stream-1"}',
    'data: [DONE]',
    '',
  ];
  return lines.join('\n');
}

test.describe('Phase 1 Governance - Chat Page E2E (H4 prep)', () => {
  test.beforeEach(async ({ page }) => {
    await setupChatMocks(page);
  });

  test('chat page renders with default agent and history', async ({ page }) => {
    await page.goto('/chat');
    await page.waitForURL('**/chat', { timeout: 15000 });
    await page.waitForTimeout(1500);

    const chatContainer = page.locator('main').or(page.locator('[class*="chat"]')).first();
    await expect(chatContainer).toBeVisible({ timeout: 10000 });
  });

  test('user can type in chat input', async ({ page }) => {
    await page.goto('/chat');
    await page.waitForURL('**/chat', { timeout: 15000 });
    await page.waitForTimeout(1500);

    const textarea = page.locator('textarea').first();
    await expect(textarea).toBeVisible({ timeout: 10000 });
    await textarea.fill('Test message from E2E');
    await expect(textarea).toHaveValue('Test message from E2E');
  });

  test('send button triggers streaming API call', async ({ page }) => {
    let streamCalled = false;
    let capturedBody = '';

    // 环境密闭：阻断 WS 连接（在线后端会使聊天走 WS 直连，page.route 拦不到 WS），
    // 强制 isConnected=false，使发送走本用例断言的 HTTP fallback 路径。
    await page.routeWebSocket('**/ws', (ws) => ws.close());

    await page.route('**/api/chat/stream', (route) => {
      streamCalled = true;
      try {
        capturedBody = route.request().postData() || '';
      } catch {
        capturedBody = '';
      }
      return route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: buildSseStream(),
      });
    });

    await page.goto('/chat');
    await page.waitForURL('**/chat', { timeout: 15000 });
    await page.waitForTimeout(1500);

    const textarea = page.locator('textarea').first();
    await expect(textarea).toBeVisible({ timeout: 10000 });
    await textarea.fill('E2E test message');

    const sendButton = page.locator('button:has-text("发送")').or(page.locator('button[type="submit"]')).first();
    if (await sendButton.count() > 0) {
      await sendButton.click();
      await page.waitForTimeout(2000);
      expect(streamCalled).toBe(true);
      expect(capturedBody).toContain('E2E test message');
    } else {
      await textarea.press('Enter');
      await page.waitForTimeout(2000);
      expect(streamCalled).toBe(true);
    }
  });

  test('chat history API contract is correct', async ({ page }) => {
    let historyCalled = false;
    let capturedUrl = '';

    await page.route('**/api/chat/history/**', (route) => {
      historyCalled = true;
      capturedUrl = route.request().url();
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          status: 'success',
          messages: [],
        }),
      });
    });

    await page.goto('/chat');
    await page.waitForURL('**/chat', { timeout: 15000 });
    await page.waitForTimeout(2000);

    expect(historyCalled).toBe(true);
    expect(capturedUrl).toContain('/api/chat/history/');
  });
});
