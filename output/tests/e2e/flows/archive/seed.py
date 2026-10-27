"""archive（FLOW-17 档案 / 18 / 20 / 22）造数：只在 seed_base 之上，全部走真实 HTTP 接口（gunicorn + app_runtime）。

水电工段：水电点位图 V1 签认，4 个工作项基线已签认，共 7 个检查点：2 个已放行、1 个待放行、2 个核对不一致（生成未闭环问题）、2 个未核对
  → 未放行 5、未闭环不一致 2（FLOW-20）。
档案：平面布局图「一楼」3 个文件（其中「一楼厨房深化节点图.pdf」被变更单 BG-001 引用）；装修合同「主合同」1 个文件。
补充事项 2 条、公告栏留言 2 条（业主、项目经理）、付款节点「开工预付款」已付。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "_lib"))
from api import Client, idem, jpeg, pdf, project_id  # noqa: E402

owner, pm, dm, qc, budget = (Client(w) for w in ("owner", "pm", "dm", "qc", "budget"))
PID = project_id(pm)
P = f"/projects/{PID}"
uid = {m["name"]: (m.get("userId") or m.get("id")) for m in pm.get(f"{P}/members")["items"]}
ph = {p["name"]: p["id"] for p in pm.get(f"{P}/structure")["phases"]}
ds = dm.post(f"{P}/drawing-sets", {"name": "水电点位图"})
v1 = dm.upload(f"{P}/drawing-sets/{ds['id']}/versions", "二楼水电点位图-V1.pdf", pdf("君华新城 · 二楼水电点位图 V1"),
               "application/pdf", extra={"changeNote": "首版（设计交底版）"})["id"]
owner.post(f"{P}/drawing-versions/{v1}/sign")
water = [w for w in pm.get(f"{P}/work-items?phase={ph['水电']}")["items"] if w["roomName"] and w["roomName"] != "全楼通用"][:4]
plan = [(0, "线管走向与点位图一致"), (0, "强电底盒高度 300mm"), (1, "给水管打压 0.8MPa 保压 30 分钟"), (1, "排水坡度 ≥2%"),
        (2, "强弱电间距 ≥300mm"), (3, "等电位联结"), (3, "地暖分水器位置")]
cps = []
for i, w in enumerate(water):
    pm.patch(f"{P}/work-items/{w['id']}", {"drawingVersionId": v1, "cost": 1800 + 300 * i, "qcUserId": uid["王工"], "plannedFinish": "2026-11-20"})
    for j, (wi, point) in enumerate(plan):
        if wi == i:
            cps.append(pm.post(f"{P}/work-items/{w['id']}/checkpoints", {"point": point, "isConcealed": True, "x": 0.2 + 0.1 * j, "y": 0.5, "pageNo": 1})["id"])
    rev = pm.post(f"{P}/work-items/{w['id']}/baseline/submit")["revisionId"]
    owner.post(f"{P}/baselines/sign", {"revisionIds": [rev]})


def check(cid, conclusion, note=""):
    f = qc.upload(f"{P}/files", f"水电现场照片-{cid}.jpg", jpeg(label=f"水电检查点 {cid}"), "image/jpeg")["id"]
    qc.post(f"{P}/checkpoints/{cid}/checks", {"conclusion": conclusion, "wasCovered": False, "note": note, "photos": [{"fileId": f}]})


for c in cps[:3]:
    check(c, "一致")
for c in cps[:2]:
    owner.post(f"{P}/checkpoints/{c}/release", headers={"Idempotency-Key": idem()})
check(cps[3], "不一致", "排水坡度实测 1.2%，低于 2%")
check(cps[4], "不一致", "强弱电线管间距 180mm，小于 300mm")

# 档案
lay = {f["name"]: f["id"] for f in pm.get(f"{P}/archive/layout/folders")["items"]}
ct = {f["name"]: f["id"] for f in pm.get(f"{P}/archive/contract/folders")["items"]}
fl1 = "一楼" if "一楼" in lay else next(iter(lay))
up = lambda c, zone, fid, name: c.upload(f"{P}/archive/{zone}/folders/{fid}/files", name, pdf(name.rsplit('.', 1)[0]), "application/pdf")  # noqa: E731
up(dm, "layout", lay[fl1], "一楼平面布局图-V3.pdf")
ref = up(pm, "layout", lay[fl1], "一楼厨房深化节点图.pdf")
up(pm, "layout", lay[fl1], "一楼现场复尺记录.pdf")
up(budget, "contract", ct.get("主合同", next(iter(ct.values()))), "君华新城联排别墅装修工程施工合同.pdf")
kitchen = next(w for w in pm.get(f"{P}/work-items")["items"] if w["floorName"] == "一楼" and w["roomName"] == "厨房")
co = pm.post(f"{P}/change-orders", {"title": "一楼厨房烟道预留位调整", "reasonCategory": "设计深化",
                                    "content": "按厨房深化节点图将烟道包封位置西移 120mm。", "workItemIds": [kitchen["id"]],
                                    "needsNewDrawing": True, "builtBeforeSign": False, "fileIds": [ref["id"]]})
# 补充事项、公告栏、付款节点
s1 = pm.post(f"{P}/supplements", {"title": "业主自购卫浴到货时间确认", "note": "业主自购马桶、浴室柜确认 11 月 20 日前到货。",
                                  "raisedOn": "2026-10-05", "dueOn": "2026-10-15", "ownerName": "刘先生"})
pm.post(f"{P}/supplements/{s1['id']}/status", {"status": "已完成"}, ok=(200, 201))
pm.post(f"{P}/supplements", {"title": "三楼露台加装户外洗手池", "note": "业主要求在三楼露台东北角加装户外洗手池，需预留给排水。",
                             "raisedOn": "2026-10-25", "dueOn": "2026-11-10", "ownerName": "张工"})
owner.post(f"{P}/notices", {"body": "二楼书房 B 的门洞看着比图纸窄，请核对一下。"})
pm.post(f"{P}/notices", {"body": "今天砌墙班组 6 人进场，重点做二楼书房 B 门洞返工。请业主下午到场放行检查点。"})
pay = budget.post(f"{P}/payments", {"name": "开工预付款", "amount": 380400, "plannedOn": "2026-09-19", "phaseIds": [ph["砌墙"]]})
budget.post(f"{P}/payments/{pay["id"]}/mark-paid", {})

seed = {"pid": PID, "phases": ph, "waterCps": cps, "coCode": co["code"], "folder": fl1, "voidTarget": "一楼现场复尺记录.pdf",
        "refFile": "一楼厨房深化节点图.pdf"}
json.dump(seed, open(os.path.join(HERE, "seed.json"), "w"), ensure_ascii=False, indent=1)
print("archive 造数完成", seed)
