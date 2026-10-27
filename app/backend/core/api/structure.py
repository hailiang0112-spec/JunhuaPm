"""项目结构（F03）：楼层、房间、工段的增删改与停用，工作项 CRUD 与基线锁定规则，工段计划编辑与计划留档（F14）。

计算口径（技术方案 §5.1.6）也放在本文件，供总览、工段详情、导入共用，避免各处各算一套：
- 工段进度 = Σ(w×p)÷Σw，保留 1 位小数，没有工作项为 0（AC-F03-05）；状态阈值 0 / 99.95（AC-F03-06）。
"""
import datetime
import secrets
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Count, Max
from django.urls import path
from django.utils import timezone
from rest_framework.response import Response

from core.api.base import ProjectView, d, iso
from core.errors import ApiError, fail, forbidden, validation
from core.models import (AcceptancePhoto, Attendance, Baseline, BaselineRevision, BaselineSignoff, ChangeOrder,
                         Checkpoint, CheckRecord, DrawingSignoff, DrawingVersion, Floor, Issue, PaymentMilestone,
                         Phase, PlanChangeLog, ProjectMemberRole, Room, User, WorkItem, WorkItemAttachment)
from core.services import audit, ledger
from core.services.projects import PHASE_COLORS, apply_rule

HAS_RECORDS = "已有记录，只能停用"
LOCKED_FIELDS = ["drawingVersionId", "description", "acceptanceCriteria", "cost", "qcUserId", "plannedFinish"]
PROGRESS_FIELDS = ["progress", "actualFinish"]


# ---------------------------------------------------------------- 口径

def today():
    """业务「今天」（Asia/Shanghai）。测试中替换本函数固定日期。"""
    return timezone.localdate()


def r1(v):
    """保留 1 位小数（四舍五入，不用银行家舍入）。"""
    if v is None:
        return None
    return float(Decimal(str(v)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def weighted(rows):
    """rows: [(权重, 完成度)]；没有工作项返回 None，由调用方决定显示 0% 还是「无事项」。"""
    sw = sum(w for w, _ in rows)
    return sum(w * p for w, p in rows) / sw if sw else None


def status_of(v):
    if v <= 0:
        return "未开始"
    return "已完成" if v >= 99.95 else "进行中"


def planned_pct(start, end, t):
    """计划基准 =（今天−计划开始）÷（计划结束−计划开始），限制在 0~100。"""
    if t <= start:
        return 0.0
    if t >= end:
        return 100.0
    return (t - start).days / (end - start).days * 100


def parse_date(v):
    if isinstance(v, datetime.date):
        return v
    try:
        return datetime.date.fromisoformat(str(v).strip())
    except (TypeError, ValueError):
        return None


def phase_progress_map(project):
    """{phase_id: 原始加权进度}（只算启用的工作项）。"""
    rows = defaultdict(list)
    for w in WorkItem.objects.filter(project=project, is_disabled=False).values("phase_id", "weight", "progress"):
        rows[w["phase_id"]].append((w["weight"], w["progress"]))
    return {pid: (weighted(r) or 0.0) for pid, r in rows.items()}


# ---------------------------------------------------------------- 关联记录

def item_record_counts(project):
    """{work_item_id: 关联记录数}。关联记录 = 签认、核对、问题、资料，以及检查点、基线修订、变更单这些不可删除的引用。"""
    out = defaultdict(int)
    qsets = [
        (BaselineSignoff.objects.filter(project=project), "revision__baseline__work_item_id"),
        (BaselineRevision.objects.filter(project=project), "baseline__work_item_id"),
        (CheckRecord.objects.filter(project=project), "checkpoint__work_item_id"),
        (Checkpoint.objects.filter(project=project), "work_item_id"),
        (Issue.objects.filter(project=project, work_item__isnull=False), "work_item_id"),
        (WorkItemAttachment.objects.filter(project=project), "work_item_id"),
        (ChangeOrder.work_items.through.objects.filter(changeorder__project=project), "workitem_id"),
    ]
    for qs, key in qsets:
        for row in qs.values(key).annotate(n=Count("pk")):
            out[row[key]] += row["n"]
    return out


def structure_counts(project):
    """楼层 / 房间 / 工段的关联记录数与下级结构数。"""
    items = list(WorkItem.objects.filter(project=project).values("id", "phase_id", "floor_id", "room_id"))
    rec = item_record_counts(project)
    floor_rec, room_rec, phase_rec = defaultdict(int), defaultdict(int), defaultdict(int)
    floor_items, room_items, phase_items = defaultdict(int), defaultdict(int), defaultdict(int)
    for it in items:
        n = rec.get(it["id"], 0)
        phase_rec[it["phase_id"]] += n
        phase_items[it["phase_id"]] += 1
        if it["floor_id"]:
            floor_rec[it["floor_id"]] += n
            floor_items[it["floor_id"]] += 1
        if it["room_id"]:
            room_rec[it["room_id"]] += n
            room_items[it["room_id"]] += 1
    for row in Issue.objects.filter(project=project, work_item__isnull=True).values("phase_id", "floor_id", "room_id"):
        if row["phase_id"]:
            phase_rec[row["phase_id"]] += 1
        if row["floor_id"]:
            floor_rec[row["floor_id"]] += 1
        if row["room_id"]:
            room_rec[row["room_id"]] += 1
    for model in (PlanChangeLog, Attendance, AcceptancePhoto, PaymentMilestone):
        for row in model.objects.filter(project=project).values("phase_id").annotate(n=Count("pk")):
            phase_rec[row["phase_id"]] += row["n"]
    room_count = defaultdict(int)
    for row in Room.objects.filter(project=project).values("floor_id").annotate(n=Count("pk")):
        room_count[row["floor_id"]] = row["n"]
    return {"floor_rec": floor_rec, "room_rec": room_rec, "phase_rec": phase_rec, "floor_items": floor_items,
            "room_items": room_items, "phase_items": phase_items, "room_count": room_count, "item_rec": rec}


# ---------------------------------------------------------------- 工作项序列化

def checkpoint_seals(project, item_ids=None):
    """工作项「检查点」列每行最多 1 个印章（DEC-304）：不得覆盖 > 不一致 > 已放行，无检查点为 None。"""
    qs = Checkpoint.objects.filter(project=project, is_draft=False)
    if item_ids is not None:
        qs = qs.filter(work_item_id__in=list(item_ids))
    by_item = defaultdict(list)
    for cp in qs.values("id", "code", "work_item_id", "is_concealed", "status").order_by("id"):
        by_item[cp["work_item_id"]].append(cp)
    out = {}
    for wid, cps in by_item.items():
        hit = next((c for c in cps if c["is_concealed"] and c["status"] != "已放行"), None)
        if hit:
            out[wid] = {"kind": "stop", "text": "不得覆盖", "checkpointId": hit["id"], "code": hit["code"]}
            continue
        hit = next((c for c in cps if c["status"] in ("不一致", "放行后发现不一致")), None)
        if hit:
            out[wid] = {"kind": "stop", "text": "不一致", "checkpointId": hit["id"], "code": hit["code"]}
            continue
        if all(c["status"] == "已放行" for c in cps):
            out[wid] = {"kind": "pass", "text": "已放行", "checkpointId": cps[0]["id"], "code": cps[0]["code"]}
    return out


def attachment_counts(project):
    return {r["work_item_id"]: r["n"] for r in WorkItemAttachment.objects.filter(project=project)
            .exclude(file__status="voided").values("work_item_id").annotate(n=Count("pk"))}


class ItemContext:
    """一次性取齐工作项列表需要的派生数据，避免逐行查询。"""

    def __init__(self, project, item_ids=None):
        self.floors = {f.id: f for f in Floor.objects.filter(project=project)}
        self.rooms = {r.id: r for r in Room.objects.filter(project=project)}
        self.phases = {p.id: p for p in Phase.objects.filter(project=project)}
        self.seals = checkpoint_seals(project, item_ids)
        self.files = attachment_counts(project)
        self.records = item_record_counts(project)


def wi_dict(wi, ctx):
    fl = ctx.floors.get(wi.floor_id)
    rm = ctx.rooms.get(wi.room_id)
    ph = ctx.phases.get(wi.phase_id)
    baseline = getattr(wi, "baseline", None)
    return {
        "id": wi.id, "name": wi.name, "phaseId": wi.phase_id, "phaseName": ph.name if ph else "",
        "floorId": wi.floor_id, "roomId": wi.room_id,
        "floorName": fl.name if fl else "全楼通用",
        "roomName": rm.name if rm else ("本层通用" if fl else "全楼通用"),
        "description": wi.description, "acceptanceCriteria": wi.acceptance_criteria,
        "cost": str(wi.cost) if wi.cost is not None else None,
        "plannedFinish": d(wi.planned_finish), "actualFinish": d(wi.actual_finish),
        "ownerName": wi.owner_name or "待指派",
        "qcUserId": wi.qc_user_id, "qcUserName": wi.qc_user.name if wi.qc_user_id else None,
        "drawingVersionId": wi.drawing_version_id, "weight": wi.weight, "progress": wi.progress,
        "status": status_of(wi.progress), "isDisabled": wi.is_disabled, "source": wi.source,
        "baselineStatus": baseline.status if baseline else "草稿",
        "checkpointSeal": ctx.seals.get(wi.id), "attachmentCount": ctx.files.get(wi.id, 0),
        "recordCount": ctx.records.get(wi.id, 0),
    }


def items_qs(project):
    return WorkItem.objects.filter(project=project).select_related("baseline", "qc_user").order_by(
        "phase__order_no", "id")


# ---------------------------------------------------------------- 结构总表

def phase_dict(p, prog, counts):
    v = prog.get(p.id, 0.0)
    return {"id": p.id, "code": p.code, "name": p.name, "colorVar": p.color_var, "orderNo": p.order_no,
            "plannedStart": d(p.planned_start), "plannedEnd": d(p.planned_end), "teamLead": p.team_lead,
            "weight": p.weight, "scopeNote": p.scope_note, "isDisabled": p.is_disabled,
            "workItemCount": counts["phase_items"].get(p.id, 0), "progress": r1(v), "status": status_of(v),
            "recordCount": counts["phase_rec"].get(p.id, 0)}


def structure_payload(project):
    counts = structure_counts(project)
    prog = phase_progress_map(project)
    floors = [{"id": f.id, "code": f.code, "name": f.name, "orderNo": f.order_no, "isDisabled": f.is_disabled,
               "roomCount": Room.objects.filter(floor=f, is_disabled=False).count(),
               "recordCount": counts["floor_rec"].get(f.id, 0),
               "childCount": counts["room_count"].get(f.id, 0) + counts["floor_items"].get(f.id, 0)}
              for f in Floor.objects.filter(project=project).order_by("order_no", "id")]
    rooms = [{"id": r.id, "code": r.code, "floorId": r.floor_id, "name": r.name, "orderNo": r.order_no,
              "isDisabled": r.is_disabled, "workItemCount": counts["room_items"].get(r.id, 0),
              "recordCount": counts["room_rec"].get(r.id, 0), "childCount": counts["room_items"].get(r.id, 0)}
             for r in Room.objects.filter(project=project).order_by("floor__order_no", "order_no", "id")]
    phases = [phase_dict(p, prog, counts) for p in Phase.objects.filter(project=project).order_by("order_no", "id")]
    return {"floors": floors, "rooms": rooms, "phases": phases,
            "workItems": {"total": WorkItem.objects.filter(project=project, is_disabled=False).count(),
                          "disabled": WorkItem.objects.filter(project=project, is_disabled=True).count()}}


class Structure(ProjectView):
    def get(self, request, project_id):
        return Response(structure_payload(self.project))


# ---------------------------------------------------------------- 楼层、房间、工段

KIND = {"floor": (Floor, "楼层"), "room": (Room, "房间"), "phase": (Phase, "工段")}


def _name(data, label):
    name = str(data.get("name", "")).strip()
    if not name:
        validation([("name", "请填写名称")])
    if len(name) > 20:
        validation([("name", f"{label}名称不超过 20 个字")])
    return name


def _dup(qs, name, label, exclude_id=None):
    if qs.filter(name=name).exclude(pk=exclude_id).exists():
        validation([("name", f"已存在同名{label}")])


def _code(prefix):
    return prefix + secrets.token_hex(3)


def _blocked(kind, obj, project):
    """有关联记录或下级结构时返回 (记录数, 下级数)；否则 (0, 0)。"""
    c = structure_counts(project)
    if kind == "floor":
        return c["floor_rec"].get(obj.id, 0), c["room_count"].get(obj.id, 0) + c["floor_items"].get(obj.id, 0)
    if kind == "room":
        return c["room_rec"].get(obj.id, 0), c["room_items"].get(obj.id, 0)
    return c["phase_rec"].get(obj.id, 0), c["phase_items"].get(obj.id, 0)


class Floors(ProjectView):
    def get(self, request, project_id):
        return Response({"items": structure_payload(self.project)["floors"]})

    def post(self, request, project_id):
        self.require("structure.edit", "只有项目经理可以修改项目结构")
        name = _name(request.data, "楼层")
        _dup(Floor.objects.filter(project=self.project), name, "楼层")
        order = (Floor.objects.filter(project=self.project).aggregate(m=Max("order_no"))["m"] or 0) + 1
        f = Floor.objects.create(project=self.project, code=_code("f"), name=name, order_no=order)
        audit.log(request.user, "floor.create", "floor", f.id, name, None, {"name": name}, project=self.project)
        return Response({"id": f.id, "name": f.name}, status=201)


class Rooms(ProjectView):
    def get(self, request, project_id):
        return Response({"items": structure_payload(self.project)["rooms"]})

    def post(self, request, project_id):
        self.require("structure.edit", "只有项目经理可以修改项目结构")
        name = _name(request.data, "房间")
        floor = Floor.objects.filter(project=self.project, pk=request.data.get("floorId"), is_disabled=False).first()
        if floor is None:
            validation([("floorId", "请选择所属楼层")])
        _dup(Room.objects.filter(floor=floor), name, "房间")
        order = (Room.objects.filter(floor=floor).aggregate(m=Max("order_no"))["m"] or 0) + 1
        r = Room.objects.create(project=self.project, floor=floor, code=_code("r"), name=name, order_no=order)
        audit.log(request.user, "room.create", "room", r.id, f"{floor.name} · {name}", None,
                  {"name": name, "floor": floor.name}, project=self.project)
        return Response({"id": r.id, "name": r.name, "floorId": floor.id}, status=201)


class Phases(ProjectView):
    def get(self, request, project_id):
        return Response({"items": structure_payload(self.project)["phases"]})

    def post(self, request, project_id):
        self.require("structure.edit", "只有项目经理可以修改项目结构")
        name = _name(request.data, "工段")
        _dup(Phase.objects.filter(project=self.project), name, "工段")
        ps = parse_date(request.data.get("plannedStart")) or self.project.planned_handover
        pe = parse_date(request.data.get("plannedEnd")) or ps
        if ps > pe:
            raise ApiError(400, "VALIDATION_FAILED", "开始日期不能晚于结束日期",
                           fields=[{"field": "plannedStart", "message": "开始日期不能晚于结束日期"}])
        n = Phase.objects.filter(project=self.project).count()
        order = (Phase.objects.filter(project=self.project).aggregate(m=Max("order_no"))["m"] or 0) + 1
        p = Phase.objects.create(project=self.project, code=f"p{n + 1}", name=name, color_var=PHASE_COLORS[n % 6],
                                 order_no=order, planned_start=ps, planned_end=pe, weight=1)
        audit.log(request.user, "phase.create", "phase", p.id, name, None, {"name": name}, project=self.project)
        return Response({"id": p.id, "name": p.name}, status=201)


class StructureItem(ProjectView):
    """改名 / 删除（无记录才可删）/ 停用（不可撤回）。kind ∈ floor / room / phase。"""
    kind = "floor"

    def _get(self, pk):
        model, _ = KIND[self.kind]
        return self.obj(model, pk)

    def patch(self, request, project_id, pk):
        self.require("structure.edit", "只有项目经理可以修改项目结构")
        model, label = KIND[self.kind]
        obj = self._get(pk)
        if obj.is_disabled:
            fail("DISABLED", f"该{label}已停用，不能改名", 409)
        name = _name(request.data, label)
        pool = Room.objects.filter(floor_id=obj.floor_id) if self.kind == "room" else model.objects.filter(project=self.project)
        _dup(pool, name, label, obj.id)
        before = obj.name
        obj.name = name
        obj.save(update_fields=["name"])
        audit.log(request.user, f"{self.kind}.rename", self.kind, obj.id, name, {"name": before}, {"name": name},
                  project=self.project)
        return Response({"id": obj.id, "name": obj.name})

    def delete(self, request, project_id, pk):
        self.require("structure.edit", "只有项目经理可以修改项目结构")
        obj = self._get(pk)
        with transaction.atomic():
            recs, children = _blocked(self.kind, obj, self.project)
            if recs or children:
                fail("HAS_RECORDS_DISABLE_ONLY", HAS_RECORDS, 409, records=recs, children=children)
            label = obj.name
            obj.delete()
            audit.log(request.user, f"{self.kind}.delete", self.kind, pk, label, {"name": label}, None,
                      project=self.project)
        return Response({"ok": True})


class StructureDisable(ProjectView):
    kind = "floor"

    def post(self, request, project_id, pk):
        self.require("structure.edit", "只有项目经理可以修改项目结构")
        model, _ = KIND[self.kind]
        obj = self.obj(model, pk)
        if not obj.is_disabled:
            obj.is_disabled = True
            obj.save(update_fields=["is_disabled"])
            audit.log(request.user, f"{self.kind}.disable", self.kind, obj.id, obj.name, {"isDisabled": False},
                      {"isDisabled": True}, project=self.project)
        return Response({"id": obj.id, "isDisabled": True})


# ---------------------------------------------------------------- 工段计划编辑与留档（F14）

PLAN_FIELDS = [("plannedStart", "planned_start", "计划开始日期"), ("plannedEnd", "planned_end", "计划结束日期"),
               ("teamLead", "team_lead", "班组负责人"), ("weight", "weight", "工段权重"),
               ("scopeNote", "scope_note", "施工范围")]


def _plan_str(v):
    return d(v) if isinstance(v, datetime.date) else ("" if v is None else str(v))


def apply_phase_plan(phase, new, actor, reason, source="manual"):
    """逐字段比对后保存；有变化才追加 1 条 PlanChangeLog 并入链。调用方需在事务内。返回留档或 None。"""
    changes = []
    for key, attr, label in PLAN_FIELDS:
        if key not in new:
            continue
        before, after = getattr(phase, attr), new[key]
        if before != after:
            changes.append({"field": key, "label": label, "before": _plan_str(before), "after": _plan_str(after)})
    if not changes:
        return None
    old_span = (phase.planned_end - phase.planned_start).days
    for key, attr, _ in PLAN_FIELDS:
        if key in new:
            setattr(phase, attr, new[key])
    phase.save()
    delta = None
    if any(c["field"] in ("plannedStart", "plannedEnd") for c in changes):
        delta = (phase.planned_end - phase.planned_start).days - old_span
    log = PlanChangeLog.objects.create(project=phase.project, phase=phase, actor=actor, changes=changes,
                                       duration_delta_days=delta, reason=(reason or "")[:200], source=source)
    ledger.append(phase.project_id, log)
    return log


def plan_log_dict(log, phase_name=None):
    proto_at = next((c.get("originalAt") for c in log.changes if c.get("originalAt")), None)
    return {"id": log.id, "at": iso(log.at), "displayAt": proto_at or timezone.localtime(log.at).strftime("%Y-%m-%d %H:%M"),
            "phaseId": log.phase_id, "phaseName": phase_name if phase_name is not None else log.phase.name,
            "changes": [{k: c.get(k) for k in ("field", "label", "before", "after")} for c in log.changes],
            "durationDeltaDays": log.duration_delta_days, "reason": log.reason, "source": log.source,
            "actorName": log.actor.name if log.actor_id else ""}


class PhasePlan(ProjectView):
    """PATCH …/phases/{id}/plan：起止日期、班组、权重、范围、原因（AC-F14-01 ~ AC-F14-03）。"""

    def patch(self, request, project_id, pk):
        self.require("phase.plan_edit", "只有项目经理可以编辑工段计划")
        data = request.data
        errs, new = [], {}
        ps, pe = parse_date(data.get("plannedStart")), parse_date(data.get("plannedEnd"))
        if not ps:
            errs.append(("plannedStart", "请填写计划开始日期"))
        if not pe:
            errs.append(("plannedEnd", "请填写计划结束日期"))
        if ps and pe and ps > pe:
            errs.append(("plannedStart", "开始日期不能晚于结束日期"))
        new["plannedStart"], new["plannedEnd"] = ps, pe
        if "teamLead" in data:
            new["teamLead"] = str(data.get("teamLead") or "").strip()[:60]
        if "scopeNote" in data:
            new["scopeNote"] = str(data.get("scopeNote") or "").strip()
        if "weight" in data:
            try:
                w = int(str(data.get("weight")).strip())
                if w < 1 or str(w) != str(data.get("weight")).strip():
                    raise ValueError
                new["weight"] = w
            except (TypeError, ValueError):
                errs.append(("weight", "工段权重为正整数"))
        if errs:
            raise ApiError(400, "VALIDATION_FAILED", "；".join(m for _, m in errs),
                           fields=[{"field": f, "message": m} for f, m in errs])
        with transaction.atomic():
            phase = Phase.objects.select_for_update().get(pk=self.obj(Phase, pk).pk)
            before = {k: _plan_str(getattr(phase, a)) for k, a, _ in PLAN_FIELDS}
            log = apply_phase_plan(phase, new, request.user, str(data.get("reason") or "").strip())
            if log:
                audit.log(request.user, "phase.plan", "phase", phase.id, phase.name, before,
                          {k: _plan_str(getattr(phase, a)) for k, a, _ in PLAN_FIELDS}, project=self.project)
        return Response({"changed": log is not None, "log": plan_log_dict(log, phase.name) if log else None,
                         "changeCount": len(log.changes) if log else 0})


# ---------------------------------------------------------------- 工作项（跨模块约定：结构与计划负责）

def _int_in(v, lo, hi):
    try:
        s = str(v).strip()
        n = int(s)
        return n if lo <= n <= hi and s.lstrip("-").isdigit() else None
    except (TypeError, ValueError):
        return None


def parse_item(data, project, current=None):
    """校验工作项字段，返回 {字段: 值}（只含请求里出现的字段）；一次返回全部字段错误。"""
    errs, out = [], {}
    creating = current is None

    def has(k):
        return creating or k in data

    if has("name"):
        name = str(data.get("name") or "").strip()
        if not name:
            errs.append(("name", "请填写工作项名称"))
        elif len(name) > 120:
            errs.append(("name", "工作项名称不超过 120 个字"))
        out["name"] = name
    if has("phaseId"):
        ph = Phase.objects.filter(project=project, pk=data.get("phaseId") or 0).first()
        if ph is None or (ph.is_disabled and (creating or ph.id != current.phase_id)):
            errs.append(("phaseId", "请选择所属工段"))
        out["phase"] = ph
    floor = room = None
    if has("floorId"):
        fid = data.get("floorId")
        if fid in (None, "", "all"):
            out["floor"] = None
        else:
            floor = Floor.objects.filter(project=project, pk=fid).first()
            if floor is None:
                errs.append(("floorId", "请选择楼层"))
            out["floor"] = floor
    if has("roomId"):
        rid = data.get("roomId")
        if rid in (None, "", "all"):
            out["room"] = None
        else:
            room = Room.objects.filter(project=project, pk=rid).first()
            if room is None:
                errs.append(("roomId", "请选择房间"))
            out["room"] = room
    if has("weight"):
        raw = data.get("weight")
        w = 1 if creating and raw in (None, "") else _int_in(raw, 1, 5)
        if w is None:
            errs.append(("weight", "权重为 1–5 的整数"))
        out["weight"] = w
    if has("progress"):
        p = 0 if creating and data.get("progress") in (None, "") else _int_in(data.get("progress"), 0, 100)
        if p is None:
            errs.append(("progress", "完成度为 0–100 的整数"))
        out["progress"] = p
    for key, attr in (("plannedFinish", "planned_finish"), ("actualFinish", "actual_finish")):
        if key in data:
            v = data.get(key)
            if v in (None, ""):
                out[key] = None
            else:
                dv = parse_date(v)
                if dv is None:
                    errs.append((key, "日期格式不正确"))
                out[key] = dv
    if "ownerName" in data:
        out["ownerName"] = str(data.get("ownerName") or "").strip()[:40]
    for key in ("description", "acceptanceCriteria"):
        if key in data:
            out[key] = str(data.get(key) or "").strip()
    if "cost" in data:
        v = data.get("cost")
        if v in (None, ""):
            out["cost"] = None
        else:
            try:
                c = Decimal(str(v)).quantize(Decimal("0.01"))
                if c < 0:
                    raise InvalidOperation
                out["cost"] = c
            except (InvalidOperation, ValueError):
                errs.append(("cost", "费用应为不小于 0 的金额"))
    if "qcUserId" in data:
        v = data.get("qcUserId")
        if v in (None, ""):
            out["qcUserId"] = None
        else:
            if not ProjectMemberRole.objects.filter(project=project, user_id=v, role="qc").exists():
                errs.append(("qcUserId", "质检人须为本项目的质检"))
            out["qcUserId"] = User.objects.filter(pk=v).values_list("pk", flat=True).first()
    if "drawingVersionId" in data:
        v = data.get("drawingVersionId")
        if v in (None, ""):
            out["drawingVersionId"] = None
        else:
            dv = DrawingVersion.objects.filter(project=project, pk=v).first()
            if dv is None:
                errs.append(("drawingVersionId", "图纸版本不存在"))
            elif not DrawingSignoff.objects.filter(version=dv).exists():
                raise ApiError(422, "DRAWING_NOT_SIGNED", "该版本尚未签认",
                               fields=[{"field": "drawingVersionId", "message": "该版本尚未签认"}])
            out["drawingVersionId"] = dv.id if dv else None
    validation(errs)
    # 楼层与房间匹配（AC-F03-04）：按合并后的取值判断
    eff_floor = out["floor"] if "floor" in out else (current.floor if current else None)
    eff_room = out["room"] if "room" in out else (current.room if current else None)
    if eff_room is not None and (eff_floor is None or eff_room.floor_id != eff_floor.id):
        raise ApiError(400, "ROOM_FLOOR_MISMATCH", "房间与楼层不匹配",
                       fields=[{"field": "roomId", "message": "房间与楼层不匹配"}])
    if creating or "floor" in out or "room" in out:
        if eff_floor is not None and eff_floor.is_disabled and (creating or eff_floor.id != current.floor_id):
            validation([("floorId", "该楼层已停用，请重新选择")])
        if eff_room is not None and eff_room.is_disabled and (creating or eff_room.id != current.room_id):
            validation([("roomId", "该房间已停用，请重新选择")])
    return out


ATTR = {"name": "name", "phase": "phase", "floor": "floor", "room": "room", "weight": "weight",
        "progress": "progress", "plannedFinish": "planned_finish", "actualFinish": "actual_finish",
        "ownerName": "owner_name", "description": "description", "acceptanceCriteria": "acceptance_criteria",
        "cost": "cost", "qcUserId": "qc_user_id", "drawingVersionId": "drawing_version_id"}
API_KEY = {"phase": "phaseId", "floor": "floorId", "room": "roomId"}


def _snap(wi):
    return {"name": wi.name, "phaseId": wi.phase_id, "floorId": wi.floor_id, "roomId": wi.room_id,
            "weight": wi.weight, "progress": wi.progress, "plannedFinish": d(wi.planned_finish),
            "actualFinish": d(wi.actual_finish), "ownerName": wi.owner_name, "cost": str(wi.cost) if wi.cost is not None else None,
            "qcUserId": wi.qc_user_id, "drawingVersionId": wi.drawing_version_id}


def changed_fields(wi, vals):
    out = []
    for k, v in vals.items():
        cur = getattr(wi, ATTR[k])
        if k in ("phase", "floor", "room"):
            cur_id = getattr(wi, ATTR[k] + "_id")
            if (v.id if v else None) != cur_id:
                out.append(k)
        elif cur != v:
            out.append(k)
    return out


def create_work_item(project, vals, actor, source="manual"):
    """新建工作项：未填说明或标准时按工序规则补齐（AC-F03-10），同时建草稿基线。调用方需在事务内。"""
    wi = WorkItem(project=project, phase=vals["phase"], floor=vals.get("floor"), room=vals.get("room"),
                  name=vals["name"], description=vals.get("description", ""),
                  acceptance_criteria=vals.get("acceptanceCriteria", ""), cost=vals.get("cost"),
                  planned_finish=vals.get("plannedFinish"), actual_finish=vals.get("actualFinish"),
                  owner_name=vals.get("ownerName") or "待指派", qc_user_id=vals.get("qcUserId"),
                  drawing_version_id=vals.get("drawingVersionId"), weight=vals.get("weight") or 1,
                  progress=vals.get("progress") or 0, source=source)
    apply_rule(wi)
    wi.save()
    Baseline.objects.create(project=project, work_item=wi)
    return wi


class WorkItems(ProjectView):
    def get(self, request, project_id):
        qs = items_qs(self.project)
        g = request.GET
        if g.get("phase"):
            qs = qs.filter(phase_id=g["phase"])
        if g.get("floor"):
            qs = qs.filter(floor__isnull=True) if g["floor"] == "all" else qs.filter(floor_id=g["floor"])
        if g.get("room"):
            qs = qs.filter(room__isnull=True) if g["room"] == "all" else qs.filter(room_id=g["room"])
        if g.get("q"):
            qs = qs.filter(name__contains=g["q"].strip())
        if g.get("includeDisabled") not in ("1", "true"):
            qs = qs.filter(is_disabled=False)
        ctx = ItemContext(self.project)
        return Response({"items": [wi_dict(w, ctx) for w in qs]})

    def post(self, request, project_id):
        self.require("structure.edit", "只有项目经理可以新增工作项")
        vals = parse_item(request.data, self.project)
        with transaction.atomic():
            wi = create_work_item(self.project, vals, request.user)
            audit.log(request.user, "work_item.create", "work_item", wi.id, wi.name, None, _snap(wi),
                      project=self.project)
        wi = items_qs(self.project).get(pk=wi.pk)
        return Response(wi_dict(wi, ItemContext(self.project, [wi.id])), status=201)


class WorkItemDetail(ProjectView):
    def get(self, request, project_id, pk):
        wi = items_qs(self.project).filter(pk=pk).first() or fail("NOT_FOUND", "记录不存在", 404)
        return Response(wi_dict(wi, ItemContext(self.project, [wi.id])))

    def patch(self, request, project_id, pk):
        """基线锁定规则统一在这里执行（AC-F05-06、AC-F05-10）；进度字段任何时候都照常保存。"""
        wi0 = self.obj(WorkItem, pk)
        vals = parse_item(request.data, self.project, current=wi0)
        changed = changed_fields(wi0, vals)
        api_changed = [API_KEY.get(k, k) for k in changed]
        if not changed:
            return Response(wi_dict(items_qs(self.project).get(pk=pk), ItemContext(self.project, [wi0.id])))
        only_cost = set(api_changed) <= {"cost"}
        if not self.can("structure.edit") and not (only_cost and self.can("baseline.edit")):
            forbidden("只有项目经理可以修改工作项" if not only_cost else "无权修改费用")
        if wi0.is_disabled:
            fail("WORK_ITEM_DISABLED", "已停用的工作项不能修改", 409)
        rejected, err = [], None
        with transaction.atomic():
            wi = WorkItem.objects.select_for_update().get(pk=wi0.pk)
            bl = Baseline.objects.select_for_update().filter(work_item=wi).first()
            status = bl.status if bl else "草稿"
            if status == "待签认":
                rejected = [k for k in api_changed if k not in PROGRESS_FIELDS]
                if rejected:
                    err = ApiError(409, "BASELINE_PENDING_SIGN", "基线待业主签认，需业主退回后才能修改")
            elif status in ("已签认", "待重签"):
                rejected = [k for k in api_changed if k in LOCKED_FIELDS]
                if rejected:
                    err = ApiError(409, "BASELINE_LOCKED", "已签认，请发起变更单或等待新版图纸重签")
            before = _snap(wi)
            saved = []
            for k in changed:
                key = API_KEY.get(k, k)
                if key in rejected:
                    continue
                setattr(wi, ATTR[k], vals[k])
                saved.append(key)
            if "ownerName" in saved and not wi.owner_name:
                wi.owner_name = "待指派"
            if saved:
                wi.save()
                audit.log(request.user, "work_item.update", "work_item", wi.id, wi.name, before, _snap(wi),
                          project=self.project)
        if err:
            err.details = {"saved": saved, "rejected": rejected}
            raise err
        return Response(wi_dict(items_qs(self.project).get(pk=pk), ItemContext(self.project, [wi0.id])))

    def delete(self, request, project_id, pk):
        self.require("structure.edit", "只有项目经理可以删除工作项")
        wi = self.obj(WorkItem, pk)
        with transaction.atomic():
            recs = item_record_counts(self.project).get(wi.id, 0)
            if recs:
                fail("HAS_RECORDS_DISABLE_ONLY", HAS_RECORDS, 409, records=recs, children=0)
            snap, name = _snap(wi), wi.name
            Baseline.objects.filter(work_item=wi).delete()
            wi.delete()
            audit.log(request.user, "work_item.delete", "work_item", pk, name, snap, None, project=self.project)
        return Response({"ok": True})


class WorkItemDisable(ProjectView):
    def post(self, request, project_id, pk):
        self.require("structure.edit", "只有项目经理可以停用工作项")
        wi = self.obj(WorkItem, pk)
        if not wi.is_disabled:
            wi.is_disabled = True
            wi.save(update_fields=["is_disabled"])
            audit.log(request.user, "work_item.disable", "work_item", wi.id, wi.name, {"isDisabled": False},
                      {"isDisabled": True}, project=self.project)
        return Response({"id": wi.id, "isDisabled": True})


P = "projects/<int:project_id>/"
urlpatterns = [
    path(P + "structure", Structure.as_view()),
    path(P + "floors", Floors.as_view()),
    path(P + "floors/<int:pk>", StructureItem.as_view(kind="floor")),
    path(P + "floors/<int:pk>/disable", StructureDisable.as_view(kind="floor")),
    path(P + "rooms", Rooms.as_view()),
    path(P + "rooms/<int:pk>", StructureItem.as_view(kind="room")),
    path(P + "rooms/<int:pk>/disable", StructureDisable.as_view(kind="room")),
    path(P + "phases", Phases.as_view()),
    path(P + "phases/<int:pk>", StructureItem.as_view(kind="phase")),
    path(P + "phases/<int:pk>/disable", StructureDisable.as_view(kind="phase")),
    path(P + "phases/<int:pk>/plan", PhasePlan.as_view()),
    path(P + "work-items", WorkItems.as_view()),
    path(P + "work-items/<int:pk>", WorkItemDetail.as_view()),
    path(P + "work-items/<int:pk>/disable", WorkItemDisable.as_view()),
]
