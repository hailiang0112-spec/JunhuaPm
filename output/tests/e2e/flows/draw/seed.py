"""draw（FLOW-06/07/08、FLOW-17 资料部分）造数：只在 seed_base 之上，全部走真实 HTTP 接口（gunicorn + app_runtime）。

图纸：4 个分册 V1 由业主签认；墙体定位图 V2 已上传待签认（FLOW-07「该版本尚未签认」）。水电点位图 V2 由浏览器上传（FLOW-06）。
基线：水电 3 项已签认（含新建的「二楼书房 B 墙内线管预埋」）；砌墙 4 项供项目经理在页面提交（2 项完整、1 项缺费用与质检人、1 项用于选择未签认版本）；
     水电 1 项已提交待签（业主退回用）；1 项计划完成 = 今天 +5 且基线未签认（即将施工）。
资料：书房 B 线管预埋工作项上 1 张照片已被核对记录引用（FLOW-17 作废被拒）。
"""
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "_lib"))
from api import Client, jpeg, pdf, project_id  # noqa: E402

admin, owner, pm, dm, qc = (Client(w) for w in ("admin", "owner", "pm", "dm", "qc"))
PID = project_id(pm)
P = f"/projects/{PID}"
FX = os.path.join(HERE, "fixtures")
uid = {m["name"]: (m.get("userId") or m.get("id")) for m in pm.get(f"{P}/members")["items"]}
s = pm.get(f"{P}/structure")
ph = {p["name"]: p["id"] for p in s["phases"]}
fl = {f["name"]: f["id"] for f in s["floors"]}
rm = {(r["floorId"], r["name"]): r["id"] for r in s["rooms"]}
today = datetime.date(2026, 10, 27)

sets, v1 = {}, {}
for name in ("平面布置图", "墙体定位图", "水电点位图", "吊顶及灯位图"):
    sets[name] = dm.post(f"{P}/drawing-sets", {"name": name})["id"]
    data = open(os.path.join(FX, "二楼水电点位图-V1.pdf"), "rb").read() if name == "水电点位图" else pdf(f"君华新城 · 二楼{name} V1")
    v = dm.upload(f"{P}/drawing-sets/{sets[name]}/versions", f"二楼{name}-V1.pdf", data, "application/pdf",
                  extra={"changeNote": "首版（设计交底版）"})
    owner.post(f"{P}/drawing-versions/{v['id']}/sign")
    v1[name] = v["id"]
wall_v2 = dm.upload(f"{P}/drawing-sets/{sets['墙体定位图']}/versions", "二楼墙体定位图-V2.pdf", pdf("君华新城 · 二楼墙体定位图 V2"),
                    "application/pdf", extra={"changeNote": "二楼主卧衣帽间隔墙后移 300mm"})["id"]

water = pm.get(f"{P}/work-items?phase={ph['水电']}")["items"]
brick = pm.get(f"{P}/work-items?phase={ph['砌墙']}")["items"]
by = lambda items, n: next(w for w in items if w["name"] == n)  # noqa: E731
sb = pm.post(f"{P}/work-items", {"name": "二楼书房 B 墙内线管预埋", "phaseId": ph["水电"], "floorId": fl["二楼"],
                                 "roomId": rm[(fl["二楼"], "书房 B")], "weight": 2, "progress": 30, "ownerName": "赵师傅",
                                 "description": "随砌筑在东墙与南墙预埋 PVC 线管及 4 个插座底盒（含变更新增的 2 个）。",
                                 "acceptanceCriteria": "管中距门洞边 ≥150mm；底盒中心距地 300mm，偏差 ±5mm；线管走向与水电点位图一致。"})


def baseline(w, dv, cost, finish, cks, submit=True):
    pm.patch(f"{P}/work-items/{w['id']}", {"drawingVersionId": dv, "cost": cost, "qcUserId": uid["王工"], "plannedFinish": finish})
    made = [pm.post(f"{P}/work-items/{w['id']}/checkpoints", {"point": t, "isConcealed": h, "x": x, "y": y, "pageNo": 1})
            for t, h, x, y in cks]
    rev = pm.post(f"{P}/work-items/{w['id']}/baseline/submit")["revisionId"] if submit else None
    return rev, made


signed_items = [sb, by(water, "二楼书房 A 强弱电布管穿线"), by(water, "一楼厨房强弱电、燃气报警与给排水")]
revs, sb_cps = [], []
for i, w in enumerate(signed_items):
    cks = [("墙内线管预埋走向", True, 0.86, 0.80), ("强电底盒高度 300mm", True, 0.89, 0.86)] if i == 0 else [("线管走向与点位图一致", True, 0.3 + 0.2 * i, 0.4)]
    r, made = baseline(w, v1["水电点位图"], 1280 + 600 * i, "2026-11-20", cks)
    revs.append(r)
    if i == 0:
        sb_cps = made
owner.post(f"{P}/baselines/sign", {"revisionIds": revs})
# 水电 1 项已提交待签（业主退回用）
ret_item = by(water, "一楼客厅强弱电与音响线预埋")
baseline(ret_item, v1["水电点位图"], 2730, "2026-11-22", [("强弱电间距 ≥300mm", True, 0.5, 0.5)])
# 即将施工（今天 +5）且基线未签认
up_item = by(water, "夹层储藏室 1 照明与插座")
pm.patch(f"{P}/work-items/{up_item['id']}", {"plannedFinish": (today + datetime.timedelta(days=5)).isoformat()})

# 砌墙 4 项（页面提交）：两项完整、一项缺费用与质检人、一项选未签认版本
roomed = [w for w in brick if w["roomName"] and w["roomName"] != "全楼通用" and w["floorName"] in ("二楼", "三楼")]
full = roomed[:2]
for i, w in enumerate(full):
    baseline(w, v1["墙体定位图"], 4980 + 1000 * i, "2026-11-12", [("拉结筋间距与伸入长度", True, 0.3, 0.3 + 0.1 * i)], submit=False)
miss = roomed[2]
pm.patch(f"{P}/work-items/{miss['id']}", {"drawingVersionId": v1["墙体定位图"], "plannedFinish": "2026-11-14"})
pm.post(f"{P}/work-items/{miss['id']}/checkpoints", {"point": "门洞位置与净宽", "isConcealed": False, "x": 0.6, "y": 0.4, "pageNo": 1})
pend_pick = roomed[3]
pm.patch(f"{P}/work-items/{pend_pick['id']}", {"drawingVersionId": v1["墙体定位图"]})
pm.post(f"{P}/work-items/{pend_pick['id']}/checkpoints", {"point": "墙体垂直度", "isConcealed": False, "x": 0.7, "y": 0.5, "pageNo": 1})

# 资料：质检上传照片到书房 B 工作项，并在核对记录中引用
att = qc.upload(f"{P}/work-items/{sb['id']}/attachments", "线管走向-核对照片.jpg", jpeg(label="线管走向"), "image/jpeg")
fid = att.get("id") if "attachmentId" not in att else att["id"]
qc.post(f"{P}/checkpoints/{sb_cps[0]['id']}/checks", {"conclusion": "一致", "wasCovered": False, "note": "",
                                                       "photos": [{"fileId": fid}]})

seed = {"pid": PID, "sets": sets, "v1": v1, "wallV2": wall_v2, "studyB": sb["id"], "studyBCps": [c["id"] for c in sb_cps],
        "signedItems": [w["id"] for w in signed_items], "signedNames": [w["name"] for w in signed_items],
        "returnItem": ret_item["name"], "upcomingItem": up_item["name"],
        "full": [w["id"] for w in full], "fullNames": [w["name"] for w in full], "miss": miss["id"], "pendPick": pend_pick["id"],
        "waterIds": [w["id"] for w in water] + [sb["id"]], "refPhoto": "线管走向-核对照片.jpg", "brickPhase": ph["砌墙"]}
json.dump(seed, open(os.path.join(HERE, "seed.json"), "w"), ensure_ascii=False, indent=1)
print("draw 造数完成", {k: seed[k] for k in ("studyB", "signedNames", "fullNames", "miss", "pendPick")})
