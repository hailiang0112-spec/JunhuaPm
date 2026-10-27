"""check 浏览器 E2E：FLOW-09（手机 375 为主）/ FLOW-10 / FLOW-11（含时间推进）。

由原 scratchpad/check/e2e.js 移植到统一的 Python 记分器，并补齐契约中的放行重复、发现时点三种取值、时限设置等项。
前置：run.sh 已建库、seed_base、seed.py、advance_time.py。
"""
import io
import json
import os
import re
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "_lib"))
from harness import WEB, Run  # noqa: E402

SEED = json.load(open(os.path.join(HERE, "seed.json")))
PID, CPS = SEED["pid"], SEED["cps"]
R = Run(HERE, expected_http=[r"/checks$", r"/release$", r"/cover$", r"/settings$", r"/discovery-corrections", r"/work-items/\d+/checkpoints"])
st = {}


def fetch(page, path):
    return page.evaluate("p => fetch('/api' + p).then(r => r.json())", path)


def jpg(color):
    b = io.BytesIO()
    Image.new("RGB", (1280, 960), color).save(b, "JPEG", quality=85)
    return b.getvalue()


def open_cp(page, cid):
    page.goto(f"{WEB}/p/{PID}/checkpoints/{cid}")
    page.wait_for_selector(".ck-detail")
    page.wait_for_timeout(600)


def submit_check(page, conclusion, cover="未覆盖", n=1, tag="", confirm=True):
    cam = page.locator("input[type=file][capture=environment]")
    cam.set_input_files(files=[{"name": f"现场照片{tag}-{i + 1}.jpg", "mimeType": "image/jpeg", "buffer": jpg((150 + 20 * i, 140, 120))} for i in range(n)])
    page.wait_for_function(f"document.querySelectorAll('.pst.ok').length === {n}", timeout=20000)
    page.locator(".seg label span", has_text=re.compile(f"^{conclusion}$")).click()
    page.locator(".seg label span", has_text=re.compile(f"^{cover}$")).click()
    page.locator("button", has_text="提交核对记录").click()
    if confirm:
        page.wait_for_selector(".dialog")
        page.locator(".dialog button", has_text="确认提交").click()


# ———————————————————————————————— FLOW-09 ————————————————————————————————
R.flow = "FLOW-09"


def f09_create():
    ctx, page = R.ctx("qc", 1440)
    page.goto(f"{WEB}/p/{PID}/work-items/{CPS['plumb']['wid']}")
    page.wait_for_selector("#hBase")
    page.click("text=新建检查点")
    page.wait_for_selector(".pickmap img")
    page.wait_for_function("document.querySelector('.pickmap img').complete")
    page.fill(".dialog textarea", "隔墙与原结构墙拉结钢筋 2Φ6@500，伸入墙内 ≥700mm（隐蔽）")
    page.check("text=是（未放行不得覆盖）")
    stage = page.locator(".pickmap .dstage")
    stage.scroll_into_view_if_needed()
    box = stage.bounding_box()
    page.mouse.click(box["x"] + box["width"] * 0.62, box["y"] + box["height"] * 0.44)
    R.shot(page, "F05-01-newck-1440")
    page.click("text=保存检查点")
    page.wait_for_selector("text=确认新增检查点")
    R.check("确认摘要：立即生效、基线保持「已签认」", "立即生效" in page.locator(".confirm-summary").inner_text() and "已签认" in page.locator(".confirm-summary").inner_text(),
            page.locator(".confirm-summary").inner_text()[:200])
    page.get_by_role("button", name="确认新增", exact=True).click()
    R.check("新建检查点立即生效并知会业主", R.toast(page, "已生效，已通知业主"))
    page.wait_for_timeout(800)
    cps = [c for c in fetch(page, f"/projects/{PID}/checkpoints")["items"] if c["point"].startswith("隔墙与原结构墙拉结钢筋")]
    R.check("检查点出现在检查点列表（非草稿）", len(cps) == 1)
    st["new"] = cps[0]["id"]
    d = fetch(page, f"/projects/{PID}/work-items/{CPS['plumb']['wid']}/detail")
    R.check("基线签认状态不变（已签认）", d["baseline"]["status"] == "已签认")
    R.check("留痕：修订与签认历史追加新增检查点", any(h["kind"] == "checkpoint_added" for h in d["history"]), [h["kind"] for h in d["history"]])
    ctx.close()
    ctx, page = R.ctx("owner", 1440)
    t = [x for x in fetch(page, "/todos")["items"] if x["type"] == "新增检查点（知会）"]
    R.check("给业主生成「新增检查点」知会待办", any("拉结钢筋" in x["title"] or CPS["plumb"]["wname"] in x["title"] or "隔墙与原结构墙" in json.dumps(x, ensure_ascii=False) for x in t), [x["title"] for x in t])
    ctx.close()


def f09_check_mobile():
    # 故意让第 1 张照片上传中断（模拟弱网）产生的 net::ERR_FAILED 属预期
    ctx, page = R.ctx("qc", 375, expect=[r"/api/projects/\d+/files"])
    fail_once = {"n": 1}

    def route(rt):
        if rt.request.method == "POST" and fail_once["n"]:
            fail_once["n"] = 0
            return rt.abort("failed")
        return rt.continue_()
    page.route(f"**/api/projects/{PID}/files", route)
    open_cp(page, st["new"])
    det = page.inner_text(".ck-detail")
    R.check("检查点记录分册、版本与坐标", "墙体定位图 V1" in det and re.search(r"坐标\s*[（(]\s*\d+", det), det[:300])
    R.check("图上显示钉点", page.locator(".pinmark").count() == 1)
    page.locator("button", has_text="提交核对记录").click()
    R.check("无照片提交被拒「至少上传 1 张现场照片」", page.locator(".formerr", has_text="至少上传 1 张现场照片").count() == 1)
    cam = page.locator("input[type=file][capture=environment]")
    R.check("拍照入口 accept=image/* 且可多选", cam.get_attribute("accept") == "image/*" and cam.get_attribute("multiple") is not None)
    cam.set_input_files(files=[{"name": "拉结筋-东墙.jpg", "mimeType": "image/jpeg", "buffer": jpg((160, 140, 120))},
                               {"name": "拉结筋-西墙.jpg", "mimeType": "image/jpeg", "buffer": jpg((120, 140, 160))}])
    page.wait_for_selector(".pst.fail", timeout=15000)
    page.wait_for_selector(".pst.ok", timeout=15000)
    R.check("1 张失败可单张重传", page.locator(".pst.fail button", has_text="重传").count() == 1)
    page.locator(".seg label span", has_text=re.compile("^一致$")).click()
    page.locator(".seg label span", has_text=re.compile("^未覆盖$")).click()
    page.locator("button", has_text="提交核对记录").click()
    R.check("全部成功前不能提交", page.locator(".formerr", has_text="还有 1 张照片未上传成功").count() == 1)
    R.shot(page, "F06-02-qc-fail-375")
    page.locator(".pst.fail button", has_text="重传").click()
    page.wait_for_function("document.querySelectorAll('.pst.ok').length === 2", timeout=15000)
    page.locator("button", has_text="提交核对记录").click()
    page.wait_for_selector(".dialog")
    dlg = page.locator(".dialog").inner_text()
    R.check("核对确认摘要含核对人、服务器时间、图纸、照片与钉点、结论、覆盖状态",
            all(k in dlg for k in ("王工", "以服务器时间为准", "墙体定位图 V1", "2 张", "一致", "未覆盖")), dlg.replace("\n", " / ")[:300])
    page.locator(".dialog button", has_text="确认提交").click()
    R.check("提交成功「核对 #1 已保存」", R.toast(page, "核对 #1 已保存"))
    page.wait_for_timeout(800)
    rec = page.locator(".rec", has_text="核对 #1").inner_text()
    R.check("记录含核对人、服务器时间、所用版本、照片钉点、结论与覆盖状态",
            all(k in rec for k in ("王工", "服务器时间", "墙体定位图 V1", "2 张", "一致", "未覆盖")), rec.replace("\n", " ")[:300])
    R.check("记录不可修改（只追加，无编辑 / 删除入口）", "只追加，不可修改" in page.inner_text(".ck-detail")
            and page.locator(".rec button:has-text('编辑'), .rec button:has-text('删除')").count() == 0)
    R.check("375 核对页无横向滚动", R.hs(page, "PAGE-F06-02 检查点核对"))
    R.shot(page, "F06-02-qc-done-375")
    # 复核：追加 #2，当前结论取最新，旧记录可查
    submit_check(page, "一致", tag="复核")
    R.check("复核追加新记录「核对 #2 已保存」", R.toast(page, "核对 #2 已保存"))
    page.wait_for_timeout(800)
    R.check("当前结论取最新（核对 #2）", "核对 #2" in page.locator(".ck-detail").inner_text().split("核对与放行历史")[0])
    R.check("旧记录 #1 仍可查", page.locator(".rec", has_text="核对 #1").count() == 1 and page.locator(".rec", has_text="核对 #2").count() == 1)
    # 「已变更」不关联变更单
    open_cp(page, CPS["top"]["cp"])
    cam = page.locator("input[type=file][capture=environment]")
    cam.set_input_files(files=[{"name": "斜砌塞紧.jpg", "mimeType": "image/jpeg", "buffer": jpg((140, 150, 160))}])
    page.wait_for_function("document.querySelectorAll('.pst.ok').length === 1", timeout=15000)
    page.locator(".seg label span", has_text=re.compile("^已变更$")).click()
    page.locator(".seg label span", has_text=re.compile("^未覆盖$")).click()
    page.locator("button", has_text="提交核对记录").click()
    page.wait_for_timeout(500)
    R.check("「已变更」无生效变更单被拒「请关联已生效的变更单」", "请关联已生效的变更单" in page.inner_text(".ck-detail"))
    R.shot(page, "F06-02-changed-no-co-375")
    ctx.close()


R.step("新建检查点", f09_create)
R.step("手机核对", f09_check_mobile)

# ———————————————————————————————— FLOW-10 ————————————————————————————————
R.flow = "FLOW-10"


def rel_btn(page):
    return page.locator("button.btn.primary.block", has_text="放行")


def f10():
    tie = CPS["tie"]["cp"]
    ctx, page = R.ctx("pm", 1440)
    open_cp(page, tie)
    R.check("项目经理无放行按钮，提示「只有业主或业主代理人可以放行」", rel_btn(page).count() == 0 and "只有业主或业主代理人可以放行" in page.inner_text(".ck-detail"))
    code = page.evaluate("""async (u) => { const c = document.cookie.split('; ').find(x => x.startsWith('csrftoken=')).split('=')[1];
        const r = await fetch(u, {method: 'POST', headers: {'X-CSRFToken': c, 'Content-Type': 'application/json', 'Idempotency-Key': 'pm-try'}, body: '{}'});
        return [r.status, (await r.json()).message]; }""", f"/api/projects/{PID}/checkpoints/{tie}/release")
    R.check("项目经理放行请求被拒「只有业主或业主代理人可以放行」", code[0] == 403 and "只有业主或业主代理人可以放行" in code[1], code)
    ctx.close()
    o, op = R.ctx("owner", 375)
    a, ap = R.ctx("member", 375)
    open_cp(op, tie)
    open_cp(ap, tie)
    R.check("放行按钮 44px 通栏", round(rel_btn(op).bounding_box()["height"]) == 44)
    rel_btn(op).click()
    dlg = op.locator(".dialog").inner_text()
    R.check("放行确认摘要（依据核对、放行人、服务器时间）", all(k in dlg for k in ("依据核对", "#1", "刘先生（业主）", "以服务器时间为准")), dlg.replace("\n", " / ")[:200])
    op.locator(".dialog button", has_text="确认放行").click()
    R.check("业主放行成功", R.toast(op, "已放行，记录已生成"))
    op.wait_for_timeout(800)
    R.check("显示「已放行」印章", op.locator(".card-hd:has(#hRel) .seal").inner_text().strip() == "已放行")
    rr = op.locator(".rel-rec").inner_text()
    R.check("放行记录含放行人、时间与所依据核对", "刘先生" in rr and re.search(r"\d{2}:\d{2}", rr) and "依据核对 #1" in rr, rr)
    R.shot(op, "F06-02-released-375")
    # 代理人在放行前打开的页面上再次放行
    rel_btn(ap).click()
    ap.locator(".dialog button", has_text="确认放行").click()
    ap.wait_for_timeout(1200)
    msg = " ".join(ap.locator(".toast").all_inner_texts()) + " " + ap.inner_text("body")
    R.check("再次放行提示由谁何时已放行「已由刘先生于 … 放行，未生成新的放行记录」",
            re.search(r"已由刘先生于 \d{4}-\d{2}-\d{2} \d{2}:\d{2} 放行，未生成新的放行记录", msg), msg[:200])
    det = fetch(ap, f"/projects/{PID}/checkpoints/{tie}")
    R.check("再次放行不新增记录（仍 1 条）", len(det["releases"]) == 1, len(det["releases"]))
    R.shot(ap, "F06-02-release-again-375")
    for key, why in (("door", "不一致"), ("column", "未核对")):
        open_cp(op, CPS[key]["cp"])
        R.check(f"「{why}」检查点无放行按钮并说明原因", rel_btn(op).count() == 0 and f"当前结论为「{why}」，不能放行" in op.inner_text(".ck-detail"))
    code = op.evaluate("""async (u) => { const c = document.cookie.split('; ').find(x => x.startsWith('csrftoken=')).split('=')[1];
        const r = await fetch(u, {method: 'POST', headers: {'X-CSRFToken': c, 'Content-Type': 'application/json', 'Idempotency-Key': 'owner-try-door'}, body: '{}'});
        return [r.status, (await r.json()).message]; }""", f"/api/projects/{PID}/checkpoints/{CPS['door']['cp']}/release")
    R.check("不一致检查点放行请求被拒并说明原因", code[0] == 422 and "不能放行" in code[1], code)
    o.close()
    a.close()
    ctx, page = R.ctx("qc", 1440)
    open_cp(page, tie)
    cam = page.locator("input[type=file][capture=environment]")
    cam.set_input_files(files=[{"name": "拉结筋复查.jpg", "mimeType": "image/jpeg", "buffer": jpg((170, 120, 110))}])
    page.wait_for_function("document.querySelectorAll('.pst.ok').length === 1", timeout=15000)
    page.locator(".seg label span", has_text=re.compile("^不一致$")).click()
    page.locator(".seg label span", has_text=re.compile("^未覆盖$")).click()
    page.locator("button", has_text="提交核对记录").click()
    page.wait_for_selector(".dialog")
    R.check("确认摘要警示「放行后发现不一致」且原放行记录保留", "放行后发现不一致" in page.locator(".dialog").inner_text())
    page.locator(".dialog button", has_text="确认提交").click()
    R.check("追加不一致核对成功", R.toast(page, "已保存"), page.locator(".toast").all_inner_texts())
    page.wait_for_timeout(800)
    det = fetch(page, f"/projects/{PID}/checkpoints/{tie}")
    R.check("状态为「放行后发现不一致」", det["status"] == "放行后发现不一致", det["status"])
    R.check("原放行记录保留", len(det["releases"]) == 1)
    iss = [i for i in fetch(page, f"/projects/{PID}/issues?status=all&pageSize=50")["items"] if i.get("checkpoint") and i["checkpoint"]["id"] == tie]
    R.check("自动生成问题", len(iss) == 1, len(iss))
    R.shot(page, "F06-02-after-release-mismatch-1440")
    ctx.close()


R.step("放行", f10)

# ———————————————————————————————— FLOW-11 ————————————————————————————————
R.flow = "FLOW-11"


def f11_labels():
    damp = CPS["damp"]
    ctx, page = R.ctx("pm", 1440)
    page.goto(f"{WEB}/p/{PID}/work-items/{damp['wid']}")
    page.wait_for_selector(".ckrow")
    row = page.locator(".ckrow", has_text=damp["point"])
    R.check("工作项页未放行隐蔽检查点显示红色「不得覆盖」", row.locator(".seal", has_text="不得覆盖").count() + row.locator(".seal", has_text="超时").count() >= 1, row.inner_text())
    page.goto(f"{WEB}/p/{PID}/phase/{SEED['brickPhase']}")
    page.wait_for_selector("text=工作项 · 完成情况")
    R.check("工段页显示「不得覆盖」", "不得覆盖" in page.inner_text("body"))
    ctx.close()
    ctx, page = R.ctx("owner", 375)
    page.goto(f"{WEB}/p/{PID}/checkpoints")
    page.wait_for_selector(".cards .ckcard")
    page.locator(".chips .chip", has_text="不得覆盖").click()
    page.wait_for_timeout(500)
    cards = page.locator(".cards .ckcard")
    txt = cards.all_inner_texts()
    R.check("手机列表「不得覆盖」筛选含防潮层，印章为红色", any(damp["point"] in t for t in txt) and page.locator(".cards .ckcard .seal.stop, .cards .ckcard .seal.bad, .cards .ckcard .seal").count() >= 1, txt[:3])
    sealcls = cards.first.locator(".seal").get_attribute("class")
    color = cards.first.locator(".seal").evaluate("e => getComputedStyle(e).color")
    R.check("「不得覆盖」印章为红色", re.match(r"rgb\((\d+), (\d+), (\d+)\)", color) and int(re.match(r"rgb\((\d+)", color).group(1)) > 150, (sealcls, color))
    R.check("375 检查点列表无横向滚动", R.hs(page, "PAGE-F06-01 检查点列表"))
    R.shot(page, "F06-01-not-cover-375")
    ctx.close()
    for who in ("owner", "member", "pm"):
        ctx, page = R.ctx(who, 1440)
        page.wait_for_selector(".todo")
        first = page.locator(".todo").first.inner_text()
        items = fetch(page, "/todos")["items"]
        R.check(f"{who} 待办中超时项置顶并标「超时」", damp["point"] in first and "超时" in first and items[0]["urgent"], first[:120])
        R.check(f"{who} 超时项仍未放行（超时只提醒）", fetch(page, f"/projects/{PID}/checkpoints/{damp['cp']}")["status"] == "待放行")
        R.shot(page, f"F16-01-timeout-{who}-1440")
        ctx.close()


def f11_cover_and_discovery():
    ring = CPS["ring"]
    ctx, page = R.ctx("pm", 375)
    open_cp(page, ring["cp"])
    page.locator("button", has_text="标记已覆盖").click()
    R.check("标记覆盖确认摘要", "未放行" in page.locator(".dialog").inner_text())
    page.locator(".dialog button", has_text="确认已覆盖").click()
    R.check("标记已覆盖成功", R.toast(page, "覆盖"))
    page.wait_for_timeout(800)
    R.check("生成「未放行先覆盖」事件", "未放行先覆盖" in page.inner_text(".ck-detail"))
    R.shot(page, "F06-02-pm-cover-375")
    ctx.close()
    ctx, page = R.ctx("owner", 1440)
    t = [x for x in fetch(page, "/todos")["items"] if x["type"] == "未放行先覆盖"]
    R.check("「未放行先覆盖」进入业主待办", any(ring["point"] in x["title"] for x in t), [x["title"] for x in t])
    ctx.close()
    ctx, page = R.ctx("qc", 375)
    out = {}
    for key, cid, cover in (("shaft", CPS["shaft"]["cp"], "未覆盖"), ("ring", ring["cp"], "已被覆盖")):
        open_cp(page, cid)
        submit_check(page, "不一致", cover=cover, tag=key)
        R.toast(page, "已保存")
        page.wait_for_timeout(800)
        out[key] = page.locator(".rec").first.inner_text()
    page.goto(f"{WEB}/p/{SEED['pid2']}/checkpoints/{SEED['late']['cp']}")
    page.wait_for_selector(".ck-detail")
    page.wait_for_timeout(600)
    submit_check(page, "不一致", tag="交房后")
    R.toast(page, "已保存")
    page.wait_for_timeout(800)
    out["late"] = page.locator(".rec").first.inner_text()
    R.check("未覆盖检查点不一致 → 发现时点「覆盖前」", "覆盖前" in out["shaft"], out["shaft"][:200])
    R.check("已覆盖检查点不一致 → 发现时点「覆盖后」", "覆盖后" in out["ring"], out["ring"][:200])
    R.check("交房日后核对不一致 → 发现时点「交房后」", "交房后" in out["late"], out["late"][:200])
    R.shot(page, "F06-02-after-handover-375")
    open_cp(page, CPS["shaft"]["cp"])
    page.locator("button", has_text="修正发现时点").first.click()
    page.locator(".dialog button", has_text="下一步").click()
    R.check("修正需填写理由", page.locator(".dialog .err", has_text="请填写修正理由").count() == 1)
    page.locator(".dialog select").first.select_option(label="覆盖后") if page.locator(".dialog select").count() else None
    page.locator(".dialog textarea").fill("现场复看发现管道井外侧已先行抹灰，核对时实际已被覆盖")
    page.locator(".dialog button", has_text="下一步").click()
    page.locator(".dialog button", has_text="确认修正").click()
    R.check("修正成功并留痕", R.toast(page, "发现时点已修正并留痕"))
    page.wait_for_timeout(800)
    fix = page.locator(".fix").first.inner_text()
    R.check("修正记录含前后值、修正人、时间与理由", "覆盖前 → 覆盖后" in fix and "王工" in fix and re.search(r"\d{2}:\d{2}", fix) and "已先行抹灰" in fix, fix)
    R.shot(page, "F06-02-qc-fix-375")
    ctx.close()


def f11_timeout_setting():
    ctx, page = R.ctx("budget", 1440)
    page.goto(f"{WEB}/p/{PID}/members")
    page.wait_for_selector(".mrow")
    R.check("预算专员无放行时限修改入口", page.locator("#tlInput").count() == 0)
    code = page.evaluate("""async (u) => { const c = document.cookie.split('; ').find(x => x.startsWith('csrftoken=')).split('=')[1];
        const r = await fetch(u, {method: 'PUT', headers: {'X-CSRFToken': c, 'Content-Type': 'application/json'}, body: JSON.stringify({releaseTimeoutHours: 12})});
        return r.status; }""", f"/api/projects/{PID}/settings")
    R.check("预算专员修改时限被拒（403）", code == 403, code)
    ctx.close()
    ctx, page = R.ctx("pm", 1440)
    page.goto(f"{WEB}/p/{PID}/members")
    page.wait_for_selector("#tlInput")
    page.fill("#tlInput", "12")
    page.click(".inline-edit button")
    R.check("项目经理把放行时限改为 12 小时", R.toast(page, "12"))
    page.wait_for_timeout(600)
    R.shot(page, "F01-02-timeout-12-1440")
    ctx.close()
    ctx, page = R.ctx("qc", 1440)
    open_cp(page, CPS["column"]["cp"])
    submit_check(page, "一致", tag="时限")
    R.toast(page, "已保存")
    page.wait_for_timeout(800)
    ctx.close()
    ctx, page = R.ctx("owner", 1440)
    open_cp(page, CPS["column"]["cp"])
    R.check("之后进入待放行的检查点按 12 小时时限", "项目时限 12 小时" in page.inner_text(".ck-detail"), page.locator(".wait").inner_text() if page.locator(".wait").count() else "")
    ctx.close()


R.step("不得覆盖与超时", f11_labels)
R.step("覆盖与发现时点", f11_cover_and_discovery)
R.step("放行时限", f11_timeout_setting)
R.finish()
