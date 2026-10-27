"""数据库授权（技术方案 §5.1.3）：app_runtime 对关键记录表只有 SELECT/INSERT。"""
from django.db import migrations


def apply_grants(apps, schema_editor):
    # GRANT / pg_roles exist only on PostgreSQL. SQLite (desktop) has a single
    # local user; skip. Fresh PostgreSQL installs still apply the same SQL.
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(SQL)

KEY_TABLES = [
    "core_drawingversion", "core_drawingsignoff", "core_baselinerevision", "core_baselinesignoff",
    "core_baselineevent", "core_checkrecord", "core_checkphoto", "core_releaserecord", "core_coverevent",
    "core_discoverycorrection", "core_changeorderevent", "core_issueevent", "core_planchangelog",
    "core_ledgerentry", "core_auditlog", "core_experienceversion",
]

SQL = """
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_runtime') THEN
    EXECUTE 'GRANT USAGE ON SCHEMA public TO app_runtime';
    EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_runtime';
    EXECUTE 'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_runtime';
    EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_runtime';
    EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO app_runtime';
    EXECUTE 'REVOKE UPDATE, DELETE, TRUNCATE ON %s FROM app_runtime';
  END IF;
END $$;
""" % ", ".join(KEY_TABLES)


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]
    operations = [migrations.RunPython(apply_grants, migrations.RunPython.noop)]
