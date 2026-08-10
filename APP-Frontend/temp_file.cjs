// 临时文件加载+控制台取证 v1（非产品代码）：加载生产 dist，抓取渲染进程 console/异常。
const { app, BrowserWindow } = require('electron');
const path = require('path');
const route = process.argv[2] || '#/pet';
const fileUrl = 'file:///' + path.join(__dirname, 'dist', 'index.html').replace(/\\/g, '/') + route;
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
app.whenReady().then(async () => {
  const win = new BrowserWindow({ width: 1000, height: 700, show: false, backgroundColor: '#12121a' });
  const logs = [];
  win.webContents.on('console-message', (_e, level, message, line, sourceId) => {
    logs.push({ level, msg: String(message).slice(0, 300) });
  });
  try {
    await win.loadURL(fileUrl);
    await wait(6000);
    const r = await win.webContents.executeJavaScript(
      `JSON.stringify({ title: document.title, body:(document.body.innerText||'').slice(0,200), hasApp: !!(document.querySelector('#root')||{}).children && !!(document.querySelector('#root')||{}).children.length })`
    );
    console.log('[file]', JSON.stringify(JSON.parse(r)));
  } catch (e) {
    console.error('[file] error', e && e.message);
  }
  console.log('[console]', JSON.stringify(logs.slice(-12)));
  try { win.destroy(); } catch {}
  app.quit();
});
