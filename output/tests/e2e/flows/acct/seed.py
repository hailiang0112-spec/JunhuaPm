"""acct（FLOW-01/02/03/14/21）造数：在 seed_demo 基础上全部走真实 HTTP 接口（gunicorn + app_runtime）。

产出 seed.json 供 e2e.py 使用。不含任何 ORM 写入。
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "_lib"))
from api import Client, idem, jpeg, pdf, project_id  # noqa: E402
import requests  # noqa: E402
from api import API  # noqa: E402

admin, owner, pm, dm, qc, budget = (Client(w) for w in ("admin", "owner", "pm", "dm", "qc", "budget"))
PID = project_id(pm)
P = f"/projects/{PID}"


def accept(link, phone, name, password="Jh123456"):
    """被邀请人在邀请页加入（公开接口，未登录）。"""
    token = link.rsplit("/", 1)[-1]
    s = requests.Session()
    s.get(API + "/auth/csrf")
    r = s.post(f"{API}/invitations/{token}/accept", json={"phone": phone, "name": name, "password": password, "password2": password},
               headers={"X-CSRFToken": s.cookies["csrftoken"]})
    assert r.status_code in (200, 201), (phone, r.status_code, r.text)


# —— 新成员：孙工（第二名质检，审核经验条目）、吴工（预算专员，用于登录锁定）、陈女士（业主方成员，改指定代理人）
sun = pm.post(f"{P}/invitations", {"phone": "13800000008", "roles": ["qc"]})
accept(sun["link"], "13800000008", "孙工")
wu = pm.post(f"{P}/invitations", {"phone": "13800000009", "roles": ["budget"]})
accept(wu["link"], "13800000009", "吴工")
chen = owner.post(f"{P}/invitations", {"phone": "13800000010", "roles": ["owner_member"]})
accept(chen["link"], "13800000010", "陈女士")
sunc = Client("13800000008")


def shot(label):
    return qc.upload(f"{P}/files", f"现场照片-{label}.jpg", jpeg(label=label), "image/jpeg")["id"]


def check(cid, conclusion, note=""):
    return qc.post(f"{P}/checkpoints/{cid}/checks", {"conclusion": conclusion, "wasCovered": False, "note": note,
                                                    "photos": [{"fileId": shot(f"CK{cid}-{conclusion}")}]})


# —— 水电 3 个检查点：不一致 → 自动生成问题 → 判定原因 → 复核一致 → 闭环（变为待放行）
cps = {c["code"]: c for c in pm.get(f"{P}/checkpoints")["items"]}
notes = {"CK-006": "线管距门洞边仅 80mm，图纸要求 ≥150mm", "CK-007": "底盒中心距地 330mm，图纸 300mm",
         "CK-008": "打压 30 分钟压降 0.08MPa，超过 0.05MPa"}
closed = {}
for code, note in notes.items():
    cid = cps[code]["id"]
    check(cid, "不一致", note)
    iss = next(i for i in pm.get(f"{P}/issues?status=all&pageSize=50")["items"]
               if i.get("checkpoint") and i["checkpoint"]["code"] == code)
    qc.post(f"{P}/issues/{iss['id']}/cause", {"cause": "施工偏离签认图"})
    pm.post(f"{P}/issues/{iss['id']}/assign", {"countermeasure": f"按签认版水电点位图返工：{note.split('，')[0]}后复核",
                                              "ownerName": "张工", "dueDate": "2026-10-30"}, ok=(200, 201, 400))
    check(cid, "一致", "返工后复核一致")
    pm.post(f"{P}/issues/{iss['id']}/close")
    closed[code] = iss["id"]

# —— 经验库：王工从两条已闭环问题提交，孙工审核为「已验证」「未验证经验」；第三条（CK-008）留给浏览器提交
exp = {}
for code, status in (("CK-006", "已验证"), ("CK-007", "未验证经验")):
    e = qc.post(f"{P}/issues/{closed[code]}/experience", {})
    sunc.post(f"/experience/{e['id']}/review", {"status": status})
    exp[code] = e["id"]

# —— 基线：厨房水电（42）业主退回 → 项目经理「被退回基线」；书房 B 布管（51）留给刘太太签认
bl42 = pm.get(f"{P}/work-items/42/baseline")
owner.post(f"{P}/baselines/{bl42['id']}/return", {"reason": "给水管打压试验需注明保压时间，请补充后重新提交"})
# 再提交一条水电基线，保证业主「待签基线」在刘太太签认后仍有一项
v2 = next(s for s in pm.get(f"{P}/drawing-sets")["items"] if s["name"] == "水电点位图")["currentSignedVersion"]["id"]
qc_id = next(m for m in pm.get(f"{P}/members")["items"] if m["name"] == "王工")
qc_uid = qc_id.get("userId") or qc_id.get("id")
pm.patch(f"{P}/work-items/48", {"drawingVersionId": v2, "cost": 1860, "qcUserId": qc_uid, "plannedFinish": "2026-11-30"})
pm.post(f"{P}/work-items/48/checkpoints", {"point": "书房 A 网络线与强电线管间距 ≥300mm", "isConcealed": True, "x": 0.52, "y": 0.6, "pageNo": 1})
pm.post(f"{P}/work-items/48/baseline/submit")

# —— 变更单：一张被业主驳回（项目经理「被驳回变更单」）
co = pm.post(f"{P}/change-orders", {"title": "一楼客厅东墙砌筑线纠偏，向内移 40mm", "reasonCategory": "施工纠偏",
                                    "content": "一楼客厅东墙放线偏差 40mm，拆除后按签认图向内移 40mm 重砌。",
                                    "workItemIds": [11], "needsNewDrawing": False, "builtBeforeSign": False})
budget.post(f"{P}/change-orders/{co['id']}/price", {"priceDelta": 900, "scheduleDeltaDays": 1, "costBearer": "业主"})
owner.post(f"{P}/change-orders/{co['id']}/reject", {"reason": "放线偏差属于施工方问题，重砌费用应由装修公司承担。"})

# —— 第二个项目「滨江壹号 · 独栋别墅」：项目经理、业主、设计经理加入；水电点位图 V1 签认并被水电工作项引用
tpl = admin.get("/templates")["items"][0]["id"]
p2 = admin.post("/projects", {"name": "滨江壹号 · 独栋别墅", "address": "滨江路 88 号", "plannedStart": "2026-09-01",
                             "plannedHandover": "2027-07-30", "templateId": tpl})
P2 = f"/projects/{p2['id']}"
for phone, role, name in (("13800000004", "pm", "张工"), ("13800000001", "owner", "刘先生"), ("13800000005", "design_manager", "李工")):
    inv = admin.post(f"{P2}/invitations", {"phone": phone, "roles": [role]})
    accept(inv["link"], phone, name)
pm.post(f"{P2}/status", {"status": "施工中"})
ds = dm.post(f"{P2}/drawing-sets", {"name": "水电点位图"})
v = dm.upload(f"{P2}/drawing-sets/{ds['id']}/versions", "滨江壹号一楼水电点位图-V1.pdf", pdf("滨江壹号 · 一楼水电点位图 V1"),
              "application/pdf", extra={"changeNote": "首版（设计交底版）"})
owner.post(f"{P2}/drawing-versions/{v['id']}/sign")
ph2 = {p["name"]: p["id"] for p in pm.get(f"{P2}/structure")["phases"]}
w2 = pm.get(f"{P2}/work-items?phase={ph2['水电']}")["items"][10]
pm.patch(f"{P2}/work-items/{w2['id']}", {"drawingVersionId": v["id"], "plannedFinish": "2026-12-20"})

seed = {"pid": PID, "pid2": p2["id"], "wi2": w2["id"], "wi2Name": w2["name"], "closedIssues": closed, "exp": exp,
        "rejectedCo": co["id"], "pendingBaselineWi": 51}
json.dump(seed, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "seed.json"), "w"), ensure_ascii=False, indent=1)
print("acct 造数完成", seed)
