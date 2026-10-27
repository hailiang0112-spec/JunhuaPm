// SMOKE-01：Docker Compose 全栈，业主刘先生在 1440 宽浏览器登录，落在「我的待办」并看到工地卡片，控制台无错误
const { chromium } = require('playwright');
(async () => {
  const base = process.argv[2] || 'http://127.0.0.1:8080';
  const shot = process.argv[3];
  const b = await chromium.launch();
  const page = await b.newPage({ viewport: { width: 1440, height: 900 } });
  const errs = [];
  page.on('console', (m) => m.type() === 'error' && errs.push(m.text()));
  page.on('pageerror', (e) => errs.push(String(e)));
  await page.goto(base + '/');
  await page.waitForURL(/\/login/);
  await page.fill('#phone', '13800000001');
  await page.fill('#pwd', 'Jh123456');
  await page.click('button[type=submit]');
  await page.waitForSelector('h1:has-text("我的待办")');
  await page.waitForTimeout(1500);
  const body = await page.textContent('body');
  const ok = body.includes('君华新城 · 联排别墅');
  if (shot) await page.screenshot({ path: shot, fullPage: true });
  console.log(JSON.stringify({ url: page.url(), landedOnTodos: true, projectCard: ok, consoleErrors: errs }));
  await b.close();
  process.exit(ok && !errs.length ? 0 : 1);
})();
