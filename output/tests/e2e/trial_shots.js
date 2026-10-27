// 试用版截图：按角色登录真实页面截图（演示库）
const { chromium } = require('playwright');
const base = 'http://127.0.0.1:5173';
const out = process.argv[2];
const shots = [
  ['13800000001', 1440, '/', '01-业主-我的待办'],
  ['13800000001', 1440, '/p/1/checkpoints', '02-业主-检查点列表'],
  ['13800000001', 1440, '/p/1/overview', '03-业主-项目总览'],
  ['13800000005', 1440, '/p/1/drawings', '04-设计经理-图纸'],
  ['13800000004', 1440, '/p/1/changes', '05-项目经理-变更单'],
  ['13800000004', 1440, '/p/1/issues', '06-项目经理-问题台账'],
  ['13800000006', 375, '/', '07-质检-手机待办'],
  ['13800000001', 375, '/p/1/checkpoints', '08-业主-手机检查点'],
];
(async () => {
  const b = await chromium.launch();
  const errs = [];
  for (const [phone, w, path, name] of shots) {
    const ctx = await b.newContext({ viewport: { width: w, height: w > 500 ? 900 : 812 }, deviceScaleFactor: w > 500 ? 1 : 2, timezoneId: 'Asia/Shanghai' });
    const page = await ctx.newPage();
    page.on('console', (m) => m.type() === 'error' && errs.push(`${name}: ${m.text()}`));
    page.on('pageerror', (e) => errs.push(`${name}: ${e}`));
    await page.goto(base + '/login');
    await page.fill('#phone', phone); await page.fill('#pwd', 'Jh123456');
    await page.click('button[type=submit]');
    await page.waitForSelector('h1:has-text("我的待办")');
    await page.goto(base + path);
    await page.waitForLoadState('networkidle'); await page.waitForTimeout(800);
    await page.screenshot({ path: `${out}/${name}.png`, fullPage: false });
    await ctx.close();
  }
  console.log(JSON.stringify({ consoleErrors: errs }));
  await b.close();
})();
