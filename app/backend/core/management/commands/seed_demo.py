"""试用演示数据：在「君华新城 · 联排别墅」上走真实接口（同样的权限、摘要链与操作日志）造出砌墙阶段的现场状态。

前置：seed_base。只在空的演示项目上执行一次；图纸与照片为程序绘制的真实 PDF / JPEG。
"""
import datetime
import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from PIL import Image, ImageDraw, ImageFont
from rest_framework.test import APIClient

from core.models import Checkpoint, DrawingSet, Project, User, WorkItem

FONT = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"


def font(size):
    try:
        return ImageFont.truetype(FONT, size)
    except OSError:
        return ImageFont.load_default()


def drawing_pdf(title, version, rooms, extra=()):
    """程序绘制一张户型图并存为 PDF（墙线、房间名、标题栏）。"""
    W, H = 1600, 1120
    im = Image.new("RGB", (W, H), "white")
    g = ImageDraw.Draw(im)
    g.rectangle((80, 80, 1520, 960), outline="#374151", width=12)
    for x0, y0, x1, y1 in [(300, 80, 300, 480), (760, 80, 760, 480), (920, 80, 920, 480), (1280, 80, 1280, 480),
                           (80, 480, 1520, 480), (80, 600, 1520, 600), (320, 600, 320, 960), (800, 600, 800, 960),
                           (1160, 600, 1160, 960)]:
        g.line((x0, y0, x1, y1), fill="#374151", width=6)
    pos = [(190, 280), (530, 280), (840, 280), (1100, 280), (1400, 280), (800, 540), (200, 780), (560, 780), (980, 780),
           (1340, 780)]
    for name, (x, y) in zip(rooms, pos):
        g.text((x, y), name, font=font(40), fill="#5b6779", anchor="mm")
    for x, y, label in extra:
        g.rectangle((x, y, x + 28, y + 16), outline="#b42318", width=4)
        g.text((x + 14, y - 22), label, font=font(24), fill="#b42318", anchor="mm")
    g.text((80, 1040), f"君华新城 · 联排别墅  {title}  V{version}", font=font(36), fill="#111827")
    buf = io.BytesIO()
    im.save(buf, "PDF", resolution=150)
    return buf.getvalue()


def photo(seed, label):
    im = Image.new("RGB", (1280, 960), (150 + seed * 7 % 60, 140 + seed * 13 % 50, 120 + seed * 5 % 40))
    g = ImageDraw.Draw(im)
    for i in range(0, 1280, 160):
        g.rectangle((i, 600, i + 150, 680), fill=(170, 90, 70), outline=(120, 110, 100), width=4)  # 砌块
    g.line((200, 300, 1100, 300), fill=(60, 60, 60), width=10)  # 线管
    g.text((40, 40), label, font=font(48), fill="white")
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    return buf.getvalue()


class Command(BaseCommand):
    help = "生成试用演示数据"

    def ok(self, r, codes=(200, 201)):
        if r.status_code not in codes:
            raise CommandError(f"{r.request['REQUEST_METHOD']} {r.request['PATH_INFO']} → {r.status_code} {r.content[:300]!r}")
        return r.json() if r.content and r["Content-Type"].startswith("application/json") else None

    def handle(self, *args, **opts):
        call_command("seed_base")
        p = Project.objects.get(name="君华新城 · 联排别墅")
        if DrawingSet.objects.filter(project=p).exists():
            self.stdout.write("演示数据已存在，跳过")
            return
        U = {u.name: u for u in User.objects.all()}

        def cli(name):
            c = APIClient()
            c.force_authenticate(U[name])
            return c

        admin, owner, owner2, member = cli("周经理"), cli("刘先生"), cli("刘太太"), cli("钱工")
        pm, dm, qc, budget = cli("张工"), cli("李工"), cli("王工"), cli("赵会计")
        P = f"/api/projects/{p.id}"
        ok = self.ok
        today = timezone.localdate()
        ph = {x.name: x for x in p.phases.all()}

        # ---- 图纸：四个分册 V1 签认；水电点位图 V2 签认（书房 B 新增插座）；墙体定位图 V2 待业主签认
        rooms2 = ["主卫", "主卧", "衣帽间", "次卧", "次卫", "走廊", "楼梯间", "家庭厅", "书房 A", "书房 B"]
        sets, v1 = {}, {}
        for name in ("平面布置图", "墙体定位图", "水电点位图", "吊顶及灯位图"):
            sets[name] = ok(dm.post(f"{P}/drawing-sets", {"name": name}, format="json"))["id"]
            v = ok(dm.post(f"{P}/drawing-sets/{sets[name]}/versions", {
                "file": SimpleUploadedFile(f"二楼{name}-V1.pdf", drawing_pdf(f"二楼{name}", 1, rooms2), "application/pdf"),
                "changeNote": "首版（设计交底版）"}, format="multipart"))
            ok(owner.post(f"{P}/drawing-versions/{v['id']}/sign", {}, format="json"))
            v1[name] = v["id"]

        def wi(floor, room, name):
            w = WorkItem.objects.filter(project=p, floor__name=floor, room__name=room, name__contains=name).first()
            if w is None:
                raise CommandError(f"模板中找不到工作项：{floor} {room} {name}")
            return w

        def baseline(w, dv, cost, finish, cks):
            ok(pm.patch(f"{P}/work-items/{w.id}", {"drawingVersionId": dv, "cost": cost, "qcUserId": U["王工"].id,
                                                   "plannedFinish": finish.isoformat()}, format="json"))
            made = [ok(pm.post(f"{P}/work-items/{w.id}/checkpoints", {"point": t, "isConcealed": h, "x": x, "y": y,
                                                                         "pageNo": 1}, format="json")) for t, h, x, y in cks]
            r = ok(pm.post(f"{P}/work-items/{w.id}/baseline/submit", {}, format="json"))
            return r["revisionId"], made

        # 砌墙工段（已签认）
        brick = [
            (wi("二楼", "书房 B", "隔墙"), v1["墙体定位图"], 3260, today - datetime.timedelta(days=3),
             [("门洞净宽 900mm", False, 0.86, 0.62), ("拉结筋间距与伸入长度", True, 0.80, 0.70)]),
            (wi("二楼", "卫生间 A", "管道井"), v1["墙体定位图"], 1480, today - datetime.timedelta(days=6),
             [("管道井封堵与闭水", True, 0.12, 0.30)]),
            (wi("一楼", "厨房", "隔墙"), v1["墙体定位图"], 2860, today + datetime.timedelta(days=2),
             [("烟道预留位按深化图定位", True, 0.33, 0.35), ("墙体垂直度", False, 0.38, 0.40)]),
        ]
        revs, cps = [], {}
        for w, dv, cost, fin, ck in brick:
            r, made = baseline(w, dv, cost, fin, ck)
            revs.append(r)
            cps.update({m["point"]: m for m in made})
        ok(owner.post(f"{P}/baselines/sign", {"revisionIds": revs[:2]}, format="json"))
        ok(owner.post(f"{P}/baselines/sign", {"revisionIds": revs[2:]}, format="json"))
        # 水电工段：两项待业主签认（业主待办）
        for w, cost, fin, ck in [
            (wi("二楼", "书房 B", "布管"), 1280, today + datetime.timedelta(days=5),
             [("墙内线管预埋走向", True, 0.88, 0.80), ("强电底盒高度 300mm", True, 0.90, 0.86)]),
            (wi("一楼", "厨房", "给排水"), 3850, today + datetime.timedelta(days=12),
             [("给水管打压 0.8MPa 保压 30 分钟", True, 0.30, 0.25)]),
        ]:
            baseline(w, v1["水电点位图"], cost, fin, ck)

        # 新版图纸：水电点位图 V2 签认；墙体定位图 V2 待签认
        v2 = ok(dm.post(f"{P}/drawing-sets/{sets['水电点位图']}/versions", {
            "file": SimpleUploadedFile("二楼水电点位图-V2.pdf",
                                       drawing_pdf("二楼水电点位图", 2, rooms2, [(1380, 900, "新增插座"), (1440, 900, "新增插座")]),
                                       "application/pdf"),
            "changeNote": "二楼书房 B 南墙新增 2 个五孔插座（业主要求）"}, format="multipart"))
        ok(dm.post(f"{P}/drawing-sets/{sets['墙体定位图']}/versions", {
            "file": SimpleUploadedFile("二楼墙体定位图-V2.pdf", drawing_pdf("二楼墙体定位图", 2, rooms2), "application/pdf"),
            "changeNote": "二楼主卧衣帽间隔墙后移 300mm"}, format="multipart"))
        ok(owner.post(f"{P}/drawing-versions/{v2['id']}/sign", {}, format="json"))

        # ---- 现场核对（质检拍照）与放行
        def shot(i, label):
            return ok(qc.post(f"{P}/files", {"file": SimpleUploadedFile(f"现场照片-{i:02d}.jpg", photo(i, label), "image/jpeg")},
                              format="multipart"))["id"]

        def check(point, conclusion, note="", covered=False):
            cid = cps[point]["id"]
            return ok(qc.post(f"{P}/checkpoints/{cid}/checks", {
                "conclusion": conclusion, "wasCovered": covered, "note": note,
                "photos": [{"fileId": shot(cid * 3 + k, f"{cps[point]['code']} {point}")} for k in range(2)]}, format="json"))

        check("管道井封堵与闭水", "一致")
        check("门洞净宽 900mm", "不一致", note="实测净宽 860mm，比图纸窄 40mm")
        check("拉结筋间距与伸入长度", "一致")
        check("烟道预留位按深化图定位", "一致")
        ok(owner.post(f"{P}/checkpoints/{cps['管道井封堵与闭水']['id']}/release", {}, format="json",
                      HTTP_IDEMPOTENCY_KEY="demo-release-1"))
        # 业主指定钱工为放行代理人，代理放行一项
        ok(owner.post(f"{P}/agent", {"userId": U["钱工"].id}, format="json"))
        ok(member.post(f"{P}/checkpoints/{cps['烟道预留位按深化图定位']['id']}/release", {}, format="json",
                       HTTP_IDEMPOTENCY_KEY="demo-release-2"))
        # 「拉结筋」待放行已超时（放行时限 24 小时）
        Checkpoint.objects.filter(pk=cps["拉结筋间距与伸入长度"]["id"]).update(
            awaiting_release_since=timezone.now() - datetime.timedelta(hours=30))
        # 项目经理登记「墙体垂直度」未核对就被覆盖 → 未放行先覆盖（非隐蔽，不产生该标签）；改用隐蔽点演示
        ok(pm.post(f"{P}/checkpoints/{cps['墙体垂直度']['id']}/cover"), (201, 409))

        # ---- 问题闭环：门洞不一致自动生成的问题，质检判定原因、指派
        issues = ok(pm.get(f"{P}/issues"))["items"]
        door = next(i for i in issues if "门洞" in i["description"])
        ok(qc.post(f"{P}/issues/{door['id']}/cause", {"cause": "施工偏离签认图"}, format="json"))
        ok(pm.post(f"{P}/issues/{door['id']}/assign", {"countermeasure": "拆除门洞一侧 40mm 砌体，按图重砌后复核",
                                                       "ownerName": "张工", "dueDate": (today + datetime.timedelta(days=2)).isoformat()},
                   format="json"), (200, 201, 400))
        opts = ok(pm.get(f"{P}/issues/options"))
        F = {f["name"]: f for f in opts["floors"]}
        PH = {x["name"]: x["id"] for x in opts["phases"]}
        room = lambda fl, rm: next(r["id"] for r in F[fl]["rooms"] if r["name"] == rm)  # noqa: E731
        ok(pm.post(f"{P}/issues", {"description": "夹层楼梯间墙体砂浆饱满度不足", "level": "一般", "phaseId": PH["砌墙"],
                                   "floorId": F["夹层"]["id"], "roomId": room("夹层", F["夹层"]["rooms"][0]["name"]),
                                   "dueDate": (today + datetime.timedelta(days=4)).isoformat()}, format="json"))

        # ---- 变更单：一张已生效、一张待业主签认、一张待预算定价
        def co(title, reason, content, ids, draw, late):
            return ok(pm.post(f"{P}/change-orders", {"title": title, "reasonCategory": reason, "content": content,
                                                     "workItemIds": ids, "needsNewDrawing": draw, "builtBeforeSign": late},
                              format="json"))
        a = co("二楼书房 B 南墙新增 2 个五孔插座", "业主要求", "业主要求在书房 B 南墙书桌位置新增 2 个五孔插座，线管随砌筑预埋。",
               [wi("二楼", "书房 B", "布管").id], True, False)
        ok(budget.post(f"{P}/change-orders/{a['id']}/price", {"priceDelta": 360, "scheduleDeltaDays": 0, "costBearer": "业主"},
                       format="json"))
        ok(owner.post(f"{P}/change-orders/{a['id']}/sign", {}, format="json"))
        b = co("二楼主卧衣帽间隔墙后移 300mm", "业主要求", "业主要求衣帽间隔墙整体后移 300mm，扩大衣帽间进深；门洞随墙后移，尺寸不变。",
               [wi("二楼", "书房 B", "隔墙").id], True, False)
        ok(budget.post(f"{P}/change-orders/{b['id']}/price", {"priceDelta": 2600, "scheduleDeltaDays": 2, "costBearer": "业主"},
                       format="json"))
        co("一楼厨房烟道包封西移 120mm", "设计深化", "按厨房深化节点图将烟道包封西移 120mm，同步调整东墙砌筑。",
           [wi("一楼", "厨房", "隔墙").id], False, True)

        # ---- 计划、进度与出勤
        brick_items = ok(pm.get(f"{P}/work-items?phase={ph['砌墙'].id}"))["items"]
        for i, it in enumerate(brick_items):
            pct = 100 if i < 10 else 60 if i < 16 else 30 if i < 20 else 0
            if pct:
                body = {"progress": pct}
                if pct == 100:
                    body["actualFinish"] = (today - datetime.timedelta(days=10 - i % 5)).isoformat()
                pm.patch(f"{P}/work-items/{it['id']}", body, format="json")
        s = ph["砌墙"]
        ok(pm.patch(f"{P}/phases/{s.id}/plan", {"plannedStart": s.planned_start.isoformat(),
                                                "plannedEnd": max(s.planned_end, today + datetime.timedelta(days=12)).isoformat(),
                                                "teamLead": "瓦工班 · 陈师傅（6 人）", "weight": s.weight, "scopeNote": s.scope_note,
                                                "reason": "砌块到货延迟，加上书房 B 门洞返工，砌墙工段顺延"}, format="json"))
        ok(pm.post(f"{P}/phases/{s.id}/attendance/batch", {"start": s.planned_start.isoformat(),
                                                           "end": (today - datetime.timedelta(days=1)).isoformat(),
                                                           "headcount": 5, "mode": "workdays"}, format="json"))
        ok(pm.put(f"{P}/phases/{s.id}/attendance/{today.isoformat()}", {"headcount": 6}, format="json"))
        fid = ok(pm.post(f"{P}/files", {"file": SimpleUploadedFile("负一楼卫生间管道井封堵-完成面.jpg", photo(90, "管道井封堵完成面"),
                                                                  "image/jpeg")}, format="multipart"))["id"]
        ok(pm.post(f"{P}/phases/{s.id}/acceptance-photos", {"fileIds": [fid]}, format="json"))

        # ---- 房屋档案、补充事项、公告栏、付款节点
        folders = {f["name"]: f["id"] for f in ok(pm.get(f"{P}/archive/contract/folders"))["items"]}
        ok(budget.post(f"{P}/archive/contract/folders/{folders['主合同']}/files", {
            "file": SimpleUploadedFile("君华新城联排别墅装修工程施工合同.pdf",
                                       drawing_pdf("施工合同（扫描件）", 1, ["合同正文"]), "application/pdf")}, format="multipart"))
        layout = {f["name"]: f["id"] for f in ok(pm.get(f"{P}/archive/layout/folders"))["items"]}
        ok(dm.post(f"{P}/archive/layout/folders/{layout['二楼']}/files", {
            "file": SimpleUploadedFile("二楼平面布局图-V3.pdf", drawing_pdf("二楼平面布局图", 3, rooms2), "application/pdf")},
            format="multipart"))
        ok(pm.post(f"{P}/supplements", {"title": "三楼露台加装户外洗手池", "note": "业主要求在三楼露台东北角加装户外洗手池，需预留给排水。",
                                        "raisedOn": (today - datetime.timedelta(days=2)).isoformat(),
                                        "dueOn": (today + datetime.timedelta(days=14)).isoformat(), "ownerName": "张工"},
                   format="json"))
        ok(pm.post(f"{P}/supplements", {"title": "业主自购卫浴到货时间确认", "raisedOn": (today - datetime.timedelta(days=20)).isoformat(),
                                        "dueOn": (today - datetime.timedelta(days=10)).isoformat(), "ownerName": "刘先生"},
                   format="json"))
        ok(owner.post(f"{P}/notices", {"body": "二楼书房 B 的门洞看着比图纸窄，请王工核对一下。"}, format="json"))
        ok(pm.post(f"{P}/notices", {"body": "今天砌墙班组 6 人进场，重点做二楼书房 B 门洞返工。请业主下午到场放行拉结筋检查点。"},
                   format="json"))
        ok(dm.post(f"{P}/notices", {"body": "二楼墙体定位图 V2 已上传（衣帽间隔墙后移 300mm），请业主签认后按新版施工。"}, format="json"))
        for name, amount, d, phases in [("开工预付款", 380400, p.planned_start, ["砌墙"]),
                                        ("砌墙完工款", 126800, today + datetime.timedelta(days=14), ["砌墙"]),
                                        ("水电完工款", 253600, today + datetime.timedelta(days=80), ["水电"])]:
            ok(budget.post(f"{P}/payments", {"name": name, "amount": amount, "plannedOn": d.isoformat(),
                                             "phaseIds": [ph[x].id for x in phases]}, format="json"))
        self.stdout.write(f"演示数据完成：项目 {p.id}，检查点 {Checkpoint.objects.filter(project=p).count()} 个")
