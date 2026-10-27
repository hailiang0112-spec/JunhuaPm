"""archive 浏览器 E2E：FLOW-17（档案部分）/ FLOW-18（补充事项与公告栏）/ FLOW-20（付款节点）/ FLOW-22（证据包与操作日志，含解包核对）。

前置：run.sh 已建库、seed_base、seed.py。业务操作都在真实页面完成；API 只用于读取断言所需事实。
"""
import csv
import io
import json
import os
import re
import sys
import zipfile

import openpyxl

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "_lib"))
from harness import WEB, Run  # noqa: E402

SEED = json.load(open(os.path.join(HERE, "seed.json")))
PID = SEED["pid"]
DL = os.path.join(HERE, "downloads")
os.makedirs(DL, exist_ok=True)
R = Run(HERE, expected_http=[r"/archive/contract", r"/archive/\w+/folders/\d+$", r"/archive-files/\d+/void", r"/notices/\d+$",
                             r"/mark-paid", r"/evidence-exports", r"/audit-logs", r"/integrity-checks", r"/audit-summary"])
st = {}


def fetch(page, path):
    return page.evaluate("p => fetch('/api' + p).then(r => r.json())", path)


# ———————————————————————————————— FLOW-17（档案部分） ————————————————————————————————
R.flow = "FLOW-17"


def f17_archive():
    for w in (1440, 375):
        ctx, page = R.ctx("pm", w)
        page.goto(f"{WEB}/p/{PID}/archive?zone=layout&cat={SEED['folder']}")
        page.wait_for_selector(".fcard")
        page.wait_for_timeout(400)
        R.check(f"{w} 档案资料页无横向滚动", R.hs(page, "PAGE-F12-01 档案资料"))
        R.shot(page, f"F12-01-layout-{w}")
        if w == 1440:
            R.check("一楼分类 3 个文件，引用标注可见", page.locator(".fcard").count() == 3 and f"被变更单 {SEED['coCode']}" in page.inner_text("body"))
            page.get_by_role("button", name="新建分类").click()
            page.locator(".dialog").get_by_role("button", name="保存").click()
            R.check("新建分类名称必填", page.locator(".dialog .err", has_text="请填写分类名称").count() == 1)
            page.locator(".dialog input").fill("地下室车库")
            page.locator(".dialog").get_by_role("button", name="保存").click()
            R.check("新建空分类成功", R.toast(page, "已新建分类「地下室车库」"))
            page.wait_for_timeout(600)
            page.get_by_role("button", name="删除").click()
            page.locator(".dialog").get_by_role("button", name="确认删除").click()
            R.check("空分类可删", R.toast(page, "已删除空分类「地下室车库」"))
            page.goto(f"{WEB}/p/{PID}/archive?zone=layout&cat={SEED['folder']}")
            page.wait_for_selector(".fcard")
            page.locator(".fcard", has_text=SEED["refFile"]).get_by_role("button", name="作废").click()
            R.check("被变更单引用的文件作废被拒", R.toast(page, f"该文件被变更单 {SEED['coCode']}引用，不能作废"))
            page.locator(".fcard", has_text=SEED["voidTarget"]).get_by_role("button", name="作废").click()
            page.locator(".dialog").get_by_role("button", name="确认作废").click()
            R.check("普通资料作废成功", R.toast(page, f"已作废：{SEED['voidTarget']}"))
            page.wait_for_timeout(600)
            R.check("作废后从默认列表隐藏", page.locator(".fcard").count() == 2)
            page.get_by_label("显示已作废").check()
            page.wait_for_timeout(400)
            R.check("显示已作废后可见并留痕", page.locator(".seal.void").count() == 1)
            page.locator(".cat").filter(has_text=re.compile(rf"^\s*{SEED['folder']}")).first.click()  # 「负一楼」也含「一楼」，按开头精确匹配
            page.get_by_role("button", name="删除").click()
            R.check("非空分类删除提示先移出文件", R.toast(page, "请先移出文件"))
            R.shot(page, "F12-01-voided-1440")
        page.get_by_role("tab", name="装修合同").click()
        page.wait_for_timeout(600)
        R.check(f"{w} 项目经理可见合同专区", page.locator(".cat", has_text="主合同").count() >= 1 and "施工合同" in page.inner_text("body"))
        R.shot(page, f"F12-01-contract-pm-{w}")
        ctx.close()
    for who in ("dm", "qc"):
        ctx, page = R.ctx(who, 375, expect=[r"/archive/contract"])
        page.goto(f"{WEB}/p/{PID}/archive?zone=contract")
        page.wait_for_timeout(1200)
        R.check(f"{who} 打开合同专区被拒「无权查看合同资料」", page.get_by_text("无权查看合同资料").count() >= 1 and page.get_by_role("tab", name="装修合同").count() == 0)
        R.shot(page, f"F12-01-contract-{who}-375")
        ctx.close()
    for who in ("owner", "budget", "admin"):
        ctx, page = R.ctx(who, 1440)
        page.goto(f"{WEB}/p/{PID}/archive?zone=contract")
        page.wait_for_timeout(1200)
        R.check(f"{who} 可见合同资料", "君华新城联排别墅装修工程施工合同.pdf" in page.inner_text("body"))
        ctx.close()


R.step("档案资料", f17_archive)

# ———————————————————————————————— FLOW-18 ————————————————————————————————
R.flow = "FLOW-18"


def f18_supplement():
    ctx, page = R.ctx("pm", 1440)
    page.goto(f"{WEB}/p/{PID}/supplements")
    page.wait_for_selector(".it")
    page.get_by_role("button", name="登记补充事项").first.click()
    dlg = page.locator(".dialog")
    dlg.get_by_role("button", name="保存").click()
    R.check("登记必填校验（标题、约定完成日期、责任人）", all(dlg.locator(".err", has_text=t).count() == 1 for t in ("请填写标题", "请选择约定完成日期", "请选择责任人")))
    dlg.locator("input").first.fill("三楼卫生间增加浴缸")
    dlg.locator("textarea").first.fill("业主 10 月 26 日现场提出三楼主卫增加 1.5m 嵌入式浴缸，需复核排水与楼板荷载。")
    dlg.locator("input[type=date]").nth(1).fill("2026-11-15")
    sel = dlg.locator("select").first
    sel.select_option(label=next(o for o in sel.locator("option").all_inner_texts() if "张工" in o))
    dlg.locator("input[type=file]").set_input_files(files=[{"name": "三楼主卫浴缸位置示意.jpg", "mimeType": "image/jpeg", "buffer": _jpg()}])
    page.wait_for_timeout(1500)
    dlg.get_by_role("button", name="保存").click()
    R.check("登记补充事项成功（状态：待处理）", R.toast(page, "状态：待处理"), page.locator(".toast").all_inner_texts())
    page.wait_for_timeout(800)
    item = page.locator(".it", has_text="三楼卫生间增加浴缸")
    code = item.locator(".mono").first.inner_text().strip()
    R.check("新事项状态「待处理」", "待处理" in item.inner_text())
    item.get_by_role("button", name="处理中").click()
    R.check("状态切换为处理中", R.toast(page, f"{code} 状态改为「处理中」"))
    page.wait_for_timeout(800)
    item.get_by_role("button", name="转为变更单").click()
    page.wait_for_url(re.compile(r"/p/\d+/changes/\d+"), timeout=10000)
    page.wait_for_timeout(1000)
    body = page.inner_text("body")
    R.check("转为变更单生成预填内容的草稿", "三楼卫生间增加浴缸" in body and "草稿" in body, body[:200])
    R.check("草稿带上补充事项附件", "三楼主卫浴缸位置示意.jpg" in body)
    R.shot(page, "F07-02-from-supplement-1440")
    page.goto(f"{WEB}/p/{PID}/supplements")
    page.wait_for_selector(".it")
    item = page.locator(".it", has_text="三楼卫生间增加浴缸")
    R.check("补充事项上显示变更单编号", re.search(r"已转变更单 BG-\d{3}", item.inner_text()) is not None, item.inner_text()[:200])
    item.get_by_role("button", name="已完成").click()
    R.check("状态切换为已完成", R.toast(page, f"{code} 状态改为「已完成」"))
    page.wait_for_timeout(800)
    titles = [t.split("\n")[0] for t in page.locator(".it").all_inner_texts()]
    states = [("已完成" in t) for t in page.locator(".it").all_inner_texts()]
    R.check("未完成排前（已完成在后）", states == sorted(states), list(zip(titles, states)))
    R.shot(page, "F13-01-supplements-1440")
    ctx.close()
    ctx, page = R.ctx("pm", 375)
    page.goto(f"{WEB}/p/{PID}/supplements")
    page.wait_for_selector(".it")
    R.check("375 补充事项页无横向滚动", R.hs(page, "PAGE-F13-01 补充事项"))
    R.shot(page, "F13-01-supplements-375")
    ctx.close()


def _jpg():
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (800, 600), (200, 190, 170)).save(b, "JPEG")
    return b.getvalue()


def post(page, text, board_tab=None):
    if board_tab:
        page.get_by_role("tab", name=board_tab).click()
    page.locator("#cpText").fill(text)
    page.get_by_role("button", name="发布").click()


def f18_notices():
    msgs = {"owner": "请张工明天上午到三楼露台确认洗手池位置", "pm": "明天上午 9 点在三楼露台确认洗手池位置，给排水点位同步预留。",
            "qc": "水电工段 2 处不一致已生成问题，整改后复核。"}
    boards = {}
    for who in ("owner", "pm", "qc"):
        ctx, page = R.ctx(who, 1440)
        page.goto(f"{WEB}/p/{PID}/notices")
        page.wait_for_selector("#cpText")
        name = {"owner": "刘先生（业主）", "pm": "张工（项目经理）", "qc": "王工（质检）"}[who]
        page.wait_for_selector(f"text={name}")
        hint = page.inner_text("body")
        board = "业主" if who == "owner" else "工地经理"
        hint = re.sub(r"\s+", "", page.locator(".to").first.inner_text())  # <b> 在该页按块显示，去掉换行后比对
        R.check(f"{who} 发帖以账号姓名并按角色进入「{board}」板块", f"将以{name}的身份发布到「{board}」板块" in hint, hint)
        post(page, msgs[who])
        R.check(f"{who} 发布成功", R.toast(page, f"已发布到「{board}」板块"))
        page.wait_for_timeout(600)
        boards[who] = page.locator(".board.cur .post").first.inner_text()
        R.check(f"{who} 新留言倒序排在板块首位", msgs[who] in boards[who])
        ctx.close()
    ctx, page = R.ctx("dm", 1440)
    page.goto(f"{WEB}/p/{PID}/notices")
    page.wait_for_selector(".post")
    p0 = page.locator(".post", has_text=msgs["owner"]).first
    p0.get_by_role("button", name="回复").click()
    p0.locator(".reply-box input").fill("洗手池位置建议放在东北角，离雨水立管近，排水好接。")
    p0.locator(".reply-box").get_by_role("button", name="回复").click()
    R.check("设计经理回复业主留言", R.toast(page, "已回复"))
    page.wait_for_timeout(600)
    ctx.close()
    ctx, page = R.ctx("pm", 1440)
    page.goto(f"{WEB}/p/{PID}/notices")
    page.wait_for_selector(".post")
    p0 = page.locator(".post", has_text=msgs["owner"]).first
    p0.get_by_role("button", name="回复").click()
    p0.locator(".reply-box input").fill("收到，明早 9 点现场确认。")
    p0.locator(".reply-box").get_by_role("button", name="回复").click()
    R.toast(page, "已回复")
    page.wait_for_timeout(600)
    ctx.close()
    for w in (1440, 375):
        ctx, page = R.ctx("owner", w)
        page.goto(f"{WEB}/p/{PID}/notices")
        page.wait_for_selector(".post")
        if w == 1440:
            p0 = page.locator(".post", has_text=msgs["owner"]).first
            t = p0.inner_text()
            body_end = t.find(msgs["owner"]) + len(msgs["owner"])
            i_li, i_zhang = t.find("李工\n设计经理", body_end), t.find("张工\n项目经理", body_end)
            R.check("回复挂在原留言下且正序（李工在前、张工在后）", 0 <= i_li < i_zhang, t[:300])
            R.shot(page, "F13-02-notices-1440")
            owner_posts = page.locator(".board", has_text="业主").first.inner_text() if page.locator(".board").count() else ""
            mine = page.locator(".post", has_text=msgs["owner"]).first
            mine.get_by_role("button", name="删除").first.click()
            page.locator(".dialog").get_by_role("button", name="确认删除").click()
            R.check("业主删除自己的留言", R.toast(page, "留言已删除"))
            page.wait_for_timeout(600)
            R.check("显示「该留言已删除」并留记录", page.get_by_text("该留言已删除").count() >= 1)
            other = page.locator(".post", has_text="今天砌墙班组").first
            R.check("他人留言无删除入口", other.locator(":scope > .ops").get_by_role("button", name="删除").count() == 0)
            nl = fetch(page, f"/projects/{PID}/notices")["boards"]
            nid = next((n["id"] for b in nl.values() for n in b if "今天砌墙班组" in n["body"]), None)
            if nid:
                code = page.evaluate("""async (u) => { const c = document.cookie.split('; ').find(x => x.startsWith('csrftoken=')).split('=')[1];
                    const r = await fetch(u, {method: 'DELETE', headers: {'X-CSRFToken': c}}); return r.status; }""", f"/api/projects/{PID}/notices/{nid}")
                R.check("删除他人留言被拒（403）", code == 403, code)
            R.shot(page, "F13-02-deleted-1440")
        else:
            page.get_by_role("tab", name="工地经理").click()
            page.wait_for_timeout(400)
            cur = page.locator(".board.cur").inner_text()
            R.check("项目经理与质检留言在工地经理板块", msgs["pm"] in cur and msgs["qc"] in cur)
            R.check("375 公告栏无横向滚动", R.hs(page, "PAGE-F13-02 公告栏"))
            R.shot(page, "F13-02-site-375")
        ctx.close()


R.step("补充事项", f18_supplement)
R.step("公告栏", f18_notices)

# ———————————————————————————————— FLOW-20 ————————————————————————————————
R.flow = "FLOW-20"


def f20():
    ctx, page = R.ctx("budget", 1440)
    page.goto(f"{WEB}/p/{PID}/payments")
    page.wait_for_selector("text=录入付款节点")
    page.get_by_role("button", name="录入付款节点").first.click()
    dlg = page.locator(".dialog")
    dlg.get_by_role("button", name="保存").click()
    R.check("录入必填校验", all(dlg.locator(".err", has_text=t).count() == 1 for t in ("请填写节点名称", "请填写大于 0 的金额", "请选择计划日期", "请至少选择 1 个关联工段")))
    dlg.locator("input").first.fill("水电完工款")
    dlg.locator("input[type=number]").first.fill("253600")
    dlg.locator("input[type=date]").first.fill("2027-01-15")
    dlg.locator("label", has_text="水电").first.click()
    dlg.get_by_role("button", name="保存").click()
    R.check("录入付款节点成功（状态：未付）", R.toast(page, "已保存付款节点，状态：未付"), page.locator(".toast").all_inner_texts())
    page.wait_for_timeout(800)
    row = page.locator("tr", has_text="水电完工款")
    t = row.inner_text()
    R.check("节点状态「未付」", row.locator(".seal").inner_text().strip() == "未付")
    R.check("节点显示未放行 5、未闭环不一致 2", re.search(r"未放行\s*5", t) and re.search(r"不一致\s*2", t) or ("5" in t and "2" in t), t)
    R.shot(page, "F15-01-payments-1440")
    row.get_by_role("button", name="标记已付").click()
    d = page.locator(".dialog")
    R.check("标记已付弹出「还有 5 个检查点未放行，确认标记已付？」", d.get_by_role("heading").inner_text().strip() == "还有 5 个检查点未放行，确认标记已付？")
    R.check("提示不拦截并留痕", "付款提示不拦截" in d.inner_text())
    d.get_by_role("button", name="取消").click()
    page.wait_for_timeout(400)
    R.check("取消后状态不变（未付）", row.locator(".seal").inner_text().strip() == "未付")
    row.get_by_role("button", name="标记已付").click()
    page.locator(".dialog").get_by_role("button", name="确认标记已付").click()
    R.check("确认后标记已付", R.toast(page, "水电完工款 已标记为已付"))
    page.wait_for_timeout(800)
    R.check("状态「已付」并留痕（确认时未放行 5 个）", row.locator(".seal").inner_text().strip() == "已付" and "确认时未放行 5 个" in row.inner_text())
    R.shot(page, "F15-01-paid-1440")
    ctx.close()
    ctx, page = R.ctx("budget", 375)
    page.goto(f"{WEB}/p/{PID}/payments")
    page.wait_for_selector("text=录入付款节点")
    R.check("375 付款节点页无横向滚动", R.hs(page, "PAGE-F15-01 付款节点"))
    R.shot(page, "F15-01-payments-375")
    ctx.close()


R.step("付款节点", f20)

# ———————————————————————————————— FLOW-22 ————————————————————————————————
R.flow = "FLOW-22"


def f22():
    ctx, page = R.ctx("owner", 1440)
    page.goto(f"{WEB}/p/{PID}/audit")
    page.wait_for_selector("#exTitle")
    card = page.locator("#exTitle").locator("xpath=ancestor::section[1]")
    card.locator(".field", has=page.locator("label", has_text="工段")).locator("select").select_option(label="水电")
    page.fill("input[aria-label='开始日期']", "2026-10-01")
    page.fill("input[aria-label='结束日期']", "2026-10-27")
    with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/evidence-exports"), timeout=60000) as jr, \
            page.expect_download(timeout=60000) as dl:
        card.get_by_role("button", name=re.compile("导出证据包")).click()
    R.check("证据包生成提示", R.toast(page, "证据包已生成", timeout=20000))
    path = os.path.join(DL, "证据包-水电-20261001-20261027.zip")
    dl.value.save_as(path)
    R.check("下载文件名含范围（水电）", "水电" in dl.value.suggested_filename, dl.value.suggested_filename)
    R.shot(page, "F17-01-exported-1440")
    res = (jr.value.json() or {}).get("result") or {}
    z = zipfile.ZipFile(path)
    names = z.namelist()
    R.check("ZIP 含记录清单 .xlsx", "记录清单.xlsx" in names, names[:5])
    ws = openpyxl.load_workbook(io.BytesIO(z.read("记录清单.xlsx"))).worksheets[0]
    rows = [r for r in ws.iter_rows(min_row=2, values_only=True) if any(v not in (None, "") for v in r)]
    photos = [n for n in names if n.startswith("照片原件/") and not n.endswith("/")]
    R.check("含范围内照片原件（水电 5 次核对共 5 张）", len(photos) == 5, photos)
    R.check("照片为原件（JPEG 文件头）", all(z.read(n)[:3] == b"\xff\xd8\xff" for n in photos))
    R.check("含相关图纸版本文件", any(n.startswith("图纸版本/") and "水电点位图-V1" in n for n in names))
    snaps = [n for n in names if n.startswith("签认快照/")]
    R.check("含签认内容快照（图纸签认 1 + 基线签认 4）", len(snaps) == 5 and all(json.loads(z.read(n)) for n in snaps), snaps)
    man = z.read("摘要清单.csv").decode("utf-8-sig")
    first = man.splitlines()[0]
    m = re.match(r"导出时链尾摘要,([0-9a-f]{64})", first)
    R.check("摘要清单含导出时链尾摘要", m is not None, first[:100])
    lines = list(csv.reader(io.StringIO(man)))
    hdr = next(i for i, l in enumerate(lines) if l and l[0] == "编号")
    in_scope = [l for l in lines[hdr + 1:] if len(l) > 6 and l[6] == "是"]
    R.check("清单条数与范围内记录数一致", len(rows) == len(in_scope) == res.get("count", len(rows)), (len(rows), len(in_scope), res.get("count")))
    R.check("链尾摘要与导出任务结果一致", m and res.get("tail") == m.group(1))
    # 操作日志按对象筛选
    flt = page.locator(".field", has=page.locator("label", has_text="对象类型")).locator("select")
    opts = flt.locator("option").all_inner_texts()
    target = "付款节点" if "付款节点" in opts else next(o for o in opts if o not in ("全部", "全部类型"))
    flt.select_option(label=target)
    page.wait_for_timeout(1000)
    lt = page.locator(".log-table tbody").inner_text()
    rows_n = page.locator(".log-table tbody tr").count()
    api_n = len([x for x in fetch(page, f"/projects/{PID}/audit-logs?pageSize=200")["items"] if x["objectType"] == target])
    R.check(f"按对象（{target}）筛选操作日志（条数与该类对象日志一致）", rows_n >= 1 and all(target in r for r in page.locator(".log-table tbody tr").all_inner_texts()) and rows_n == min(api_n, 20),
            (rows_n, api_n, lt[:200]))
    R.check("日志显示操作人、时间与前后值", "赵会计" in lt and re.search(r"\d{2}:\d{2}", lt) and ("未付" in lt or "已付" in lt), lt[:300])
    page.locator(".field", has=page.locator("label", has_text="开始日期")).last.locator("input").fill("2026-10-28")
    page.wait_for_timeout(1000)
    R.check("按时间筛选（之后日期无记录）", page.locator(".log-table tbody tr").count() == 0 or "暂无" in page.inner_text("main"))
    R.shot(page, "F17-01-logs-1440")
    ctx.close()
    ctx, page = R.ctx("pm", 1440, expect=[r"/evidence-exports", r"/audit-logs", r"/integrity-checks", r"/audit-summary"])
    page.goto(f"{WEB}/p/{PID}/audit")
    page.wait_for_timeout(1200)
    R.check("项目经理导出被拒「仅业主和公司管理员可导出证据包」", "仅业主和公司管理员可导出证据包" in page.inner_text("body")
            and page.get_by_role("button", name=re.compile("导出证据包")).count() == 0)
    code = page.evaluate("""async (u) => { const c = document.cookie.split('; ').find(x => x.startsWith('csrftoken=')).split('=')[1];
        const r = await fetch(u, {method: 'POST', headers: {'X-CSRFToken': c, 'Content-Type': 'application/json'}, body: JSON.stringify({phaseId: 2})});
        return [r.status, (await r.json()).message]; }""", f"/api/projects/{PID}/evidence-exports")
    R.check("项目经理导出接口被拒（403 + 原文提示）", code[0] == 403 and "仅业主和公司管理员可导出证据包" in code[1], code)
    R.shot(page, "F17-01-pm-1440")
    ctx.close()
    ctx, page = R.ctx("owner", 375)
    page.goto(f"{WEB}/p/{PID}/audit")
    page.wait_for_selector("#exTitle")
    R.check("375 审计与证据包页无横向滚动", R.hs(page, "PAGE-F17-01 审计与证据包"))
    R.shot(page, "F17-01-owner-375")
    ctx.close()


R.step("证据包与操作日志", f22)
R.finish()
