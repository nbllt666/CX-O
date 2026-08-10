// 临时 CDP 驱动 v1（非产品代码）：在已运行的 CXO-Pet 桌宠窗内触发 IPC 创建管理窗/弹幕窗。
// 用法：node temp_cdp.cjs <pageWsUrl>
const wsUrl = process.argv[2];
if (!wsUrl) {
  console.error('usage: node temp_cdp.cjs <ws://.../devtools/page/ID>');
  process.exit(1);
}

let id = 0;
const pending = new Map();
const ws = new WebSocket(wsUrl);

function send(method, params) {
  const msgId = ++id;
  return new Promise((resolve, reject) => {
    pending.set(msgId, { resolve, reject });
    ws.send(JSON.stringify({ id: msgId, method, params }));
  });
}

ws.onmessage = (ev) => {
  const msg = JSON.parse(ev.data);
  if (msg.id && pending.has(msg.id)) {
    const { resolve, reject } = pending.get(msg.id);
    pending.delete(msg.id);
    if (msg.error) reject(new Error(JSON.stringify(msg.error)));
    else resolve(msg.result);
  }
};

ws.onopen = async () => {
  try {
    await send('Runtime.enable', {});
    for (const expr of [
      'window.electronAPI && window.electronAPI.openManagementWindow ? (window.electronAPI.openManagementWindow(), "management-open") : "NO-API"',
      'window.electronAPI && window.electronAPI.toggleDanmakuWindow ? (window.electronAPI.toggleDanmakuWindow(), "danmaku-toggle") : "NO-API"',
    ]) {
      const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
      console.log('[cdp]', JSON.stringify(r.result && r.result.value));
      await new Promise((res) => setTimeout(res, 1200));
    }
  } catch (e) {
    console.error('[cdp] error', e && e.message);
  } finally {
    ws.close();
    setTimeout(() => process.exit(0), 300);
  }
};

ws.onerror = (e) => {
  console.error('[cdp] ws error', e && e.message);
  process.exit(1);
};
