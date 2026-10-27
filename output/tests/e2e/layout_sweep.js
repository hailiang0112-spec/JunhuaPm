// 布局回归扫描：全部路由 × 1440/375 × 多角色；检查页面级横向滚动、被截断的 .tag/.seal、控制台错误
const { chromium } = require('playwright');
const base = process.argv[2] || 'http://127.0.0.1:5173';
const P = '/p/1';
const ROUTES = ['/', '/me', '/experience', P, `${P}/floors`, `${P}/phase/1`, `${P}/phase/2`, `${P}/drawings`, `${P}/drawings/1`,
  `${P}/baselines`, `${P}/work-items/19`, `${P}/checkpoints`, `${P}/checkpoints/1`, `${P}/checkpoints/2`, `${P}/changes`,
  `${P}/changes/1`, `${P}/changes/new`, `${P}/issues`, `${P}/archive`, `${P}/supplements`, `${P}/notices`, `${P}/payments`,
  `${P}/members`, `${P}/structure`, `${P}/import`, `${P}/audit`];
const ADMIN = ['/company/projects', '/company/templates', P, `${P}/members`, `${P}/audit`];
const ROLES = [['13800000001', ROUTES], ['13800000004', ROUTES], ['13800000000', ADMIN]];
(async () => {
  const b = await chromium.launch();
  const bad = []; let checked = 0;
  for (const [phone, routes] of ROLES) for (const w of [1440, 375]) {
    const ctx = await b.newContext({ viewport: { width: w, height: w > 500 ? 900 : 812 }, timezoneId: 'Asia/Shanghai' });
    const page = await ctx.newPage();
    let cur = '';
    page.on('pageerror', (e) => bad.push(`${phone}@${w} ${cur} pageerror ${e.message}`));
    page.on('console', (m) => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) bad.push(`${phone}@${w} ${cur} console ${m.text()}`); });
    await page.goto(base + '/login'); await page.fill('#phone', phone); await page.fill('#pwd', 'Jh123456');
    await page.click('button[type=submit]'); await page.waitForSelector('h1:has-text("我的待办")');
    for (const r of routes) {
      cur = r; await page.goto(base + r); await page.waitForLoadState('networkidle'); await page.waitForTimeout(400);
      const res = await page.evaluate(() => {
        const out = [];
        const de = document.documentElement;
        if (de.scrollWidth > de.clientWidth + 1) out.push(`页面横向滚动 ${de.scrollWidth}>${de.clientWidth}`);
        for (const el of document.querySelectorAll('.tag,.seal')) {
          const cs = getComputedStyle(el);
          if (el.offsetParent && el.scrollWidth > el.clientWidth + 1 && cs.overflow !== 'visible') out.push(`截断 ${el.className}「${el.textContent.trim().slice(0, 30)}」`);
          const box = el.getBoundingClientRect(); const pr = el.parentElement.getBoundingClientRect();
          if (el.offsetParent && box.width > 0 && box.right > pr.right + 2 && getComputedStyle(el.parentElement).overflowX === 'visible' && !el.closest('.scroll-x,.chips,[class*=scroll]')) out.push(`溢出父容器 ${el.className}「${el.textContent.trim().slice(0, 30)}」`);
        }
        return out;
      });
      checked++;
      res.forEach((x) => bad.push(`${phone}@${w} ${r} ${x}`));
    }
    await ctx.close();
  }
  console.log(JSON.stringify({ checked, problems: bad }, null, 1));
  await b.close();
  process.exit(bad.length ? 1 : 0);
})();
