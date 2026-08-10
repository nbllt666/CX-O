// 临时控制台取证 v1（非产品代码）：连接 target，enable Runtime/Log，reload，收集 console/异常 5 秒。
// 用法：node temp_console.cjs <wsUrl>
const wsUrl = process.argv[2];
if (!wsUrl) { console.error('usage: node temp_console.cjs <ws>'); process.exit(1); }
let id = 0;
const pending = new Map();
const events = [];
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
    return;
  }
  if (m.method === 'Runtime.exceptionThrown') {
    const ed = m.params.exceptionDetails || {};
    const exc = ed.exception;
    const desc = exc && exc.description ? exc.description : (ed.text || '');
    events.push({ type: 'exception', detail: desc.slice(0, 800), url: ed.url, line: ed.lineNumber });
  } else if (m.method === 'Runtime.consoleAPICalled') {
    const args = (m.params.args || []).map((a) => a.value !== undefined ? String(a.value) : a.description).join(' ');
    events.push({ type: 'console', level: m.params.type, msg: args.slice(0, 200) });
  } else if (m.method === 'Log.entryAdded') {
    events.push({ type: 'log', level: m.params.entry.level, msg: (m.params.entry.text || '').slice(0, 200), source: m.params.entry.source });
  }
};
ws.onerror = () => { console.error('ws error'); process.exit(1); };
ws.onopen = async () => {
  try {
    await send('Runtime.enable', {});
    await send('Log.enable', {});
    await send('Page.enable', {});
    await send('Page.reload', { ignoreCache: true });
  } catch (e) { console.error('setup error', e.message); }
  setTimeout(async () => {
    const r = await send('Runtime.evaluate', {
      expression: 'JSON.stringify({title: document.title, body:(document.body.innerText||"").slice(0,80), hasApp: !!(document.querySelector("#root")||{}).children && !!(document.querySelector("#root")||{}).children.length})',
      returnByValue: true,
    }).catch(() => ({}));
    console.log('[after-reload]', JSON.stringify(r.result && r.result.value));
    console.log('[events]', JSON.stringify(events));
    try { ws.close(); } catch {}
    setTimeout(() => process.exit(0), 300);
  }, 6000);
};
