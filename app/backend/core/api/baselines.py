"""基线提交 / 签认 / 退回 / 重签、工作项详情聚合、工作项资料（API-F05-01、API-F05-02、API-F12-02 资料部分）。

状态迁移（技术方案 §5.1.5）：草稿 / 已退回 / 待重签 →(提交，字段齐全)→ 待签认 →(签认)→ 已签认 / →(退回)→ 已退回。
修订、签认、事件都是关键记录，写入后在同一事务里入链。
"""
import datetime
import decimal

from django.db import transaction
from django.db.models import Max, Q
from django.urls import path
from django.utils import timezone
from rest_framework.response import Response

from core.api.base import ProjectView, d, iso
from core.api.drawings import version_brief, version_label
from core.errors import ApiError, fail, forbidden
from core.models import (Baseline, BaselineEvent, BaselineRevision, BaselineSignoff, ChangeOrder, CheckPhoto, Checkpoint,
                         DrawingVersion, ProjectMemberRole, StoredFile, User, WorkItem, WorkItemAttachment)
from core.services import audit, ledger, storage

ATTACH_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".pdf", ".doc", ".docx", ".xls", ".xlsx"}
SOON_DAYS = 7
REQUIRED = [
    ("drawingVersionId", "签认版图纸分册版本"), ("description", "工作说明"), ("acceptanceCriteria", "验收标准"),
    ("cost", "费用（元）"), ("plannedFinish", "计划完成日期"), ("qcUserId", "质检人"), ("checkpoints", "检查点"),
]
FIELD_HINT = {
    "drawingVersionId": "请选择签认版图纸分册版本", "description": "请填写工作说明", "acceptanceCriteria": "请填写验收标准",
    "cost": "请填写费用（元）", "plannedFinish": "请填写计划完成日期", "qcUserId": "请选择质检人",
    "checkpoints": "至少添加 1 个检查点",
}
PENDING_MSG = "基线待业主签认，需业主退回后才能修改"
LOCKED_MSG = "已签认，请发起变更单或等待新版图纸重签"


def fmt_time(dt):
    return iso(dt)[:16].replace("T", " ") if dt else ""


def money_text(v):
    if v in (None, ""):
        return "—"
    v = decimal.Decimal(str(v))
    return f"{v:,.2f}".rstrip("0").rstrip(".") + " 元"


def location(wi):
    return {"phaseId": wi.phase_id, "phaseName": wi.phase.name, "floorId": wi.floor_id,
            "floorName": wi.floor.name if wi.floor else "全楼通用", "roomId": wi.room_id,
            "roomName": wi.room.name if wi.room else ""}


def baseline_for(wi, lock=False):
    bl, _ = Baseline.objects.get_or_create(work_item=wi, defaults={"project_id": wi.project_id})
    if lock:
        bl = Baseline.objects.select_for_update().get(pk=bl.pk)
    return bl


def snapshot(wi):
    """基线完整内容快照（DATA-F05-02 content）。"""
    dv = wi.drawing_version
    cps = Checkpoint.objects.filter(work_item=wi).order_by("id")
    return {
        "workItemId": wi.id, "name": wi.name, **location(wi),
        "drawingVersionId": dv.id if dv else None, "drawingSetId": dv.drawing_set_id if dv else None,
        "drawingSetName": dv.drawing_set.name if dv else "", "drawingVersionNo": dv.version_no if dv else None,
        "drawingFileSha256": dv.file.sha256 if dv else "",
        "description": wi.description, "acceptanceCriteria": wi.acceptance_criteria,
        "cost": str(wi.cost) if wi.cost is not None else None, "plannedFinish": d(wi.planned_finish),
        "qcUserId": wi.qc_user_id, "qcUserName": wi.qc_user.name if wi.qc_user else "",
        "checkpoints": [{"id": c.id, "code": c.code, "point": c.point, "isConcealed": c.is_concealed,
                         "drawingVersionId": c.drawing_version_id, "pageNo": c.page_no, "x": c.x, "y": c.y}
                        for c in cps],
    }


def rev_dict(r):
    if r is None:
        return None
    so = r.signoff if hasattr(r, "signoff") else None
    return {"id": r.id, "revNo": r.rev_no, "kind": r.kind, "createdAt": iso(r.created_at), "actor": r.actor.name,
            "content": r.content, "changeOrderId": r.change_order_id,
            "signedBy": so.signer.name if so else None, "signedAt": iso(so.signed_at) if so else None}


def is_soon(wi, bl, today=None):
    """AC-F05-09：计划完成日期距今不超过 7 天且基线未签认。"""
    today = today or timezone.localdate()
    return bool(wi.planned_finish and bl.status not in ("已签认", "待重签")
                and wi.planned_finish <= today + datetime.timedelta(days=SOON_DAYS))


def qc_members(project):
    ids = ProjectMemberRole.objects.filter(project=project, role="qc").values_list("user_id", flat=True)
    return User.objects.filter(pk__in=ids).order_by("id")


# ───────────── 资料 ─────────────

def file_refs(sf):
    """文件被核对、签认（图纸版本）或变更单引用的情况（AC-F12-03）。"""
    refs = []
    for ph in CheckPhoto.objects.filter(file=sf).select_related("check_record__checkpoint"):
        cr = ph.check_record
        n = cr.checkpoint.checks.filter(checked_at__lte=cr.checked_at, pk__lte=cr.pk).count()
        refs.append({"kind": "check", "id": cr.id, "label": f"{cr.checkpoint.code} 核对 #{n}"})
    for v in DrawingVersion.objects.filter(Q(file=sf) | Q(cad_file=sf)).select_related("drawing_set"):
        refs.append({"kind": "drawing", "id": v.id, "label": f"{version_label(v)} 签认图纸"})
    for co in ChangeOrder.objects.filter(files=sf):
        refs.append({"kind": "change_order", "id": co.id, "label": f"变更单 {co.code}"})
    return refs


def attachment_dict(a):
    f = a.file
    out = storage.file_dict(f)
    out.update({"attachmentId": a.id, "uploaderId": f.uploader_id, "uploaderName": f.uploader.name if f.uploader else "",
                "uploadedAt": iso(f.created_at), "isVoided": f.status == "voided",
                "voidedBy": f.voided_by.name if f.voided_by else None, "voidedAt": iso(f.voided_at),
                "refs": file_refs(f)})
    return out


def attachments_of(wi):
    qs = (WorkItemAttachment.objects.filter(work_item=wi).select_related("file__uploader", "file__voided_by")
          .order_by("-created_at", "-id"))
    return [attachment_dict(a) for a in qs]


# ───────────── 历史 ─────────────

def history(bl):
    """修订与签认历史（只追加）：修订、签认记录、事件，倒序。"""
    out = []
    revs = list(bl.revisions.select_related("actor", "change_order", "signoff__signer").order_by("rev_no"))
    for r in revs:
        c = r.content
        dv = f"{c.get('drawingSetName', '')} V{c.get('drawingVersionNo')}" if c.get("drawingVersionId") else ""
        if r.kind == "change_order":
            code = r.change_order.code if r.change_order else ""
            out.append({"at": iso(r.created_at), "kind": "change_order", "revNo": r.rev_no,
                        "text": f"变更单 {code} 生效，追加修订 r{r.rev_no}",
                        "changeOrder": {"id": r.change_order_id, "code": code} if r.change_order_id else None})
        else:
            resubmit = any(x.rev_no < r.rev_no and hasattr(x, "signoff") for x in revs)
            verb = "提交重签" if resubmit else "提交基线待签"
            out.append({"at": iso(r.created_at), "kind": "submit", "revNo": r.rev_no,
                        "text": f"{r.actor.name}{verb}（r{r.rev_no}，{dv}，费用 {money_text(c.get('cost'))}）"})
        if hasattr(r, "signoff"):
            so = r.signoff
            out.append({"at": iso(so.signed_at), "kind": "signoff", "revNo": r.rev_no,
                        "text": f"{so.signer.name}签认 r{r.rev_no}（{dv}，费用 {money_text(c.get('cost'))}）· 签认记录含完整内容快照"})
    for ev in bl.events.select_related("actor", "drawing_version__drawing_set", "drawing_version__signoff__signer",
                                       "checkpoint").order_by("at"):
        if ev.kind == "returned":
            text = f"{ev.actor.name}退回基线：{ev.reason}"
        elif ev.kind == "resign_required":
            v = ev.drawing_version
            text = f"{version_label(v)} 由{ev.actor.name}签认，本项被设计经理标为受影响 → 待重签"
        elif ev.kind == "checkpoint_added":
            cp = ev.checkpoint
            text = f"{ev.actor.name}新增检查点 {cp.code if cp else ''} {cp.point if cp else ''}，立即生效，已知会业主"
        else:
            text = f"{ev.actor.name} {ev.kind} {ev.reason}".strip()
        out.append({"at": iso(ev.at), "kind": ev.kind, "text": text, "checkpointId": ev.checkpoint_id})
    out.sort(key=lambda x: x["at"], reverse=True)
    return out


def baseline_block(wi, bl):
    cur = bl.current_revision
    signed = bl.signed_revision
    effective = signed if bl.status in ("已签认", "待重签") and signed else (cur if bl.status == "待签认" else None)
    base_dv = None
    if bl.status in ("已签认", "待重签") and signed and signed.content.get("drawingVersionId"):
        base_dv = DrawingVersion.objects.filter(pk=signed.content["drawingVersionId"]).select_related("drawing_set").first()
    elif wi.drawing_version and hasattr(wi.drawing_version, "signoff"):
        base_dv = wi.drawing_version
    resign = None
    if bl.status == "待重签":
        ev = bl.events.filter(kind="resign_required").select_related("drawing_version__drawing_set").order_by("-at").first()
        if ev:
            resign = {"newVersion": version_brief(ev.drawing_version), "oldVersion": version_brief(base_dv),
                      "at": iso(ev.at)}
    return {
        "id": bl.id, "status": bl.status, "returnReason": bl.return_reason, "submittedAt": iso(bl.submitted_at),
        "currentRevision": rev_dict(cur), "signedRevision": rev_dict(signed), "effectiveRevision": rev_dict(effective),
        "isResign": bool(signed) and bl.status in ("待签认", "待重签"),
        "baseDrawingVersion": version_brief(base_dv), "resign": resign, "soon": is_soon(wi, bl),
    }


def work_item_dict(wi):
    return {"id": wi.id, "name": wi.name, **location(wi), "weight": wi.weight, "progress": wi.progress,
            "actualFinish": d(wi.actual_finish), "description": wi.description,
            "acceptanceCriteria": wi.acceptance_criteria, "cost": str(wi.cost) if wi.cost is not None else None,
            "plannedFinish": d(wi.planned_finish), "qcUserId": wi.qc_user_id,
            "qcUserName": wi.qc_user.name if wi.qc_user else "", "ownerName": wi.owner_name,
            "drawingVersion": version_brief(wi.drawing_version), "isDisabled": wi.is_disabled,
            "checkpointHints": wi.checkpoint_hints}


def load_wi(view, wid):
    return view.obj(WorkItem.objects.select_related("phase", "floor", "room", "qc_user", "drawing_version__drawing_set"), wid)


# ───────────── 视图 ─────────────

class WorkItemDetail(ProjectView):
    http_method_names = ["get"]

    def get(self, request, project_id, wid):
        """工作项详情聚合（PAGE-F05-01）：基线状态、当前修订、修订与签认历史、事件、资料。"""
        wi = load_wi(self, wid)
        bl = baseline_for(wi)
        atts = attachments_of(wi)
        return Response({
            "workItem": work_item_dict(wi), "baseline": baseline_block(wi, bl), "history": history(bl),
            "attachments": atts, "attachmentCount": sum(1 for a in atts if not a["isVoided"]),
            "voidedCount": sum(1 for a in atts if a["isVoided"]),
            "checkpointCount": Checkpoint.objects.filter(work_item=wi).count(),
            "qcCandidates": [{"id": u.id, "name": u.name} for u in qc_members(self.project)],
            "ownerNames": list(User.objects.filter(project_roles__project=self.project, project_roles__role="owner")
                               .order_by("id").values_list("name", flat=True)),
        })


class WorkItemBaseline(ProjectView):
    http_method_names = ["get"]

    def get(self, request, project_id, wid):
        wi = load_wi(self, wid)
        bl = baseline_for(wi)
        return Response({**baseline_block(wi, bl), "history": history(bl)})


class BaselineSubmit(ProjectView):
    http_method_names = ["post"]

    def post(self, request, project_id, wid):
        """提交基线待签（AC-F05-01、AC-F05-02、AC-F05-08、AC-F05-10）。

        body 可带 drawingVersionId、description、acceptanceCriteria、cost、plannedFinish、qcUserId；带了就先写入工作项再校验，
        这样待重签时也能在提交时更新图纸版本（锁定字段只能经由重签提交改变）。整个过程一个事务，校验失败不留任何改动。
        """
        self.require("baseline.submit", "只有项目经理可以提交基线")
        data = request.data
        with transaction.atomic():
            wi = WorkItem.objects.select_for_update().get(pk=load_wi(self, wid).pk)
            bl = baseline_for(wi, lock=True)
            if bl.status == "待签认":
                raise ApiError(409, "BASELINE_PENDING_SIGN", PENDING_MSG)
            if bl.status == "已签认":
                raise ApiError(409, "BASELINE_LOCKED", LOCKED_MSG)
            before = snapshot(wi)
            errs = self._apply(wi, data)
            wi.save()
            wi = WorkItem.objects.select_related("phase", "floor", "room", "qc_user", "drawing_version__drawing_set",
                                                 "drawing_version__file").get(pk=wi.pk)
            missing = [(k, FIELD_HINT[k]) for k, _ in REQUIRED if self._empty(wi, k)]
            unsigned = wi.drawing_version is not None and not hasattr(wi.drawing_version, "signoff")
            fields = [e for e in errs if e[0] not in dict(missing)] + missing
            if unsigned and not any(f == "drawingVersionId" for f, _ in fields):
                fields.insert(0, ("drawingVersionId", "该版本尚未签认"))
            if fields:
                if len(fields) == 1 and fields[0] == ("drawingVersionId", "该版本尚未签认"):
                    raise ApiError(422, "DRAWING_NOT_SIGNED", "该版本尚未签认",
                                   fields=[{"field": "drawingVersionId", "message": "该版本尚未签认"}])
                labels = dict(REQUIRED)
                names = [labels[k] for k, _ in missing]
                msg = ("以下字段缺失，无法提交：" + "、".join(names)) if names else "；".join(m for _, m in fields)
                raise ApiError(400, "VALIDATION_FAILED", msg, fields=[{"field": f, "message": m} for f, m in fields],
                               details={"missing": names})
            Checkpoint.objects.filter(work_item=wi, is_draft=True).update(is_draft=False)  # 草稿检查点随提交生效
            no = (bl.revisions.aggregate(m=Max("rev_no"))["m"] or 0) + 1
            rev = BaselineRevision.objects.create(project=self.project, baseline=bl, rev_no=no, kind="submit",
                                                  content=snapshot(wi), actor=request.user)
            ledger.append(self.project.id, rev)
            prev = bl.status
            bl.status = "待签认"
            bl.current_revision = rev
            bl.return_reason = ""
            bl.submitted_at = timezone.now()
            bl.save(update_fields=["status", "current_revision", "return_reason", "submitted_at"])
            audit.log(request.user, "baseline.submit", "baseline", bl.id, wi.name, project=self.project,
                      before={"status": prev, "content": before}, after={"status": "待签认", "revNo": no})
        return Response({"id": bl.id, "status": bl.status, "revisionId": rev.id, "revNo": no, "content": rev.content},
                        status=201)

    def _apply(self, wi, data):
        errs = []
        if "drawingVersionId" in data:
            v = data.get("drawingVersionId")
            if v in (None, ""):
                wi.drawing_version = None
            else:
                dv = DrawingVersion.objects.filter(project=self.project, pk=v).first()
                if dv is None:
                    errs.append(("drawingVersionId", "图纸版本不存在"))
                else:
                    wi.drawing_version = dv
        for key, attr in (("description", "description"), ("acceptanceCriteria", "acceptance_criteria")):
            if key in data:
                setattr(wi, attr, str(data.get(key) or "").strip())
        if "cost" in data:
            raw = data.get("cost")
            if raw in (None, ""):
                wi.cost = None
            else:
                try:
                    wi.cost = decimal.Decimal(str(raw))
                    if wi.cost < 0:
                        raise decimal.InvalidOperation
                except decimal.InvalidOperation:
                    errs.append(("cost", "费用须为不小于 0 的数字"))
                    wi.cost = None
        if "plannedFinish" in data:
            raw = data.get("plannedFinish")
            try:
                wi.planned_finish = datetime.date.fromisoformat(str(raw)) if raw else None
            except ValueError:
                errs.append(("plannedFinish", "计划完成日期格式不正确"))
                wi.planned_finish = None
        if "qcUserId" in data:
            raw = data.get("qcUserId")
            if raw in (None, ""):
                wi.qc_user = None
            else:
                u = qc_members(self.project).filter(pk=raw).first()
                if u is None:
                    errs.append(("qcUserId", "质检人须为本项目质检"))
                    wi.qc_user = None
                else:
                    wi.qc_user = u
        return errs

    @staticmethod
    def _empty(wi, key):
        return {
            "drawingVersionId": wi.drawing_version_id is None, "description": not wi.description.strip(),
            "acceptanceCriteria": not wi.acceptance_criteria.strip(), "cost": wi.cost is None,
            "plannedFinish": wi.planned_finish is None, "qcUserId": wi.qc_user_id is None,
            "checkpoints": not Checkpoint.objects.filter(work_item=wi).exists(),
        }[key]


def pending_item(bl):
    wi = bl.work_item
    rev = bl.current_revision
    c = rev.content
    return {
        "baselineId": bl.id, "revisionId": rev.id, "revNo": rev.rev_no, "workItemId": wi.id, "name": wi.name,
        **location(wi), "plannedFinish": c.get("plannedFinish"), "cost": c.get("cost"),
        "drawing": f"{c.get('drawingSetName')} V{c.get('drawingVersionNo')}", "drawingVersionId": c.get("drawingVersionId"),
        "description": c.get("description"), "acceptanceCriteria": c.get("acceptanceCriteria"),
        "qcUserName": c.get("qcUserName"), "checkpoints": c.get("checkpoints", []),
        "isResign": bl.signed_revision_id is not None, "soon": is_soon(wi, bl), "submittedAt": iso(bl.submitted_at),
        "submittedBy": rev.actor.name,
    }


class PendingBaselines(ProjectView):
    http_method_names = ["get"]

    def get(self, request, project_id):
        """待签基线，按工段或楼层分组（AC-F05-03、AC-F05-04）。"""
        group = "floor" if request.GET.get("group") == "floor" else "phase"
        qs = (Baseline.objects.filter(project=self.project, status="待签认", current_revision__isnull=False)
              .select_related("work_item__phase", "work_item__floor", "work_item__room", "current_revision__actor")
              .order_by("work_item__phase__order_no", "work_item__floor__order_no", "work_item__id"))
        groups, order = {}, []
        total = decimal.Decimal(0)
        for bl in qs:
            it = pending_item(bl)
            total += decimal.Decimal(it["cost"] or 0)
            wi = bl.work_item
            if group == "phase":
                key, name, sort = f"p{wi.phase_id}", wi.phase.name, (wi.phase.order_no, wi.phase_id)
            else:
                key = f"f{wi.floor_id or 0}"
                name = wi.floor.name if wi.floor else "全楼通用"
                sort = (wi.floor.order_no if wi.floor else -1, wi.floor_id or 0)
            if key not in groups:
                groups[key] = {"key": key, "name": name, "sort": sort, "items": [], "cost": decimal.Decimal(0)}
                order.append(key)
            groups[key]["items"].append(it)
            groups[key]["cost"] += decimal.Decimal(it["cost"] or 0)
        out = sorted(groups.values(), key=lambda g: g["sort"])
        for g in out:
            g.pop("sort")
            g["cost"] = str(g["cost"])
        return Response({"group": group, "groups": out, "total": sum(len(g["items"]) for g in out),
                         "totalCost": str(total)})


class BaselineSign(ProjectView):
    http_method_names = ["post"]

    def post(self, request, project_id):
        """批量签认（SEQ-F05-01，AC-F05-04、AC-F01-10）：按 ID 升序锁行，每项独立签认记录与内容快照。"""
        self.require("baseline.sign", "只有业主可以签认基线")
        raw = request.data.get("revisionIds") or []
        try:
            ids = sorted({int(x) for x in raw})
        except (TypeError, ValueError):
            fail("VALIDATION_FAILED", "请选择要签认的基线")
        if not ids:
            fail("VALIDATION_FAILED", "请选择要签认的基线")
        revs = {r.id: r for r in BaselineRevision.objects.filter(project=self.project, pk__in=ids)}
        if len(revs) != len(ids):
            fail("NOT_FOUND", "记录不存在", 404)
        bl_ids = sorted({r.baseline_id for r in revs.values()})
        with transaction.atomic():
            bls = list(Baseline.objects.select_for_update().filter(pk__in=bl_ids).order_by("id"))
            bls = list(Baseline.objects.filter(pk__in=bl_ids).select_related("work_item__phase", "work_item__floor",
                                                                             "work_item__room").order_by("id"))
            phases = {b.work_item.phase_id for b in bls}
            floors = {b.work_item.floor_id for b in bls}
            if len(phases) > 1 and len(floors) > 1:
                fail("VALIDATION_FAILED", "批量签认只能在同一工段或同一楼层内勾选")
            by_bl = {b.id: b for b in bls}
            for rid in ids:
                r = revs[rid]
                b = by_bl[r.baseline_id]
                done = BaselineSignoff.objects.filter(revision=r).select_related("signer").first()
                if done:
                    raise ApiError(409, "ALREADY_SIGNED",
                                   f"「{b.work_item.name}」已由{done.signer.name}于{fmt_time(done.signed_at)}签认",
                                   details={"signer": done.signer.name, "signedAt": iso(done.signed_at),
                                            "workItemId": b.work_item_id})
                if b.status != "待签认" or b.current_revision_id != r.id:
                    raise ApiError(409, "BASELINE_STATE", f"「{b.work_item.name}」基线状态已变化，请刷新",
                                   details={"workItemId": b.work_item_id, "status": b.status})
            records = []
            for rid in ids:
                r = revs[rid]
                b = by_bl[r.baseline_id]
                so = BaselineSignoff.objects.create(project=self.project, revision=r, signer=request.user,
                                                    content_snapshot=r.content)
                ledger.append(self.project.id, so)
                b.status = "已签认"
                b.signed_revision = r
                b.save(update_fields=["status", "signed_revision"])
                audit.log(request.user, "baseline.sign", "baseline", b.id, b.work_item.name, project=self.project,
                          before={"status": "待签认"}, after={"status": "已签认", "revNo": r.rev_no})
                records.append({"signoffId": so.id, "baselineId": b.id, "workItemId": b.work_item_id,
                                "revisionId": r.id, "signer": request.user.name, "signedAt": iso(so.signed_at)})
        return Response({"count": len(records), "items": records})


class BaselineReturn(ProjectView):
    http_method_names = ["post"]

    def post(self, request, project_id, baseline_id):
        """退回（AC-F05-05）：必填理由，事件入链，状态「已退回」，项目经理待办由派生查询产生。"""
        self.require("baseline.sign", "只有业主可以退回基线")
        reason = str(request.data.get("reason", "")).strip()
        if not reason:
            raise ApiError(400, "VALIDATION_FAILED", "请填写退回理由",
                           fields=[{"field": "reason", "message": "请填写退回理由"}])
        if len(reason) > 200:
            raise ApiError(400, "VALIDATION_FAILED", "退回理由不超过 200 字",
                           fields=[{"field": "reason", "message": "退回理由不超过 200 字"}])
        self.obj(Baseline, baseline_id)
        with transaction.atomic():
            bl = Baseline.objects.select_for_update().select_related("work_item").get(pk=baseline_id)
            if bl.status != "待签认":
                last = bl.events.filter(kind="returned").select_related("actor").order_by("-at").first()
                if bl.status == "已退回" and last:
                    raise ApiError(409, "ALREADY_RETURNED", f"已由{last.actor.name}于{fmt_time(last.at)}退回",
                                   details={"actor": last.actor.name, "at": iso(last.at)})
                raise ApiError(409, "BASELINE_STATE", "基线状态已变化，请刷新", details={"status": bl.status})
            ev = BaselineEvent.objects.create(project=self.project, baseline=bl, kind="returned", reason=reason,
                                              actor=request.user)
            ledger.append(self.project.id, ev)
            bl.status = "已退回"
            bl.return_reason = reason
            bl.save(update_fields=["status", "return_reason"])
            audit.log(request.user, "baseline.return", "baseline", bl.id, bl.work_item.name, project=self.project,
                      before={"status": "待签认"}, after={"status": "已退回", "reason": reason})
        return Response({"id": bl.id, "status": bl.status, "returnReason": reason})


class Attachments(ProjectView):
    http_method_names = ["get", "post"]

    def get(self, request, project_id, wid):
        wi = load_wi(self, wid)
        items = attachments_of(wi)
        return Response({"items": items, "count": sum(1 for a in items if not a["isVoided"])})

    def post(self, request, project_id, wid):
        """单文件上传（前端逐个上传，超限文件单独被拒，AC-F12-01、AC-F12-02）。"""
        self.require("file.upload", "无权上传资料")
        wi = load_wi(self, wid)
        f = request.FILES.get("file")
        if f is None:
            raise ApiError(400, "VALIDATION_FAILED", "请选择文件", fields=[{"field": "file", "message": "请选择文件"}])
        with transaction.atomic():
            sf = storage.save_upload(f, request.user, self.project, ATTACH_EXT)
            a = WorkItemAttachment.objects.create(project=self.project, work_item=wi, file=sf)
            audit.log(request.user, "attachment.upload", "work_item_attachment", a.id, sf.original_name,
                      project=self.project, after={"workItemId": wi.id, "sha256": sf.sha256, "size": sf.size})
        return Response(attachment_dict(a), status=201)


class AttachmentVoid(ProjectView):
    http_method_names = ["post"]

    def post(self, request, project_id, attachment_id):
        """作废（AC-F12-03）：仅上传者；被核对、签认或变更单引用的不能作废；记录作废人与时间。"""
        a = self.obj(WorkItemAttachment, attachment_id)
        with transaction.atomic():
            sf = StoredFile.objects.select_for_update().get(pk=a.file_id)
            if sf.uploader_id != request.user.id:
                forbidden("只能作废自己上传的资料")
            if sf.status == "voided":
                raise ApiError(409, "ALREADY_VOIDED", f"已由{sf.voided_by.name}于{fmt_time(sf.voided_at)}作废")
            refs = file_refs(sf)
            if refs:
                raise ApiError(409, "FILE_REFERENCED", "该文件已被核对、签认或变更单引用，不能作废",
                               details={"refs": refs, "file": sf.original_name})
            sf.status = "voided"
            sf.voided_by = request.user
            sf.voided_at = timezone.now()
            sf.save(update_fields=["status", "voided_by", "voided_at"])
            audit.log(request.user, "attachment.void", "work_item_attachment", a.id, sf.original_name,
                      project=self.project, before={"status": "normal"}, after={"status": "voided"})
        a.file = sf
        return Response(attachment_dict(a))


urlpatterns = [
    path("projects/<int:project_id>/work-items/<int:wid>/detail", WorkItemDetail.as_view()),
    path("projects/<int:project_id>/work-items/<int:wid>/baseline", WorkItemBaseline.as_view()),
    path("projects/<int:project_id>/work-items/<int:wid>/baseline/submit", BaselineSubmit.as_view()),
    path("projects/<int:project_id>/work-items/<int:wid>/attachments", Attachments.as_view()),
    path("projects/<int:project_id>/attachments/<int:attachment_id>/void", AttachmentVoid.as_view()),
    path("projects/<int:project_id>/baselines/pending", PendingBaselines.as_view()),
    path("projects/<int:project_id>/baselines/sign", BaselineSign.as_view()),
    path("projects/<int:project_id>/baselines/<int:baseline_id>/return", BaselineReturn.as_view()),
]
