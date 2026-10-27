"""迁移后自检（技术方案 §5.1.3）：运行账号对关键记录表不得有 UPDATE / DELETE / TRUNCATE，否则部署失败。"""
from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = "检查 app_runtime 对关键记录表的授权"

    def handle(self, *args, **opts):
        tables = sorted({m._meta.db_table for m in apps.get_app_config("core").get_models() if getattr(m, "KEY_RECORD", False)}
                        | {"core_ledgerentry", "core_auditlog", "core_experienceversion"})
        with connection.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname = 'app_runtime'")
            if not cur.fetchone():
                raise CommandError("数据库中没有 app_runtime 账号")
            cur.execute("""SELECT table_name, privilege_type FROM information_schema.role_table_grants
                           WHERE grantee = 'app_runtime' AND table_name = ANY(%s)
                           AND privilege_type IN ('UPDATE', 'DELETE', 'TRUNCATE')""", [tables])
            bad = cur.fetchall()
        if bad:
            raise CommandError(f"运行账号对关键记录表仍有改删权限：{bad}")
        self.stdout.write(f"授权自检通过：{len(tables)} 张关键记录表仅 SELECT/INSERT")
