"""check（FLOW-09/10/11）造数：只在 seed_base 之上，全部走真实 HTTP 接口（gunicorn + app_runtime）。

项目 1：墙体定位图 V1 签认；8 个砌墙工作项基线已签认，各带 1 个检查点：
  门洞（非隐蔽，核对不一致）、拉结筋（隐蔽，一致待放行）、构造柱（隐蔽，未核对）、防潮层（隐蔽，一致待放行 → 超时，见 advance_time.py）、
  圈梁（隐蔽，一致待放行，供项目经理标记已覆盖）、管道井（隐蔽，未核对，供核对不一致·覆盖前）、斜砌（隐蔽，未核对，供「已变更」）、垂直度（非隐蔽，供新建检查点）。
  业主指定钱工为放行代理人。
项目 2「湖畔花园 · 叠拼别墅」：计划交房 2026-10-20（已过），1 个已签认基线检查点供「交房后」核对。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "_lib"))
import requests  # noqa: E402
from api import API, Client, jpeg, pdf, project_id  # noqa: E402

admin, owner, pm, dm, qc = (Client(w) for w in ("admin", "owner", "pm", "dm", "qc"))
PID = project_id(pm)


def setup(P, wanted):
    uid = {m["name"]: (m.get("userId") or m.get("id")) for m in pm.get(f"{P}/members")["items"]}
    ds = dm.post(f"{P}/drawing-sets", {"name": "墙体定位图"})
    v1 = dm.upload(f"{P}/drawing-sets/{ds['id']}/versions", "二楼墙体定位图-V1.pdf", pdf("君华新城 · 二楼墙体定位图 V1"),
                   "application/pdf", extra={"changeNote": "首版（设计交底版）"})
    owner.post(f"{P}/drawing-versions/{v1['id']}/sign")
    ph = {p["name"]: p["id"] for p in pm.get(f"{P}/structure")["phases"]}
    brick = [w for w in pm.get(f"{P}/work-items?phase={ph['砌墙']}")["items"] if w["roomName"] and w["roomName"] != "全楼通用"]
    out, revs = {}, []
    for i, (key, point, hid) in enumerate(wanted):
        w = brick[i]
        pm.patch(f"{P}/work-items/{w['id']}", {"drawingVersionId": v1["id"], "cost": 2400 + 200 * i, "qcUserId": uid["王工"],
                                              "plannedFinish": "2026-11-10"})
        cp = pm.post(f"{P}/work-items/{w['id']}/checkpoints", {"point": point, "isConcealed": hid, "x": 0.2 + 0.07 * i, "y": 0.3 + 0.05 * i, "pageNo": 1})
        revs.append(pm.post(f"{P}/work-items/{w['id']}/baseline/submit")["revisionId"])
        out[key] = {"cp": cp["id"], "code": cp["code"], "wid": w["id"], "wname": w["name"], "point": point}
    owner.post(f"{P}/baselines/sign", {"revisionIds": revs})
    return out, ph


def check(P, cid, conclusion, note=""):
    f = qc.upload(f"{P}/files", f"现场照片-{cid}.jpg", jpeg(label=f"检查点 {cid}"), "image/jpeg")["id"]
    return qc.post(f"{P}/checkpoints/{cid}/checks", {"conclusion": conclusion, "wasCovered": False, "note": note, "photos": [{"fileId": f}]})


P = f"/projects/{PID}"
cps, ph = setup(P, [("door", "门洞净宽 900mm", False), ("tie", "拉结筋间距与伸入长度", True), ("column", "构造柱钢筋绑扎", True),
                    ("damp", "隔墙底部防潮层", True), ("ring", "圈梁钢筋", True), ("shaft", "管道井封堵与闭水", True),
                    ("top", "砌体顶部斜砌塞紧", True), ("plumb", "墙体垂直度", False)])
check(P, cps["door"]["cp"], "不一致", "实测净宽 860mm，比图纸窄 40mm")
for k in ("tie", "damp", "ring"):
    check(P, cps[k]["cp"], "一致")
owner.post(f"{P}/agent", {"userId": next(m.get("userId") or m.get("id") for m in pm.get(f"{P}/members")["items"] if m["name"] == "钱工")})


def accept(link, phone):
    s = requests.Session()
    s.get(API + "/auth/csrf")
    r = s.post(f"{API}/invitations/{link.rsplit('/', 1)[-1]}/accept", json={"phone": phone, "password": "Jh123456"},
               headers={"X-CSRFToken": s.cookies["csrftoken"]})
    assert r.status_code in (200, 201), r.text


tpl = admin.get("/templates")["items"][0]["id"]
p2 = admin.post("/projects", {"name": "湖畔花园 · 叠拼别墅", "address": "湖畔路 2 号", "plannedStart": "2025-10-20",
                             "plannedHandover": "2026-10-20", "templateId": tpl})
P2 = f"/projects/{p2['id']}"
for phone, role in (("13800000004", "pm"), ("13800000001", "owner"), ("13800000005", "design_manager"), ("13800000006", "qc")):
    accept(admin.post(f"{P2}/invitations", {"phone": phone, "roles": [role]})["link"], phone)
pm.post(f"{P2}/status", {"status": "施工中"})
cps2, _ = setup(P2, [("late", "交房后返修：门洞净宽 900mm", False)])

seed = {"pid": PID, "pid2": p2["id"], "cps": cps, "late": cps2["late"], "brickPhase": ph["砌墙"]}
json.dump(seed, open(os.path.join(HERE, "seed.json"), "w"), ensure_ascii=False, indent=1)
print("check 造数完成", {k: (v["code"], v["cp"]) for k, v in cps.items()}, "项目 2", p2["id"])
