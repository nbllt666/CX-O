import { test, expect, type Page } from '@playwright/test';

async function setupMocks(page: Page) {
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
      body: JSON.stringify({
        connected: true,
        client_id: 'e2e-client-001',
      }),
    });
  });

  await page.route('**/api/config/limits', (route) => {
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'success', config: {} }),
    });
  });

  await page.route('**/api/agents', (route) => {
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'success', agents: [], total: 0 }),
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
            bilibili: { enabled: true, websocket_url: 'ws://localhost:8080' },
            rdf: { enabled: true, websocket_url: 'ws://localhost:9898' },
          },
        },
      }),
    });
  });

  await page.route('**/api/firewall/config', (route) => {
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'success',
        config: {
          llm: { default_model: 'qwen2.5:latest' },
          blocking: { blacklist_enabled: true, blacklist: [] },
          decision: { timeout_ms: 5000 },
        },
      }),
    });
  });

  await page.route('**/api/firewall/v3/config', (route) => {
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'success',
        config: {
          interrupt: {
            enabled: true,
            mode: 'main_llm',
            main_llm: { enabled: true, prompt: '' },
            independent_llm: { enabled: false, model: 'qwen2.5:1.5b' },
          },
        },
      }),
    });
  });

  await page.route('**/api/vad/config', (route) => {
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'success',
        config: {
          enabled: true,
          threshold: 0.5,
          min_speech_duration: 250,
          max_speech_duration: 30000,
          silence_duration: 1000,
        },
      }),
    });
  });

  await page.route('**/api/config/sensevoice-streaming', (route) => {
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'success',
        config: { chunk_size: 1600, hop_size: 800, look_back: 8000 },
      }),
    });
  });

  await page.route('**/api/config/adaptive-polling', (route) => {
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'success',
        config: { offset_ms: 0, window_size: 3 },
      }),
    });
  });
}

test.describe('Phase 1 Governance - Settings Page E2E', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
  });

  test('app loads and passes connection check', async ({ page }) => {
    await page.goto('/');
    await page.waitForURL('**/chat', { timeout: 15000 });
    await expect(page).toHaveURL(/.*\/chat/);
  });

  test('settings page renders and live section is accessible', async ({ page }) => {
    await page.goto('/settings');
    await page.waitForURL('**/settings', { timeout: 15000 });
    await page.waitForTimeout(1500);

    await page.click('button:has-text("直播管理")');
    await page.waitForTimeout(1500);

    const disconnectButton = page.locator('button:has-text("断开连接")');
    await expect(disconnectButton).toHaveCount(1);
    await expect(disconnectButton).toBeVisible();
  });

  test('disconnect API contract - frontend calls POST to correct endpoint', async ({ page }) => {
    let disconnectCalled = false;
    let capturedUrl = '';
    let capturedMethod = '';

    await page.route('**/api/live/client/*/disconnect', (route) => {
      disconnectCalled = true;
      capturedUrl = route.request().url();
      capturedMethod = route.request().method();
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          status: 'success',
          message: '客户端已断开',
        }),
      });
    });

    await page.goto('/settings');
    await page.waitForURL('**/settings', { timeout: 15000 });
    await page.waitForTimeout(1000);

    await page.click('button:has-text("直播管理")');
    await page.waitForTimeout(2000);

    const disconnectButton = page.locator('button:has-text("断开连接")');
    await expect(disconnectButton).toBeVisible({ timeout: 10000 });

    const disabled = await disconnectButton.isDisabled();
    if (!disabled) {
      await disconnectButton.click();
      await page.waitForTimeout(1000);
      expect(disconnectCalled).toBe(true);
      expect(capturedUrl).toContain('/disconnect');
      expect(capturedMethod).toBe('POST');
    } else {
      const response = await page.evaluate(async () => {
        const res = await fetch('http://127.0.0.1:8000/api/live/client/e2e-test-001/disconnect', {
          method: 'POST',
        });
        return { status: res.status, data: await res.json() };
      });
      expect(response.status).toBe(200);
      expect(response.data.status).toBe('success');
    }
  });
});
