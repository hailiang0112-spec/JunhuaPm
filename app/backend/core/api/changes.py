"""变更单（API-F07-01，SEQ-F07-01）：发起 → 预算定价 → 业主签认 / 驳回 → 修改后重新提交。

状态迁移见技术方案 §5.1.5：草稿 →(提交)→ 待预算定价 →(定价)→ 待业主签认 →(签认)→ 已生效 / →(驳回)→ 已驳回；
已驳回 →(重新提交，编号不变，round_no+1，清空上一轮定价)→ 待预算定价。
变更单是投影表（可更新，先锁行）；每一步都追加 ChangeOrderEvent（关键记录，入链）。
"""
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.db.models import Max, Q
from django.urls import path
from django.utils import timezone
from rest_framework.response import Response

from core import perms
from core.api.base import ProjectView, d, iso, paginate, user_brief
from core.errors import ApiError, validation
from core.models import (Baseline, BaselineRevision, ChangeOrder, DrawingVersion, Project, ProjectMemberRole,
                         StoredFile, WorkItem)
from core.services import audit, ledger, storage
from core.services.shared import change_event

STATUSES = ["草稿", "待预算定价", "待业主签认", "已生效", "已驳回"]
# 事件操作人的角色标签：按事件种类优先取对应角色（同一账号可能兼多个角色）
KIND_ROLE = {"created": "pm", "resubmitted": "pm", "priced": "budget", "signed": "owner", "rejected": "owner"}


def state_conflict(co, message="变更单状态已变化，请刷新", code="CHANGE_ORDER_STATE"):
    """重复或越权的状态迁移：409，带上最近一次流转的「谁、何时」（技术方案 §4.4）。"""
    last = co.events.select_related("actor").order_by("-at", "-id").first()
    details = {"status": co.status}
    if last:
        details.update({"by": last.actor.name, "at": iso(last.at), "kind": last.kind})
    raise ApiError(409, code, message, details=details)


def wi_label(wi):
    floor = wi.floor.name if wi.floor_id else "全楼"
    room = wi.room.name if wi.room_id else "本层通用"
    return f"{floor} · {room} · {wi.name}（{wi.phase.name}）"


def role_label(user, project, prefer=None):
    roles = set(ProjectMemberRole.objects.filter(project=project, user=user).values_list("role", flat=True))
    if prefer in roles:
        return perms.ROLE_LABELS[prefer]
    for r in ["pm", "budget", "owner", "design_manager", "qc", "owner_member", "owner_agent"]:
        if r in roles:
            return perms.ROLE_LABELS[r]
    return perms.ROLE_LABELS["admin"] if user.is_company_admin else ""


def num(v):
    if v is None:
        return None
    return int(v) if v == v.to_integral_value() else float(v)


def snapshot(co):
    """发起 / 重新提交 / 签认时写入事件的完整内容快照。"""
    return {"code": co.code, "title": co.title, "reasonCategory": co.reason_category, "content": co.content,
            "workItemIds": sorted(co.work_items.values_list("id", flat=True)),
            "needsNewDrawing": co.needs_new_drawing, "builtBeforeSign": co.built_before_sign,
            "fileIds": sorted(co.files.values_list("id", flat=True))}


def source_dict(co):
    if co.source_issue_id:
        iss = co.source_issue
        label = f"问题 {iss.code}"
        if iss.checkpoint_id:
            label += f"（检查点 {iss.checkpoint.code} 核对不一致）"
        return {"type": "issue", "id": iss.id, "code": iss.code, "label": label}
    if co.source_supplement_id:
        s = co.source_supplement
        return {"type": "supplement", "id": s.id, "code": "", "label": f"补充事项「{s.title}」"}
    return None


def co_dict(co):
    return {
        "id": co.id, "code": co.code, "seqNo": co.seq_no, "roundNo": co.round_no, "title": co.title,
        "reasonCategory": co.reason_category, "content": co.content, "needsNewDrawing": co.needs_new_drawing,
        "builtBeforeSign": co.built_before_sign, "isLate": bool(co.built_before_sign), "status": co.status,
        "priceDelta": num(co.price_delta), "scheduleDeltaDays": co.schedule_delta_days, "costBearer": co.cost_bearer,
        "rejectReason": co.reject_reason, "workItemCount": co.work_items.count(),
        "createdBy": user_brief(co.created_by), "createdAt": iso(co.created_at), "source": source_dict(co),
    }


def co_detail(co):
    out = co_dict(co)
    project = co.project
    revs = {r.baseline.work_item_id: r for r in BaselineRevision.objects.filter(change_order=co).select_related("baseline")}
    out["workItems"] = [{"id": wi.id, "name": wi.name, "label": wi_label(wi), "phaseName": wi.phase.name,
                         "floorName": wi.floor.name if wi.floor_id else "", "roomName": wi.room.name if wi.room_id else "",
                         "revision": ({"revNo": revs[wi.id].rev_no, "at": iso(revs[wi.id].created_at)} if wi.id in revs else None)}
                        for wi in co.work_items.select_related("phase", "floor", "room").order_by("id")]
    out["files"] = [storage.file_dict(f) for f in co.files.order_by("id")]
    events = []
    for ev in co.events.select_related("actor").order_by("at", "id"):
        events.append({"id": ev.id, "kind": ev.kind, "roundNo": ev.round_no, "payload": ev.payload,
                       "actor": user_brief(ev.actor), "actorRole": role_label(ev.actor, project, KIND_ROLE.get(ev.kind)),
                       "at": iso(ev.at)})
    out["events"] = events
    by_kind = lambda k: [e for e in events if e["kind"] == k and e["roundNo"] == co.round_no]  # noqa: E731
    priced = by_kind("priced")
    signed = by_kind("signed")
    out["pricedBy"] = priced[-1]["actor"] if priced and co.price_delta is not None else None
    out["pricedAt"] = priced[-1]["at"] if priced and co.price_delta is not None else None
    out["signedBy"] = signed[-1]["actor"] if signed else None
    out["signedAt"] = signed[-1]["at"] if signed else None
    out["rejects"] = [{"roundNo": e["roundNo"], "by": e["actor"], "at": e["at"], "reason": e["payload"].get("reason", "")}
                      for e in events if e["kind"] == "rejected"]
    # 新版图纸（AC-F07-07）：设计经理姓名、已关联本单的新版
    dms = list(ProjectMemberRole.objects.filter(project=project, role="design_manager").select_related("user")
               .order_by("id").values_list("user__name", flat=True))
    linked = DrawingVersion.objects.filter(change_order=co).select_related("drawing_set").order_by("id")
    out["drawing"] = {
        "designManagers": dms,
        "linkedVersions": [{"id": v.id, "setId": v.drawing_set_id, "setName": getattr(v.drawing_set, "name", ""),
                            "versionNo": v.version_no, "at": iso(v.created_at)} for v in linked],
        "todoPending": bool(co.needs_new_drawing and co.status == "已生效" and not linked),
    }
    budgets = list(ProjectMemberRole.objects.filter(project=project, role="budget").select_related("user")
                   .order_by("id").values_list("user__name", flat=True))
    out["budgetNames"] = budgets
    return out


def parse_bool(v):
    if isinstance(v, bool):
        return v
    if v in ("true", "1", 1, "是"):
        return True
    if v in ("false", "0", 0, "否"):
        return False
    return None


def clean_form(view, data):
    """AC-F07-01：五个必填项一次列出全部缺失项。返回清洗后的字段。"""
    errs = []
    reason = str(data.get("reasonCategory") or "").strip()
    content = str(data.get("content") or "").strip()
    ids = data.get("workItemIds") or []
    ids = [int(x) for x in ids if str(x).isdigit()] if isinstance(ids, list) else []
    items = list(WorkItem.objects.filter(project=view.project, pk__in=ids, is_disabled=False))
    needs = parse_bool(data.get("needsNewDrawing"))
    built = parse_bool(data.get("builtBeforeSign"))
    if reason not in ChangeOrder.REASONS:
        errs.append(("reasonCategory", "请选择原因类别"))
    if not content:
        errs.append(("content", "请填写变更内容"))
    if not items or len(items) != len(set(ids)):
        errs.append(("workItemIds", "请至少选择 1 个受影响工作项"))
    if needs is None:
        errs.append(("needsNewDrawing", "请选择是否需要新版图纸"))
    if built is None:
        errs.append(("builtBeforeSign", "请选择现场是否已按此施工"))
    file_ids = data.get("fileIds") or []
    file_ids = [int(x) for x in file_ids if str(x).isdigit()] if isinstance(file_ids, list) else []
    files = list(StoredFile.objects.filter(project=view.project, pk__in=file_ids, status="normal"))
    if len(files) != len(set(file_ids)):
        errs.append(("fileIds", "附件不存在或已作废"))
    validation(errs)
    title = str(data.get("title") or "").strip() or content.splitlines()[0][:28]
    return {"reason_category": reason, "content": content, "needs_new_drawing": needs, "built_before_sign": built,
            "title": title[:100]}, items, files


def apply_form(co, fields, items, files):
    for k, v in fields.items():
        setattr(co, k, v)
    co.save()
    co.work_items.set(items)
    co.files.set(files)


def locked(view, co_id):
    co = view.obj(ChangeOrder, co_id)
    return ChangeOrder.objects.select_for_update().get(pk=co.pk)


def respond(co, http_status=200):
    co = ChangeOrder.objects.select_related("created_by", "source_issue__checkpoint", "source_supplement", "project").get(pk=co.pk)
    return Response(co_detail(co), status=http_status)


class ChangeOrders(ProjectView):
    def get(self, request, project_id):
        qs = ChangeOrder.objects.filter(project=self.project).select_related("created_by", "source_issue__checkpoint",
                                                                            "source_supplement")
        st = request.GET.get("status")
        if st:
            qs = qs.filter(status=st)
        if request.GET.get("late") in ("1", "true"):
            qs = qs.filter(built_before_sign=True)
        kw = request.GET.get("q", "").strip()
        if kw:
            cond = Q(title__icontains=kw) | Q(content__icontains=kw)
            digits = kw.upper().replace("BG-", "").replace("BG", "")
            if digits.isdigit():
                cond |= Q(seq_no=int(digits))
            qs = qs.filter(cond)
        return Response(paginate(request, qs.order_by("-seq_no"), co_dict))

    def post(self, request, project_id):
        """项目经理直接发起：提交成功后才分配编号（DEC-071），状态「待预算定价」（AC-F07-02）。"""
        self.require("change.create", "只有项目经理可以发起变更单")
        fields, items, files = clean_form(self, request.data)
        with transaction.atomic():
            p = Project.objects.select_for_update().get(pk=self.project.pk)
            p.change_order_seq += 1
            p.save(update_fields=["change_order_seq"])
            co = ChangeOrder(project=self.project, seq_no=p.change_order_seq, status="待预算定价", created_by=request.user)
            apply_form(co, fields, items, files)
            change_event(co, request.user, "created", snapshot(co))
            audit.log(request.user, "change.create", "change_order", co.id, f"{co.code} {co.title}", None,
                      {"status": co.status, "builtBeforeSign": co.built_before_sign}, project=self.project)
        return respond(co, 201)


class ChangeOrderDetail(ProjectView):
    def get(self, request, project_id, co_id):
        co = self.obj(ChangeOrder, co_id)
        return respond(co)


class SubmitDraft(ProjectView):
    """从问题 / 补充事项生成的草稿（shared.create_change_draft）补齐字段后提交，编号沿用草稿编号。"""

    def post(self, request, project_id, co_id):
        self.require("change.create", "只有项目经理可以发起变更单")
        fields, items, files = clean_form(self, request.data)
        with transaction.atomic():
            co = locked(self, co_id)
            if co.status != "草稿":
                state_conflict(co)
            co.status = "待预算定价"
            apply_form(co, fields, items, files)
            change_event(co, request.user, "created", snapshot(co))
            audit.log(request.user, "change.create", "change_order", co.id, f"{co.code} {co.title}", {"status": "草稿"},
                      {"status": co.status, "builtBeforeSign": co.built_before_sign}, project=self.project)
        return respond(co)


class Price(ProjectView):
    """AC-F07-03：费用可为负数，工期为整数天（可 0 或负），承担方三选一 → 待业主签认。"""

    def post(self, request, project_id, co_id):
        self.require("change.price", "只有预算专员可以定价")
        data = request.data
        errs = []
        try:
            price = Decimal(str(data.get("priceDelta")).strip())
            if not price.is_finite() or abs(price) >= Decimal("1e10"):
                raise InvalidOperation
            price = price.quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            price = None
            errs.append(("priceDelta", "请填写费用增减"))
        days_raw = data.get("scheduleDeltaDays")
        days = None
        if isinstance(days_raw, int) and not isinstance(days_raw, bool):
            days = days_raw
        elif isinstance(days_raw, str) and days_raw.strip().lstrip("-").isdigit():
            days = int(days_raw.strip())
        if days is None:
            errs.append(("scheduleDeltaDays", "请填写工期影响（整数天）"))
        bearer = str(data.get("costBearer") or "")
        if bearer not in ChangeOrder.BEARERS:
            errs.append(("costBearer", "请选择费用承担方"))
        validation(errs)
        with transaction.atomic():
            co = locked(self, co_id)
            if co.status != "待预算定价":
                state_conflict(co, "变更单已定价或状态已变化，请刷新")
            co.price_delta, co.schedule_delta_days, co.cost_bearer = price, days, bearer
            co.status = "待业主签认"
            co.save()
            change_event(co, request.user, "priced", {"priceDelta": str(price), "scheduleDeltaDays": days,
                                                       "costBearer": bearer})
            audit.log(request.user, "change.price", "change_order", co.id, f"{co.code} {co.title}",
                      {"status": "待预算定价"}, {"status": co.status, "priceDelta": str(price),
                                            "scheduleDeltaDays": days, "costBearer": bearer}, project=self.project)
        return respond(co)


def revision_content(baseline, wi, co):
    """基于当前修订追加一条引用变更单的修订；没有修订时以工作项当前锁定字段为底稿。"""
    if baseline.current_revision_id:
        content = dict(baseline.current_revision.content)
    else:
        content = {"workItemId": wi.id, "name": wi.name, "drawingVersionId": wi.drawing_version_id,
                   "description": wi.description, "acceptanceCriteria": wi.acceptance_criteria,
                   "cost": str(wi.cost) if wi.cost is not None else None, "plannedFinish": d(wi.planned_finish),
                   "qcUserId": wi.qc_user_id,
                   "checkpoints": [{"id": c.id, "code": c.code, "point": c.point, "isConcealed": c.is_concealed}
                                   for c in wi.checkpoints.order_by("id")]}
    content["changeOrder"] = {"id": co.id, "code": co.code, "title": co.title, "content": co.content,
                              "reasonCategory": co.reason_category, "priceDelta": str(co.price_delta),
                              "scheduleDeltaDays": co.schedule_delta_days, "costBearer": co.cost_bearer}
    content["changeOrders"] = list(content.get("changeOrders", [])) + [co.code]
    return content


class Sign(ProjectView):
    """AC-F07-04：业主签认 → 已生效；每个受影响工作项的基线追加 kind=change_order 的修订并入链。"""

    def post(self, request, project_id, co_id):
        self.require("change.sign", "只有业主可以签认变更单")
        with transaction.atomic():
            co = locked(self, co_id)
            if co.status == "已生效":
                ev = co.events.filter(kind="signed").select_related("actor").order_by("-at").first()
                raise ApiError(409, "ALREADY_SIGNED",
                               f"已由 {ev.actor.name} 于 {timezone.localtime(ev.at):%Y-%m-%d %H:%M} 签认" if ev else "变更单已生效",
                               details={"by": ev.actor.name if ev else "", "at": iso(ev.at) if ev else None})
            if co.status != "待业主签认":
                state_conflict(co)
            co.status = "已生效"
            co.save()
            snap = snapshot(co)
            snap.update({"priceDelta": str(co.price_delta), "scheduleDeltaDays": co.schedule_delta_days,
                         "costBearer": co.cost_bearer, "roundNo": co.round_no})
            change_event(co, request.user, "signed", snap)
            revised = []
            for wi in co.work_items.select_related("phase").order_by("id"):
                baseline = Baseline.objects.filter(work_item=wi).first() or Baseline.objects.create(project=self.project, work_item=wi)
                baseline = Baseline.objects.select_for_update().get(pk=baseline.pk)
                rev_no = (baseline.revisions.aggregate(m=Max("rev_no"))["m"] or 0) + 1
                rev = BaselineRevision.objects.create(project=self.project, baseline=baseline, rev_no=rev_no,
                                                      kind="change_order", content=revision_content(baseline, wi, co),
                                                      change_order=co, actor=request.user)
                ledger.append(self.project.id, rev)
                # 已签认 / 待重签的基线：修订即业主签认内容，两个指针都前移；
                # 草稿、已退回、待签认的基线不动指针，避免打乱基线自身的提交与签认流程。
                if baseline.status in ("已签认", "待重签"):
                    baseline.current_revision = rev
                    baseline.signed_revision = rev
                    baseline.save(update_fields=["current_revision", "signed_revision"])
                revised.append({"workItemId": wi.id, "revNo": rev_no})
            audit.log(request.user, "change.sign", "change_order", co.id, f"{co.code} {co.title}",
                      {"status": "待业主签认"}, {"status": "已生效", "revisions": revised}, project=self.project)
        return respond(co)


class Reject(ProjectView):
    """AC-F07-05 / AC-F07-06：驳回必须填写理由 → 已驳回，退回项目经理。"""

    def post(self, request, project_id, co_id):
        self.require("change.sign", "只有业主可以驳回变更单")
        reason = str(request.data.get("reason") or "").strip()
        if not reason:
            raise ApiError(400, "VALIDATION_FAILED", "请填写驳回理由", fields=[{"field": "reason", "message": "请填写驳回理由"}])
        if len(reason) > 300:
            raise ApiError(400, "VALIDATION_FAILED", "驳回理由不超过 300 字", fields=[{"field": "reason", "message": "驳回理由不超过 300 字"}])
        with transaction.atomic():
            co = locked(self, co_id)
            if co.status != "待业主签认":
                state_conflict(co)
            co.status = "已驳回"
            co.reject_reason = reason
            co.save()
            change_event(co, request.user, "rejected", {"reason": reason})
            audit.log(request.user, "change.reject", "change_order", co.id, f"{co.code} {co.title}",
                      {"status": "待业主签认"}, {"status": "已驳回", "reason": reason}, project=self.project)
        return respond(co)


class Resubmit(ProjectView):
    """AC-F07-09：已驳回单修改后重新提交，编号不变、round_no+1、清空上一轮定价，原驳回事件保留。"""

    def post(self, request, project_id, co_id):
        self.require("change.create", "只有项目经理可以重新提交变更单")
        fields, items, files = clean_form(self, request.data)
        try:
            with transaction.atomic():
                co = locked(self, co_id)
                if co.status != "已驳回":
                    state_conflict(co)
                co.round_no += 1
                co.price_delta = None
                co.schedule_delta_days = None
                co.cost_bearer = ""
                co.reject_reason = ""
                co.status = "待预算定价"
                apply_form(co, fields, items, files)
                change_event(co, request.user, "resubmitted", snapshot(co))
                audit.log(request.user, "change.resubmit", "change_order", co.id, f"{co.code} {co.title}",
                          {"status": "已驳回", "roundNo": co.round_no - 1}, {"status": co.status, "roundNo": co.round_no},
                          project=self.project)
        except IntegrityError:
            state_conflict(self.obj(ChangeOrder, co_id))
        return respond(co)


class WorkItemOptions(ProjectView):
    """发起表单的受影响工作项候选（楼层 · 房间 · 工作项（工段）），已停用的不列。"""

    def get(self, request, project_id):
        qs = WorkItem.objects.filter(project=self.project, is_disabled=False).select_related("phase", "floor", "room")
        items = [{"id": wi.id, "label": wi_label(wi), "name": wi.name, "phaseName": wi.phase.name,
                  "floorName": wi.floor.name if wi.floor_id else "", "roomName": wi.room.name if wi.room_id else ""}
                 for wi in qs.order_by("floor__order_no", "room__order_no", "phase__order_no", "id")]
        return Response({"items": items})


urlpatterns = [
    path("projects/<int:project_id>/change-orders", ChangeOrders.as_view()),
    path("projects/<int:project_id>/change-orders/work-item-options", WorkItemOptions.as_view()),
    path("projects/<int:project_id>/change-orders/<int:co_id>", ChangeOrderDetail.as_view()),
    path("projects/<int:project_id>/change-orders/<int:co_id>/submit", SubmitDraft.as_view()),
    path("projects/<int:project_id>/change-orders/<int:co_id>/price", Price.as_view()),
    path("projects/<int:project_id>/change-orders/<int:co_id>/sign", Sign.as_view()),
    path("projects/<int:project_id>/change-orders/<int:co_id>/reject", Reject.as_view()),
    path("projects/<int:project_id>/change-orders/<int:co_id>/resubmit", Resubmit.as_view()),
]
