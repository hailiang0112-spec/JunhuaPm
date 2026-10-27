"""F01 / F02 基础验证。"""
from rest_framework.test import APIClient


def test_login_lock_and_me(users):
    c = APIClient()
    for _ in range(4):
        r = c.post("/api/auth/login", {"phone": "13900000001", "password": "wrong1234"}, format="json")
        assert r.status_code == 400 and r.json()["message"] == "手机号或密码错误"
    r = c.post("/api/auth/login", {"phone": "13900000001", "password": "wrong1234"}, format="json")
    assert r.status_code == 423 and r.json()["details"]["remainingSeconds"] == 900
    r = c.post("/api/auth/login", {"phone": "13900000001", "password": "Jh123456"}, format="json")
    assert r.status_code == 423  # 锁定期内正确密码也拒绝


def test_project_create_from_template(client_for, company, users):
    admin = client_for("admin")
    r = admin.post("/api/projects", {"name": "", "plannedStart": "2026-09-19", "plannedHandover": "2026-09-01"}, format="json")
    assert r.status_code == 400
    fields = {f["field"] for f in r.json()["fields"]}
    assert {"name", "address", "plannedHandover", "templateId"} <= fields
    tpl = admin.get("/api/templates").json()["items"][0]["id"]
    r = admin.post("/api/projects", {"name": "测试工地", "address": "测试路 1 号", "plannedStart": "2026-09-19",
                                     "plannedHandover": "2027-08-30", "templateId": tpl}, format="json")
    assert r.status_code == 201 and r.json()["status"] == "筹备"
    d = admin.get(f"/api/projects/{r.json()['id']}").json()
    assert d["stats"] == {"floors": 6, "rooms": 32, "phases": 6, "workItems": 187}


def test_isolation_and_roles(client_for, project):
    r = client_for("outsider").get(f"/api/projects/{project.id}")
    assert r.status_code == 403 and r.json()["code"] == "PROJECT_FORBIDDEN" and "name" not in r.json()
    r = client_for("pm").post(f"/api/projects/{project.id}/invitations", {"phone": "13700000000", "roles": ["admin"]}, format="json")
    assert r.status_code == 403 and r.json()["message"] == "只有公司管理员可以设置该角色"
    r = client_for("owner").post(f"/api/projects/{project.id}/invitations", {"phone": "13700000000", "roles": ["pm"]}, format="json")
    assert r.status_code == 403 and r.json()["message"] == "业主只能邀请业主方成员"
