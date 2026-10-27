"""测试夹具：公司、8 个角色账号、从君华模板创建的项目；client_for(角色) 返回已登录的 API 客户端。"""
import datetime

import pytest
from rest_framework.test import APIClient

from core.models import ProjectMemberRole, User
from core.services.projects import create_from_template, default_company, ensure_company_template

PW = "Jh123456"
ROLE_USERS = {
    "admin": ("13900000000", "周经理"), "owner": ("13900000001", "刘先生"), "owner2": ("13900000002", "刘太太"),
    "owner_member": ("13900000003", "钱工"), "pm": ("13900000004", "张工"), "design_manager": ("13900000005", "李工"),
    "qc": ("13900000006", "王工"), "budget": ("13900000007", "赵会计"), "outsider": ("13900000009", "外人"),
}


@pytest.fixture
def company(db):
    c = default_company()
    ensure_company_template(c)
    return c


@pytest.fixture
def users(db):
    out = {}
    for key, (phone, name) in ROLE_USERS.items():
        out[key] = User.objects.create_user(phone=phone, name=name, password=PW, is_company_admin=(key == "admin"))
    return out


@pytest.fixture
def project(company, users):
    from core.models import Template
    tpl = Template.objects.filter(company=company).first()
    p = create_from_template(company, tpl, "君华新城 · 联排别墅", "君华新城 A 区 12 栋", datetime.date(2026, 9, 19),
                             datetime.date(2027, 8, 30), users["admin"])
    p.status = "施工中"
    p.save()
    for key, u in users.items():
        role = {"owner2": "owner"}.get(key, key)
        if role in ProjectMemberRole.ROLES:
            ProjectMemberRole.objects.create(project=p, user=u, role=role)
    return p


@pytest.fixture
def client_for(users):
    def make(key):
        c = APIClient()
        c.force_authenticate(users[key])
        return c
    return make
