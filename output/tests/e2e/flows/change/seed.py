"""change（FLOW-12/13）造数：只在 seed_base 之上，全部走真实 HTTP 接口（gunicorn + app_runtime）。

图纸：墙体定位图 V1 签认。基线已签认：二楼书房 B 隔墙（带「门洞净宽 900mm」检查点）、一楼厨房 2 项（BG-003 受影响）、一楼餐厅隔墙。
变更单：BG-001 已生效、BG-002 已定价待业主签认（页面中被业主驳回后重提）。
问题：书房 B 门洞核对不一致 → 自动生成问题（照片 2 张）；手工问题 3 条：要求闭环 2026-10-20（超期 7 天）、2026-10-24（超期 3 天）、一条重复登记（供作废）。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "_lib"))
from api import Client, jpeg, pdf, project_id  # noqa: E402

owner, pm, dm, qc, budget = (Client(w) for w in ("owner", "pm", "dm", "qc", "budget"))
PID = project_id(pm)
P = f"/projects/{PID}"
uid = {m["name"]: (m.get("userId") or m.get("id")) for m in pm.get(f"{P}/members")["items"]}
ds = dm.post(f"{P}/drawing-sets", {"name": "墙体定位图"})
v1 = dm.upload(f"{P}/drawing-sets/{ds['id']}/versions", "一二楼墙体定位图-V1.pdf", pdf("君华新城 · 一二楼墙体定位图 V1"),
               "application/pdf", extra={"changeNote": "首版（设计交底版）"})["id"]
owner.post(f"{P}/drawing-versions/{v1}/sign")
ph = {p["name"]: p["id"] for p in pm.get(f"{P}/structure")["phases"]}
items = pm.get(f"{P}/work-items")["items"]
find = lambda fl, rm, kw: next(w for w in items if w["floorName"] == fl and w["roomName"] == rm and kw in w["name"])  # noqa: E731
study = find("二楼", "书房 B", "隔墙")
kitchen = [w for w in items if w["floorName"] == "一楼" and w["roomName"] == "厨房"][:2]
living = find("一楼", "餐厅", "隔墙")
revs, cps = [], {}
for i, (w, point, hid) in enumerate([(study, "门洞净宽 900mm", False), (kitchen[0], "烟道预留位按深化图定位", True),
                                      (kitchen[1], "给水管走向与点位图一致", True), (living, "墙体垂直度", False)]):
    pm.patch(f"{P}/work-items/{w['id']}", {"drawingVersionId": v1, "cost": 2860 + 300 * i, "qcUserId": uid["王工"], "plannedFinish": "2026-11-12"})
    cps[w["id"]] = pm.post(f"{P}/work-items/{w['id']}/checkpoints", {"point": point, "isConcealed": hid, "x": 0.3 + 0.1 * i, "y": 0.4, "pageNo": 1})
    revs.append(pm.post(f"{P}/work-items/{w['id']}/baseline/submit")["revisionId"])
for r in revs:  # 批量签认只能同工段或同楼层，这里逐条签
    owner.post(f"{P}/baselines/sign", {"revisionIds": [r]})

# 变更单 BG-001 已生效、BG-002 待业主签认
a = pm.post(f"{P}/change-orders", {"title": "二楼主卧衣帽间隔墙后移 300mm", "reasonCategory": "业主要求",
                                   "content": "业主要求衣帽间隔墙整体后移 300mm，扩大衣帽间进深；门洞随墙后移，尺寸不变。",
                                   "workItemIds": [study["id"]], "needsNewDrawing": True, "builtBeforeSign": False})
budget.post(f"{P}/change-orders/{a['id']}/price", {"priceDelta": 2600, "scheduleDeltaDays": 2, "costBearer": "业主"})
owner.post(f"{P}/change-orders/{a['id']}/sign")
b = pm.post(f"{P}/change-orders", {"title": "一楼餐厅东墙砌筑线纠偏，向内移 40mm", "reasonCategory": "施工纠偏",
                                   "content": "一楼餐厅东墙放线偏差 40mm，拆除后按签认图向内移 40mm 重砌。",
                                   "workItemIds": [living["id"]], "needsNewDrawing": False, "builtBeforeSign": False})
budget.post(f"{P}/change-orders/{b['id']}/price", {"priceDelta": 900, "scheduleDeltaDays": 1, "costBearer": "业主"})

# 书房 B 门洞核对不一致（2 张照片）→ 自动生成问题
photos = [qc.upload(f"{P}/files", f"书房B门洞-{i + 1}.jpg", jpeg(label=f"门洞净宽 860mm（{i + 1}）"), "image/jpeg")["id"] for i in range(2)]
qc.post(f"{P}/checkpoints/{cps[study['id']]['id']}/checks", {"conclusion": "不一致", "wasCovered": False,
                                                              "note": "门洞净宽 860mm，与图纸 900mm 不符", "photos": [{"fileId": f} for f in photos]})
opts = pm.get(f"{P}/issues/options")
F = {f["name"]: f for f in opts["floors"]}
room = lambda fl, rm: next(r["id"] for r in F[fl]["rooms"] if r["name"] == rm)  # noqa: E731


def manual(desc, level, fl, rm, due, measure="", owner_name=""):
    return pm.post(f"{P}/issues", {"description": desc, "level": level, "phaseId": ph["砌墙"], "floorId": F[fl]["id"], "roomId": room(fl, rm),
                                   "dueDate": due, "countermeasure": measure, "ownerName": owner_name})


o7 = manual("二楼卫生间 A 管道井封堵不严，闭水试验渗漏", "重要", "二楼", "卫生间 A", "2026-10-20", "重新封堵并做闭水试验", "张工")
o3 = manual("一楼餐厅隔墙顶部塞缝不密实", "一般", "一楼", "餐厅", "2026-10-24", "斜砌塞紧后挂网抹灰", "张工")
dup = manual("夹层设备间砌体垂直度偏差（重复登记）", "一般", "夹层", "设备间", "2026-11-03")
seed = {"pid": PID, "studyCp": cps[study["id"]]["id"], "studyCode": cps[study["id"]]["code"], "kitchen": [w["id"] for w in kitchen],
        "kitchenNames": [w["name"] for w in kitchen], "co2": b["id"], "co2Code": b["code"], "overdue7": o7["id"], "overdue3": o3["id"],
        "dup": dup["id"], "dupCode": dup["code"]}
json.dump(seed, open(os.path.join(HERE, "seed.json"), "w"), ensure_ascii=False, indent=1)
print("change 造数完成", seed)
