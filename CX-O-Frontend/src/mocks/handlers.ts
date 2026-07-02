import { http, HttpResponse } from 'msw';

const BASE = 'http://localhost';

export const handlers = [
  http.get(`${BASE}/api/health`, () => {
    return HttpResponse.json({
      status: 'healthy',
      version: '1.0.0-mock',
      services: { database: 'connected', llm: 'connected' },
    });
  }),

  http.get(`${BASE}/api/live/client/status`, () => {
    return HttpResponse.json({
      status: 'success',
      config: { status: 'connected', client_id: 'mock-client-001' },
    });
  }),

  http.post(`${BASE}/api/live/client/:clientId/disconnect`, ({ params }) => {
    return HttpResponse.json({
      status: 'success',
      message: `客户端 ${params.clientId} 已断开`,
    });
  }),

  http.get(`${BASE}/api/config`, () => {
    return HttpResponse.json({
      status: 'success',
      config: { theme: 'dark', language: 'zh-CN' },
    });
  }),

  http.get(`${BASE}/api/agents`, () => {
    return HttpResponse.json({
      status: 'success',
      agents: [],
      total: 0,
    });
  }),

  http.get(`${BASE}/api/chat/history/:sessionId`, ({ params }) => {
    return HttpResponse.json({
      status: 'success',
      messages: [
        {
          id: 'mock-msg-1',
          role: 'user',
          content: `Mocked history for ${params.sessionId}`,
          timestamp: new Date().toISOString(),
        },
      ],
    });
  }),

  http.post(`${BASE}/api/chat/stream`, async ({ request }) => {
    const body = await request.json().catch(() => ({}));
    const userMsg = (body as { message?: string })?.message || '';
    const sseLines = [
      'data: {"type":"start","message_id":"mock-stream-1"}',
      'data: {"type":"partial","content":"Mocked reply to: "}',
      `data: {"type":"partial","content":${JSON.stringify(userMsg.slice(0, 50))}}`,
      'data: {"type":"done","message_id":"mock-stream-1"}',
      'data: [DONE]',
      '',
    ];
    return new HttpResponse(sseLines.join('\n'), {
      status: 200,
      headers: { 'Content-Type': 'text/event-stream' },
    });
  }),

  // ===== M19 prep: Tools API mocks =====
  http.get(`${BASE}/api/tools`, ({ request }) => {
    const url = new URL(request.url);
    const category = url.searchParams.get('category');
    const tools: Record<string, unknown> = {
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
        status: category === 'inactive' ? 'active' : 'inactive',
        config: {},
        created_at: '2026-01-02T00:00:00Z',
        use_count: 5,
      },
    };
    return HttpResponse.json({ tools });
  }),

  http.get(`${BASE}/api/tools/stats`, () => {
    return HttpResponse.json({
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
    });
  }),

  http.post(`${BASE}/api/tools`, async ({ request }) => {
    const body = await request.json().catch(() => ({}));
    return HttpResponse.json({
      id: 'tool-new-mock',
      name: (body as { name?: string })?.name || 'new_tool',
      description: (body as { description?: string })?.description || '',
      type: 'custom',
      status: 'active',
      config: {},
      created_at: new Date().toISOString(),
      use_count: 0,
    });
  }),

  http.patch(`${BASE}/api/tools/:toolId`, ({ params }) => {
    return HttpResponse.json({
      id: params.toolId as string,
      name: 'updated_tool',
      description: 'Updated via mock',
      type: 'custom',
      status: 'active',
      config: {},
      created_at: '2026-01-01T00:00:00Z',
      use_count: 0,
    });
  }),

  http.delete(`${BASE}/api/tools/:toolId`, () => {
    return new HttpResponse(null, { status: 204 });
  }),

  // ===== M19 prep: Memories API mocks =====
  http.get(`${BASE}/api/memories`, () => {
    return HttpResponse.json({
      memories: [
        {
          id: 1,
          content: 'Mocked long-term memory',
          type: 'long_term',
          importance: 3,
          tags: ['test', 'mock'],
          created_at: '2026-01-01T00:00:00Z',
          is_archived: false,
        },
        {
          id: 2,
          content: 'Mocked short-term memory',
          type: 'short_term',
          importance: 1,
          tags: ['temp'],
          created_at: '2026-01-02T00:00:00Z',
          is_archived: false,
        },
      ],
    });
  }),

  http.get(`${BASE}/api/memories/agents`, () => {
    return HttpResponse.json({
      agents: [
        { agent_id: 'default', table_name: 'memories_default', created_at: '2026-01-01T00:00:00Z' },
      ],
    });
  }),

  http.post(`${BASE}/api/memories`, async ({ request }) => {
    const body = await request.json().catch(() => ({}));
    return HttpResponse.json({
      id: 999,
      content: (body as { content?: string })?.content || 'new memory',
      type: (body as { type?: string })?.type || 'long_term',
      importance: (body as { importance?: number })?.importance ?? 3,
      tags: [],
      created_at: new Date().toISOString(),
      is_archived: false,
    });
  }),

  http.put(`${BASE}/api/memories/:memoryId`, ({ params }) => {
    return HttpResponse.json({
      id: Number(params.memoryId),
      content: 'Updated memory content',
      type: 'long_term',
      importance: 3,
      tags: ['updated'],
      created_at: '2026-01-01T00:00:00Z',
      is_archived: false,
    });
  }),

  http.delete(`${BASE}/api/memories/:memoryId`, () => {
    return new HttpResponse(null, { status: 204 });
  }),

  http.post(`${BASE}/api/archive/memory`, () => {
    return new HttpResponse(null, { status: 204 });
  }),
];
