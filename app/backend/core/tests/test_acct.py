"""acct 模块验收（TDD 契约 FLOW-01、FLOW-02、FLOW-03、FLOW-14、FLOW-21），API 级。

期望值来自契约与 requirements 的已知业务数据（君华模板 6 层 32 间 6 工段 187 项、7 天、15 分钟等），
不由被测代码推算。签认、放行等动作属于其他模块的接口，这里在数据库层模拟其结果，只验证本模块的派生与权限。
"""
import datetime
import hashlib
import json
import logging

import pytest
from django.conf import settings
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import (AuditLog, Baseline, BaselineEvent, ChangeOrder, ChangeOrderEvent, CheckPhoto, Checkpoint,
                         CheckRecord, CoverEvent, DrawingSet, DrawingVersion, ExperienceEntry, Invitation, Issue,
                         Project, ProjectMemberRole, ReleaseRecord, StoredFile, Template, User, WorkItem)
from core.services.projects import create_from_template

PW = "Jh123456"


def login(phone, password=PW):
    c = APIClient()
    r = c.post("/api/auth/login", {"phone": phone, "password": password}, format="json")
    assert r.status_code == 200, r.json()
    return c


def perms_of(client, pid):
    r = client.get(f"/api/projects/{pid}")
    assert r.status_code == 200, r.json()
    return set(r.json()["permissions"])


def second_project(company, admin, name="滨江壹号 · 独栋别墅"):
    tpl = Template.objects.filter(company=company).first()
    return create_from_template(company, tpl, name, "滨江路 88 号", datetime.date(2026, 10, 1),
                                datetime.date(2027, 9, 30), admin)


# ───────────────────────── FLOW-01 项目、成员、邀请 ─────────────────────────

def test_flow01_create_project_validation_and_template_copy(client_for, company, users):
    admin = client_for("admin")
    before = Project.objects.count()
    r = admin.post("/api/projects", {"name": "", "address": "君华新城 B 区 3 栋", "plannedStart": "2026-11-01",
                                     "plannedHandover": "2026-10-01"}, format="json")
    assert r.status_code == 400
    fields = {f["field"]: f["message"] for f in r.json()["fields"]}
    assert fields["name"] == "请填写项目名称"
    assert fields["plannedHandover"] == "计划交房日期不能早于计划开工日期"
    r = admin.post("/api/projects", {"name": "云栖台 · 合院别墅"}, format="json")
    fields = {f["field"]: f["message"] for f in r.json()["fields"]}
    assert fields["plannedStart"] == "请选择计划开工日期" and fields["plannedHandover"] == "请选择计划交房日期"
    assert Project.objects.count() == before  # 不产生任何项目记录

    tpl = admin.get("/api/templates").json()["items"][0]
    assert tpl["stats"] == {"phases": 6, "floors": 6, "rooms": 32, "workItems": 187, "rules": 71}
    r = admin.post("/api/projects", {"name": "云栖台 · 合院别墅", "address": "云栖路 6 号", "plannedStart": "2026-11-20",
                                     "plannedHandover": "2027-10-30", "templateId": tpl["id"]}, format="json")
    assert r.status_code == 201 and r.json()["status"] == "筹备"
    d = admin.get(f"/api/projects/{r.json()['id']}").json()
    assert d["stats"] == {"floors": 6, "rooms": 32, "phases": 6, "workItems": 187}
    # 工序说明随模板补齐：放线定位命中规则 #1
    wi = WorkItem.objects.get(project_id=d["id"], name="放线定位、材料进场验收")
    assert wi.description.startswith("按图纸在楼地面弹出墙体与门窗洞口线")


def test_flow01_roles_scoped_and_project_list_filtered(client_for, company, users, project):
    admin = client_for("admin")
    other = second_project(company, users["admin"])
    sun = User.objects.create_user(phone="13900000011", name="孙工", password=PW)
    ProjectMemberRole.objects.create(project=project, user=sun, role="owner_member")
    r = admin.put(f"/api/projects/{project.id}/members/{sun.id}/roles", {"roles": ["design_manager", "qc"]}, format="json")
    assert r.status_code == 200
    r = admin.put(f"/api/projects/{project.id}/members/{sun.id}/roles", {"roles": []}, format="json")
    assert r.status_code == 400 and r.json()["fields"][0]["message"] == "请至少保留一个角色；如需移出项目请使用「移除」"
    c = APIClient()
    c.force_authenticate(sun)
    p = perms_of(c, project.id)
    assert {"drawing.upload", "checkpoint.check"} <= p
    assert c.get(f"/api/projects/{other.id}").status_code == 403  # 角色只在项目 A 生效
    assert [x["id"] for x in c.get("/api/projects").json()["items"]] == [project.id]
    ids = {x["id"] for x in admin.get("/api/projects").json()["items"]}
    assert {project.id, other.id} <= ids  # 公司管理员看到全部项目
    m = {x["name"]: x for x in admin.get(f"/api/projects/{project.id}/members").json()["items"]}
    assert m["孙工"]["roleLabels"] == ["设计经理", "质检"] and m["孙工"]["phone"] == "13900000011"
    pm_view = {x["name"]: x for x in client_for("pm").get(f"/api/projects/{project.id}/members").json()["items"]}
    assert pm_view["孙工"]["phone"] == "139****0011"  # 非公司管理员看到打码手机号


def test_flow01_invitations(client_for, users, project):
    pm = client_for("pm")
    r = pm.post(f"/api/projects/{project.id}/invitations", {"phone": "13700000000", "roles": ["admin"]}, format="json")
    assert r.status_code == 403 and r.json()["message"] == "只有公司管理员可以设置该角色"
    assert not Invitation.objects.exists()
    r = client_for("owner").post(f"/api/projects/{project.id}/invitations", {"phone": "13700000000", "roles": ["pm"]}, format="json")
    assert r.status_code == 403 and r.json()["message"] == "业主只能邀请业主方成员"
    r = client_for("owner").post(f"/api/projects/{project.id}/invitations", {"phone": "13700000008", "roles": ["owner_member"]}, format="json")
    assert r.status_code == 201

    r = pm.post(f"/api/projects/{project.id}/invitations", {"phone": "18600002201", "roles": ["qc"]}, format="json")
    assert r.status_code == 201
    link = r.json()["link"]
    token = link.rsplit("/", 1)[1]
    inv = Invitation.objects.get(pk=r.json()["id"])
    assert inv.token_hash == hashlib.sha256(token.encode()).hexdigest()  # 只存哈希
    assert abs((inv.expires_at - inv.created_at) - datetime.timedelta(days=7)) < datetime.timedelta(seconds=1)

    anon = APIClient()
    info = anon.get(f"/api/invitations/{token}").json()
    assert info["phoneMasked"] == "186****2201" and info["roleLabels"] == ["质检"] and info["hasAccount"] is False
    assert info["inviter"] == "张工" and info["inviterRole"] == "项目经理"
    r = anon.post(f"/api/invitations/{token}/accept", {"phone": "18600002202", "name": "周质检", "password": "Zj123456"}, format="json")
    assert r.status_code == 400 and r.json()["fields"][0]["message"] == "手机号与邀请不一致，请使用收到邀请的手机号"
    r = anon.post(f"/api/invitations/{token}/accept", {"phone": "18600002201", "name": "周质检", "password": "Zj123456"}, format="json")
    assert r.status_code == 200 and r.json()["name"] == "周质检"
    u = User.objects.get(phone="18600002201")
    assert u.name == "周质检" and set(ProjectMemberRole.objects.filter(user=u).values_list("role", flat=True)) == {"qc"}
    # 已使用
    r = APIClient().post(f"/api/invitations/{token}/accept", {"phone": "18600002201", "name": "冒名", "password": "Zj123456"}, format="json")
    assert r.status_code == 410 and r.json()["message"] == "邀请已失效，请联系邀请人重新发送"

    # 已有账号：校验原密码后关联，密码不变
    r = pm.post(f"/api/projects/{project.id}/invitations", {"phone": users["budget"].phone, "roles": ["owner_member"]}, format="json")
    token2 = r.json()["link"].rsplit("/", 1)[1]
    info = APIClient().get(f"/api/invitations/{token2}").json()
    assert info["hasAccount"] is True and info["accountName"] == "赵会计"
    r = APIClient().post(f"/api/invitations/{token2}/accept", {"phone": users["budget"].phone, "password": "wrong1234"}, format="json")
    assert r.status_code == 400 and r.json()["fields"][0]["message"] == "原密码不正确"
    r = APIClient().post(f"/api/invitations/{token2}/accept", {"phone": users["budget"].phone, "password": PW}, format="json")
    assert r.status_code == 200
    users["budget"].refresh_from_db()
    assert users["budget"].check_password(PW) and users["budget"].name == "赵会计"
    assert ProjectMemberRole.objects.filter(user=users["budget"], project=project, role="owner_member").exists()

    # 过期与撤销
    r = pm.post(f"/api/projects/{project.id}/invitations", {"phone": "13700000001", "roles": ["budget"]}, format="json")
    t3 = r.json()["link"].rsplit("/", 1)[1]
    Invitation.objects.filter(pk=r.json()["id"]).update(expires_at=timezone.now() - datetime.timedelta(seconds=1))
    assert APIClient().get(f"/api/invitations/{t3}").status_code == 410
    r = pm.post(f"/api/projects/{project.id}/invitations", {"phone": "13700000002", "roles": ["budget"]}, format="json")
    t4, iid = r.json()["link"].rsplit("/", 1)[1], r.json()["id"]
    assert pm.post(f"/api/projects/{project.id}/invitations/{iid}/revoke").json()["state"] == "已撤销"
    r = APIClient().post(f"/api/invitations/{t4}/accept", {"phone": "13700000002", "name": "李四", "password": "Ls123456"}, format="json")
    assert r.status_code == 410 and not User.objects.filter(phone="13700000002").exists()
    states = {x["id"]: x["state"] for x in pm.get(f"/api/projects/{project.id}/invitations").json()["items"]}
    assert states[iid] == "已撤销"


def test_flow01_template_change_does_not_affect_existing(client_for, company, users, project):
    admin = client_for("admin")
    tid = admin.get("/api/admin/templates").json()["items"][0]["id"]
    d = admin.get(f"/api/admin/templates/{tid}").json()
    content = d["content"]
    content["phases"][0]["name"] = "砌墙与二次结构"
    content["phases"][0]["weight"] = 10
    r = admin.put(f"/api/admin/templates/{tid}", {"content": content}, format="json")
    assert r.status_code == 400 and r.json()["fields"][0]["message"] == "工段权重合计为 102%，需为 100%"
    content["phases"][1]["weight"] = 20
    content["phases"][0]["tasks"].append({"name": "夹层设备间隔墙砌筑", "floor": "me", "room": None, "weight": 2,
                                          "checkpoints": [{"point": "", "isConcealed": True}]})
    r = admin.put(f"/api/admin/templates/{tid}", {"content": content}, format="json")
    assert r.status_code == 400 and r.json()["fields"][0]["message"] == "请填写检查要点，或删除空的检查点模板"
    content["phases"][0]["tasks"][-1]["checkpoints"] = [{"point": "拉结筋间距 ≤500mm", "isConcealed": True}]
    r = admin.put(f"/api/admin/templates/{tid}", {"content": content}, format="json")
    assert r.status_code == 200 and r.json()["stats"]["workItems"] == 188
    assert client_for("pm").get(f"/api/admin/templates/{tid}").status_code == 403
    r = admin.post("/api/projects", {"name": "湖畔花园 · 叠拼别墅", "address": "湖畔路 2 号", "plannedStart": "2026-12-01",
                                     "plannedHandover": "2027-11-30", "templateId": tid}, format="json")
    new = admin.get(f"/api/projects/{r.json()['id']}").json()
    assert new["stats"]["workItems"] == 188 and new["phases"][0]["name"] == "砌墙与二次结构"
    old = admin.get(f"/api/projects/{project.id}").json()
    assert old["stats"]["workItems"] == 187 and old["phases"][0]["name"] == "砌墙"


def test_flow01_remove_member_and_project_status(client_for, users, project):
    pm, admin = client_for("pm"), client_for("admin")
    r = pm.post(f"/api/projects/{project.id}/invitations", {"phone": "13700000003", "roles": ["owner_member"]}, format="json")
    inv_id = r.json()["id"]
    # 已交房缺日期被拒
    r = pm.post(f"/api/projects/{project.id}/status", {"status": "已交房"}, format="json")
    assert r.status_code == 400 and r.json()["fields"][0]["message"] == "请填写实际交房日期"
    assert admin.post(f"/api/projects/{project.id}/status", {"status": "已交房", "actualHandover": "2027-08-20"},
                      format="json").status_code == 403  # 状态只由项目经理推进
    r = pm.post(f"/api/projects/{project.id}/status", {"status": "已交房", "actualHandover": "2027-08-20"}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "已交房" and r.json()["actualHandover"] == "2027-08-20"
    assert pm.post(f"/api/projects/{project.id}/status", {"status": "施工中"}, format="json").status_code == 400
    hist = admin.get(f"/api/projects/{project.id}/members").json()["statusHistory"]
    assert hist[-1]["actor"] == "张工" and hist[-1]["after"]["status"] == "已交房"
    # 移除项目经理：下一次请求起无权访问，历史署名不变
    assert pm.get(f"/api/projects/{project.id}").status_code == 200
    assert admin.delete(f"/api/projects/{project.id}/members/{users['pm'].id}").status_code == 200
    r = pm.get(f"/api/projects/{project.id}")
    assert r.status_code == 403 and r.json()["message"] == "无权访问该项目" and "name" not in r.json()
    items = {x["id"]: x for x in admin.get(f"/api/projects/{project.id}/invitations").json()["items"]}
    assert items[inv_id]["createdBy"] == "张工"
    assert AuditLog.objects.filter(action="member.remove", object_id=str(users["pm"].id)).exists()


# ───────────────────────── FLOW-02 代理人、多业主、公司管理员只读 ─────────────────────────

def test_flow02_agent_lifecycle_and_admin_readonly(client_for, users, project):
    owner, owner2 = client_for("owner"), client_for("owner2")
    member = client_for("owner_member")
    pid = project.id
    p = perms_of(member, pid)
    assert "checkpoint.release" not in p and not ({"baseline.sign", "checkpoint.check", "change.price", "file.upload"} & p)
    assert member.post(f"/api/projects/{pid}/agent", {"userId": users["owner_member"].id}, format="json").status_code == 403
    r = owner.post(f"/api/projects/{pid}/agent", {"userId": users["owner2"].id}, format="json")
    assert r.status_code == 400  # 业主本人不能被指定为代理人
    assert owner.post(f"/api/projects/{pid}/agent", {"userId": users["owner_member"].id}, format="json").status_code == 200
    p = perms_of(member, pid)
    assert "checkpoint.release" in p and not ({"baseline.sign", "drawing.sign", "change.sign"} & p)

    # 代理放行记录（由放行模块写入，这里直接落库）
    cp = make_checkpoint(project, users, "待放行", "CK-001", "构造柱钢筋绑扎")
    check = CheckRecord.objects.get(checkpoint=cp)
    rr = ReleaseRecord.objects.create(project=project, checkpoint=cp, releaser=users["owner_member"], is_proxy=True, basis_check=check)

    # 刘太太（另一业主）改指定另一成员
    jian = User.objects.create_user(phone="13900000012", name="钱监理", password=PW)
    ProjectMemberRole.objects.create(project=project, user=jian, role="owner_member")
    r = owner2.post(f"/api/projects/{pid}/agent", {"userId": jian.id}, format="json")
    assert r.status_code == 200 and r.json()["agent"]["name"] == "钱监理"
    assert "checkpoint.release" not in perms_of(member, pid)
    assert ProjectMemberRole.objects.filter(project=project, role="owner_agent").count() == 1
    data = owner.get(f"/api/projects/{pid}/members").json()
    assert data["agent"]["name"] == "钱监理" and data["agent"]["grantedBy"] == "刘太太"
    assert [(h["actor"], h["after"]["agent"]) for h in data["agentHistory"]] == [("刘先生", "钱工"), ("刘太太", "钱监理")]
    # 撤销代理：下一次请求即失去放行权，既有代理放行记录不变
    jc = APIClient()
    jc.force_authenticate(jian)
    assert "checkpoint.release" in perms_of(jc, pid)
    assert owner.delete(f"/api/projects/{pid}/agent").status_code == 200
    assert "checkpoint.release" not in perms_of(jc, pid)
    rr.refresh_from_db()
    assert rr.is_proxy is True and rr.releaser_id == users["owner_member"].id

    # 公司管理员：签认、核对、放行、定价均无权限；成员与邀请管理仍可用
    admin = client_for("admin")
    p = perms_of(admin, pid)
    assert not ({"baseline.sign", "checkpoint.check", "checkpoint.release", "change.price"} & p)
    assert {"member.manage", "invitation.create"} <= p
    assert admin.post(f"/api/projects/{pid}/invitations", {"phone": "13700000004", "roles": ["pm"]}, format="json").status_code == 201
    assert admin.post(f"/api/projects/{pid}/agent", {"userId": jian.id}, format="json").status_code == 403


def test_flow02_second_owner_sign_clears_todo(client_for, users, project):
    """刘太太签认后，刘先生的同项待办消失（签认接口属于基线模块，这里在库里模拟签认结果）。"""
    wi = WorkItem.objects.filter(project=project, name__contains="隔墙砌筑").first()
    Baseline.objects.filter(work_item=wi).update(status="待签认", submitted_at=timezone.now())
    t1 = client_for("owner").get("/api/todos").json()
    t2 = client_for("owner2").get("/api/todos").json()
    assert any(x["kind"] == "baseline_sign" for x in t1["items"]) and any(x["kind"] == "baseline_sign" for x in t2["items"])
    Baseline.objects.filter(work_item=wi).update(status="已签认")
    assert not any(x["kind"] == "baseline_sign" for x in client_for("owner").get("/api/todos").json()["items"])


# ───────────────────────── FLOW-03 登录、锁定、重置密码、改密 ─────────────────────────

def test_flow03_login_session_and_lock(users):
    c = login(users["qc"].phone)
    me = c.get("/api/me").json()
    assert me["name"] == "王工" and me["mustChangePassword"] is False
    assert settings.SESSION_COOKIE_AGE == 7 * 24 * 3600 and settings.SESSION_SAVE_EVERY_REQUEST is True  # 7 天无操作失效
    bad = APIClient()
    for i in range(4):
        r = bad.post("/api/auth/login", {"phone": users["qc"].phone, "password": "Wrong1234"}, format="json")
        assert r.status_code == 400
    r = bad.post("/api/auth/login", {"phone": users["qc"].phone, "password": "Wrong1234"}, format="json")
    assert r.status_code == 423 and r.json()["details"]["remainingSeconds"] == 15 * 60
    r = bad.post("/api/auth/login", {"phone": users["qc"].phone, "password": PW}, format="json")
    assert r.status_code == 423


def test_flow03_reset_password_and_change(client_for, users, project, caplog):
    caplog.set_level(logging.DEBUG)
    admin = client_for("admin")
    assert client_for("pm").post(f"/api/admin/users/{users['qc'].id}/reset-password").status_code == 403
    r = admin.post(f"/api/admin/users/{users['qc'].id}/reset-password")
    assert r.status_code == 200 and r["Cache-Control"] == "no-store"
    temp = r.json()["tempPassword"]
    # 临时密码不出现在操作日志与应用日志
    dumped = json.dumps(list(AuditLog.objects.values("object_label", "before", "after")), ensure_ascii=False)
    assert temp not in dumped and temp not in caplog.text
    assert AuditLog.objects.filter(action="password.reset", object_id=str(users["qc"].id)).exists()

    c = login(users["qc"].phone, temp)
    assert c.get("/api/me").json()["mustChangePassword"] is True
    r = c.get("/api/projects")
    assert r.status_code == 403 and r.json()["code"] == "PASSWORD_CHANGE_REQUIRED"
    r = c.post("/api/me/password", {"newPassword": "abc"}, format="json")
    assert r.status_code == 400 and r.json()["fields"][0]["message"] == "密码至少 8 位，且必须同时包含字母和数字"
    assert c.post("/api/me/password", {"newPassword": "Wg2026new"}, format="json").status_code == 200
    assert c.get("/api/projects").status_code == 200

    # 两台设备：一台改密后另一台会话失效，本设备保持登录
    a, b = login(users["qc"].phone, "Wg2026new"), login(users["qc"].phone, "Wg2026new")
    r = a.post("/api/me/password", {"oldPassword": "错的密码1", "newPassword": "Wg2026xyz"}, format="json")
    assert r.status_code == 400 and r.json()["fields"][0] == {"field": "oldPassword", "message": "原密码不正确"}
    assert a.post("/api/me/password", {"oldPassword": "Wg2026new", "newPassword": "Wg2026xyz"}, format="json").status_code == 200
    assert a.get("/api/me").status_code == 200
    assert b.get("/api/me").status_code in (401, 403)


# ───────────────────────── 测试数据工具 ─────────────────────────

def drawing(project, user, name="平面布置图", no=1, signed=False):
    sf = StoredFile.objects.create(project=project, storage_key=f"x/{name}{no}.pdf", sha256="0" * 64, size=1,
                                   mime="application/pdf", original_name=f"{name}V{no}.pdf")
    ds = DrawingSet.objects.filter(project=project, name=name).first() or DrawingSet.objects.create(project=project, name=name)
    v = DrawingVersion.objects.create(project=project, drawing_set=ds, version_no=no, file=sf, change_note="首版",
                                      affected_work_item_ids=[1, 2, 3], created_by=user)
    return v


def make_checkpoint(project, users, status, code, point, wi=None, since_hours=0):
    wi = wi or WorkItem.objects.filter(project=project, room__isnull=False).first()
    dv = DrawingVersion.objects.filter(project=project).first() or drawing(project, users["design_manager"])
    cp = Checkpoint.objects.create(project=project, work_item=wi, code=code, point=point, is_concealed=True,
                                   drawing_version=dv, x=0.5, y=0.5, status=status, created_by=users["pm"])
    if status in ("待放行", "不一致", "已放行"):
        chk = CheckRecord.objects.create(project=project, checkpoint=cp, checker=users["qc"], drawing_version=dv,
                                         was_latest_signed=True, conclusion="一致" if status != "不一致" else "不一致",
                                         was_covered=False, note="")
        cp.latest_check = chk
        cp.awaiting_release_since = timezone.now() - datetime.timedelta(hours=since_hours)
        cp.save()
    return cp


def change_order(project, users, seq, status, title, **kw):
    return ChangeOrder.objects.create(project=project, seq_no=seq, title=title, status=status, created_by=users["pm"],
                                      reason_category="业主要求", content=title, **kw)


# ───────────────────────── FLOW-14 经验库 ─────────────────────────

def closed_issue(project, users):
    wi = WorkItem.objects.filter(project=project, phase__name="水电", room__isnull=False).first()
    cp = make_checkpoint(project, users, "不一致", "CK-031", "给水管打压试验", wi=wi)
    check = CheckRecord.objects.get(checkpoint=cp)
    sf = StoredFile.objects.create(project=project, storage_key="x/p.jpg", sha256="1" * 64, size=1, mime="image/jpeg",
                                   original_name="现场.jpg")
    CheckPhoto.objects.create(project=project, check_record=check, file=sf, file_sha256=sf.sha256, pin_x=0.1, pin_y=0.1)
    return Issue.objects.create(project=project, seq_no=1, source_check=check, checkpoint=cp, work_item=wi, phase=wi.phase,
                                floor=wi.floor, room=wi.room, description="刘先生发现打压不足",
                                countermeasure="刘先生要求在君华新城 A 区 12 栋复压，打压 0.6MPa 保压 30 分钟",
                                found_on=datetime.date(2026, 10, 20), cause="施工偏离签认图", status="已闭环",
                                created_by=users["qc"], source="check")


def test_flow14_experience_submit_review_revise_suggest(client_for, company, users, project):
    issue = closed_issue(project, users)
    qc = client_for("qc")
    open_issue = Issue.objects.create(project=project, seq_no=2, description="未闭环", found_on=datetime.date(2026, 10, 21),
                                      status="未闭环", phase=issue.phase)
    assert qc.post(f"/api/projects/{project.id}/issues/{open_issue.id}/experience", {}, format="json").status_code == 422
    assert client_for("pm").post(f"/api/projects/{project.id}/issues/{issue.id}/experience", {}, format="json").status_code == 403

    r = qc.post(f"/api/projects/{project.id}/issues/{issue.id}/experience",
                {"process": "给水管打压", "checkPoint": "封槽前打压 0.6MPa 保压 30 分钟，压降 ≤0.05MPa"}, format="json")
    assert r.status_code == 201
    e = r.json()
    assert e["status"] == "待审核" and e["phaseName"] == "水电" and e["issueType"] == "施工偏离签认图"
    assert e["photoCount"] == 0
    text = json.dumps(e, ensure_ascii=False)
    assert "刘先生" not in text and "君华新城 A 区 12 栋" not in text and "13900000001" not in text
    v1 = ExperienceEntry.objects.get(pk=e["id"]).current_version
    stored = f"{v1.process}{v1.issue_type}{v1.check_point}{v1.countermeasure}"
    assert "刘先生" not in stored and "君华新城" not in stored and v1.photo_file_ids == []
    assert qc.post(f"/api/projects/{project.id}/issues/{issue.id}/experience", {}, format="json").status_code == 409

    # 审核前对其他项目成员不可见
    other = second_project(company, users["admin"])
    sun = User.objects.create_user(phone="13900000011", name="孙工", password=PW)
    ProjectMemberRole.objects.create(project=other, user=sun, role="qc")
    pm2 = User.objects.create_user(phone="13900000013", name="陈经理", password=PW)
    ProjectMemberRole.objects.create(project=other, user=pm2, role="pm")
    c_pm2, c_sun = APIClient(), APIClient()
    c_pm2.force_authenticate(pm2)
    c_sun.force_authenticate(sun)
    assert c_pm2.get("/api/experience").json()["total"] == 0
    assert c_pm2.get("/api/experience?tab=pending").status_code == 403
    pend = c_sun.get("/api/experience?tab=pending").json()
    assert pend["total"] == 1 and pend["items"][0]["submitter"] == "王工"

    # 另一名质检审核为「历史观察」
    assert c_pm2.post(f"/api/experience/{e['id']}/review", {"status": "历史观察"}, format="json").status_code == 403
    assert c_sun.post(f"/api/experience/{e['id']}/review", {}, format="json").status_code == 400
    r = c_sun.post(f"/api/experience/{e['id']}/review", {"status": "历史观察"}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "历史观察" and r.json()["reviewer"] == "孙工" and r.json()["reviewedAt"]
    r = qc.post(f"/api/experience/{e['id']}/review", {"status": "已验证"}, format="json")
    assert r.status_code == 409 and r.json()["message"] == "该条目已由 孙工 审核"
    lst = c_pm2.get("/api/experience").json()
    assert lst["total"] == 1 and lst["items"][0]["status"] == "历史观察"

    # 修改生成新版本，旧版本可查
    r = c_sun.post(f"/api/experience/{e['id']}/versions", {"process": "给水管打压", "issueType": "施工偏离签认图",
                                                          "checkPoint": "封槽前打压 0.6MPa 保压 30 分钟", "countermeasure": "整改后复压并留照片",
                                                          "status": "历史观察"}, format="json")
    assert r.status_code == 400 and r.json()["fields"][0]["message"] == "请填写修改说明"
    r = c_sun.post(f"/api/experience/{e['id']}/versions", {"process": "给水管打压", "issueType": "施工偏离签认图",
                                                          "checkPoint": "封槽前打压 0.6MPa 保压 30 分钟", "countermeasure": "整改后复压并留照片",
                                                          "status": "已验证", "changeNote": "滨江壹号复核有效"}, format="json")
    assert r.status_code == 200 and r.json()["verNo"] == 3 and r.json()["status"] == "已验证"
    vs = c_pm2.get(f"/api/experience/{e['id']}/versions").json()["items"]
    assert [v["verNo"] for v in vs] == [3, 2, 1]
    assert vs[2]["checkPoint"] == "封槽前打压 0.6MPa 保压 30 分钟，压降 ≤0.05MPa" and vs[1]["status"] == "历史观察"

    # 推荐：另一项目的项目经理为水电工段新建检查点时，按已验证、历史观察、未验证经验排序
    def reviewed(status, process, phase="水电"):
        ent = ExperienceEntry.objects.create(company=company, status="待审核", submitter=users["qc"])
        from core.models import ExperienceVersion
        v = ExperienceVersion.objects.create(entry=ent, ver_no=1, phase_name=phase, process=process, issue_type="图纸本身未表达清楚",
                                             check_point=f"{process}检查要点", countermeasure="对策", status="待审核", author=users["qc"])
        ent.current_version = v
        ent.save()
        c_sun.post(f"/api/experience/{ent.id}/review", {"status": status}, format="json")
    reviewed("未验证经验", "强电线管敷设")
    reviewed("历史观察", "弱电箱定位")
    reviewed("已验证", "门洞砌筑", phase="砌墙")
    pending = ExperienceEntry.objects.create(company=company, status="待审核", submitter=users["qc"])
    from core.models import ExperienceVersion
    pending.current_version = ExperienceVersion.objects.create(entry=pending, ver_no=1, phase_name="水电", process="待审条目",
                                                               issue_type="x", check_point="x", countermeasure="x",
                                                               status="待审核", author=users["qc"])
    pending.save()
    phase_id = other.phases.get(name="水电").id
    s = c_pm2.get(f"/api/projects/{other.id}/experience/suggestions?phaseId={phase_id}").json()
    assert [(x["process"], x["status"]) for x in s["items"]] == [
        ("给水管打压", "已验证"), ("弱电箱定位", "历史观察"), ("强电线管敷设", "未验证经验")]
    assert s["items"][0]["checkPoint"] == "封槽前打压 0.6MPa 保压 30 分钟"
    assert c_pm2.get(f"/api/projects/{project.id}/experience/suggestions?phaseId={phase_id}").status_code == 403


# ───────────────────────── FLOW-21 我的待办 ─────────────────────────

@pytest.fixture
def todo_world(project, users):
    now = timezone.now()
    owner_member = users["owner_member"]
    ProjectMemberRole.objects.create(project=project, user=owner_member, role="owner_agent")
    rooms = list(WorkItem.objects.filter(project=project, room__isnull=False).order_by("id"))
    w = {}
    w["overdue"] = make_checkpoint(project, users, "待放行", "CK-018", "隔墙拉结筋", wi=rooms[0], since_hours=42)
    w["pending"] = make_checkpoint(project, users, "待放行", "CK-024", "构造柱钢筋绑扎", wi=rooms[1], since_hours=2)
    covered = make_checkpoint(project, users, "未核对", "CK-027", "圈梁钢筋", wi=rooms[2])
    covered.unreleased_cover, covered.covered_at = True, now
    covered.save()
    CoverEvent.objects.create(project=project, checkpoint=covered, source="pm_mark", recorder=users["pm"], was_unreleased=True)
    w["uncheck"] = make_checkpoint(project, users, "未核对", "CK-035", "隔墙拉结筋", wi=rooms[3])
    Baseline.objects.filter(work_item=rooms[4]).update(status="待签认", submitted_at=now)
    rooms[5].planned_finish = timezone.localdate() + datetime.timedelta(days=6)
    rooms[5].save()
    Baseline.objects.filter(work_item=rooms[6]).update(status="已退回", return_reason="烟道位置等变更单签认后再签")
    signed_baseline = Baseline.objects.get(work_item=rooms[7])
    signed_baseline.status = "已签认"
    signed_baseline.save()
    cp48 = make_checkpoint(project, users, "未核对", "CK-048", "插座底盒标高", wi=rooms[7])
    w["notify"] = BaselineEvent.objects.create(project=project, baseline=signed_baseline, kind="checkpoint_added",
                                               checkpoint=cp48, actor=users["pm"])
    drawing(project, users["design_manager"], "水电点位图", 3)
    co3 = change_order(project, users, 3, "待业主签认", "一楼厨房烟道预留位偏移 120mm", price_delta=1800, cost_bearer="设计方")
    ChangeOrderEvent.objects.create(project=project, change_order=co3, round_no=1, kind="priced", actor=users["budget"])
    change_order(project, users, 4, "待预算定价", "负一楼保姆间增设一道隔墙")
    co2 = change_order(project, users, 2, "已驳回", "二楼卫生间 A 加设壁龛", reject_reason="费用偏高，请重新报价")
    ChangeOrderEvent.objects.create(project=project, change_order=co2, round_no=1, kind="rejected", actor=users["owner"])
    change_order(project, users, 1, "已生效", "一楼客厅门洞加宽至 1200mm", needs_new_drawing=True)
    return w


def types_of(client):
    data = client.get("/api/todos").json()
    count = client.get("/api/todos/count").json()
    assert count["total"] == data["total"] == len(data["items"])  # 导航总数与列表一致
    return data, {x["type"] for x in data["items"]}


def test_flow21_todos_by_role(client_for, users, project, todo_world):
    data, types = types_of(client_for("owner"))
    assert types == {"待放行检查点", "未放行先覆盖", "待签基线", "即将施工，基线未签认", "待签图纸", "待签变更单", "新增检查点（知会）"}
    first = data["items"][0]
    assert first["sealText"] == "超时" and first["urgent"] and first["title"].startswith("CK-018")
    assert "已超时 18 小时（放行时限 24 小时）" in first["due"] and first["projectName"] == project.name
    assert first["who"] == "刘先生（业主）、刘太太（业主）、钱工（代理人）"
    assert first["path"] == f"/p/{project.id}/checkpoints/{todo_world['overdue'].id}"
    assert data["items"][1]["type"] == "未放行先覆盖" and data["items"][1]["who"] == "记录人：张工（项目经理）"
    assert data["urgent"] == 2
    change = next(x for x in data["items"] if x["type"] == "待签变更单")
    assert change["title"] == "BG-003 一楼厨房烟道预留位偏移 120mm · +1,800 元 · 设计方承担"
    assert change["due"].startswith("赵会计 ") and change["due"].endswith(" 定价")
    for x in data["items"]:  # 复制微信消息所需字段：项目名、事项、负责人、截止或超时、直达路径
        assert x["projectName"] and x["title"] and x["who"] and x["msgDue"] and x["path"].startswith(f"/p/{project.id}/")

    _, types = types_of(client_for("owner_member"))  # 被指定为代理人
    assert types == {"待放行检查点"}
    _, types = types_of(client_for("qc"))
    assert types == {"待核对检查点"}
    _, types = types_of(client_for("budget"))
    assert types == {"待预算定价变更单"}
    _, types = types_of(client_for("design_manager"))
    assert types == {"待出新版图纸"}
    data, types = types_of(client_for("pm"))
    assert types == {"待放行检查点", "被退回基线", "被驳回变更单", "即将施工，基线未签认"}
    assert [x["sealText"] for x in data["items"] if x["type"] == "待放行检查点"] == ["超时"]  # 项目经理只看超时
    data, _ = types_of(client_for("admin"))
    assert data["total"] == 0 and len(data["sites"]) >= 1  # 公司管理员没有业务待办，但看到工地


def test_flow21_release_and_ack_clear_todos(client_for, users, project, todo_world):
    owner, owner2 = client_for("owner"), client_for("owner2")
    before = owner.get("/api/todos/count").json()
    # 放行（放行接口属于检查点模块，这里在库里写入放行结果）
    cp = todo_world["pending"]
    ReleaseRecord.objects.create(project=project, checkpoint=cp, releaser=users["owner"], is_proxy=False, basis_check=cp.latest_check)
    Checkpoint.objects.filter(pk=cp.pk).update(status="已放行", released_at=timezone.now())
    after = owner.get("/api/todos/count").json()
    assert after["total"] == before["total"] - 1 and after["checkpoints"] == before["checkpoints"] - 1
    assert not any(x["objectId"] == cp.id and x["kind"] == "release" for x in owner2.get("/api/todos").json()["items"])

    ev = todo_world["notify"]
    assert client_for("pm").post("/api/todos/ack", {"kind": "checkpoint_added", "objectId": ev.id}, format="json").status_code == 404
    r = owner.post("/api/todos/ack", {"kind": "checkpoint_added", "objectId": ev.id}, format="json")
    assert r.status_code == 200
    assert owner.post("/api/todos/ack", {"kind": "checkpoint_added", "objectId": ev.id}, format="json").status_code == 200
    assert owner.get("/api/todos/count").json()["total"] == after["total"] - 1
    assert any(x["kind"] == "checkpoint_added" for x in owner2.get("/api/todos").json()["items"])  # 各自确认
