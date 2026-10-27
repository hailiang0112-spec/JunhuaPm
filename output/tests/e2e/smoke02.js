// SMOKE-02 核心闭环冒烟（浏览器 E2E，全部步骤在真实页面完成）
// 公司管理员从模板新建项目并邀请业主 / 项目经理 / 质检 / 设计经理 → 设计经理上传图纸 V1 → 业主签认图纸
// → 项目经理为一个工作项提交基线（含 1 个隐蔽检查点）→ 业主签认基线 → 质检上传 1 张照片核对「一致」→ 业主放行
// 用法：node smoke02.js [baseUrl]（默认 http://127.0.0.1:5305）
// 重复运行：受邀手机号已有账号时，邀请页走「输入登录密码加入」分支；每次新建一个带时间戳的项目，断言只看本项目。
const path = require('path');
const fs = require('fs');
const { spawnSync } = require('child_process');
const { chromium } = require('playwright');

const BASE = (process.argv[2] || 'http://127.0.0.1:5305').replace(/\/$/, '');
const OUT = path.join(__dirname, 'smoke02');
const FIX = path.join(OUT, 'fixtures');
const PDF = path.join(FIX, '水电点位图-V1.pdf');
const JPG = path.join(FIX, '现场照片-线管预埋.jpg');
const PY = '/home/user/君华别墅装修项目管理平台/app/backend/.venv/bin/python';
const ADMIN = { phone: '13800000000', pwd: 'Jh123456', name: '周经理' };
const PWD = 'Jh2026abc';
const PEOPLE = {
  owner: { phone: '13911110001', name: '刘先生', role: '业主' },
  pm: { phone: '13911110004', name: '张工', role: '项目经理' },
  qc: { phone: '13911110006', name: '王工', role: '质检' },
  dm: { phone: '13911110005', name: '李工', role: '设计经理' },
};
const VIEW = { viewport: { width: 1440, height: 900 }, timezoneId: 'Asia/Shanghai', locale: 'zh-CN' };
const T = 20000;

const stamp = new Date(Date.now() + 8 * 3600e3).toISOString().slice(5, 19).replace(/[-T:]/g, '');
const PROJECT = `云栖台 · 合院别墅装修工程（冒烟 ${stamp}）`;
const SET_NAME = '水电点位图';
const CK_POINT = '南墙新增插座底盒线管走向、埋深与图纸一致，线管固定间距不大于 1m';

fs.mkdirSync(OUT, { recursive: true });
function ensureFixtures() {
  if (fs.existsSync(PDF) && fs.existsSync(JPG)) return;
  fs.mkdirSync(FIX, { recursive: true });
  const code = `
from PIL import Image, ImageDraw
im=Image.new('RGB',(1600,1000),'white'); d=ImageDraw.Draw(im)
d.rectangle([80,80,1520,920],outline='black',width=6); d.line([800,80,800,920],fill='black',width=4); d.line([80,500,1520,500],fill='black',width=4)
for x in range(200,1500,200): d.ellipse([x-12,288,x+12,312],outline='blue',width=4)
im.save(${JSON.stringify(PDF)},'PDF',resolution=100)
p=Image.new('RGB',(1200,900),(180,170,150)); dp=ImageDraw.Draw(p)
for y in range(100,900,150): dp.line([0,y,1200,y+40],fill=(60,60,200),width=10)
p.save(${JSON.stringify(JPG)},'JPEG',quality=85)`;
  const r = spawnSync(PY, ['-c', code], { stdio: 'inherit' });
  if (r.status !== 0) throw new Error('生成 PDF / JPEG 测试文件失败');
}

// Playwright 1.63 对含中文的本地路径 setInputFiles 会得到 0 个文件，改为按内容传入（保留中文文件名）
const fileArg = (p, mimeType) => ({ name: path.basename(p), mimeType, buffer: fs.readFileSync(p) });

const consoleErrors = [];
const apiErrors = [];
const steps = [];
let shotNo = 0;

async function newRole(browser, role) {
  const ctx = await browser.newContext(VIEW);
  const page = await ctx.newPage();
  page.setDefaultTimeout(T);
  page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push({ role, url: page.url(), text: m.text() }); });
  page.on('pageerror', (e) => consoleErrors.push({ role, url: page.url(), text: `pageerror: ${e.message}` }));
  page.on('response', async (r) => {
    if (!r.url().includes('/api/') || r.status() < 400) return;
    let body = '';
    try { body = (await r.text()).slice(0, 400); } catch { /* 响应体不可读 */ }
    apiErrors.push({ role, method: r.request().method(), url: r.url().replace(BASE, ''), status: r.status(), body });
  });
  return { ctx, page, role };
}

async function shot(page, name) {
  shotNo += 1;
  const file = path.join(OUT, `${String(shotNo).padStart(2, '0')}-${name}.png`);
  await page.waitForTimeout(400);
  await page.screenshot({ path: file, fullPage: true });
  return file;
}

async function step(name, who, fn) {
  const t0 = Date.now();
  try {
    const detail = await fn();
    steps.push({ name, ok: true, ms: Date.now() - t0, detail: detail || '' });
    console.log(`✔ ${name}${detail ? ` — ${detail}` : ''}`);
  } catch (e) {
    let file = '';
    try { file = await shot(who.page, `失败-${name}`); } catch { /* 页面已关闭 */ }
    steps.push({ name, ok: false, ms: Date.now() - t0, detail: e.message.split('\n')[0], screenshot: file, url: who.page.url() });
    console.log(`✘ ${name} — ${e.message.split('\n')[0]}${file ? `（截图 ${file}）` : ''}`);
    throw e;
  }
}

async function login(p, phone, pwd) {
  await p.page.goto(`${BASE}/login`);
  await p.page.fill('#phone', phone);
  await p.page.fill('#pwd', pwd);
  await p.page.click('button[type=submit]');
  await p.page.waitForSelector('h1:has-text("我的待办")');
}

const dialog = (page, title) => page.locator(`[role=dialog][aria-label="${title}"]`);
const toast = (page, text) => page.locator('.toast', { hasText: text }).first().waitFor();

async function acceptInvite(p, link, person) {
  await p.page.goto(link);
  await p.page.waitForSelector('#jPhone');
  await p.page.fill('#jPhone', person.phone);
  const existing = (await p.page.locator('#jOld').count()) > 0;
  if (existing) {
    await p.page.fill('#jOld', PWD);
    await p.page.click('button:has-text("确认加入")');
  } else {
    await p.page.fill('#jName', person.name);
    await p.page.fill('#jPwd', PWD);
    await p.page.fill('#jPwd2', PWD);
    await p.page.click('button:has-text("设置密码并加入")');
  }
  await p.page.waitForSelector('h1:has-text("我的待办")');
  return existing ? '已有账号，输入原密码加入' : '';
}

// 业主待办中本项目的行（.todo 内 .p = 「项目名 · 类型」，.t = 标题）
async function ownerTodos(page) {
  await page.goto(`${BASE}/`);
  await page.waitForSelector('#todoHd');
  await page.waitForTimeout(500);
  return page.locator('.todo').evaluateAll((els, proj) => els.map((e) => ({
    p: e.querySelector('.p')?.textContent || '', t: e.querySelector('.t')?.textContent || '',
  })).filter((x) => x.p.startsWith(proj + ' · ')), PROJECT);
}

(async () => {
  ensureFixtures();
  const browser = await chromium.launch();
  const admin = await newRole(browser, '公司管理员');
  const roles = {};
  for (const k of Object.keys(PEOPLE)) roles[k] = await newRole(browser, PEOPLE[k].name);
  const { owner, pm, qc, dm } = roles;
  const ctx = { pid: 0, links: {}, wid: 0, wiName: '', cid: 0, ckCode: '', baselineTodo: '', releaseTodo: '' };
  let failed = false;

  try {
    await step('1 公司管理员登录', admin, async () => { await login(admin, ADMIN.phone, ADMIN.pwd); });

    await step('2 从公司模板新建项目', admin, async () => {
      const page = admin.page;
      await page.goto(`${BASE}/admin/projects`);
      await page.locator('button:has-text("新建项目")').first().click();
      const dlg = dialog(page, '新建项目');
      await dlg.locator('#nName').fill(PROJECT);
      await dlg.locator('#nAddr').fill('杭州市西湖区云栖台 7 号院');
      const d = new Date(Date.now() + 8 * 3600e3);
      const ymd = (x) => x.toISOString().slice(0, 10);
      await dlg.locator('#nStart').fill(ymd(d));
      await dlg.locator('#nEnd').fill(ymd(new Date(d.getTime() + 180 * 86400e3)));
      const tpl = dlg.locator('.tpl input[type=radio]').first();
      await tpl.waitFor();
      await tpl.check();
      await dlg.locator('button:has-text("创建项目")').click();
      await toast(page, `已创建「${PROJECT}」`);
      const row = page.locator('tr', { hasText: PROJECT });
      await row.locator('.seal', { hasText: '筹备' }).waitFor();
      const href = await row.locator('a:has-text("成员")').getAttribute('href');
      ctx.pid = Number(href.match(/\/p\/(\d+)\//)[1]);
      await shot(page, '建项目后');
      return `项目 ${ctx.pid}「${PROJECT}」状态筹备`;
    });

    await step('3 邀请业主、项目经理、质检、设计经理', admin, async () => {
      const page = admin.page;
      await page.goto(`${BASE}/p/${ctx.pid}/members`);
      for (const k of ['owner', 'pm', 'qc', 'dm']) {
        const who = PEOPLE[k];
        await page.locator('button:has-text("生成邀请")').click();
        const dlg = dialog(page, '生成邀请链接');
        await dlg.locator('#iPhone').fill(who.phone);
        await dlg.locator('label', { hasText: new RegExp(`^${who.role}$`) }).locator('input[type=checkbox]').check();
        await dlg.locator('button:has-text("生成链接")').click();
        const box = dlg.locator('.linkbox');
        await box.waitFor();
        ctx.links[k] = (await box.textContent()).trim();
        if (!/\/invite\/[\w-]+$/.test(ctx.links[k])) throw new Error(`邀请链接格式异常：${ctx.links[k]}`);
        await dlg.locator('button:has-text("完成")').click();
        await dlg.waitFor({ state: 'detached' });
      }
      await page.locator('h2#invHd').waitFor();
      await shot(page, '邀请后-邀请记录');
      return Object.entries(ctx.links).map(([k, v]) => `${PEOPLE[k].name} ${v.replace(BASE, '')}`).join('；');
    });

    await step('4 四位成员打开邀请链接加入', admin, async () => {
      const notes = [];
      for (const k of ['owner', 'pm', 'qc', 'dm']) {
        const r = await acceptInvite(roles[k], ctx.links[k], PEOPLE[k]);
        notes.push(`${PEOPLE[k].name}${r ? `（${r}）` : '（新注册）'}`);
      }
      await admin.page.goto(`${BASE}/p/${ctx.pid}/members`);
      for (const k of Object.keys(PEOPLE)) await admin.page.locator('.tags', { hasText: PEOPLE[k].role }).first().waitFor();
      await admin.page.waitForTimeout(500);
      const body = await admin.page.textContent('body');
      const miss = Object.values(PEOPLE).filter((p) => !body.includes(p.name));
      if (miss.length) throw new Error(`成员列表缺少：${miss.map((p) => p.name).join('、')}`);
      await shot(admin.page, '邀请后-成员已加入');
      return notes.join('、');
    });

    await step('5 设计经理新建分册并上传图纸 V1', dm, async () => {
      const page = dm.page;
      await page.goto(`${BASE}/p/${ctx.pid}/drawings`);
      await page.locator('button:has-text("新建分册")').first().click();
      const ns = dialog(page, '新建图纸分册');
      await ns.locator('input').fill(SET_NAME);
      await ns.locator('button:has-text("新建")').click();
      await toast(page, `已新建分册「${SET_NAME}」`);
      await page.locator('button:has-text("上传首版")').click();
      const up = dialog(page, `上传新版 · ${SET_NAME} V1`);
      await up.locator('input[type=file][accept=".pdf,.jpg,.jpeg,.png"]').setInputFiles(fileArg(PDF, 'application/pdf'));
      await up.locator('textarea').fill('首版：一至三层强弱电点位、给排水点位');
      await up.locator('button:has-text("发布")').click();
      await dialog(page, `发布 ${SET_NAME} V1`).locator('button:has-text("确认发布")').click();
      await toast(page, `已发布 ${SET_NAME} V1`);
      await page.locator('.tl li', { hasText: 'V1' }).locator('.seal', { hasText: '待签认' }).waitFor();
      await shot(page, '图纸V1已发布');
    });

    await step('6 业主在图纸页签认 V1', owner, async () => {
      const page = owner.page;
      await page.goto(`${BASE}/p/${ctx.pid}/drawings`);
      await page.locator('button:has-text("签认 V1")').click();
      await dialog(page, `签认${SET_NAME} V1`).locator('button:has-text("确认签认")').click();
      await toast(page, 'V1 已签认');
      await page.locator('.tl li', { hasText: 'V1' }).locator('.seal', { hasText: '已签认' }).waitFor();
      await page.locator('.signrec').waitFor();
      await shot(page, '图纸V1业主签认后');
      return (await page.locator('.signrec').textContent()).trim();
    });

    await step('7 项目经理进入工段并打开一个工作项', pm, async () => {
      const page = pm.page;
      await page.goto(`${BASE}/p/${ctx.pid}`);
      const cards = page.locator('a.phcard');
      await cards.first().waitFor();
      const water = page.locator('a.phcard', { hasText: '水电' });
      await ((await water.count()) ? water.first() : cards.first()).click();
      await page.waitForURL(/\/phase\/\d+/);
      const link = page.locator('table.tasktbl a.tn').first();
      await link.waitFor();
      ctx.wiName = (await link.textContent()).trim();
      await link.click();
      await page.waitForURL(/\/work-items\/\d+/);
      ctx.wid = Number(page.url().match(/work-items\/(\d+)/)[1]);
      await page.locator('#hBase').waitFor();
      return `工作项 ${ctx.wid}「${ctx.wiName}」`;
    });

    await step('8 项目经理填写基线并保存草稿（引用已签认图纸 V1）', pm, async () => {
      const page = pm.page;
      await page.locator('button:has-text("编辑并提交待签")').click();
      const dlg = dialog(page, '编辑基线');
      const sel = dlg.locator('.field', { hasText: '签认版图纸分册与版本' }).locator('select');
      await sel.locator('option', { hasText: `${SET_NAME} V1` }).first().waitFor({ state: 'attached' });
      const val = await sel.locator('option', { hasText: `${SET_NAME} V1` }).first().getAttribute('value');
      await sel.selectOption(val);
      const ta = dlg.locator('textarea');
      if (!(await ta.nth(0).inputValue()).trim()) await ta.nth(0).fill('按水电点位图 V1 开槽、预埋 PVC 线管，强弱电分管敷设');
      if (!(await ta.nth(1).inputValue()).trim()) await ta.nth(1).fill('线管走向与图纸一致，埋深不小于 15mm，固定间距不大于 1m');
      await dlg.locator('.field', { hasText: '费用（元）' }).locator('input').fill('3860');
      const fin = new Date(Date.now() + 8 * 3600e3 + 30 * 86400e3).toISOString().slice(0, 10);
      await dlg.locator('.field', { hasText: '计划完成日期' }).locator('input').fill(fin);
      const qcSel = dlg.locator('.field', { hasText: '质检人' }).locator('select');
      await qcSel.selectOption({ label: PEOPLE.qc.name });
      await dlg.locator('button:has-text("保存草稿")').click();
      await toast(page, '基线草稿已保存');
      await dlg.waitFor({ state: 'detached' });
    });

    await step('9 项目经理在签认图上点选位置新建 1 个隐蔽检查点', pm, async () => {
      const page = pm.page;
      await page.locator('button:has-text("新建检查点")').click();
      const dlg = dialog(page, '新建检查点');
      await dlg.locator('textarea').first().fill(CK_POINT);
      await dlg.locator('input[name=hid]').first().check();
      const img = dlg.locator('.pickwrap .dstage img');
      await img.waitFor();
      await page.waitForFunction(() => { const i = document.querySelector('.pickwrap .dstage img'); return i && i.complete && i.naturalWidth > 0; });
      const box = await img.boundingBox();
      await page.mouse.click(box.x + box.width * 0.35, box.y + box.height * 0.3);
      await dlg.locator('.dpin.s-new').waitFor();
      await dlg.locator('button:has-text("保存检查点")').click();
      await toast(page, '已加入基线编辑稿');
      await dlg.waitFor({ state: 'detached' });
      const row = page.locator('a.ckrow').first();
      await row.waitFor();
      ctx.cid = Number((await row.getAttribute('href')).match(/checkpoints\/(\d+)/)[1]);
      ctx.ckCode = (await row.locator('.idc').textContent()).trim();
      const txt = await row.textContent();
      if (!txt.includes('隐蔽') || txt.includes('非隐蔽')) throw new Error(`检查点不是隐蔽：${txt}`);
      return `${ctx.ckCode}（id ${ctx.cid}）`;
    });

    await step('10 项目经理提交基线给业主签认', pm, async () => {
      const page = pm.page;
      await page.locator('button:has-text("编辑并提交待签")').click();
      const dlg = dialog(page, '编辑基线');
      await dlg.locator('.ckdraft li', { hasText: ctx.ckCode }).waitFor();
      await dlg.locator('button:has-text("提交业主签认")').click();
      await toast(page, '已提交，等待业主签认');
      await page.locator('#hBase').locator('xpath=..').locator('.seal', { hasText: '待签认' }).waitFor();
      await shot(page, '基线提交后');
    });

    await step('11 业主待办（签认前）出现基线签认待办', owner, async () => {
      const rows = await ownerTodos(owner.page);
      const bl = rows.find((r) => r.p.endsWith(' · 待签基线') && r.t.includes(ctx.wiName));
      if (!bl) throw new Error(`业主待办中没有本项目基线签认待办：${JSON.stringify(rows)}`);
      ctx.baselineTodo = bl.t;
      await shot(owner.page, '业主待办-基线签认前');
      return `${bl.p} / ${bl.t}`;
    });

    await step('12 业主在基线签认页展开并签认', owner, async () => {
      const page = owner.page;
      const row = page.locator('.todo', { hasText: PROJECT }).filter({ hasText: ctx.baselineTodo });
      await row.locator('a:has-text("去处理")').click();
      await page.waitForURL(/\/baselines/);
      const it = page.locator('.it', { hasText: ctx.wiName }).first();
      await it.locator('button.exp').click();
      await it.locator('.cks', { hasText: ctx.ckCode }).waitFor();
      await it.locator('button:has-text("签认此项")').click();
      await dialog(page, '签认 1 项基线').locator('button:has-text("确认签认")').click();
      await toast(page, '已签认 1 项');
      await it.locator('.seal', { hasText: '已签认' }).waitFor();
      await shot(page, '业主签认基线后');
    });

    await step('13 质检打开检查点，上传 1 张照片并核对为「一致」', qc, async () => {
      const page = qc.page;
      await page.goto(`${BASE}/`);
      await page.waitForSelector('#todoHd');
      await page.waitForTimeout(500);
      const qcRows = await page.locator('.todo').evaluateAll((els) => els.map((e) => `${e.querySelector('.p')?.textContent} / ${e.querySelector('.t')?.textContent}`));
      const todo = page.locator('.todo', { hasText: PROJECT }).filter({ hasText: `${ctx.ckCode} ` });
      const viaTodo = (await todo.count()) > 0;
      if (viaTodo) await todo.first().locator('a:has-text("去处理")').click();
      else await page.goto(`${BASE}/p/${ctx.pid}/checkpoints/${ctx.cid}`);
      await page.waitForURL(new RegExp(`/checkpoints/${ctx.cid}`));
      await page.locator('#hForm').waitFor();
      await page.locator('label.addtile', { hasText: '相册' }).locator('input[type=file]').setInputFiles(fileArg(JPG, 'image/jpeg'));
      await page.locator('.ptile .pst.ok').waitFor();
      await page.locator('input[name=conc][value="一致"]').check();
      await page.locator('input[name=cover][value="未覆盖"]').check();
      await page.locator('button:has-text("提交核对记录")').click();
      await page.locator('[role=dialog] button:has-text("确认提交")').click();
      await toast(page, '已保存');
      await page.locator('#hRel').locator('xpath=..').locator('.seal', { hasText: '待放行' }).waitFor();
      await shot(page, '质检核对后');
      return viaTodo ? '经质检「我的待办」进入' : `质检待办中未找到该检查点，按地址进入；质检待办 ${qcRows.length} 项：${qcRows.slice(0, 5).join('；')}`;
    });

    await step('14 业主待办（放行前）出现该检查点放行待办', owner, async () => {
      const rows = await ownerTodos(owner.page);
      const rel = rows.find((r) => r.p.endsWith(' · 待放行检查点') && r.t.startsWith(`${ctx.ckCode} `));
      if (!rel) throw new Error(`业主待办中没有本项目检查点放行待办：${JSON.stringify(rows)}`);
      ctx.releaseTodo = rel.t;
      const stillBl = rows.find((r) => r.t === ctx.baselineTodo && r.p.endsWith(' · 待签基线'));
      await shot(owner.page, '业主待办-放行前');
      if (stillBl) throw new Error(`基线已签认但签认待办仍在：${JSON.stringify(stillBl)}`);
      return `${rel.p} / ${rel.t}`;
    });

    await step('15 业主放行该检查点', owner, async () => {
      const page = owner.page;
      const row = page.locator('.todo', { hasText: PROJECT }).filter({ hasText: ctx.releaseTodo });
      await row.locator('a:has-text("去处理")').click();
      await page.waitForURL(new RegExp(`/checkpoints/${ctx.cid}`));
      await page.locator('button:has-text("放行")').first().click();
      await dialog(page, `确认放行 ${ctx.ckCode}`).locator('button:has-text("确认放行")').click();
      await toast(page, '已放行');
      await shot(page, '业主放行后');
    });

    await step('16 断言：检查点详情显示「已放行」印章', owner, async () => {
      const page = owner.page;
      await page.reload();
      await page.locator('#hHead').locator('xpath=..').locator('.seal.pass', { hasText: '已放行' }).waitFor();
      await page.locator('#hRel').locator('xpath=..').locator('.seal.pass', { hasText: '已放行' }).waitFor();
      return `${ctx.ckCode} 检查点卡与业主放行卡均为「已放行」`;
    });

    await step('17 断言：工作项基线显示「已签认」', owner, async () => {
      const page = owner.page;
      await page.goto(`${BASE}/p/${ctx.pid}/work-items/${ctx.wid}`);
      await page.locator('#hBase').locator('xpath=..').locator('.seal.pass', { hasText: '已签认' }).waitFor();
      await page.locator('a.ckrow', { hasText: ctx.ckCode }).locator('.seal', { hasText: '已放行' }).waitFor();
      await shot(page, '工作项基线已签认');
    });

    await step('18 断言：业主待办中放行待办与基线签认待办均已消失', owner, async () => {
      const rows = await ownerTodos(owner.page);
      await shot(owner.page, '业主待办-放行后');
      const left = rows.filter((r) => (r.p.endsWith(' · 待签基线') && r.t === ctx.baselineTodo) || r.t.startsWith(`${ctx.ckCode} `));
      if (left.length) throw new Error(`仍存在对应待办：${JSON.stringify(left)}`);
      return `本项目剩余业主待办 ${rows.length} 项${rows.length ? `：${rows.map((r) => r.t).join('；')}` : ''}`;
    });
  } catch {
    failed = true;
  }

  await browser.close();
  const result = { project: PROJECT, ctx, steps, consoleErrors, apiErrors };
  fs.writeFileSync(path.join(OUT, 'result.json'), JSON.stringify(result, null, 2));
  console.log('\n控制台 error / pageerror：', consoleErrors.length ? JSON.stringify(consoleErrors, null, 2) : '无');
  console.log('接口 4xx/5xx：', apiErrors.length ? JSON.stringify(apiErrors, null, 2) : '无');
  const ok = !failed && steps.every((s) => s.ok) && !consoleErrors.length;
  console.log(ok ? '\nSMOKE-02 通过' : '\nSMOKE-02 未通过');
  process.exit(ok ? 0 : 1);
})();
