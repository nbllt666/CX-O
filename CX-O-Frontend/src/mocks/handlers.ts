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
];
