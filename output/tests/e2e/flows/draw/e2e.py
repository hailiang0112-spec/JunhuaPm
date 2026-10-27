"""draw 浏览器 E2E：FLOW-07 → FLOW-08（签认态）→ FLOW-06 → FLOW-08（待重签与重签）→ FLOW-17 资料部分。

前置：run.sh 已建库、seed_base、make_pdf.py、seed.py。业务操作都在真实页面完成；API 只用于读取断言所需事实。
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "_lib"))
from harness import WEB, Run  # noqa: E402

SEED = json.load(open(os.path.join(HERE, "seed.json")))
PID, SB = SEED["pid"], SEED["studyB"]
FX = os.path.join(HERE, "fixtures")
PDF_MIME = "application/pdf"
R = Run(HERE, expected_http=[r"/baseline/submit", r"/work-items/\d+$", r"/drawing-sets/\d+/versions", r"/drawing-versions/\d+$",
                             r"/baselines/\d+/return", r"/attachments/\d+/void", r"/checkpoints$"])
st = {}


def fetch(page, path):
    return page.evaluate("p => fetch('/api' + p).then(r => r.json())", path)


def buf(name, data, mime):
    return {"name": name, "mimeType": mime, "buffer": data}


def detail(page, wid):
    return fetch(page, f"/projects/{PID}/work-items/{wid}/detail")


def open_edit(page, wid):
    page.goto(f"{WEB}/p/{PID}/work-items/{wid}")
    page.wait_for_selector("#hBase")
    page.locator("#hBase").locator("xpath=ancestor::section[1]").locator("button:has-text('编辑')").first.click()
    page.wait_for_selector(".dialog select")
    page.wait_for_function("document.querySelector('.dialog select').options.length > 1")


# ———————————————————————————————— FLOW-07 ————————————————————————————————
R.flow = "FLOW-07"


def f07_pm():
    ctx, page = R.ctx("pm", 1440)
    open_edit(page, SEED["miss"])
    page.click(".dlg-ft button:has-text('提交业主签认')")
    page.wait_for_selector(".dialog .formerr")
    fe = page.locator(".dialog .formerr").inner_text()
    R.check("缺费用与质检人时一次列出全部缺失项", "费用" in fe and "质检人" in fe, fe)
    R.check("对应字段同时标红", page.locator(".dialog .field.invalid").count() >= 2)
    R.shot(page, "F05-01-missing-1440")
    page.click(".dlg-ft button:has-text('取消')")
    open_edit(page, SEED["pendPick"])
    sel = page.locator(".dialog select").first
    pend = [o for o in sel.locator("option").all() if "墙体定位图 V2" in o.inner_text()]
    R.check("版本下拉含待业主签认的墙体定位图 V2", len(pend) == 1 and "待业主签认" in pend[0].inner_text())
    sel.select_option(pend[0].get_attribute("value"))
    R.check("选未签认版本被拒「该版本尚未签认」并清空", page.locator(".dialog .err", has_text="该版本尚未签认").count() == 1 and sel.input_value() == "")
    page.click(".dlg-ft button:has-text('取消')")
    for wid in SEED["full"]:
        open_edit(page, wid)
        page.click(".dlg-ft button:has-text('提交业主签认')")
        R.check(f"完整基线（{wid}）提交成功", R.toast(page, "已提交，等待业主签认"))
        page.wait_for_timeout(600)
    page.locator("[aria-label=修改费用]").click()
    R.check("待签认期间修改被拒「基线待业主签认，需业主退回后才能修改」", R.toast(page, "基线待业主签认，需业主退回后才能修改"))
    R.shot(page, "F05-01-pending-1440")
    ctx.close()


def f07_owner():
    for w in (375, 1440):
        ctx, page = R.ctx("owner", w)
        page.goto(f"{WEB}/p/{PID}/baselines")
        page.wait_for_selector(".grp")
        page.wait_for_timeout(500)
        R.check(f"{w} 基线签认页无横向滚动", R.hs(page, "PAGE-F05-02 基线签认"))
        R.shot(page, f"F05-02-pending-{w}")
        if w == 375:
            ctx.close()
            continue
        a = page.locator(".it", has_text=SEED["fullNames"][0])
        b = page.locator(".it", has_text=SEED["fullNames"][1])
        R.check("未展开时勾选框不可用、无签认按钮", a.locator(".ck").is_disabled() and a.locator("text=签认此项").count() == 0)
        a.locator(".exp").click()
        R.check("展开后出现签认按钮", a.locator("text=签认此项").count() == 1)
        b.locator(".exp").click()
        a.locator(".ck").check()
        b.locator(".ck").check()
        grp = page.locator(".grp", has=a)
        grp.locator("button", has_text="签认本组所选（2）").click()
        sm = page.locator(".dialog").inner_text()
        R.check("批量签认确认摘要（2 项、签认人刘先生）", "2" in sm and "刘先生" in sm, sm.replace("\n", " ")[:200])
        R.shot(page, "F05-02-confirm-1440")
        page.get_by_role("button", name="确认签认", exact=True).click()
        R.check("批量签认生成 2 条独立签认记录", R.toast(page, "已签认 2 项，生成 2 条签认记录"))
        page.wait_for_timeout(800)
        for wid in SEED["full"]:
            dj = json.dumps(detail(page, wid), ensure_ascii=False)
            d = detail(page, wid)
            R.check(f"工作项 {wid} 基线已签认，签认记录含签认人、时间与内容快照",
                    d["baseline"]["status"] == "已签认" and "刘先生" in dj and re.search(r"2026-10-2\dT", dj) is not None
                    and (d["workItem"].get("description") or "")[:10] in dj)
        r = page.locator(".it", has_text=SEED["returnItem"])
        r.locator(".exp").click()
        r.locator("text=退回").click()
        page.click(".dlg-ft button:has-text('下一步')")
        R.check("退回无理由被拒「请填写退回理由」", page.locator(".dialog .err", has_text="请填写退回理由").count() == 1)
        page.fill(".dialog textarea", "给水管打压试验需注明保压时间，请补充后重新提交")
        page.click(".dlg-ft button:has-text('下一步')")
        page.get_by_role("button", name="确认退回", exact=True).click()
        R.check("有理由退回成功", R.toast(page, "已退回，项目经理将收到待办"))
        ctx.close()
    ctx, page = R.ctx("pm", 1440)
    t = [x for x in fetch(page, "/todos")["items"] if x["type"] == "被退回基线"]
    R.check("退回后状态「已退回」并给项目经理生成待办", any(SEED["returnItem"] in x["title"] for x in t), [x["title"] for x in t])
    ctx.close()


R.step("项目经理提交", f07_pm)
R.step("业主签认与退回", f07_owner)

# ———————————————————————————————— FLOW-08（签认态） ————————————————————————————————
R.flow = "FLOW-08"


def f08_locked():
    ctx, page = R.ctx("pm", 1440)
    page.goto(f"{WEB}/p/{PID}/work-items/{SB}")
    page.wait_for_selector("#hBase")
    page.locator("[aria-label=修改费用]").click()
    R.check("已签认修改费用被拒（提示走变更单或等待重签）", R.toast(page, "已签认，请发起变更单或等待新版图纸重签"))
    page.fill(".prog input[type=number]", "60")
    page.click("text=保存进度")
    R.check("完成度可改", R.toast(page, "进度已保存（完成度 60%）"))
    ctx.close()


R.step("签认态锁定", f08_locked)

# ———————————————————————————————— FLOW-06 ————————————————————————————————
R.flow = "FLOW-06"


def f06_upload():
    ctx, page = R.ctx("dm", 1440)
    page.goto(f"{WEB}/p/{PID}/drawings?volume={SEED['sets']['水电点位图']}")
    page.wait_for_selector(".tl")
    page.click("text=上传新版")
    page.wait_for_selector("text=上传新版 · 水电点位图 V2")
    dlg = page.locator(".dialog[aria-label^='上传新版']")
    dlg.locator("input[type=file][accept*='.dwg']").set_input_files(files=[buf("二楼水电点位图-V2.dwg", b"AC1027" + b"\0" * 2048, "application/octet-stream")])
    dlg.locator("textarea").fill("二楼书房 B 南墙新增 2 个五孔插座（业主要求）")
    page.get_by_role("button", name="发布", exact=True).click()
    page.wait_for_timeout(600)
    R.check("只有 CAD 被拒「请同时上传 PDF 或图片版…」", "请同时上传 PDF 或图片版" in dlg.inner_text(), dlg.inner_text()[:200])
    dlg.locator("input[type=file][accept*='.pdf']").set_input_files(files=[buf("二楼水电点位图-V2.pdf", open(os.path.join(FX, "二楼水电点位图-V2.pdf"), "rb").read(), PDF_MIME)])
    dlg.locator("textarea").fill("")
    page.get_by_role("button", name="发布", exact=True).click()
    page.wait_for_timeout(600)
    R.check("V2 不写改动说明被拒「请说明本版改了什么」", "请说明本版改了什么" in dlg.inner_text())
    dlg.locator("textarea").fill("二楼书房 B 南墙新增 2 个五孔插座（业主要求）；三楼主卧床头插座下移 150mm")
    water = [w for w in fetch(page, f"/projects/{PID}/work-items")["items"] if w["id"] in SEED["waterIds"]]
    names = list(SEED["signedNames"]) + [w["name"] for w in water if w["name"] not in SEED["signedNames"] and w["name"] != SEED["returnItem"]][:9]
    for n in names:
        dlg.locator("label.pk", has_text=n).first.locator("input").check()
    R.check("勾选 12 个受影响工作项（其中 3 个基线已签认）", "已勾选 12 项" in dlg.inner_text() and dlg.locator("label.pk:has(input:checked) .tag.ok").count() == 3)
    R.shot(page, "F04-01-upload-1440")
    page.get_by_role("button", name="发布", exact=True).click()
    cf = page.locator(".dialog[aria-label='发布 水电点位图 V2']")
    cf.wait_for(timeout=8000)
    R.check("发布前确认摘要（不可删除替换）", "V2" in cf.inner_text(), cf.inner_text()[:200])
    R.shot(page, "F04-01-publish-confirm-1440")
    cf.get_by_role("button", name="确认发布", exact=True).click()
    R.check("合规上传生成 V2", R.toast(page, "已发布 水电点位图 V2，等待业主签认"))
    page.wait_for_timeout(800)
    s = next(x for x in fetch(page, f"/projects/{PID}/drawing-sets")["items"] if x["name"] == "水电点位图")
    v2 = next(v for v in s["versions"] if v["versionNo"] == 2)
    st["v2"] = v2["id"]
    R.check("V2 状态「待业主签认」，V1 仍为当前签认版", v2["status"] == "待业主签认" and s["currentSignedVersion"]["versionNo"] == 1)
    R.check("页面无删除 / 替换入口（已发布版本只读）", page.locator("button:has-text('删除'), button:has-text('替换')").count() == 0)
    code = page.evaluate("""async (u) => { const c = document.cookie.split('; ').find(x => x.startsWith('csrftoken=')).split('=')[1];
        const a = await fetch(u, {method: 'DELETE', headers: {'X-CSRFToken': c}});
        const b = await fetch(u, {method: 'PUT', headers: {'X-CSRFToken': c, 'Content-Type': 'application/json'}, body: '{}'});
        return [a.status, b.status]; }""", f"/api/projects/{PID}/drawing-versions/{SEED['v1']['水电点位图']}")
    R.check("删除或替换 V1 被拒（405/403）", all(c in (403, 405) for c in code), code)
    ctx.close()


def f06_sign():
    ctx, page = R.ctx("owner", 1440)
    page.goto(f"{WEB}/p/{PID}/drawings?volume={SEED['sets']['水电点位图']}")
    page.wait_for_selector(".tl")
    page.click("text=签认 V2")
    page.wait_for_selector("text=签认水电点位图 V2")
    R.check("签认摘要警示已签认基线将待重签", "基线已签认的" in page.locator(".dialog").inner_text())
    R.shot(page, "F04-01-sign-1440")
    page.get_by_role("button", name="确认签认", exact=True).click()
    R.check("签认 V2 成功", R.toast(page, "V2 已签认"))
    page.wait_for_timeout(800)
    s = next(x for x in fetch(page, f"/projects/{PID}/drawing-sets")["items"] if x["name"] == "水电点位图")
    cur = s["currentSignedVersion"]
    R.check("V2 成为当前签认版且签认记录含文件摘要", cur["versionNo"] == 2 and cur["signedBy"] == "刘先生" and cur["signSha256"] == cur["file"]["sha256"])
    sts = [detail(page, w)["baseline"]["status"] for w in SEED["signedItems"]]
    R.check("3 个已签认基线变为「待重签」", sts == ["待重签"] * 3, sts)
    owner_t = json.dumps(fetch(page, "/todos")["items"], ensure_ascii=False)
    R.check("给业主生成待重签待办（3 项）", all(n in owner_t for n in SEED["signedNames"]), "业主待办中未出现待重签工作项")
    ctx.close()
    ctx, page = R.ctx("pm", 1440)
    pm_t = json.dumps(fetch(page, "/todos")["items"], ensure_ascii=False)
    R.check("给项目经理生成待重签待办（3 项）", all(n in pm_t for n in SEED["signedNames"]), "项目经理待办中未出现待重签工作项")
    page.goto(WEB + "/")
    page.wait_for_selector(".todo, .state")
    R.shot(page, "F16-01-pm-after-v2-1440")
    ctx.close()


def f06_compare_mobile():
    for w in (1440, 375):
        ctx, page = R.ctx("qc", w)
        page.goto(f"{WEB}/p/{PID}/drawings/{SEED['v1']['水电点位图']}")
        page.wait_for_selector(".dstage img")
        page.click("#cmpBtn")
        page.wait_for_timeout(1200)
        txt = page.inner_text("body")
        R.check(f"{w} 对比并排显示两版与期间改动说明", page.locator("#cmpBtn").inner_text().strip() == "退出对比" and page.locator(".dstage img").count() >= 2
                and "新增 2 个五孔插座" in txt, page.locator(".dstage img").count())
        R.check(f"{w} 对比视图无横向滚动", R.hs(page, "PAGE-F04-02 图纸对比"))
        R.shot(page, f"F04-02-compare-{w}")
        ctx.close()
    ctx, page = R.ctx("qc", 375)
    page.goto(f"{WEB}/p/{PID}/work-items/{SB}")
    page.wait_for_selector("#hBase")
    page.locator("a[href*='/drawings/']").first.click()
    page.wait_for_selector(".dstage img")
    page.wait_for_timeout(600)
    R.check("手机端显示基线引用的版本号（V1）", "基线引用 V1" in page.inner_text(".topbar"), page.inner_text(".topbar")[:120])
    R.check("手机端显示「图纸已更新，基线待重签」", page.locator(".banner", has_text="图纸已更新，基线待重签").count() == 1)
    R.check("375 图纸查看器无横向滚动", R.hs(page, "PAGE-F04-02 图纸查看器"))
    R.shot(page, "F04-02-viewer-375")
    ctx.close()


R.step("上传新版", f06_upload)
R.step("业主签认 V2", f06_sign)
R.step("对比与手机查看", f06_compare_mobile)

# ———————————————————————————————— FLOW-08（待重签与重签） ————————————————————————————————
R.flow = "FLOW-08"


def f08_resign():
    for w in (375, 1440):
        ctx, page = R.ctx("qc", w)
        page.goto(f"{WEB}/p/{PID}/checkpoints/{SEED['studyBCps'][1]}")
        page.wait_for_selector(".ck-detail")
        page.wait_for_timeout(600)
        body = page.inner_text(".ck-detail") if page.locator(".ck-detail").count() else page.inner_text("body")
        R.check(f"{w} 核对页显示「该工作项有新版图纸待重签」", page.locator(".banner", has_text="该工作项有新版图纸待重签").count() == 1)
        R.check(f"{w} 核对页底图为原签认版 V1", "水电点位图 V1" in page.inner_text("body"))
        R.check(f"{w} 核对页无横向滚动", R.hs(page, "PAGE-F06-02 检查点核对（待重签）"))
        R.shot(page, f"F06-02-resign-{w}")
        ctx.close()
    ctx, page = R.ctx("pm", 1440)
    page.goto(f"{WEB}/p/{PID}/work-items/{SB}")
    page.wait_for_selector("#hBase")
    R.check("工作项显示待重签横幅与印章", page.locator(".banner", has_text="基线待重签").count() == 1 and page.locator(".seal", has_text="待重签").count() >= 1)
    page.click("text=更新图纸版本并重新提交")
    page.wait_for_selector("text=更新基线并提交重签")
    sel = page.locator(".dialog select").first
    page.wait_for_function("document.querySelector('.dialog select').options.length > 2")
    v2 = [o for o in sel.locator("option").all() if "水电点位图 V2" in o.inner_text()][0].get_attribute("value")
    sel.select_option(v2)
    page.click(".dlg-ft button:has-text('提交业主签认')")
    R.check("更新图纸版本重提", R.toast(page, "已提交，等待业主重签"))
    ctx.close()
    ctx, page = R.ctx("owner", 1440)
    page.goto(f"{WEB}/p/{PID}/baselines")
    page.wait_for_selector(".grp")
    it = page.locator(".it", has_text="二楼书房 B 墙内线管预埋")
    R.check("待签列表中标「重签」", it.locator(".tag", has_text="重签").count() >= 1)
    it.locator(".exp").click()
    it.locator("text=签认此项").click()
    page.get_by_role("button", name="确认签认", exact=True).click()
    R.check("业主重签成功", R.toast(page, "已签认 1 项"))
    page.wait_for_timeout(800)
    d = detail(page, SB)
    dj = json.dumps(d, ensure_ascii=False)
    dv = d["workItem"]["drawingVersion"] or {}
    R.check("重签后状态恢复「已签认」并引用新版本 V2", d["baseline"]["status"] == "已签认" and dv.get("id") == st.get("v2") and dv.get("versionNo") == 2, (d["baseline"]["status"], dv))
    so = [h["text"] for h in d["history"] if h["kind"] == "signoff"]
    R.check("旧签认记录保留（r1 V1 与 r2 V2 两条签认）", len(so) == 2 and any("V1" in t for t in so) and any("V2" in t for t in so), so)
    page.goto(f"{WEB}/p/{PID}/work-items/{SB}")
    page.wait_for_selector("#hBase")
    page.wait_for_timeout(500)
    R.shot(page, "F05-01-resigned-1440")
    owner_up = [x for x in fetch(page, "/todos")["items"] if x["type"] == "即将施工，基线未签认"]
    R.check("临近施工未签认工作项给业主生成「即将施工，基线未签认」待办", any(SEED["upcomingItem"] in x["title"] for x in owner_up), [x["title"] for x in owner_up])
    ctx.close()
    ctx, page = R.ctx("pm", 1440)
    pm_up = [x for x in fetch(page, "/todos")["items"] if x["type"] == "即将施工，基线未签认"]
    R.check("临近施工未签认工作项给项目经理生成待办", any(SEED["upcomingItem"] in x["title"] for x in pm_up), [x["title"] for x in pm_up])
    ctx.close()


R.step("待重签与重签", f08_resign)

# ———————————————————————————————— FLOW-17 资料部分 ————————————————————————————————
R.flow = "FLOW-17"


def f17_attach():
    wid = SEED["signedItems"][1]
    ctx, page = R.ctx("qc", 1440)
    page.goto(f"{WEB}/p/{PID}/work-items/{wid}")
    page.wait_for_selector(".upbtn")
    before = page.locator(".frow").count()
    from PIL import Image
    import io
    def img(c):
        b = io.BytesIO()
        Image.new("RGB", (640, 480), c).save(b, "JPEG")
        return b.getvalue()
    # 60MB 超过 Playwright 内存 buffer 上限（50MB），4 个文件统一写临时文件后按路径一次选择
    tmp = os.path.join(HERE, "logs", "上传临时")
    os.makedirs(tmp, exist_ok=True)
    files = {"书房A线管走向-1.jpg": img((154, 165, 177)), "书房A底盒高度-2.jpg": img((200, 184, 154)),
             "PVC线管合格证.pdf": open(os.path.join(FX, "二楼水电点位图-V1.pdf"), "rb").read()}
    paths = []
    for n, data in files.items():
        paths.append(os.path.join(tmp, n))
        open(paths[-1], "wb").write(data)
    paths.append(os.path.join(tmp, "现场全景视频导出-60MB.pdf"))
    with open(paths[-1], "wb") as fh:
        fh.write(b"%PDF-1.4\n")
        fh.truncate(60 * 1024 * 1024)
    page.set_input_files(".upbtn input", paths)
    page.wait_for_selector(".upok", timeout=30000)
    page.wait_for_timeout(800)
    R.check("合格文件全部保存（已上传 3 个文件）", "已上传 3 个文件" in page.locator(".upok").inner_text())
    rej = page.locator(".uprej").inner_text()
    R.check("60MB 文件单独被拒并显示文件名与原因", "现场全景视频导出-60MB.pdf" in rej and "超过 50MB" in rej, rej)
    R.check("资料数为 3", page.locator(".frow").count() - before == 3 and before == 0, (before, page.locator(".frow").count()))
    R.check("图片有缩略图", page.locator(".frow img").count() == 2)
    href = page.locator(".frow", has_text="PVC线管合格证.pdf").locator("a").first.get_attribute("href")
    code = page.evaluate("u => fetch(u).then(r => [r.status, r.headers.get('content-type')])", href)
    R.check("PDF 可下载", code[0] == 200 and "pdf" in (code[1] or ""), (href, code))
    page.locator(".frow", has_text="PVC线管合格证.pdf").locator("text=作废").click()
    page.get_by_role("button", name="确认作废", exact=True).click()
    R.check("普通资料作废成功", R.toast(page, "已作废"))
    page.wait_for_timeout(600)
    R.check("作废后从默认列表隐藏", page.locator(".frow", has_text="PVC线管合格证.pdf").count() == 0)
    page.check("text=显示已作废")
    R.check("勾选显示已作废可见并留痕", page.locator(".frow.void", has_text="PVC线管合格证.pdf").count() == 1
            and "王工" in page.locator(".frow.void").inner_text())
    R.shot(page, "F05-01-attachments-1440")
    page.goto(f"{WEB}/p/{PID}/work-items/{SB}")
    page.wait_for_selector(".frow")
    page.locator(".frow", has_text=SEED["refPhoto"]).locator("text=作废").click()
    page.wait_for_timeout(800)
    msg = " ".join(page.locator(".toast").all_inner_texts())
    if page.locator(".dialog").count():
        msg += " " + page.locator(".dialog").inner_text()
    R.check("被核对记录引用的照片作废被拒", "引用" in msg, msg[:200])
    R.check("被引用照片仍在列表中", page.locator(".frow", has_text=SEED["refPhoto"]).count() == 1)
    ctx.close()
    ctx, page = R.ctx("qc", 375)
    page.goto(f"{WEB}/p/{PID}/work-items/{wid}")
    page.wait_for_selector(".frow")
    R.check("375 工作项详情（资料）无横向滚动", R.hs(page, "PAGE-F05-01 工作项详情"))
    R.shot(page, "F05-01-attachments-375")
    ctx.close()
    import shutil
    shutil.rmtree(os.path.join(HERE, "logs", "上传临时"), ignore_errors=True)


def f17_acceptance():
    from PIL import Image
    import io
    b = io.BytesIO()
    Image.new("RGB", (800, 600), (150, 150, 140)).save(b, "JPEG")
    ctx, page = R.ctx("pm", 1440)
    page.goto(f"{WEB}/p/{PID}/phase/{SEED['brickPhase']}")
    page.wait_for_selector("#ph-t")
    page.set_input_files(".upcard input[type=file]", files=[buf("负一楼卫生间管道井封堵-完成面.jpg", b.getvalue(), "image/jpeg")])
    R.check("验收图片上传默认「待复验」", R.toast(page, "状态为「待复验」"))
    page.wait_for_timeout(800)
    fig = page.locator("figure.photo").first
    R.check("新图片印章为待复验", fig.locator(".seal").inner_text().strip() == "待复验")
    seq = []
    for _ in range(3):
        page.wait_for_timeout(3200)
        fig.locator(".ops button").click()
        page.wait_for_timeout(1000)
        seq.append(fig.locator(".seal").inner_text().strip())
    R.check("状态按 施工中 → 待复验 → 已验收 循环切换", seq == ["已验收", "施工中", "待复验"], seq)
    R.shot(page, "F10-03-acceptance-1440")
    ctx.close()


R.step("工作项资料", f17_attach)
R.step("验收图片", f17_acceptance)
R.finish()
