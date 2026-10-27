"""操作日志（DATA-F17-02）。密码类字段一律不写（NFR-006）。"""
from core.models import AuditLog

SENSITIVE = {"password", "temp_password", "new_password", "old_password", "token"}


def _clean(d):
    if not isinstance(d, dict):
        return d
    return {k: ("***" if k in SENSITIVE else v) for k, v in d.items()}


def log(actor, action, object_type, object_id="", label="", before=None, after=None, project=None):
    AuditLog.objects.create(project=project, actor=actor if getattr(actor, "pk", None) else None, action=action,
                            object_type=object_type, object_id=str(object_id), object_label=label[:120],
                            before=_clean(before), after=_clean(after))
