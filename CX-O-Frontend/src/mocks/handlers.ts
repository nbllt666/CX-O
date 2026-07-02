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
];
