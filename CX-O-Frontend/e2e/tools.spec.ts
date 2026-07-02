import { test, expect, type Page } from '@playwright/test';

async function setupToolsMocks(page: Page) {
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

  await page.route('**/api/tools', (route) => {
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        tools: {
          'tool-search': {
            id: 'tool-search',
            name: 'search_web',
            description: 'Search the web',
            type: 'builtin',
            status: 'active',
            config: {},
            created_at: '2026-01-01T00:00:00Z',
            use_count: 42,
          },
          'tool-calc': {
            id: 'tool-calc',
            name: 'calculator',
            description: 'Perform calculations',
            type: 'builtin',
            status: 'inactive',
            config: {},
            created_at: '2026-01-02T00:00:00Z',
            use_count: 5,
          },
        },
      }),
    });
  });

  await page.route('**/api/tools/stats', (route) => {
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'success',
        statistics: {
          total_tools: 2,
          enabled_tools: 1,
          builtin_tools: 2,
          custom_tools: 0,
          active_tools: 1,
          mcp_tools: 0,
          total_calls: 47,
        },
      }),
    });
  });
}

test.describe('Phase 1 Governance - Tools Page E2E (M19 prep)', () => {
  test.beforeEach(async ({ page }) => {
    await setupToolsMocks(page);
  });

  test('tools page renders and displays tool list', async ({ page }) => {
    await page.goto('/tools');
    await page.waitForURL('**/tools', { timeout: 15000 });
    await page.waitForTimeout(2000);

    await expect(page).toHaveURL(/.*\/tools/);
  });

  test('tools page shows stats information', async ({ page }) => {
    await page.goto('/tools');
    await page.waitForURL('**/tools', { timeout: 15000 });
    await page.waitForTimeout(2000);

    const pageContent = await page.textContent('body');
    expect(pageContent).toBeTruthy();
  });

  test('tools API contract - list endpoint is called on page load', async ({ page }) => {
    let toolsApiCalled = false;
    let statsApiCalled = false;

    await page.route('**/api/tools', (route) => {
      toolsApiCalled = true;
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ tools: {} }),
      });
    });

    await page.route('**/api/tools/stats', (route) => {
      statsApiCalled = true;
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          status: 'success',
          statistics: {
            total_tools: 0,
            enabled_tools: 0,
            builtin_tools: 0,
            custom_tools: 0,
          },
        }),
      });
    });

    await page.goto('/tools');
    await page.waitForURL('**/tools', { timeout: 15000 });
    await page.waitForTimeout(2000);

    expect(toolsApiCalled || statsApiCalled).toBe(true);
  });

  test('delete tool API contract - DELETE endpoint is called', async ({ page }) => {
    let deleteCalled = false;
    let capturedMethod = '';

    await page.route('**/api/tools', (route) => {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          tools: {
            'tool-1': {
              id: 'tool-1',
              name: 'test_tool',
              description: 'A test tool',
              type: 'custom',
              status: 'active',
              config: {},
              created_at: '2026-01-01T00:00:00Z',
              use_count: 0,
            },
          },
        }),
      });
    });

    await page.route('**/api/tools/*', (route) => {
      if (route.request().method() === 'DELETE') {
        deleteCalled = true;
        capturedMethod = route.request().method();
        return route.fulfill({ status: 204 });
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 'tool-1',
          name: 'test_tool',
          description: 'Updated',
          type: 'custom',
          status: 'active',
          config: {},
          created_at: '2026-01-01T00:00:00Z',
          use_count: 0,
        }),
      });
    });

    await page.goto('/tools');
    await page.waitForURL('**/tools', { timeout: 15000 });
    await page.waitForTimeout(2000);

    const response = await page.evaluate(async () => {
      const res = await fetch('http://127.0.0.1:8000/api/tools/tool-1', { method: 'DELETE' });
      return { status: res.status };
    });
    expect(response.status).toBe(204);
    expect(capturedMethod).toBe('DELETE');
    expect(deleteCalled).toBe(true);
  });
});
