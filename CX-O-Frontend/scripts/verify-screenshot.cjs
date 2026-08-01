const { chromium } = require('@playwright/test');

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error') errors.push('[console.error] ' + msg.text());
    if (msg.type() === 'warning') errors.push('[console.warn] ' + msg.text());
  });
  page.on('pageerror', (err) => errors.push('[pageerror] ' + err.message));

  await page.goto('http://localhost:3000', { waitUntil: 'networkidle', timeout: 30000 });
  await page.waitForTimeout(2500);

  const title = await page.title();
  const bodyBg = await page.evaluate(() => {
    const cs = getComputedStyle(document.body);
    const root = document.documentElement;
    const rootCs = getComputedStyle(root);
    return {
      bodyBg: cs.backgroundColor,
      bodyColor: cs.color,
      dataTheme: root.getAttribute('data-theme'),
      varColorBgPrimary: getComputedStyle(root).getPropertyValue('--color-bg-primary').trim(),
      varBackground: getComputedStyle(root).getPropertyValue('--background').trim(),
      varGlassPrimary: getComputedStyle(root).getPropertyValue('--glass-surface-primary').trim(),
      rootChildCount: root.childElementCount,
      bodyText: (document.body.innerText || '').slice(0, 200),
    };
  });

  await page.screenshot({ path: 'scripts/t3-verify-home.png' });
  console.log('TITLE:', title);
  console.log('BODY_STATE:', JSON.stringify(bodyBg, null, 2));
  console.log('CONSOLE_ERRORS/WARNINGS:', errors.length ? errors.join('\n') : '(none)');
  await browser.close();
})().catch((e) => { console.error('SCRIPT_ERROR:', e.message); process.exit(1); });
