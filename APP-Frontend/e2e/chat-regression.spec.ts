import { expect, type Page, test, type WebSocketRoute } from '@playwright/test';

const agents = [
  { id: 'a1', name: '代理甲', is_default: true, system_prompt: '' },
  { id: 'a2', name: '代理乙', is_default: false, system_prompt: '' },
];

async function setup(page: Page, options: { holdHistory?: Promise<void>; offlineWs?: boolean } = {}) {
  const rows = agents.map((agent) => ({ ...agent }));
  const sockets = new Map<string, WebSocketRoute>();
  const sent: { agent_id: string; message: string }[] = [];
  let agentReads = 0;
  await page.addInitScript(() => localStorage.clear());
  await page.route('**/health', (route) => route.fulfill({ json: { status: 'healthy' } }));
  // 只拦业务端点，不能匹配 Vite 的 /src/api/*.ts 模块请求。
  await page.route((url) => url.pathname.startsWith('/api/'), async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/agents') {
      agentReads += 1;
      await route.fulfill({ json: { status: 'success', agents: rows } });
    } else if (path.endsWith('/clone')) {
      const agent = { ...agents[0], id: 'a3', name: '甲副本', is_default: false };
      rows.push(agent);
      await route.fulfill({ json: { status: 'success', agent } });
    } else if (path.includes('/chat/history/')) {
      if (path.endsWith('agent-a1')) await options.holdHistory;
      await route.fulfill({ json: { status: 'success', messages: [{ id: 'h1', role: 'assistant', content: '已加载历史', created_at: '2026-10-10T10:00:00Z' }] } });
    } else if (path === '/api/chat/stream' || path === '/api/memory-agent/chat/stream') {
      // 与当前后端 _generate_chat_events 的真实失败事件形状一致。
      await route.fulfill({ contentType: 'text/event-stream', body: 'data: {"type":"error","message":"流式聊天处理失败，请稍后重试"}\n\n' });
    } else {
      await route.fulfill({ json: { status: 'success', providers: [], ollama_models: [], assets: [], limits: {} } });
    }
  });
  await page.routeWebSocket('**/ws', (socket) => {
    if (options.offlineWs) { socket.close(); return; }
    socket.onMessage((raw) => {
      const message = JSON.parse(String(raw));
      if (message.type === 'config') sockets.set(message.agent_id, socket);
      if (message.type === 'chat_stream') sent.push(message);
    });
  });
  return { sockets, sent, reads: () => agentReads };
}

test('聊天：等待历史后发送，梦境不截断回复，切换 Agent 恢复发送', async ({ page }) => {
  let releaseHistory!: () => void;
  const holdHistory = new Promise<void>((resolve) => { releaseHistory = resolve; });
  const mock = await setup(page, { holdHistory });
  await page.goto('/#/chat');
  const input = page.getByPlaceholder(/输入消息/);
  await input.fill('甲问题');
  const send = page.getByRole('button', { name: '发送', exact: true });
  await expect(send).toBeDisabled();
  await input.press('Enter');
  expect(mock.sent).toHaveLength(0);
  releaseHistory();
  await expect(send).toBeEnabled();
  await expect.poll(() => mock.sockets.has('a1')).toBe(true);
  await send.click();
  await expect.poll(() => mock.sent.length).toBe(1);
  mock.sockets.get('a1')!.send(JSON.stringify({ type: 'content', content: '前半' }));
  mock.sockets.get('a1')!.send(JSON.stringify({ type: 'dream.surface', data: { content: '梦境插入' } }));
  mock.sockets.get('a1')!.send(JSON.stringify({ type: 'content', content: '后半' }));
  await expect(page.getByText('前半后半', { exact: true })).toBeVisible();
  await expect(page.getByText('（梦境）梦境插入', { exact: true })).toBeVisible();
  await page.getByRole('combobox').selectOption('a2');
  await expect(page.getByTitle('停止', { exact: true })).toHaveCount(0);
  await expect.poll(() => mock.sockets.has('a2')).toBe(true);
  await input.fill('乙问题');
  await send.click();
  await expect.poll(() => mock.sent.length).toBe(2);
  expect(mock.sent[1].agent_id).toBe('a2');
  mock.sockets.get('a2')!.send(JSON.stringify({ type: 'content', content: '乙回复' }));
  mock.sockets.get('a2')!.send(JSON.stringify({ type: 'done' }));
  await expect(page.getByText('乙回复', { exact: true })).toBeVisible();
  await expect(page.getByTitle('停止', { exact: true })).toHaveCount(0);
});

test('Agent 克隆完成后立即出现副本，不等待缓存过期', async ({ page }) => {
  const mock = await setup(page);
  await page.goto('/#/agents');
  const clone = page.getByRole('button', { name: /克隆|Clone/ }).first();
  await expect(clone).toBeVisible();
  const before = mock.reads();
  await clone.click();
  await expect(page.getByText('甲副本', { exact: true })).toBeVisible();
  expect(mock.reads()).toBeGreaterThan(before);
});

test('@mock 断线回退 SSE：上游 error 显示错误气泡并恢复发送', async ({ page }) => {
  await setup(page, { offlineWs: true });
  await page.goto('/#/chat');
  const input = page.getByPlaceholder(/输入消息/);
  await expect(page.getByText('已加载历史', { exact: true })).toBeVisible();
  await input.fill('失败请求');
  await page.getByRole('button', { name: '发送', exact: true }).click();
  await expect(page.getByText(/流式聊天处理失败，请稍后重试/)).toBeVisible();
  await expect(page.getByText(/unknown|响应已完成/)).toHaveCount(0);
  await expect(page.getByTitle('停止', { exact: true })).toHaveCount(0);
  await input.fill('重试');
  await expect(page.getByRole('button', { name: '发送', exact: true })).toBeEnabled();
});

test('@mock 记忆管理页显示真实 SSE message 错误帧，保留失败说明', async ({ page }) => {
  await setup(page);
  await page.goto('/#/memory-agent');
  const input = page.getByLabel(/输入指令/);
  await input.fill('失败请求');
  await page.getByRole('button', { name: '发送', exact: true }).click();
  await expect(page.getByText('流式聊天处理失败，请稍后重试', { exact: true })).toBeVisible();
  await expect(page.getByText(/响应已完成|unknown/)).toHaveCount(0);
  await input.fill('重试');
  await expect(page.getByRole('button', { name: '发送', exact: true })).toBeEnabled();
});
