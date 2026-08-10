// 临时 GUI 冒烟文本取证脚本 v1（非产品代码）。单窗单进程。
// 用法：electron temp_text.cjs <name> <route> [width height]
const { app, BrowserWindow } = require('electron');
const fs = require('fs');
const path = require('path');

const outDir = path.join(__dirname, 'release', 'smoke_shots');
fs.mkdirSync(outDir, { recursive: true });

const name = process.argv[2] || 'shot';
const route = process.argv[3] || '/';
const width = Number(process.argv[4] || 1280);
const height = Number(process.argv[5] || 800);
const BASE = 'http://127.0.0.1:3100';
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

app.whenReady().then(async () => {
  const win = new BrowserWindow({ width, height, show: false, backgroundColor: '#12121a' });
  try {
    await win.loadURL(BASE + route);
    await wait(3500);
    const result = await win.webContents.executeJavaScript(
      `JSON.stringify({ title: document.title, text: (document.body.innerText||'').slice(0, 800) })`,
    );
    const parsed = JSON.parse(result);
    const record = {
      route,
      title: parsed.title,
      text: parsed.text,
      ts: new Date().toISOString(),
    };
    fs.writeFileSync(path.join(outDir, name + '.txt'), JSON.stringify(record, null, 2));
    console.log('[text] saved', name, '| title=', parsed.title);
    console.log('[text] snippet=', parsed.text.replace(/\n+/g, ' ').slice(0, 300));
  } catch (e) {
    console.error('[text] error', name, e && e.message);
  } finally {
    try { win.destroy(); } catch {}
    app.quit();
  }
});
