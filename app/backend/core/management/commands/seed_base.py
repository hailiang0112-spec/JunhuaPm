"""基础种子：公司、8 个演示账号、君华模板与「君华新城 · 联排别墅」项目（施工中）。可重复执行。"""
import datetime

from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Project, ProjectMemberRole, User
from core.services.projects import create_from_template, default_company, ensure_company_template

PASSWORD = "Jh123456"
USERS = [
    ("13800000000", "周经理", None, True),
    ("13800000001", "刘先生", "owner", False),
    ("13800000002", "刘太太", "owner", False),
    ("13800000003", "钱工", "owner_member", False),
    ("13800000004", "张工", "pm", False),
    ("13800000005", "李工", "design_manager", False),
    ("13800000006", "王工", "qc", False),
    ("13800000007", "赵会计", "budget", False),
]


class Command(BaseCommand):
    help = "创建基础演示数据"

    @transaction.atomic
    def handle(self, *args, **opts):
        company = default_company()
        tpl = ensure_company_template(company)
        users = {}
        for phone, name, role, admin in USERS:
            u = User.objects.filter(phone=phone).first() or User.objects.create_user(phone=phone, name=name, password=PASSWORD, is_company_admin=admin)
            users[phone] = (u, role)
        project = Project.objects.filter(name="君华新城 · 联排别墅").first()
        if project is None:
            project = create_from_template(company, tpl, "君华新城 · 联排别墅", "君华新城 A 区 12 栋（建面 386㎡）",
                                           datetime.date(2026, 9, 19), datetime.date(2027, 8, 30), users["13800000000"][0])
            project.status = "施工中"
            project.save()
        for u, role in users.values():
            if role:
                ProjectMemberRole.objects.get_or_create(project=project, user=u, role=role)
        self.stdout.write(f"项目 {project.id}「{project.name}」：工作项 {project.work_items.count()}，房间 {project.rooms.count()}")
