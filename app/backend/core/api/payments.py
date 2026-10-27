"""付款节点（API-F15-01，REQ-F15-01/02）：预算专员维护；列表带关联工段的未放行检查点数和未闭环不一致问题数；
标记已付只提示不拦截，仍有未放行检查点时需带 confirmUnreleased=N 二次确认，确认后留痕（AC-F15-03）。
"""
import datetime
import decimal

from django.db import transaction
from django.urls import path
from django.utils import timezone
from rest_framework.response import Response

from core.api.base import ProjectView, d, iso
from core.errors import ApiError, validation
from core.models import Checkpoint, Issue, PaymentMilestone, Phase
from core.services import audit

OPEN_ISSUE = ["未闭环", "处理中"]


def counts(project, phase_ids):
    """计数口径（PAGE-F15-01 §8）：关联工段（多个求和）内未放行的检查点、未闭环且由不一致核对生成的问题。"""
    unreleased = (Checkpoint.objects.filter(project=project, work_item__phase_id__in=phase_ids, is_draft=False)
                  .exclude(status="已放行").count())
    open_issues = Issue.objects.filter(project=project, phase_id__in=phase_ids, status__in=OPEN_ISSUE,
                                       source_check__isnull=False).count()
    return unreleased, open_issues


def ser(project, m):
    phases = sorted(m.phases.all(), key=lambda p: (p.order_no, p.id)) or [m.phase]
    unreleased, open_issues = counts(project, [p.id for p in phases])
    return {"id": m.id, "name": m.name, "amount": int(m.amount) if m.amount == int(m.amount) else str(m.amount),
            "plannedOn": d(m.planned_on), "phases": [{"id": p.id, "name": p.name, "colorVar": p.color_var} for p in phases],
            "unreleased": unreleased, "openIssues": open_issues, "status": m.status, "paidAt": iso(m.paid_at),
            "paidBy": m.paid_by.name if m.paid_by else None, "paidConfirmedUnreleased": m.paid_confirmed_unreleased}


def parse(project, data):
    errs = []
    name = str(data.get("name", "")).strip()
    if not name:
        errs.append(("name", "请填写节点名称"))
    elif len(name) > 60:
        errs.append(("name", "节点名称不能超过 60 字"))
    amount = None
    try:
        amount = decimal.Decimal(str(data.get("amount", "")).replace(",", ""))
        if amount <= 0 or amount != amount.to_integral_value():
            amount = None
    except decimal.InvalidOperation:
        amount = None
    if amount is None:
        errs.append(("amount", "请填写大于 0 的金额"))
    planned = None
    try:
        planned = datetime.date.fromisoformat(str(data.get("plannedOn", "")))
    except ValueError:
        errs.append(("plannedOn", "请选择计划日期"))
    ids = []
    try:
        ids = [int(x) for x in (data.get("phaseIds") or [])]
    except (TypeError, ValueError):
        ids = []
    phases = list(Phase.objects.filter(project=project, pk__in=ids).order_by("order_no", "id"))
    if not phases or len(phases) != len(set(ids)):
        errs.append(("phaseIds", "请至少选择 1 个关联工段"))
    validation(errs)
    return {"name": name, "amount": amount, "planned_on": planned}, phases


def snapshot(m, phases):
    return {"name": m.name, "amount": str(m.amount), "plannedOn": d(m.planned_on), "phases": [p.name for p in phases]}


class Payments(ProjectView):
    def get(self, request, project_id):
        qs = (PaymentMilestone.objects.filter(project=self.project).select_related("phase", "paid_by")
              .prefetch_related("phases").order_by("planned_on", "id"))
        items = [ser(self.project, m) for m in qs]
        return Response({"items": items, "total": len(items), "paidCount": sum(1 for x in items if x["status"] == "已付")})

    @transaction.atomic
    def post(self, request, project_id):
        self.require("payment.edit")
        fields, phases = parse(self.project, request.data or {})
        m = PaymentMilestone.objects.create(project=self.project, phase=phases[0], status="未付", **fields)
        m.phases.set(phases)
        audit.log(request.user, "新增", "付款节点", m.id, m.name, None, {**snapshot(m, phases), "status": "未付"}, project=self.project)
        return Response(ser(self.project, m), status=201)


class PaymentDetail(ProjectView):
    http_method_names = ["get", "patch"]

    def get(self, request, project_id, mid):
        return Response(ser(self.project, self.obj(PaymentMilestone, mid)))

    @transaction.atomic
    def patch(self, request, project_id, mid):
        self.require("payment.edit")
        m = PaymentMilestone.objects.select_for_update().filter(pk=mid, project=self.project).first()
        if m is None:
            raise ApiError(404, "NOT_FOUND", "付款节点不存在")
        if m.status == "已付":
            raise ApiError(409, "PAYMENT_PAID", "已付节点不能修改")
        old_phases = sorted(m.phases.all(), key=lambda p: (p.order_no, p.id)) or [m.phase]
        before = snapshot(m, old_phases)
        fields, phases = parse(self.project, {**{"name": m.name, "amount": str(m.amount), "plannedOn": d(m.planned_on),
                                                 "phaseIds": [p.id for p in old_phases]}, **(request.data or {})})
        for k, v in fields.items():
            setattr(m, k, v)
        m.phase = phases[0]
        m.save()
        m.phases.set(phases)
        after = snapshot(m, phases)
        changed = [k for k in after if before[k] != after[k]]
        if changed:
            audit.log(request.user, "修改", "付款节点", m.id, m.name, {k: before[k] for k in changed}, {k: after[k] for k in changed},
                      project=self.project)
        return Response(ser(self.project, m))


class MarkPaid(ProjectView):
    @transaction.atomic
    def post(self, request, project_id, mid):
        self.require("payment.edit")
        m = PaymentMilestone.objects.select_for_update().filter(pk=mid, project=self.project).first()
        if m is None:
            raise ApiError(404, "NOT_FOUND", "付款节点不存在")
        if m.status == "已付":
            who = m.paid_by.name if m.paid_by else ""
            raise ApiError(409, "ALREADY_PAID", f"已由{who}于 {iso(m.paid_at)} 标记已付", details={"by": who, "at": iso(m.paid_at)})
        phase_ids = list(m.phases.values_list("id", flat=True)) or [m.phase_id]
        unreleased, open_issues = counts(self.project, phase_ids)
        confirm = (request.data or {}).get("confirmUnreleased")
        if unreleased and str(confirm) != str(unreleased):
            # 只提示不拦截：服务端返回 N，前端二次确认后带 confirmUnreleased=N 再提交（API-F15-01）
            raise ApiError(409, "CONFIRM_UNRELEASED", f"还有 {unreleased} 个检查点未放行，确认标记已付？",
                           details={"unreleased": unreleased, "openIssues": open_issues})
        m.status = "已付"
        m.paid_at = timezone.now()
        m.paid_by = request.user
        m.paid_confirmed_unreleased = unreleased
        m.save(update_fields=["status", "paid_at", "paid_by", "paid_confirmed_unreleased"])
        audit.log(request.user, "状态变更", "付款节点", m.id, m.name, {"status": "未付"},
                  {"status": "已付", "确认时未放行检查点": unreleased, "确认时未闭环不一致": open_issues}, project=self.project)
        return Response(ser(self.project, m))


urlpatterns = [
    path("projects/<int:project_id>/payments", Payments.as_view()),
    path("projects/<int:project_id>/payments/<int:mid>", PaymentDetail.as_view()),
    path("projects/<int:project_id>/payments/<int:mid>/mark-paid", MarkPaid.as_view()),
]
