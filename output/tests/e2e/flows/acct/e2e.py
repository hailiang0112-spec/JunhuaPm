"""acct 浏览器 E2E：FLOW-01 / 02 / 03 / 14 / 21（TDD 验收契约 FLOW 行「浏览器 E2E」部分）。

前置：run.sh 已建库、seed_demo、seed.py。所有业务操作都在真实页面完成；API 只用于读取断言所需的事实。
"""
import datetime
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "_lib"))
from harness import WEB, Run  # noqa: E402

SEED = json.load(open(os.path.join(HERE, "seed.json")))
PID, PID2 = SEED["pid"], SEED["pid2"]
BACKEND_LOG = os.path.join(HERE, "logs", "backend.log")
# 预期的业务 4xx：登录失败 401/423、被拒操作 403/409/422、未登录探测 /api/me 401
R = Run(HERE, expected_http=[r"/api/auth/login", r"/api/me\b", r"/invitations", r"/status", r"/members", r"/api/projects/\d+/?$",
                             r"/api/todos", r"/api/projects$", r"/checkpoints/\d+", r"/admin/templates"])


def fetch(page, path):
    return page.evaluate("p => fetch('/api' + p).then(r => r.json())", path)


def todo_rows(page):
    page.wait_for_selector(".todo, .state", timeout=15000)
    page.wait_for_timeout(300)
    return page.locator(".todo").count()


def nav_badge(page):
    loc = page.locator(".side .navitem .badge, .tabbar .badge").first
    return loc.inner_text().strip() if loc.count() else "0"


def types_of(page):
    return set(x["type"] for x in fetch(page, "/todos")["items"])


# ———————————————————————————————— FLOW-01 ————————————————————————————————
R.flow = "FLOW-01"
st = {}


def f01_create():
    ctx, page = R.ctx("admin", 1440)
    page.goto(WEB + "/admin/projects")
    page.wait_for_selector("tbody tr")
    before = len(fetch(page, "/projects")["items"])
    page.click(".topbar .btn.primary")
    page.click("button:has-text('创建项目')")
    errs = page.locator(".field.invalid .err").all_inner_texts()
    R.check("缺项目名称提交被拒并提示", any("项目名称" in e for e in errs), errs)
    R.check("被拒后不产生项目", len(fetch(page, "/projects")["items"]) == before)
    page.fill("#nName", "湖畔花园 · 叠拼别墅")
    page.fill("#nAddr", "湖畔路 2 号")
    page.fill("#nStart", "2026-12-01")
    page.fill("#nEnd", "2027-11-30")
    tpl = page.locator(".dialog select").first
    if tpl.count():
        opts = tpl.locator("option").all_inner_texts()
        R.check("模板下拉含「君华」模板", any("君华" in o for o in opts), opts)
    page.click("button:has-text('创建项目')")
    R.check("完整提交后 toast", R.toast(page, "湖畔花园"))
    page.wait_for_timeout(800)
    p = next((x for x in fetch(page, "/projects")["items"] if x["name"] == "湖畔花园 · 叠拼别墅"), None)
    R.check("新项目出现在列表且状态「筹备」", p and p["status"] == "筹备", p)
    if p:
        s = fetch(page, f"/projects/{p['id']}/structure")
        wis = fetch(page, f"/projects/{p['id']}/work-items")["items"]
        got = (len(s["floors"]), len(s["rooms"]), len(s["phases"]), len(wis))
        R.check("模板复制到位：楼层 6、房间 32、工段 6、工作项 187", got == (6, 32, 6, 187), got)
        st["p3"] = p["id"]
        st["p3weights"] = [x["weight"] for x in s["phases"]]
    R.shot(page, "F01-01-projects-1440")
    ctx.close()
    ctx, page = R.ctx("admin", 375)
    page.goto(WEB + "/admin/projects")
    page.wait_for_selector("text=湖畔花园")
    R.check("375 项目管理无横向滚动", R.hs(page, "PAGE-F01-01 项目管理"))
    page.click(".topbar .btn.primary")
    page.wait_for_selector("#nName")
    R.check("375 新建项目弹窗无横向滚动", R.hs(page, "PAGE-F01-01 新建弹窗"))
    R.shot(page, "F01-01-new-375")
    ctx.close()


def f01_roles():
    ctx, page = R.ctx("admin", 1440)
    page.goto(f"{WEB}/p/{PID}/members")
    row = page.locator(".mrow", has_text="孙工")
    row.locator("text=编辑角色").click()
    page.check(".dialog label:has-text('预算专员') input")
    page.click(".dlg-ft button:has-text('保存')")
    R.check("多角色保存 toast", R.toast(page, "孙工"))
    page.wait_for_timeout(500)
    tags = row.locator(".tags").inner_text()
    R.check("孙工同时具有质检与预算专员", "质检" in tags and "预算专员" in tags, tags)
    R.shot(page, "F01-02-roles-1440")
    ctx.close()
    ctx, page = R.ctx("13800000008", 1440)
    names = [x["name"] for x in fetch(page, "/projects")["items"]]
    R.check("角色只在该项目生效：孙工项目列表只含君华新城", names == [n for n in names if n.startswith("君华新城")] and len(names) == 1, names)
    roles = fetch(page, f"/projects/{PID}")
    R.check("孙工在本项目角色含 budget", "budget" in json.dumps(roles), str(roles)[:200])
    ctx.close()


def f01_invite():
    ctx, page = R.ctx("pm", 1440)
    page.goto(f"{WEB}/p/{PID}/members")
    page.click(".topbar .btn.primary")
    page.fill("#iPhone", "13900001111")
    adm = page.locator(".dialog label:has-text('公司管理员') input")
    if adm.count():
        adm.check()
        page.click("button:has-text('生成链接')")
        page.wait_for_timeout(600)
        msg = " ".join(page.locator(".dialog .err, .dialog .notice, .toast").all_inner_texts())
        R.check("项目经理邀请公司管理员被拒「只有公司管理员可以设置该角色」", "只有公司管理员可以设置该角色" in msg, msg)
        adm.uncheck()
    else:
        R.check("项目经理邀请弹窗不提供公司管理员角色（无法设置）", True)
    page.check(".dialog label:has-text('质检') input")
    page.click("button:has-text('生成链接')")
    page.wait_for_selector(".linkbox")
    link = page.locator(".linkbox").inner_text().strip()
    R.check("生成邀请链接", "/invite/" in link, link)
    hint = page.locator(".dialog").inner_text()
    m = re.search(r"仅可使用一次，(\d{4}-\d{2}-\d{2} \d{2}:\d{2}) 前有效", hint)
    exp = datetime.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M") if m else None
    now_bj = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) + datetime.timedelta(hours=8)
    R.check("邀请一次性、7 天有效（截止 = 现在 + 7 天）", exp and abs((exp - now_bj).total_seconds() - 7 * 86400) < 180, hint[:200])
    page.click(".dlg-ft button:has-text('完成')")
    ctx.close()
    path = link[link.index("/invite/"):]
    # 新手机号加入（375）
    ctx, page = R.ctx("anon", 375, login=None)
    page.goto(WEB + path)
    page.wait_for_selector("#jPhone")
    R.check("375 邀请页无横向滚动", R.hs(page, "PAGE-F02-02 邀请落地"))
    page.fill("#jPhone", "13900001111")
    page.fill("#jName", "冯质检")
    page.fill("#jPwd", "Fz2026abc")
    page.fill("#jPwd2", "Fz2026abc")
    page.click("button[type=submit]")
    page.wait_for_url(WEB + "/", timeout=10000)
    me = fetch(page, "/me")
    R.check("新号以所填姓名建号并进入首页", me.get("name") == "冯质检", me)
    R.shot(page, "F02-02-joined-375")
    page.goto(WEB + path)
    page.wait_for_selector("#invTitle")
    R.check("邀请一次性：再次打开提示「邀请已失效…」", "邀请已失效" in page.inner_text("#invTitle"))
    R.shot(page, "F02-02-dead-375")
    ctx.close()
    ctx, page = R.ctx("13900001111", 375, password="Fz2026abc", expect=[r"/api/projects/\d+/"])
    st["feng"] = ctx  # 留着给「移除后下一次请求即无权」
    st["fengPage"] = page
    # 已有账号加入（项目经理在第二个项目邀请赵会计）
    ctx, page = R.ctx("pm", 1440)
    page.goto(f"{WEB}/p/{PID2}/members")
    page.click(".topbar .btn.primary")
    page.fill("#iPhone", "13800000007")
    page.check(".dialog label:has-text('预算专员') input")
    page.click("button:has-text('生成链接')")
    page.wait_for_selector(".linkbox")
    link2 = page.locator(".linkbox").inner_text().strip()
    ctx.close()
    ctx, page = R.ctx("anon", 1440, login=None)
    page.goto(WEB + link2[link2.index("/invite/"):])
    page.wait_for_selector(".notice.info")
    R.check("已有账号显示「输入你的登录密码即可加入」", "输入你的登录密码即可加入" in page.inner_text(".notice.info"))
    page.fill("#jPhone", "13800000007")
    page.fill("#jOld", "Wrong2026x")
    page.click("button[type=submit]")
    page.wait_for_timeout(800)
    R.check("已有账号输错原密码被拒", "原密码不正确" in page.inner_text("body"))
    page.fill("#jOld", "Jh123456")
    page.click("button[type=submit]")
    page.wait_for_url(WEB + "/", timeout=10000)
    names = [x["name"] for x in fetch(page, "/projects")["items"]]
    R.check("已有账号关联到第二个项目", any(n.startswith("滨江壹号") for n in names), names)
    R.shot(page, "F02-02-exist-1440")
    ctx.close()
    ctx, page = R.ctx("budget", 1440)  # 原密码仍可登录 = 密码不变
    R.check("已有账号加入后原密码不变（仍可用原密码登录）", "/login" not in page.url)
    ctx.close()


def f01_owner_invite():
    ctx, page = R.ctx("owner", 1440)
    page.goto(f"{WEB}/p/{PID}/members")
    page.click(".topbar .btn.primary")
    page.wait_for_selector(".dialog")
    opts = [x.strip() for x in page.locator(".dialog .checks label").all_inner_texts()]
    R.check("业主邀请只能选「业主方成员」", opts == ["业主方成员"], opts)
    page.click(".dlg-ft button:has-text('取消')")
    ctx.close()


def f01_template():
    ctx, page = R.ctx("admin", 1440)
    page.goto(WEB + "/admin/templates")
    page.wait_for_selector("tbody tr")
    rows = page.locator("tbody tr")
    for i, w in ((0, None), (1, None)):
        pass
    w0 = st["p3weights"][0]
    w1 = st["p3weights"][1]
    for i, w in ((0, w0 + 2), (1, w1 - 2)):
        rows.nth(i).locator("text=编辑").click()
        page.fill(".dialog input[type=number]", str(w))
        page.click(".dlg-ft button:has-text('保存工段')")
        page.wait_for_timeout(200)
    page.click(".topbar button:has-text('保存模板')")
    R.check("修改公司模板（工段权重）保存成功", R.toast(page, "模板"), page.locator(".toast").all_inner_texts())
    R.shot(page, "F03-01-template-1440")
    page.goto(WEB + "/admin/projects")
    page.click(".topbar .btn.primary")
    page.fill("#nName", "云栖台 · 合院别墅")
    page.fill("#nAddr", "云栖路 6 号")
    page.fill("#nStart", "2026-11-20")
    page.fill("#nEnd", "2027-10-30")
    page.click("button:has-text('创建项目')")
    R.check("改模板后再建项目成功", R.toast(page, "云栖台"))
    page.wait_for_timeout(800)
    p4 = next(x for x in fetch(page, "/projects")["items"] if x["name"] == "云栖台 · 合院别墅")
    new_w = [x["weight"] for x in fetch(page, f"/projects/{p4['id']}/structure")["phases"]][:2]
    old_w = [x["weight"] for x in fetch(page, f"/projects/{st['p3']}/structure")["phases"]][:2]
    R.check("新项目按修改后的模板（权重 +2/−2）", new_w == [w0 + 2, w1 - 2], new_w)
    R.check("模板修改不影响已建项目", old_w == [w0, w1], old_w)
    ctx.close()


def f01_remove():
    ctx, page = R.ctx("admin", 1440)
    page.goto(f"{WEB}/p/{PID}/members")
    row = page.locator(".mrow", has_text="冯质检")
    row.locator("text=移除").click()
    page.click(".dlg-ft button:has-text('确认移除')")
    R.check("移除成员 toast", R.toast(page, "已移除 冯质检"))
    ctx.close()
    page = st["fengPage"]
    page.goto(f"{WEB}/p/{PID}/checkpoints")
    page.wait_for_timeout(1500)
    body = page.inner_text("body")
    R.check("被移除者下一次请求即无权访问", "/forbidden" in page.url or "无权" in body or "没有权限" in body, page.url + " " + body[:120])
    R.shot(page, "F01-03-removed-375")
    st["feng"].close()


def f01_deliver():
    ctx, page = R.ctx("pm", 1440)
    page.goto(f"{WEB}/p/{PID2}/members")
    page.click("text=推进为已交房")
    page.click(".dlg-ft button:has-text('下一步')")
    errs = page.locator(".field.invalid .err").all_inner_texts()
    R.check("已交房缺日期被拒「请填写实际交房日期」", any("请填写实际交房日期" in e for e in errs), errs)
    R.shot(page, "F01-02-deliver-1440")
    page.click(".dlg-ft button:has-text('取消')")
    R.check("项目状态未变（仍为施工中）", fetch(page, f"/projects/{PID2}")["status"] == "施工中")
    ctx.close()


for name, fn in (("新建项目", f01_create), ("多角色", f01_roles), ("邀请", f01_invite), ("业主邀请", f01_owner_invite),
                 ("改模板再建项目", f01_template), ("移除成员", f01_remove), ("已交房缺日期", f01_deliver)):
    R.step(name, fn)

# ———————————————————————————————— FLOW-03 ————————————————————————————————
R.flow = "FLOW-03"


def f03_login():
    for w in (1440, 375):
        ctx, page = R.ctx("anon", w, login=None)
        page.goto(WEB + "/login")
        R.check(f"{w} 登录页无横向滚动", R.hs(page, "PAGE-F02-01 登录"))
        page.fill("#phone", "13800000006")
        page.fill("#pwd", "Jh123456")
        page.click("button[type=submit]")
        page.wait_for_url(WEB + "/", timeout=10000)
        page.wait_for_selector(".todo, .state")
        R.check(f"{w} 正确密码登录进入我的待办", page.url == WEB + "/" and "待办" in page.inner_text("body"))
        sid = next((c for c in ctx.cookies() if c["name"] == "sessionid"), None)
        left = (sid["expires"] - time.time()) / 86400 if sid else 0
        R.check(f"{w} 会话 7 天无操作失效（Cookie 有效期 ≈7 天）", 6.9 < left <= 7.01, round(left, 3))
        ctx.close()


def f03_lock():
    ctx, page = R.ctx("anon", 375, login=None)
    page.goto(WEB + "/login")
    for i in range(5):
        page.fill("#phone", "13800000009")
        page.fill("#pwd", f"Wrong{i}abc")
        page.click("button[type=submit]")
        page.wait_for_timeout(700)
    body = page.inner_text("body")
    m = re.search(r"请在\s*(\d{1,2}):(\d{2})\s*后重试", body)
    R.check("第 5 次错误后锁定并显示剩余时间", "该账号已锁定" in body and m is not None, body[:200])
    if m:
        R.check("剩余时间约 15 分钟", 14 * 60 <= int(m.group(1)) * 60 + int(m.group(2)) <= 15 * 60, m.group(0))
    R.check("锁定期间登录按钮不可用", page.locator("button[type=submit]").is_disabled())
    R.shot(page, "F02-01-locked-375")
    page.fill("#pwd", "Jh123456")
    ctx.close()


def f03_reset():
    ctx, page = R.ctx("admin", 1440)
    page.goto(f"{WEB}/p/{PID}/members")
    row = page.locator(".mrow", has_text="陈女士")
    row.locator("text=重置密码").click()
    with page.expect_response(lambda r: "reset-password" in r.url) as rr:
        page.click(".dlg-ft button:has-text('确认重置')")
    resp = rr.value
    cc = resp.headers.get("cache-control", "")
    R.check("重置密码接口响应不可缓存（Cache-Control: no-store）", "no-store" in cc, cc)
    page.wait_for_selector(".temp-pwd")
    temp = page.locator(".temp-pwd").inner_text().strip()
    R.check("临时密码在重置弹窗中显示", len(temp) >= 8, temp)
    R.shot(page, "F01-02-temp-1440")
    page.click(".dlg-ft button:has-text('关闭')")
    page.wait_for_timeout(300)
    R.check("关闭后临时密码不再显示（只显示一次）", page.locator(".temp-pwd").count() == 0 and temp not in page.inner_text("body"))
    page.reload()
    page.wait_for_selector(".mrow")
    R.check("刷新后页面不含临时密码", temp not in page.content())
    ctx.close()
    time.sleep(1)
    log = open(BACKEND_LOG, encoding="utf-8", errors="ignore").read()
    R.check("服务端日志检索不到临时密码明文", temp not in log, f"backend.log {len(log)} 字节")
    ctx, page = R.ctx("anon", 375, login=None)
    page.goto(WEB + "/login")
    page.fill("#phone", "13800000010")
    page.fill("#pwd", temp)
    page.click("button[type=submit]")
    page.wait_for_url(lambda u: "/login" not in u, timeout=10000)
    page.wait_for_selector(".force-banner")
    R.check("临时密码登录后进入改密页并提示", "/me" in page.url and "临时密码" in page.inner_text(".force-banner"))
    R.check("375 强制改密页无横向滚动", R.hs(page, "PAGE-F02-03 强制改密"))
    R.shot(page, "F02-03-forced-375")
    page.locator(".tabbar a").first.click()
    page.wait_for_timeout(500)
    R.check("改密前点导航仍停留在个人设置", "/me" in page.url, page.url)
    page.fill("#pNew", "Jh123456")
    page.fill("#pNew2", "Jh123456")
    page.click("form button[type=submit]")
    page.wait_for_url(WEB + "/", timeout=10000)
    R.check("设置新密码后可访问首页", page.url == WEB + "/")
    ctx.close()


def f03_two_devices():
    a, pa = R.ctx("13800000010", 1440)
    b, pb = R.ctx("13800000010", 375)
    pa.goto(WEB + "/me")
    pa.fill("#pOld", "Wrong999x")
    pa.fill("#pNew", "Cn2026abc")
    pa.fill("#pNew2", "Cn2026abc")
    pa.click("form button[type=submit]")
    pa.wait_for_timeout(700)
    R.check("原密码错误被拒", "原密码不正确" in pa.inner_text("body"))
    pa.fill("#pOld", "Jh123456")
    pa.click("form button[type=submit]")
    R.check("修改密码成功 toast", R.toast(pa, "密码"))
    R.shot(pa, "F02-03-changed-1440")
    pb.goto(WEB + "/")
    pb.wait_for_timeout(2000)
    R.check("改密后另一设备的会话失效（回到登录页）", "/login" in pb.url, pb.url)
    pa.goto(WEB + "/")
    pa.wait_for_timeout(1000)
    R.check("改密设备本身仍保持登录", "/login" not in pa.url, pa.url)
    a.close()
    b.close()


for name, fn in (("登录", f03_login), ("锁定", f03_lock), ("重置密码", f03_reset), ("两台设备", f03_two_devices)):
    R.step(name, fn)

# ———————————————————————————————— FLOW-21 ————————————————————————————————
R.flow = "FLOW-21"
EXPECT = {
    "owner": ({"待放行检查点", "待签基线", "待签图纸", "待签变更单"}, set()),
    "member": ({"待放行检查点"}, {"待放行检查点"}),
    "qc": ({"待核对检查点"}, {"待核对检查点"}),
    "budget": ({"待预算定价变更单"}, {"待预算定价变更单"}),
    "dm": ({"待出新版图纸"}, {"待出新版图纸"}),
    "pm": ({"被退回基线", "被驳回变更单", "即将施工，基线未签认"}, set()),
}
FORBIDDEN_FOR = {"owner": {"待核对检查点", "待预算定价变更单", "被退回基线", "被驳回变更单", "待出新版图纸"},
                 "pm": {"待签基线", "待签图纸", "待签变更单", "待核对检查点", "待预算定价变更单"}}


def f21_roles():
    for who, (must, only) in EXPECT.items():
        for w in (1440, 375):
            ctx, page = R.ctx(who, w)
            n = todo_rows(page)
            types = types_of(page)
            api_total = fetch(page, "/todos/count")["total"]
            if w == 1440:
                R.check(f"{who} 待办类型包含 {sorted(must)}", must <= types, sorted(types))
                if only:
                    R.check(f"{who} 只看到其待办类型", types == only, sorted(types))
                if who in FORBIDDEN_FOR:
                    R.check(f"{who} 看不到其他角色的待办类型", not (types & FORBIDDEN_FOR[who]), sorted(types & FORBIDDEN_FOR[who]))
                if who == "pm":
                    rel = [x for x in fetch(page, "/todos")["items"] if x["type"] == "待放行检查点"]
                    R.check("项目经理的待放行只含超时项", all(x["urgent"] for x in rel), [x["title"] for x in rel])
            R.check(f"{who}@{w} 导航总数与列表条数一致", str(n) == nav_badge(page) == str(api_total), (n, nav_badge(page), api_total))
            R.check(f"{who}@{w} 首页无横向滚动", R.hs(page, f"PAGE-F16-01 我的待办 {who}"))
            R.shot(page, f"F16-01-{who}-{w}")
            ctx.close()


def f21_release_and_copy():
    ctx, page = R.ctx("owner", 375)
    ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=WEB)
    todo_rows(page)
    before = page.locator(".todo").count()
    badge0 = nav_badge(page)
    first = page.locator(".todo").first
    first.locator("button:has-text('复制微信消息')").click()
    R.check("复制后提示「已复制」", R.toast(page, "已复制"))
    clip = page.evaluate("navigator.clipboard.readText()")
    item = fetch(page, "/todos")["items"][0]
    R.check("剪贴板含项目名", item["projectName"] in clip, clip)
    R.check("剪贴板含事项", item["title"] in clip, clip)
    R.check("剪贴板含负责人", "刘先生" in clip, clip)
    R.check("剪贴板含截止或超时信息", ("超时" in clip) or ("截止" in clip) or ("计划" in clip), clip)
    R.check("剪贴板含直达链接", re.search(r"https?://\S+" + re.escape(item["path"]), clip) is not None, clip)
    # 放行一条待放行检查点
    rel = [x for x in fetch(page, "/todos")["items"] if x["kind"] == "release" and not x["urgent"]]
    target = rel[0]
    page.goto(WEB + target["path"])
    btn = page.locator("button.btn.primary.block", has_text="放行")
    btn.wait_for(timeout=10000)
    btn.click()
    page.locator(".dialog button", has_text="确认放行").click()
    R.check("业主放行成功 toast", R.toast(page, "已放行"))
    page.goto(WEB + "/")
    page.wait_for_timeout(800)
    after = todo_rows(page)
    ids = [x["id"] for x in fetch(page, "/todos")["items"]]
    R.check("放行后该待办消失", target["id"] not in ids)
    R.check("待办数量减 1 且导航数同步", after == before - 1 and nav_badge(page) == str(int(badge0) - 1), (before, after, badge0, nav_badge(page)))
    st["releasedByOwner"] = target["objectId"]
    ctx.close()


R.step("各角色待办", f21_roles)
R.step("放行与复制微信消息", f21_release_and_copy)

# ———————————————————————————————— FLOW-02 ————————————————————————————————
R.flow = "FLOW-02"


def release_btn(page):
    page.wait_for_selector(".ck-detail", timeout=15000)
    page.wait_for_timeout(500)
    return page.locator("button.btn.primary.block", has_text="放行").count()


def f02_agent():
    cps = None
    o, op = R.ctx("owner", 1440)
    cps = {c["code"]: c["id"] for c in fetch(op, f"/projects/{PID}/checkpoints")["items"] if c["status"] == "待放行"}
    pending = [c for c in cps.values() if c != st.get("releasedByOwner")]
    st["agentTarget"], st["agentTarget2"] = pending[0], pending[1]
    op.goto(f"{WEB}/p/{PID}/members")
    op.wait_for_selector("#pxHd")
    op.click("button:has-text('撤销代理')")
    op.click(".dlg-ft button:has-text('确认撤销')")
    R.check("业主撤销原代理人（钱工）", R.toast(op, "已撤销代理人"))
    m, mp = R.ctx("member", 375)
    mp.goto(f"{WEB}/p/{PID}/checkpoints/{st['agentTarget']}")
    R.check("业主方成员在指定前无放行按钮（只读）", release_btn(mp) == 0)
    R.shot(mp, "F06-02-member-readonly-375")
    op.reload()
    op.wait_for_selector("#pxHd")
    op.click(".card-ft button:has-text('指定代理人')")
    op.select_option("#pxSel", label="钱工（业主方成员）")
    op.click(".dlg-ft button:has-text('下一步')")
    op.click(".dlg-ft button:has-text('确认')")
    R.check("业主指定钱工为代理人", R.toast(op, "钱工"))
    mp.reload()
    R.check("指定后代理人看到放行按钮", release_btn(mp) == 1)
    R.check("375 检查点详情无横向滚动", R.hs(mp, "PAGE-F06-02 检查点详情（代理人）"))
    mp.locator("button.btn.primary.block", has_text="放行").click()
    dlg = mp.locator(".dialog").inner_text()
    R.check("代理放行确认摘要标注代理", "代理" in dlg, dlg.replace("\n", " ")[:200])
    mp.locator(".dialog button", has_text="确认放行").click()
    R.check("代理人放行成功", R.toast(mp, "已放行"))
    mp.wait_for_timeout(600)
    R.check("放行记录标注「代理放行」", "代理放行" in mp.inner_text(".ck-detail"))
    R.shot(mp, "F06-02-agent-released-375")
    # 代理人仍不能签认基线、图纸、变更单
    mp.goto(f"{WEB}/p/{PID}/baselines")
    mp.wait_for_timeout(1500)
    R.check("代理人不能签认基线（无签认按钮）", mp.locator("button:has-text('签认')").count() == 0)
    mp.goto(f"{WEB}/p/{PID}/drawings")
    mp.wait_for_timeout(1500)
    R.check("代理人不能签认图纸", mp.locator("button.btn.primary:has-text('签认 V')").count() == 0)
    co2 = next(c["id"] for c in fetch(mp, f"/projects/{PID}/change-orders")["items"] if c["status"] == "待业主签认")
    mp.goto(f"{WEB}/p/{PID}/changes/{co2}")
    mp.wait_for_timeout(1500)
    R.check("代理人不能签认变更单", mp.locator("button:has-text('签认变更单')").count() == 0)
    # 改指定另一成员
    op.reload()
    op.wait_for_selector("#pxHd")
    op.click(".card-ft button:has-text('更换代理人')")
    op.select_option("#pxSel", label="陈女士（业主方成员）")
    op.click(".dlg-ft button:has-text('下一步')")
    op.click(".dlg-ft button:has-text('确认')")
    R.check("业主改指定陈女士", R.toast(op, "陈女士"))
    op.wait_for_timeout(500)
    tl = op.locator("#pxHd").locator("xpath=../..").inner_text()
    R.check("代理人变更留痕（时间线含钱工与陈女士）", "钱工" in tl and "陈女士" in tl, tl[:300])
    R.shot(op, "F01-02-agent-change-1440")
    mp.goto(f"{WEB}/p/{PID}/checkpoints/{st['agentTarget2']}")
    R.check("改指定后原代理人失去放行权", release_btn(mp) == 0)
    # 撤销代理
    op.click("button:has-text('撤销代理')")
    op.click(".dlg-ft button:has-text('确认撤销')")
    R.check("撤销代理成功", R.toast(op, "已撤销代理人"))
    c3, p3 = R.ctx("13800000010", 1440, password="Cn2026abc")
    p3.goto(f"{WEB}/p/{PID}/checkpoints/{st['agentTarget2']}")
    R.check("撤销后下一次请求即不能放行", release_btn(p3) == 0)
    c3.close()
    op.goto(f"{WEB}/p/{PID}/checkpoints/{st['agentTarget']}")
    op.wait_for_selector(".ck-detail")
    op.wait_for_timeout(500)
    R.check("既有代理放行记录不变", "代理放行" in op.inner_text(".ck-detail") and "钱工" in op.inner_text(".ck-detail"))
    m.close()
    o.close()


def f02_wife_sign():
    o, op = R.ctx("owner", 1440)
    before = [x for x in fetch(op, "/todos")["items"] if x["type"] == "待签基线"]
    o.close()
    ctx, page = R.ctx("owner2", 1440)
    page.goto(f"{WEB}/p/{PID}/baselines")
    page.wait_for_selector(".grp")
    it = page.locator(".it", has_text="二楼书房 B 强弱电布管穿线")
    it.locator(".exp").click()
    it.locator("text=签认此项").click()
    sm = page.locator(".dialog").inner_text()
    R.check("签认摘要署名刘太太", "刘太太" in sm, sm.replace("\n", " ")[:200])
    page.get_by_role("button", name="确认签认", exact=True).click()
    R.check("刘太太签认即时生效", R.toast(page, "已签认 1 项"))
    R.shot(page, "F05-02-wife-signed-1440")
    bl = fetch(page, f"/projects/{PID}/work-items/{SEED['pendingBaselineWi']}/baseline")
    R.check("基线状态已签认", bl.get("status") == "已签认", bl.get("status"))
    det = json.dumps(fetch(page, f"/projects/{PID}/work-items/{SEED['pendingBaselineWi']}/detail"), ensure_ascii=False)
    R.check("签认记录署名为刘太太", "刘太太" in det)
    ctx.close()
    o, op = R.ctx("owner", 1440)
    after = [x for x in fetch(op, "/todos")["items"] if x["type"] == "待签基线"]
    cnt = lambda xs: sum(int(m.group(1)) if (m := re.search(r"基线 (\d+) 项", x["title"])) else 1 for x in xs)
    R.check("刘先生的同项待办消失（待签基线项数减 1）", not any("书房 B" in x["title"] for x in after) and cnt(after) == cnt(before) - 1,
            ([x["title"] for x in before], [x["title"] for x in after]))
    o.close()


def f02_admin():
    ctx, page = R.ctx("admin", 1440)
    page.goto(f"{WEB}/p/{PID}/checkpoints/{st['agentTarget2']}")
    page.wait_for_selector(".ck-detail")
    page.wait_for_timeout(500)
    R.check("公司管理员无放行 / 核对按钮", page.locator(".ck-detail .btn.primary, #hForm").count() == 0)
    page.goto(f"{WEB}/p/{PID}/baselines")
    page.wait_for_timeout(1500)
    R.check("公司管理员无基线签认按钮", page.locator("button:has-text('签认')").count() == 0)
    cos = fetch(page, f"/projects/{PID}/change-orders")["items"]
    page.goto(f"{WEB}/p/{PID}/changes/" + str(next(c["id"] for c in cos if c["status"] == "待预算定价")))
    page.wait_for_timeout(1500)
    R.check("公司管理员无定价按钮", page.locator("button:has-text('提交定价')").count() == 0)
    page.goto(f"{WEB}/p/{PID}/members")
    page.wait_for_selector(".mrow")
    R.check("公司管理员成员与邀请管理仍可用", page.locator("text=编辑角色").count() > 0 and page.locator(".topbar .btn.primary").count() == 1)
    R.shot(page, "F01-02-admin-1440")
    ctx.close()


for name, fn in (("代理人", f02_agent), ("刘太太签认", f02_wife_sign), ("公司管理员", f02_admin)):
    R.step(name, fn)

# ———————————————————————————————— FLOW-14 ————————————————————————————————
R.flow = "FLOW-14"


def f14():
    ctx, page = R.ctx("qc", 1440)
    iid = SEED["closedIssues"]["CK-008"]
    page.goto(f"{WEB}/p/{PID}/issues?id={iid}")
    page.click("button:has-text('提交到经验库')")
    page.wait_for_selector(".dialog")
    dlg = page.locator(".dialog").inner_text()
    R.check("提交条目含工段、工序、问题类型、检查要点、对策", all(k in dlg for k in ("工段", "工序", "问题类型", "检查要点", "对策")), dlg[:300])
    R.check("提交条目不含业主姓名与地址", "刘先生" not in dlg and "刘太太" not in dlg and "君华新城 A 区" not in dlg)
    R.check("默认不带照片", page.locator(".dialog input[type=checkbox]:checked").count() == 0)
    R.shot(page, "F08-01-exp-submit-1440")
    page.click(".dialog button:has-text('提交待审核')")
    R.check("提交经验条目 toast", R.toast(page, "已提交经验库"))
    ctx.close()
    ctx, page = R.ctx("13800000008", 1440)
    page.goto(WEB + "/experience")
    page.click(".tabs .chip:has-text('待审核')")
    page.wait_for_selector(".entry button:has-text('审核')")
    entry = page.locator(".entry", has_text="打压")
    entry.locator("button:has-text('审核')").click()
    page.click(".radios label:has-text('历史观察')")
    page.click(".dlg-ft button:has-text('下一步')")
    sm = page.locator(".dialog").inner_text()
    R.check("审核确认摘要含审核人孙工", "孙工" in sm, sm[:200])
    page.click(".dlg-ft button:has-text('审核通过')")
    R.check("审核通过 toast", R.toast(page, "已审核"))
    page.click(".tabs .chip:has-text('经验条目')")
    page.wait_for_timeout(600)
    card = page.locator(".entry", has_text="打压").first
    txt = card.inner_text()
    R.check("审核后条目可见并记录审核人、时间、状态", "历史观察" in txt and "孙工 审核" in txt and re.search(r"\d{2}:\d{2}", txt), txt[:200])
    card.locator("button:has-text('修改')").click()
    page.fill("input[placeholder^='例如：三个工地']", "滨江壹号复核：保压 30 分钟压降限值写明")
    cm = page.locator(".dialog textarea").last
    cm.fill(cm.input_value() + "；打压记录同时拍压力表读数")
    page.click(".dlg-ft button:has-text('保存为新版本')")
    R.check("修改生成新版本 toast「已保存为 v2，旧版本保留可查」", R.toast(page, "旧版本保留可查"))
    page.wait_for_timeout(500)
    page.locator(".entry", has_text="打压").first.locator("button:has-text('版本历史')").click()
    page.wait_for_timeout(600)
    hist = page.locator(".dialog").inner_text()
    R.check("旧版本可查（版本历史含 V1 与新版本）", hist.count("V") >= 2 or len(page.locator(".vlist .vh").all()) >= 2, hist[:300])
    R.shot(page, "F09-01-history-1440")
    ctx.close()
    for w in (1440, 375):
        ctx, page = R.ctx("owner", w)
        page.goto(WEB + "/experience")
        page.wait_for_selector(".entry")
        R.check(f"{w} 审核后对公司其他项目成员可见（业主可见该条目）", page.locator(".entry", has_text="打压").count() == 1)
        R.check(f"{w} 经验库无横向滚动", R.hs(page, "PAGE-F09-01 经验库"))
        R.shot(page, f"F09-01-owner-{w}")
        ctx.close()
    ctx, page = R.ctx("pm", 1440)
    page.goto(f"{WEB}/p/{PID2}/work-items/{SEED['wi2']}")
    page.click("text=新建检查点")
    page.wait_for_selector(".expl li")
    tags = [t.strip() for t in page.locator(".expl li .tag").all_inner_texts()]
    R.check("另一项目新建水电检查点时列出水电已审核条目（3 条）", len(tags) == 3, tags)
    R.check("按已验证、历史观察、未验证经验排序", tags == ["已验证", "历史观察", "未验证经验"], tags)
    first_point = page.locator(".expl li p").first.inner_text()
    page.locator(".expl li button:has-text('加入要点')").first.click()
    R.check("一键加入检查要点", first_point in page.locator(".dialog textarea").first.input_value())
    R.shot(page, "F05-01-exp-suggest-1440")
    ctx.close()


R.step("经验库", f14)
R.finish()
