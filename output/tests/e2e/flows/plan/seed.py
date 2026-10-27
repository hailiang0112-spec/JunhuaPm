"""plan（FLOW-04/05/15/16/19/23）造数：只在 seed_base 之上，全部走真实 HTTP 接口（gunicorn + app_runtime）。

项目 1「君华新城 · 联排别墅」按 FLOW-15 的已知数据构造证据链：
  不一致 10 条（覆盖前 7）；隐蔽检查点已放行或已覆盖 8 个（合规 6）；核对记录 20 条（用当时最新签认版 18）；已生效变更单 4 张（后补 1）。
  砌墙全部工作项完成度 100，水电前 5 项 40；水电 10-21 3 人、10-22 4 人；砌墙一条基线已签认（FLOW-05 用）。
项目 2「湖畔花园 · 叠拼别墅」（筹备）：砌墙只保留 3 项，权重 2/2/1、完成度 100/50/0（FLOW-04）。
项目 3「云栖台 · 合院别墅」（筹备）：原型 JSON 导入目标（FLOW-23）。
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "_lib"))
import requests  # noqa: E402
from api import API, Client, idem, jpeg, pdf, project_id  # noqa: E402

admin, owner, pm, dm, qc, budget = (Client(w) for w in ("admin", "owner", "pm", "dm", "qc", "budget"))
PID = project_id(pm)
P = f"/projects/{PID}"
uid = {m["name"]: (m.get("userId") or m.get("id")) for m in pm.get(f"{P}/members")["items"]}
ph = {p["name"]: p for p in pm.get(f"{P}/structure")["phases"]}
brick = pm.get(f"{P}/work-items?phase={ph['砌墙']['id']}")["items"]
water = pm.get(f"{P}/work-items?phase={ph['水电']['id']}")["items"]
roomed = [w for w in brick if w["roomName"] and w["roomName"] != "全楼通用"]

# —— 图纸：墙体定位图 V1 签认
ds = dm.post(f"{P}/drawing-sets", {"name": "墙体定位图"})
v1 = dm.upload(f"{P}/drawing-sets/{ds['id']}/versions", "二楼墙体定位图-V1.pdf", pdf("君华新城 · 二楼墙体定位图 V1"),
               "application/pdf", extra={"changeNote": "首版（设计交底版）"})
owner.post(f"{P}/drawing-versions/{v1['id']}/sign")

study_b = next(w for w in roomed if w["floorName"] == "二楼" and w["roomName"] == "书房 B")
used = [study_b] + [w for w in roomed if w["id"] != study_b["id"]][:9]
# 基线草稿上的检查点是草稿（不计入指标）：先为所用工作项提交并签认基线，之后新建的检查点直接生效
revs = []
for i, w in enumerate(used):
    pm.patch(f"{P}/work-items/{w['id']}", {"drawingVersionId": v1["id"], "qcUserId": uid["王工"], "cost": 2000 + 100 * i,
                                          "plannedFinish": "2026-10-20"})
    pm.post(f"{P}/work-items/{w['id']}/checkpoints", {"point": "隔墙位置与墙体定位图一致", "isConcealed": False,
                                                     "x": 0.5, "y": 0.5, "pageNo": 1})
    revs.append(pm.post(f"{P}/work-items/{w['id']}/baseline/submit")["revisionId"])
owner.post(f"{P}/baselines/sign", {"revisionIds": revs})


def cp(w, point, concealed, k):
    return pm.post(f"{P}/work-items/{w['id']}/checkpoints", {"point": point, "isConcealed": concealed,
                                                            "x": 0.1 + 0.08 * (k % 10), "y": 0.2 + 0.06 * (k % 8), "pageNo": 1})["id"]


def check(cid, conclusion, covered=False, note=""):
    f = qc.upload(f"{P}/files", f"现场照片-{cid}.jpg", jpeg(label=f"检查点 {cid}"), "image/jpeg")["id"]
    return qc.post(f"{P}/checkpoints/{cid}/checks", {"conclusion": conclusion, "wasCovered": covered, "note": note,
                                                    "photos": [{"fileId": f}]})


k = 0
# 不一致 10 条：7 条覆盖前（未覆盖），3 条覆盖后（核对时已覆盖）
for i in range(10):
    w = used[i % len(used)]
    c = cp(w, f"门洞净宽与墙体定位图一致（第 {i + 1} 处）", False, k); k += 1
    check(c, "不一致", covered=i >= 7, note=f"实测净宽 {860 + i}mm，图纸 900mm")
# 隐蔽 8 个：6 个核对一致后业主放行（合规），2 个核对一致后未放行即被项目经理标记已覆盖（不合规）
conc = []
for i in range(8):
    c = cp(used[i % len(used)], f"拉结筋间距与伸入长度（第 {i + 1} 处）", True, k); k += 1
    check(c, "一致")
    conc.append(c)
for c in conc[:6]:
    owner.post(f"{P}/checkpoints/{c}/release", headers={"Idempotency-Key": idem()})
for c in conc[6:]:
    pm.post(f"{P}/checkpoints/{c}/cover")
# 再建 2 个检查点（基线仍引用 V1），墙体定位图 V2 签认后再核对 → 未用当时最新签认版
late = [cp(used[i], f"墙体垂直度（第 {i + 1} 处）", False, k + i) for i in range(2)]
v2 = dm.upload(f"{P}/drawing-sets/{ds['id']}/versions", "二楼墙体定位图-V2.pdf", pdf("君华新城 · 二楼墙体定位图 V2"),
               "application/pdf", extra={"changeNote": "二楼主卧衣帽间隔墙后移 300mm"})
owner.post(f"{P}/drawing-versions/{v2['id']}/sign")
for c in late:
    check(c, "一致")

# —— 已生效变更单 4 张，其中 1 张后补
cos = [("二楼书房 B 门洞加宽至 1000mm", False), ("一楼厨房烟道包封西移 120mm", False),
       ("二楼主卧衣帽间隔墙后移 300mm", False), ("负一楼车库储物架墙体加固", True)]
for i, (title, late_flag) in enumerate(cos):
    co = pm.post(f"{P}/change-orders", {"title": title, "reasonCategory": "业主要求", "content": f"{title}，按变更单施工。",
                                        "workItemIds": [used[i]["id"]], "needsNewDrawing": False, "builtBeforeSign": late_flag})
    budget.post(f"{P}/change-orders/{co['id']}/price", {"priceDelta": 1200 + 300 * i, "scheduleDeltaDays": 1, "costBearer": "业主"})
    owner.post(f"{P}/change-orders/{co['id']}/sign")

# —— 进度：砌墙全部 100，水电前 5 项 40
for w in brick:
    pm.patch(f"{P}/work-items/{w['id']}", {"progress": 100, "actualFinish": "2026-10-15"})
for w in water[:5]:
    pm.patch(f"{P}/work-items/{w['id']}", {"progress": 40})
# —— 出勤：水电 10-21 3 人、10-22 4 人（日历按工段求和用）
for day, n in (("2026-10-21", 3), ("2026-10-22", 4)):
    pm.put(f"{P}/phases/{ph['水电']['id']}/attendance/{day}", {"headcount": n})
# —— FLOW-05：砌墙一条基线已签认（导入时不得修改）
signed = next(w for w in roomed if w["id"] not in {x["id"] for x in used})
pm.patch(f"{P}/work-items/{signed['id']}", {"drawingVersionId": v2["id"], "cost": 3260, "qcUserId": uid["王工"],
                                            "plannedFinish": "2026-11-05", "description": "按墙体定位图 V2 新砌 120mm 轻质砖隔墙",
                                            "acceptanceCriteria": "垂直度偏差 ≤5mm；灰缝饱满度 ≥80%"})
cp(signed, "隔墙位置与墙体定位图 V2 一致", False, 40)
rev = pm.post(f"{P}/work-items/{signed['id']}/baseline/submit")
owner.post(f"{P}/baselines/sign", {"revisionIds": [rev["revisionId"]]})


def accept(link, phone):
    s = requests.Session()
    s.get(API + "/auth/csrf")
    r = s.post(f"{API}/invitations/{link.rsplit('/', 1)[-1]}/accept", json={"phone": phone, "password": "Jh123456"},
               headers={"X-CSRFToken": s.cookies["csrftoken"]})
    assert r.status_code in (200, 201), r.text


tpl = admin.get("/templates")["items"][0]["id"]
extra = {}
for name, addr in (("湖畔花园 · 叠拼别墅", "湖畔路 2 号"), ("云栖台 · 合院别墅", "云栖路 6 号")):
    p = admin.post("/projects", {"name": name, "address": addr, "plannedStart": "2026-09-19", "plannedHandover": "2027-08-30",
                                 "templateId": tpl})
    inv = admin.post(f"/projects/{p['id']}/invitations", {"phone": "13800000004", "roles": ["pm"]})
    accept(inv["link"], "13800000004")
    extra[name] = p["id"]
# 项目 2：砌墙只留 3 项（权重 2/2/1、完成度 100/50/0）
P2 = f"/projects/{extra['湖畔花园 · 叠拼别墅']}"
ph2 = {p["name"]: p["id"] for p in pm.get(f"{P2}/structure")["phases"]}
b2 = pm.get(f"{P2}/work-items?phase={ph2['砌墙']}")["items"]
keep = [w for w in b2 if w["roomName"] and w["roomName"] != "全楼通用"][:3]
for w in b2:
    if w["id"] not in {x["id"] for x in keep}:
        pm.delete(f"{P2}/work-items/{w['id']}")
for w, (wt, pg) in zip(keep, ((2, 100), (2, 50), (1, 0))):
    pm.patch(f"{P2}/work-items/{w['id']}", {"weight": wt, "progress": pg})

seed = {"pid": PID, "pidFlow04": extra["湖畔花园 · 叠拼别墅"], "pidImport": extra["云栖台 · 合院别墅"],
        "studyB": study_b["id"], "signedItem": signed["id"], "signedItemName": signed["name"],
        "phases": {k: v["id"] for k, v in ph.items()}, "weights": {k: v["weight"] for k, v in ph.items()},
        "brickIds": [w["id"] for w in brick], "waterIds": [w["id"] for w in water], "flow04Items": [w["name"] for w in keep]}
json.dump(seed, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "seed.json"), "w"), ensure_ascii=False, indent=1)
print("plan 造数完成", {k: v for k, v in seed.items() if k not in ("brickIds", "waterIds")})
