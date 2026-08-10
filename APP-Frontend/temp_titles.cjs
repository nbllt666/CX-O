// 临时 CDP 标题取证 v1（非产品代码）：逐个连接到页面 target，读取真实 document.title 与 hash。
// 用法：node temp_titles.cjs <wsUrl1> <wsUrl2> ...
const urls = process.argv.slice(2);
if (!urls.length) { console.error('usage: node temp_titles.cjs <ws...>'); process.exit(1); }

function probe(wsUrl) {
  return new Promise((resolve) => {
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
    ws.onerror = () => { resolve({ error: 'ws-error' }); };
    ws.onopen = async () => {
      try {
        await send('Runtime.enable', {});
        const r = await send('Runtime.evaluate', {
          expression: 'JSON.stringify({ title: document.title, hash: location.hash, href: location.href })',
          returnByValue: true,
        });
        resolve({ value: r.result && r.result.value });
      } catch (e) {
        resolve({ error: e.message });
      } finally {
        ws.close();
      }
    };
  });
}

(async () => {
  for (const u of urls) {
    const r = await probe(u);
    console.log('[titles]', JSON.stringify(r));
  }
  process.exit(0);
})();
