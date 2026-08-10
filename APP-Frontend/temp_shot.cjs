// 临时 GUI 冒烟截图脚本 v3（复用已安装 Electron 的 chromium，非产品代码）。
// 单窗单进程：electron temp_shot.cjs <name> <route> <width> <height> [transparent]
const { app, BrowserWindow } = require('electron');
const fs = require('fs');
const path = require('path');

const outDir = path.join(__dirname, 'release', 'smoke_shots');
fs.mkdirSync(outDir, { recursive: true });

const name = process.argv[2] || 'shot';
const route = process.argv[3] || '/';
const width = Number(process.argv[4] || 1280);
const height = Number(process.argv[5] || 800);
const transparent = process.argv[6] === 'transparent';
const BASE = 'http://127.0.0.1:3100';

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

app.whenReady().then(async () => {
  const win = new BrowserWindow({
    width, height, show: false,
    frame: false,
    transparent,
    backgroundColor: transparent ? '#00000000' : '#12121a',
  });
  try {
    await win.loadURL(BASE + route);
    await wait(3500);
    const img = await win.webContents.capturePage();
    fs.writeFileSync(path.join(outDir, name + '.png'), img.toPNG());
    console.log('[shot] saved', name, path.join(outDir, name + '.png'));
  } catch (e) {
    console.error('[shot] error', name, e && e.message);
  } finally {
    try { win.destroy(); } catch {}
    app.quit();
  }
});
