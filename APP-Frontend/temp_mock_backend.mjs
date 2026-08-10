// 临时 GUI 冒烟用 mock 后端 v2：带 CORS 头（对齐真实后端/Electron configureCors 行为）。非产品代码。
import http from 'node:http';

const server = http.createServer((req, res) => {
  const url = req.url || '/';
  res.setHeader('Content-Type', 'application/json');
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');
  if (req.method === 'OPTIONS') {
    res.writeHead(204);
    return res.end();
  }
  if (url === '/health') {
    res.writeHead(200);
    return res.end(JSON.stringify({ status: 'ok', service: 'mock' }));
  }
  res.writeHead(200);
  return res.end(JSON.stringify({ data: [], items: [], list: [], ok: true }));
});

server.listen(8100, '127.0.0.1', () => {
  console.log('[mock-backend] listening on http://127.0.0.1:8100 (with CORS)');
});
