"""摘要链（技术方案 §5.1.3，DATA-F17-01）。

hash = SHA-256(content_bytes ‖ prev_hash_hex)。每个项目一条链，用事务级 advisory lock 串行化。
content 为规范化 JSON：键按字典序、无多余空白、时间为 UTC ISO 8601 微秒、Decimal 为字符串。
"""
import datetime
import decimal
import hashlib
import json

from django.db import connection, transaction

from core.models import LedgerEntry

GENESIS = "0" * 64
CANON = "canon_v1"


def _norm(v):
    if isinstance(v, datetime.datetime):
        return v.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if isinstance(v, datetime.date):
        return v.isoformat()
    if isinstance(v, decimal.Decimal):
        return str(v)
    if isinstance(v, dict):
        return {k: _norm(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_norm(x) for x in v]
    return v


def canonical(record_type, fields):
    return json.dumps({"canon": CANON, "type": record_type, "fields": _norm(fields)},
                      ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(content, prev_hash):
    return hashlib.sha256(content.encode("utf-8") + prev_hash.encode("ascii")).hexdigest()


def record_fields(obj):
    """取模型实例的具体字段（外键取 *_id），作为入链内容。"""
    out = {}
    for f in obj._meta.concrete_fields:
        out[f.attname] = getattr(obj, f.attname)
    return out


def _lock_chain(project_id):
    """Serialize appends for one project.

    PostgreSQL uses a transaction advisory lock (the deploy path). SQLite has no
    advisory locks; an UPDATE takes the database reserved lock for the rest of
    this transaction so two desktop threads cannot mint the same seq. The unique
    (project, seq) constraint is the backstop.
    """
    if connection.vendor == "postgresql":
        with connection.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s, %s)", [7301, project_id])
        return
    from core.models import Project

    table = Project._meta.db_table
    with connection.cursor() as cur:
        cur.execute(f'UPDATE "{table}" SET "id" = "id" WHERE "id" = %s', [project_id])


def append(project_id, obj, extra=None):
    """在当前事务内把关键记录写入摘要链。调用方必须已在 transaction.atomic() 中保存 obj。"""
    assert transaction.get_connection().in_atomic_block, "ledger.append 必须在事务内调用"
    record_type = obj._meta.db_table
    fields = record_fields(obj)
    if extra:
        fields.update(extra)
    _lock_chain(project_id)
    last = LedgerEntry.objects.filter(project_id=project_id).order_by("-seq").first()
    prev = last.hash if last else GENESIS
    seq = (last.seq + 1) if last else 1
    content = canonical(record_type, fields)
    return LedgerEntry.objects.create(project_id=project_id, seq=seq, record_type=record_type, record_id=obj.pk,
                                      content=content, prev_hash=prev, hash=digest(content, prev))


def verify(project_id, current_records=True):
    """逐条重算摘要链；同时与当前库内关键记录内容比对，发现事后篡改。

    返回 {"ok": bool, "count": n, "tail": hash, "first_bad": {seq, record_type, record_id, created_at} | None}
    """
    from django.apps import apps

    prev = GENESIS
    count = 0
    models_by_table = {m._meta.db_table: m for m in apps.get_app_config("core").get_models()}
    for e in LedgerEntry.objects.filter(project_id=project_id).order_by("seq").iterator():
        count += 1
        bad = e.prev_hash != prev or digest(e.content, e.prev_hash) != e.hash
        if not bad and current_records:
            model = models_by_table.get(e.record_type)
            obj = model.objects.filter(pk=e.record_id).first() if model else None
            if obj is None:
                bad = True
            else:
                stored = json.loads(e.content)["fields"]
                now = json.loads(canonical(e.record_type, record_fields(obj)))["fields"]
                bad = any(stored[k] != v for k, v in now.items() if k in stored)
        if bad:
            return {"ok": False, "count": count, "tail": prev,
                    "first_bad": {"seq": e.seq, "record_type": e.record_type, "record_id": e.record_id,
                                  "created_at": e.created_at.isoformat()}}
        prev = e.hash
    return {"ok": True, "count": count, "tail": prev, "first_bad": None}
