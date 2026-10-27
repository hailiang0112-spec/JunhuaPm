"""change 浏览器 E2E：FLOW-12（变更单）/ FLOW-13（问题闭环）。

前置：run.sh 已建库、seed_base、seed.py。业务操作都在真实页面完成；API 只用于读取断言所需事实。
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "_lib"))
from harness import WEB, Run  # noqa: E402

SEED = json.load(open(os.path.join(HERE, "seed.json")))
PID = SEED["pid"]
R = Run(HERE, expected_http=[r"/change-orders", r"/issues/\d+/(close|void|reopen|cause)"])
st = {}


def fetch(page, path):
    return page.evaluate("p => fetch('/api' + p).then(r => r.json())", path)


def todos(page, typ):
    return [x for x in fetch(page, "/todos")["items"] if x["type"] == typ]


def co_by_code(page, code):
    return next(c for c in fetch(page, f"/projects/{PID}/change-orders?pageSize=50")["items"] if c["code"] == code)


def fill_co(page, title, reason, content, picks, needs, built):
    # 表单无独立标题字段：标题取「变更内容」首行（后端 changes.py 取首行前 28 字）
    page.locator(".co-form [aria-label='原因类别'] label", has_text=reason).click()
    page.locator(".co-form textarea[aria-label='变更内容']").fill(f"{title}\n{content}")
    for kw in picks:
        page.fill("input[aria-label='搜索受影响工作项']", kw)
        page.wait_for_timeout(300)
        page.locator(".picker label", has_text=kw).first.locator("input").check()
    page.fill("input[aria-label='搜索受影响工作项']", "")
    page.locator("[aria-label='是否需要新版图纸'] label").filter(has_text=re.compile("^需要$" if needs else "^不需要$")).click()
    page.locator("[aria-label='现场是否已按此施工'] label", has_text="已施工" if built else "未施工").click()


# ———————————————————————————————— FLOW-12 ————————————————————————————————
R.flow = "FLOW-12"


def f12_create():
    ctx, page = R.ctx("pm", 1440)
    page.goto(f"{WEB}/p/{PID}/changes")
    page.wait_for_selector("text=发起变更单")
    page.click("text=发起变更单")
    page.wait_for_url("**/changes/new")
    page.click("button[type=submit] >> text=提交变更单")
    page.wait_for_selector("#co-missing")
    miss = page.inner_text("#co-missing")
    R.check("缺项一次列出（还缺 5 项）", "还缺 5 项" in miss, miss)
    R.shot(page, "F07-02-new-empty-1440")
    fill_co(page, "一楼厨房烟道预留位调整", "设计深化", "按厨房深化节点图将烟道包封位置西移 120mm，同步调整厨房东墙砌筑与排烟管预留孔洞。",
            SEED["kitchenNames"], True, False)
    page.click("button[type=submit] >> text=提交变更单")
    R.check("发起 BG-003 成功（待预算定价，已通知预算专员）", R.toast(page, "已生成变更单 BG-003，状态：待预算定价"))
    page.wait_for_timeout(800)
    co = co_by_code(page, "BG-003")
    st["bg3"] = co["id"]
    R.check("编号为项目内序号 BG-003、状态「待预算定价」", co["status"] == "待预算定价")
    ctx.close()
    ctx, page = R.ctx("budget", 1440)
    R.check("给预算专员生成待预算定价待办", any("BG-003" in x["title"] for x in todos(page, "待预算定价变更单")))
    page.goto(f"{WEB}/p/{PID}/changes/{st['bg3']}")
    page.wait_for_selector("text=提交定价")
    page.click("text=提交定价")
    R.check("定价必填校验（承担方）", page.locator("text=请选择费用承担方").count() == 1)
    page.fill("input[aria-label='费用增减（元）']", "1800")
    page.fill("input[aria-label='工期影响（天）']", "1")
    page.locator("[aria-label='费用承担方'] label", has_text="设计方").click()
    page.click("text=提交定价")
    R.check("定价成功", R.toast(page, "已提交定价，已通知业主签认"))
    page.wait_for_timeout(800)
    R.check("定价后「待业主签认」", page.locator(".hd-row .seal", has_text="待业主签认").count() == 1)
    R.shot(page, "F07-02-priced-1440")
    ctx.close()


def f12_sign():
    ctx, page = R.ctx("owner", 1440)
    R.check("给业主生成待签变更单待办", any("BG-003" in x["title"] for x in todos(page, "待签变更单")))
    page.goto(f"{WEB}/p/{PID}/changes/{st['bg3']}")
    page.wait_for_selector("h2#dTitle")
    det = page.inner_text("body")
    R.check("详情显示费用 +1,800、工期 1 天、承担方设计方", "1,800" in det and "设计方" in det)
    page.click("button.btn.primary:has-text('签认变更单')")
    page.wait_for_selector(".dialog")
    R.shot(page, "F07-02-sign-confirm-1440")
    page.locator(".dialog button", has_text="确认签认").click()
    R.check("业主签认成功", R.toast(page, "已签认，变更单 BG-003 生效"))
    page.wait_for_timeout(1000)
    R.check("签认后「已生效」", page.locator(".hd-row .seal", has_text="已生效").count() == 1)
    R.check("受影响工作项基线各追加一条修订（2 条）", page.locator("text=基线已追加修订").count() == 2, page.locator("text=基线已追加修订").count())
    for wid in SEED["kitchen"]:
        hist = fetch(page, f"/projects/{PID}/work-items/{wid}/detail")["history"]
        R.check(f"工作项 {wid} 修订历史引用 BG-003", any("BG-003" in h.get("text", "") for h in hist), [h.get("text", "")[:40] for h in hist][:4])
    R.shot(page, "F07-02-signed-1440")
    ctx.close()
    ctx, page = R.ctx("dm", 1440)
    R.check("给设计经理生成「按变更单出新版图纸」待办", any("BG-003" in x["title"] for x in todos(page, "待出新版图纸")))
    ctx.close()


def f12_reject_resubmit():
    ctx, page = R.ctx("owner", 1440)
    page.goto(f"{WEB}/p/{PID}/changes/{SEED['co2']}")
    page.wait_for_selector("h2#dTitle")
    page.click("button.btn.danger >> text=驳回")
    page.click("text=确认驳回")
    R.check("无理由驳回被拒「请填写驳回理由」", page.locator("text=请填写驳回理由").count() == 1)
    page.fill("#rjReason", "放线偏差属于施工方问题，重砌费用应由装修公司承担，不同意由业主承担。")
    page.click("text=确认驳回")
    R.check("驳回成功并通知项目经理", R.toast(page, "已驳回，已通知项目经理"))
    page.wait_for_timeout(800)
    R.check("状态「已驳回」且理由保存", page.locator(".hd-row .seal", has_text="已驳回").count() == 1 and "不同意由业主承担" in page.inner_text("body"))
    R.shot(page, "F07-02-rejected-1440")
    ctx.close()
    ctx, page = R.ctx("pm", 375)
    R.check("给项目经理生成被驳回变更单待办", any(SEED["co2Code"] in x["title"] for x in todos(page, "被驳回变更单")))
    page.goto(f"{WEB}/p/{PID}/changes/{SEED['co2']}")
    page.click("button:has-text('修改后重新提交')")
    page.wait_for_selector(f"text=编号不变 {SEED['co2Code']}")
    page.locator(".co-form textarea").first.fill("一楼餐厅东墙按签认图向内移 40mm 重砌，重砌费用由装修公司承担。")
    page.click("button[type=submit] >> text=重新提交变更单")
    page.wait_for_selector("text=确认重新提交")
    page.click("text=确认重新提交")
    R.check("重新提交成功（编号不变）", R.toast(page, f"已重新提交 {SEED['co2Code']}，状态：待预算定价"))
    page.wait_for_timeout(800)
    R.check("回到「待预算定价」", page.locator(".hd-row .seal", has_text="待预算定价").count() == 1)
    R.check("驳回记录保留（历史驳回 1 次）", page.locator("text=历史驳回 1 次").count() == 1)
    R.check("375 变更单详情无横向滚动", R.hs(page, "PAGE-F07-02 变更单详情"))
    R.shot(page, "F07-02-resubmitted-375")
    co = co_by_code(page, SEED["co2Code"])
    R.check("编号不变、状态待预算定价", co["id"] == SEED["co2"] and co["status"] == "待预算定价")
    ctx.close()


def f12_late():
    ctx, page = R.ctx("pm", 1440)
    page.goto(f"{WEB}/p/{PID}/changes/new")
    page.wait_for_selector(".co-form")
    fill_co(page, "夹层楼梯间增设检修门洞（600×1800mm）", "现场条件", "夹层楼梯间结构梁下需留检修通道，现场已预留 600×1800mm 检修门洞，补办变更单。",
            ["夹层设备间"], False, True)
    page.click("button[type=submit] >> text=提交变更单")
    R.check("后补变更单提交成功", R.toast(page, "已生成变更单 BG-004"))
    page.wait_for_timeout(800)
    R.check("第三张标记为「后补变更」", "后补变更" in page.inner_text("body"))
    page.goto(f"{WEB}/p/{PID}/changes")
    page.wait_for_selector(".co-filters")
    page.click(".co-filters .chip >> text=后补变更")
    page.wait_for_timeout(600)
    R.check("列表「后补变更」筛选含 BG-004", "BG-004" in page.inner_text("main") if page.locator("main").count() else "BG-004" in page.inner_text("body"))
    R.shot(page, "F07-01-late-1440")
    ctx.close()
    ctx, page = R.ctx("pm", 375)
    page.goto(f"{WEB}/p/{PID}/changes")
    page.wait_for_selector(".co-card")
    R.check("375 变更单列表无横向滚动", R.hs(page, "PAGE-F07-01 变更单列表"))
    R.shot(page, "F07-01-list-375")
    ctx.close()


for n, fn in (("发起与定价", f12_create), ("签认生效", f12_sign), ("驳回与重提", f12_reject_resubmit), ("后补变更", f12_late)):
    R.step(n, fn)

# ———————————————————————————————— FLOW-13 ————————————————————————————————
R.flow = "FLOW-13"


def study_issue(page):
    return next(i for i in fetch(page, f"/projects/{PID}/issues?status=all&pageSize=50")["items"]
                if i.get("checkpoint") and i["checkpoint"]["id"] == SEED["studyCp"])


def open_issue(page, iid):
    page.goto(f"{WEB}/p/{PID}/issues?id={iid}")
    page.wait_for_selector("#dwTitle")
    page.wait_for_timeout(500)


def f13_auto_and_cause():
    ctx, page = R.ctx("qc", 1440)
    iss = study_issue(page)
    st["iss"] = iss["id"]
    open_issue(page, iss["id"])
    dw = page.locator(".drawer").inner_text() if page.locator(".drawer").count() else page.inner_text("body")
    R.check("自动生成的问题带检查点、工作项、楼层房间", SEED["studyCode"] in dw and "二楼书房 B 隔墙砌筑" in dw and "二楼" in dw and "书房 B" in dw, dw[:300])
    R.check("带照片（2 张）", page.locator(".drawer img, .dw-bd img").count() >= 2, page.locator(".drawer img, .dw-bd img").count())
    R.check("带发现时点「覆盖前」、状态「未闭环」", "覆盖前" in dw and "未闭环" in dw)
    sug = {}
    for cause, expect in (("设计已改但未签变更单", "补签变更单"), ("施工偏离签认图", "返工后复核"), ("图纸本身未表达清楚", "设计经理出新版或书面澄清")):
        page.locator("label.cause", has_text=cause).click()
        R.toast(page, "已保存原因")
        page.wait_for_timeout(600)
        sug[cause] = page.locator(".sugg").inner_text()
        R.check(f"原因「{cause}」显示「{expect}…」", expect in sug[cause], sug[cause])
    R.check("「补签变更单」提示可一键生成变更单草稿", "一键生成变更单草稿" in sug["设计已改但未签变更单"], sug["设计已改但未签变更单"])
    R.shot(page, "F08-01-drawer-1440")
    page.locator("label.cause", has_text="施工偏离签认图").click()
    page.wait_for_timeout(800)
    ctx.close()


def f13_manual_and_overdue():
    ctx, page = R.ctx("pm", 1440)
    page.goto(f"{WEB}/p/{PID}/issues")
    page.wait_for_selector("text=问题台账")
    page.click("text=登记问题")
    dlg = page.locator(".dialog")
    dlg.locator("textarea[aria-label='问题描述']").fill("一楼厨房东墙阳角不顺直，偏差 6mm")
    dlg.locator("[aria-label='等级'] label", has_text="一般").click()
    dlg.locator("select[aria-label='所属工段']").select_option(label="砌墙")
    dlg.locator("input[aria-label='要求闭环日期']").fill("2026-11-05")
    dlg.locator("select[aria-label='楼层']").select_option(label="一楼")
    page.wait_for_timeout(200)
    dlg.locator("select[aria-label='房间']").select_option(label="厨房")
    page.locator(".dlg-ft >> text=提交").click()
    R.check("手工登记问题成功（状态未闭环）", R.toast(page, "状态：未闭环"), page.locator(".toast").all_inner_texts())
    page.wait_for_timeout(800)
    man = next(i for i in fetch(page, f"/projects/{PID}/issues?status=all&pageSize=50")["items"] if i["description"].startswith("一楼厨房东墙阳角不顺直"))
    R.check("未填对策记「待补充对策」、负责人记「待指派」", man["countermeasure"] == "待补充对策" and man["ownerName"] == "待指派", (man["countermeasure"], man["ownerName"]))
    rows = page.locator("tbody tr").all_inner_texts()
    o7 = next((r for r in rows if "管道井封堵不严" in r), "")
    R.check("要求闭环 2026-10-20 的未闭环问题显示超期 7 天", re.search(r"\b7\b", o7) is not None, o7)
    order = [r for r in rows if "管道井封堵不严" in r or "塞缝不密实" in r]
    R.check("按超期降序（7 天在 3 天之前）", len(order) == 2 and "管道井封堵不严" in order[0], order)
    R.check("排序说明「按超期天数从大到小排序」", page.locator("text=按超期天数从大到小排序").count() == 1)
    R.shot(page, "F08-01-list-1440")
    page.goto(f"{WEB}/p/{PID}")
    page.wait_for_selector("text=问题遗留清单")
    leg = page.locator("section", has_text="问题遗留清单").last.inner_text()
    i7, i3 = leg.find("管道井封堵不严"), leg.find("塞缝不密实")
    R.check("遗留清单按超期降序（7 天排在 3 天前）", 0 <= i7 < i3, leg[:300])
    ctx.close()
    ctx, page = R.ctx("qc", 375)
    page.goto(f"{WEB}/p/{PID}/issues")
    page.wait_for_selector(".is-card")
    R.check("375 问题台账无横向滚动", R.hs(page, "PAGE-F08-01 问题台账"))
    R.shot(page, "F08-01-list-375")
    ctx.close()


def f13_close_reopen():
    ctx, page = R.ctx("pm", 1440)
    open_issue(page, st["iss"])
    page.click(".dw-ft >> text=标记已闭环")
    page.click("text=确认闭环")
    page.wait_for_selector(".dw-bd .note.bad")
    R.check("检查点仍为不一致时闭环被拒", "请先由质检复核为一致或已变更" in page.inner_text(".dw-bd .note.bad"))
    R.shot(page, "F08-01-close-blocked-1440")
    ctx.close()
    ctx, page = R.ctx("qc", 375)
    page.goto(f"{WEB}/p/{PID}/checkpoints/{SEED['studyCp']}")
    page.wait_for_selector(".ck-detail")
    from PIL import Image
    import io
    b = io.BytesIO()
    Image.new("RGB", (1280, 960), (150, 160, 150)).save(b, "JPEG")
    page.locator("input[type=file][capture=environment]").set_input_files(files=[{"name": "书房B门洞返工后.jpg", "mimeType": "image/jpeg", "buffer": b.getvalue()}])
    page.wait_for_function("document.querySelectorAll('.pst.ok').length === 1", timeout=15000)
    page.locator(".seg label span", has_text=re.compile("^一致$")).click()
    page.locator(".seg label span", has_text=re.compile("^未覆盖$")).click()
    page.locator("button", has_text="提交核对记录").click()
    page.locator(".dialog button", has_text="确认提交").click()
    R.check("质检复核为一致", R.toast(page, "已保存"))
    ctx.close()
    ctx, page = R.ctx("pm", 1440)
    open_issue(page, st["iss"])
    page.click(".dw-ft >> text=标记已闭环")
    page.click("text=确认闭环")
    R.check("复核后闭环成功", R.toast(page, "闭环"), page.locator(".toast").all_inner_texts())
    page.wait_for_timeout(800)
    x = next(i for i in fetch(page, f"/projects/{PID}/issues?status=all&pageSize=50")["items"] if i["id"] == st["iss"])
    R.check("闭环记当日 2026-10-27", x["status"] == "已闭环" and x.get("closedOn") == "2026-10-27", (x["status"], x.get("closedOn")))
    open_issue(page, st["iss"])
    page.click(".dw-ft >> text=重新打开")
    if page.locator(".dialog button", has_text="确认").count():
        page.locator(".dialog button", has_text="确认").last.click()
    R.check("重新打开成功", R.toast(page, "打开"), page.locator(".toast").all_inner_texts())
    page.wait_for_timeout(800)
    x = next(i for i in fetch(page, f"/projects/{PID}/issues?status=all&pageSize=50")["items"] if i["id"] == st["iss"])
    R.check("重开恢复「处理中」", x["status"] == "处理中", x["status"])
    open_issue(page, st["iss"])
    dw = page.locator(".drawer").inner_text() if page.locator(".drawer").count() else page.inner_text("body")
    R.check("闭环与重开留痕", "闭环" in dw and "重新打开" in dw, dw[-300:])
    R.shot(page, "F08-01-reopened-1440")
    ctx.close()


def f13_void():
    ctx, page = R.ctx("owner", 1440)
    before = fetch(page, f"/projects/{PID}/overview")["kpi"]["issues"]
    open_issue(page, SEED["dup"])
    page.click(".dw-ft >> text=作废")
    page.click("text=确认作废")
    R.check("删除改为填理由作废（无理由被拒）", page.locator("text=请填写作废理由").count() >= 1)
    page.fill("textarea[aria-label='作废理由']", "与夹层设备间砌体垂直度偏差问题重复登记")
    page.click("text=确认作废")
    R.check("作废成功", R.toast(page, "作废"), page.locator(".toast").all_inner_texts())
    page.wait_for_timeout(800)
    after = fetch(page, f"/projects/{PID}/overview")["kpi"]["issues"]
    R.check("作废问题不计入统计", after == before - 1, (before, after))
    page.goto(f"{WEB}/p/{PID}/issues")
    page.wait_for_selector("tbody tr")
    R.check("默认列表不含作废问题", SEED["dupCode"] not in page.inner_text("tbody"))
    page.locator(".chip-row .chip", has_text="已作废").click()
    page.wait_for_timeout(600)
    R.check("筛选「已作废」可见", SEED["dupCode"] in page.inner_text("tbody") and "重复登记" in page.inner_text("body"))
    R.shot(page, "F08-01-voided-1440")
    ctx.close()


for n, fn in (("自动生成与原因", f13_auto_and_cause), ("手工登记与超期", f13_manual_and_overdue), ("闭环与重开", f13_close_reopen), ("作废", f13_void)):
    R.step(n, fn)
R.finish()
