// 临时深度探针 v1（非产品代码）：在指定页面 target 内评估表达式并返回，安全退出。
// 用法：node temp_probe.cjs <wsUrl> <expression>
const wsUrl = process.argv[2];
const expression = process.argv[3] || 'document.title';
if (!wsUrl) { console.error('usage: node temp_probe.cjs <ws> <expr>'); process.exit(1); }

let id = 0;
const pending = new Map();
const ws = new WebSocket(wsUrl);
const send = (method, params) => new Promise((res, rej) => {
  const mid = ++id;
  pending.set(mid, { res, rej });
  ws.send(JSON.stringify({ id: mid, method, params }));
});
ws.onmessage = (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) {
    const { res, rej } = pending.get(m.id);
    pending.delete(m.id);
    m.error ? rej(new Error(JSON.stringify(m.error))) : res(m.result);
  }
};
ws.onerror = () => { console.error('ws error'); process.exit(1); };
ws.onopen = async () => {
  try {
    await send('Runtime.enable', {});
    const r = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    console.log('[probe]', JSON.stringify(r.result && r.result.value));
  } catch (e) {
    console.error('[probe] error', e.message);
  } finally {
    try { ws.close(); } catch {}
    setTimeout(() => process.exit(0), 500);
  }
};
