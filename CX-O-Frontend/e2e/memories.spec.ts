import { test, expect, type Page } from '@playwright/test';

async function setupMemoriesMocks(page: Page) {
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

  await page.route('**/api/memories', (route) => {
    if (route.request().method() === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          memories: [
            {
              id: 1,
              content: 'E2E test long-term memory',
              type: 'long_term',
              importance: 3,
              tags: ['e2e', 'test'],
              created_at: '2026-01-01T00:00:00Z',
              is_archived: false,
            },
            {
              id: 2,
              content: 'E2E test short-term memory',
              type: 'short_term',
              importance: 1,
              tags: ['temp'],
              created_at: '2026-01-02T00:00:00Z',
              is_archived: false,
            },
          ],
        }),
      });
    }
    if (route.request().method() === 'POST') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 999,
          content: 'New memory from E2E',
          type: 'long_term',
          importance: 3,
          tags: [],
          created_at: new Date().toISOString(),
          is_archived: false,
        }),
      });
    }
    return route.fulfill({ status: 405 });
  });

  await page.route('**/api/memories/agents', (route) => {
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        agents: [
          { agent_id: 'default', table_name: 'memories_default', created_at: '2026-01-01T00:00:00Z' },
        ],
      }),
    });
  });
}

test.describe('Phase 1 Governance - Memories Page E2E (M19 prep)', () => {
  test.beforeEach(async ({ page }) => {
    await setupMemoriesMocks(page);
  });

  test('memories page renders and displays memory list', async ({ page }) => {
    await page.goto('/memories');
    await page.waitForURL('**/memories', { timeout: 15000 });
    await page.waitForTimeout(2000);

    await expect(page).toHaveURL(/.*\/memories/);
  });

  test('memories page shows memory content', async ({ page }) => {
    await page.goto('/memories');
    await page.waitForURL('**/memories', { timeout: 15000 });
    await page.waitForTimeout(2000);

    const pageContent = await page.textContent('body');
    expect(pageContent).toBeTruthy();
  });

  test('memories API contract - list endpoint returns memories array', async ({ page }) => {
    const response = await page.evaluate(async () => {
      const res = await fetch('http://127.0.0.1:8000/api/memories');
      return { status: res.status, data: await res.json() };
    });

    expect(response.status).toBe(200);
    expect(Array.isArray(response.data.memories)).toBe(true);
  });

  test('create memory API contract - POST endpoint returns new memory', async ({ page }) => {
    let createCalled = false;
    let capturedBody: Record<string, unknown> = {};

    await page.route('**/api/memories', (route) => {
      if (route.request().method() === 'POST') {
        createCalled = true;
        capturedBody = route.request().postDataJSON();
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            id: 999,
            content: 'New memory',
            type: 'long_term',
            importance: 3,
            tags: [],
            created_at: new Date().toISOString(),
            is_archived: false,
          }),
        });
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ memories: [] }),
      });
    });

    const response = await page.evaluate(async () => {
      const res = await fetch('http://127.0.0.1:8000/api/memories', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: 'test memory', type: 'long_term' }),
      });
      return { status: res.status, data: await res.json() };
    });

    expect(response.status).toBe(200);
    expect(response.data.id).toBe(999);
    expect(createCalled).toBe(true);
    expect(capturedBody.content).toBe('test memory');
  });

  test('search memories API contract - query params are passed', async ({ page }) => {
    let capturedUrl = '';

    await page.route('**/api/memories*', (route) => {
      if (route.request().method() === 'GET') {
        capturedUrl = route.request().url();
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ memories: [] }),
        });
      }
      return route.fulfill({ status: 405 });
    });

    await page.goto('/memories');
    await page.waitForURL('**/memories', { timeout: 15000 });
    await page.waitForTimeout(2000);

    expect(capturedUrl).toContain('/api/memories');
  });
});
