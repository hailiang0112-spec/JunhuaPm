"""问题（API-F08-01）：台账筛选与超期排序、手工登记、原因与处置建议、补充对策与指派、闭环 / 重开 / 作废，
以及从问题一键生成变更单草稿（DEC-083，复用 shared.create_change_draft）。

状态迁移（技术方案 §5.1.5）：未闭环 →(闭环)→ 已闭环 →(重开)→ 处理中 →(闭环)→ 已闭环；未闭环或处理中 →(作废)→ 已作废。
每次变化都用 shared.issue_event 追加留痕并入链。
"""
import datetime

from django.db import transaction
from django.db.models import Case, F, IntegerField, Q, Value, When
from django.urls import path
from django.utils import timezone
from rest_framework.response import Response

from core.api.base import ProjectView, d, iso, paginate, user_brief
from core.api.changes import role_label
from core.errors import ApiError, fail, validation
from core.models import (ChangeOrder, CheckRecord, DiscoveryCorrection, Floor, Issue, Phase, Project,
                         ProjectMemberRole, Room)
from core.services import audit, storage
from core.services.shared import create_change_draft, issue_event, next_issue_seq

OPEN = ("未闭环", "处理中")
SUGGESTIONS = {  # AC-F08-02
    "设计已改但未签变更单": "补签变更单（可一键生成变更单草稿）",
    "施工偏离签认图": "返工后复核",
    "图纸本身未表达清楚": "设计经理出新版或书面澄清",
}
EVENT_LABELS = {"created": "生成问题", "cause_set": "选择原因", "measure": "补充对策", "assign": "指派负责人",
                "closed": "标记已闭环", "reopened": "重新打开，清除闭环日期", "voided": "作废", "change_draft": "生成变更单草稿"}
# 问题事件操作人的角色标签优先级
KIND_ROLE = {"cause_set": "qc", "closed": None, "reopened": None, "change_draft": "pm"}


def today():
    return timezone.localdate()


def overdue_days(issue, now=None):
    """AC-F08-04：超期天数 = 今天 − 要求闭环日期，仅未闭环 / 处理中且已过期时为正。"""
    now = now or today()
    if issue.status in OPEN and issue.due_date and issue.due_date < now:
        return (now - issue.due_date).days
    return 0


def latest_check(cp):
    if cp is None:
        return None
    if cp.latest_check_id:
        return cp.latest_check
    return CheckRecord.objects.filter(checkpoint=cp).order_by("-checked_at", "-id").first()


def issue_dict(i, now=None):
    cp = i.checkpoint
    lc = latest_check(cp) if cp else None
    return {
        "id": i.id, "code": i.code, "seqNo": i.seq_no, "description": i.description, "level": i.level,
        "countermeasure": i.countermeasure, "ownerName": i.owner_name, "foundOn": d(i.found_on), "dueDate": d(i.due_date),
        "overdueDays": overdue_days(i, now), "cause": i.cause, "suggestion": SUGGESTIONS.get(i.cause, ""),
        "status": i.status, "closedOn": d(i.closed_on), "voidReason": i.void_reason, "source": i.source,
        "isMismatch": bool(cp),
        "sourceLabel": f"不一致 {cp.code}" if cp else "手工登记",
        "phase": {"id": i.phase.id, "name": i.phase.name} if i.phase_id else None,
        "floor": {"id": i.floor.id, "name": i.floor.name} if i.floor_id else None,
        "room": {"id": i.room.id, "name": i.room.name} if i.room_id else None,
        "workItem": {"id": i.work_item.id, "name": i.work_item.name} if i.work_item_id else None,
        "checkpoint": ({"id": cp.id, "code": cp.code, "point": cp.point, "status": cp.status,
                        "latestConclusion": lc.conclusion if lc else None} if cp else None),
        "createdBy": user_brief(i.created_by), "createdAt": iso(i.created_at),
    }


def issue_detail(i):
    out = issue_dict(i)
    sc = i.source_check
    if sc:
        corr = DiscoveryCorrection.objects.filter(check_record=sc).order_by("-at", "-id").first()
        out["sourceCheck"] = {"id": sc.id, "checkedAt": iso(sc.checked_at), "conclusion": sc.conclusion,
                              "discoveryPhase": corr.after if corr else sc.discovery_phase, "note": sc.note,
                              "checker": user_brief(sc.checker),
                              "photos": [storage.file_dict(p.file) for p in sc.photos.select_related("file").order_by("id")]}
    else:
        out["sourceCheck"] = None
    out["events"] = [{"id": e.id, "kind": e.kind, "label": EVENT_LABELS.get(e.kind, e.kind), "before": e.before,
                      "after": e.after, "reason": e.reason, "actor": user_brief(e.actor),
                      "actorRole": role_label(e.actor, i.project, KIND_ROLE.get(e.kind)), "at": iso(e.at)}
                     for e in i.events.select_related("actor").order_by("at", "id")]
    out["changeOrders"] = [{"id": c.id, "code": c.code, "status": c.status}
                           for c in ChangeOrder.objects.filter(source_issue=i).order_by("id")]
    return out


def base_qs(project):
    return Issue.objects.filter(project=project).select_related(
        "phase", "floor", "room", "work_item", "checkpoint__latest_check", "created_by", "project")


def parse_date(v):
    try:
        return datetime.date.fromisoformat(str(v))
    except (TypeError, ValueError):
        return None


class Issues(ProjectView):
    def get(self, request, project_id):
        qs = base_qs(self.project)
        st = request.GET.get("status") or "valid"
        if st == "valid":
            qs = qs.exclude(status="已作废")  # 已作废只在「已作废」筛选中可见（AC-F08-07）
        elif st != "all":
            qs = qs.filter(status=st)
        src = request.GET.get("source")
        if src == "check":
            qs = qs.filter(checkpoint__isnull=False)
        elif src == "manual":
            qs = qs.filter(checkpoint__isnull=True)
        if request.GET.get("level"):
            qs = qs.filter(level=request.GET["level"])
        if request.GET.get("phaseId", "").isdigit():
            qs = qs.filter(phase_id=int(request.GET["phaseId"]))
        kw = request.GET.get("q", "").strip()
        if kw:
            qs = qs.filter(Q(description__icontains=kw) | Q(checkpoint__code__icontains=kw))
        # 未闭环与处理中在前，按超期天数从大到小（= 要求闭环日期从早到晚）；已闭环、已作废在后
        qs = qs.annotate(grp=Case(When(status__in=OPEN, then=Value(0)), When(status="已闭环", then=Value(1)),
                                  default=Value(2), output_field=IntegerField()))
        qs = qs.order_by("grp", F("due_date").asc(nulls_last=True), "-seq_no")
        now = today()
        out = paginate(request, qs, lambda x: issue_dict(x, now))
        valid_open = Issue.objects.filter(project=self.project, status__in=OPEN)  # 作废问题不计入统计
        out["counts"] = {"open": valid_open.count(), "overdue": valid_open.filter(due_date__lt=now).count(),
                         "closed": Issue.objects.filter(project=self.project, status="已闭环").count()}
        out["today"] = d(now)
        return Response(out)

    def post(self, request, project_id):
        """AC-F08-03 / DEC-081：描述、等级、工段、楼层、房间、要求闭环日期必填；对策、负责人可空。"""
        self.require("issue.create")
        data = request.data
        errs = []
        desc = str(data.get("description") or "").strip()
        level = str(data.get("level") or "")
        phase = Phase.objects.filter(project=self.project, pk=data.get("phaseId") or 0).first() if str(data.get("phaseId") or "").isdigit() else None
        due = parse_date(data.get("dueDate"))
        floor = Floor.objects.filter(project=self.project, pk=data.get("floorId")).first() if str(data.get("floorId") or "").isdigit() else None
        room = Room.objects.filter(project=self.project, pk=data.get("roomId")).first() if str(data.get("roomId") or "").isdigit() else None
        if not desc:
            errs.append(("description", "请填写问题描述"))
        if level not in Issue.LEVELS:
            errs.append(("level", "请选择等级"))
        if not phase:
            errs.append(("phaseId", "请选择所属工段"))
        if not due:
            errs.append(("dueDate", "请选择要求闭环日期"))
        if not floor:
            errs.append(("floorId", "请选择楼层"))
        if not room:
            errs.append(("roomId", "请选择房间"))
        elif floor and room.floor_id != floor.id:
            errs.append(("roomId", "房间与楼层不匹配"))
        validation(errs)
        measure = str(data.get("countermeasure") or "").strip() or "待补充对策"
        owner = str(data.get("ownerName") or "").strip()[:40] or "待指派"
        with transaction.atomic():
            Project.objects.select_for_update().get(pk=self.project.pk)  # 串行化项目内序号
            issue = Issue.objects.create(project=self.project, seq_no=next_issue_seq(self.project), phase=phase,
                                         floor=floor, room=room, description=desc, level=level, countermeasure=measure,
                                         owner_name=owner, found_on=today(), due_date=due, status="未闭环",
                                         source="manual", created_by=request.user)
            issue_event(issue, request.user, "created", after="未闭环")
            audit.log(request.user, "issue.create", "issue", issue.id, f"{issue.code} {desc[:60]}", None,
                      {"status": "未闭环", "level": level, "countermeasure": measure, "ownerName": owner}, project=self.project)
        return Response(issue_detail(base_qs(self.project).get(pk=issue.pk)), status=201)


class IssueOptions(ProjectView):
    """登记表单与指派的候选：工段、楼层及其房间、项目成员姓名。"""

    def get(self, request, project_id):
        phases = [{"id": p.id, "name": p.name} for p in Phase.objects.filter(project=self.project, is_disabled=False).order_by("order_no", "id")]
        floors = []
        for f in Floor.objects.filter(project=self.project, is_disabled=False).order_by("order_no", "id"):
            floors.append({"id": f.id, "name": f.name,
                           "rooms": [{"id": r.id, "name": r.name} for r in f.rooms.filter(is_disabled=False).order_by("order_no", "id")]})
        names = []
        for r in ProjectMemberRole.objects.filter(project=self.project, role__in=["pm", "design_manager", "qc", "budget"]).select_related("user").order_by("id"):
            if r.user.name not in names:
                names.append(r.user.name)
        return Response({"phases": phases, "floors": floors, "members": names, "levels": Issue.LEVELS,
                         "causes": [{"cause": c, "suggestion": s} for c, s in SUGGESTIONS.items()]})


class IssueAction(ProjectView):
    def locked(self, issue_id):
        i = self.obj(Issue, issue_id)
        return Issue.objects.select_for_update().get(pk=i.pk)

    def done(self, issue):
        return Response(issue_detail(base_qs(self.project).get(pk=issue.pk)))

    def conflict(self, issue, message):
        last = issue.events.select_related("actor").order_by("-at", "-id").first()
        details = {"status": issue.status}
        if last:
            details.update({"by": last.actor.name, "at": iso(last.at)})
        raise ApiError(409, "ISSUE_STATE", message, details=details)


class IssueDetail(IssueAction):
    def get(self, request, project_id, issue_id):
        return Response(issue_detail(base_qs(self.project).get(pk=self.obj(Issue, issue_id).pk)))


class SetCause(IssueAction):
    """AC-F08-02：质检选原因（三选一），返回处置建议。"""

    def post(self, request, project_id, issue_id):
        self.require("issue.cause", "只有质检可以选择不一致原因")
        cause = str(request.data.get("cause") or "")
        if cause not in SUGGESTIONS:
            validation([("cause", "请选择不一致原因")])
        with transaction.atomic():
            issue = self.locked(issue_id)
            if not issue.checkpoint_id:
                fail("NOT_MISMATCH", "只有核对不一致生成的问题需要选择原因", 422)
            if issue.status == "已作废":
                self.conflict(issue, "问题已作废，不能修改")
            before = issue.cause
            if before != cause:
                issue.cause = cause
                issue.save(update_fields=["cause"])
                issue_event(issue, request.user, "cause_set", before=before, after=cause)
                audit.log(request.user, "issue.cause", "issue", issue.id, issue.code, {"cause": before}, {"cause": cause},
                          project=self.project)
        return self.done(issue)


class Assign(IssueAction):
    """DEC-082：项目经理、质检补充对策与指派负责人，每次变化追加留痕。"""

    def post(self, request, project_id, issue_id):
        self.require("issue.assign", "只有项目经理或质检可以补充对策和指派")
        data = request.data
        with transaction.atomic():
            issue = self.locked(issue_id)
            if issue.status not in OPEN:
                self.conflict(issue, f"问题{issue.status}，不能修改对策或负责人")
            before = {"countermeasure": issue.countermeasure, "ownerName": issue.owner_name}
            changed = False
            if "countermeasure" in data:
                m = str(data.get("countermeasure") or "").strip() or "待补充对策"
                if m != issue.countermeasure:
                    issue_event(issue, request.user, "measure", before=issue.countermeasure[:40], after=m[:40], reason=m[:300])
                    issue.countermeasure = m
                    changed = True
            if "ownerName" in data:
                o = str(data.get("ownerName") or "").strip()[:40] or "待指派"
                if o != issue.owner_name:
                    issue_event(issue, request.user, "assign", before=issue.owner_name, after=o)
                    issue.owner_name = o
                    changed = True
            if changed:
                issue.save(update_fields=["countermeasure", "owner_name"])
                audit.log(request.user, "issue.assign", "issue", issue.id, issue.code, before,
                          {"countermeasure": issue.countermeasure, "ownerName": issue.owner_name}, project=self.project)
        return self.done(issue)


class Close(IssueAction):
    """AC-F08-05 / AC-F08-06：闭环记当天；不一致问题须检查点最新结论为一致或已变更。"""

    def post(self, request, project_id, issue_id):
        self.require("issue.close", "只有项目经理或质检可以闭环问题")
        with transaction.atomic():
            issue = self.locked(issue_id)
            if issue.status not in OPEN:
                self.conflict(issue, "问题已闭环" if issue.status == "已闭环" else "问题已作废，不能闭环")
            if issue.checkpoint_id:
                lc = latest_check(issue.checkpoint)
                if not lc or lc.conclusion not in ("一致", "已变更"):
                    raise ApiError(422, "NEEDS_RECHECK", "请先由质检复核为一致或已变更")
            before = issue.status
            issue.status = "已闭环"
            issue.closed_on = today()
            issue.save(update_fields=["status", "closed_on"])
            issue_event(issue, request.user, "closed", before=before, after="已闭环")
            audit.log(request.user, "issue.close", "issue", issue.id, issue.code, {"status": before},
                      {"status": "已闭环", "closedOn": d(issue.closed_on)}, project=self.project)
        return self.done(issue)


class Reopen(IssueAction):
    def post(self, request, project_id, issue_id):
        self.require("issue.close", "只有项目经理或质检可以重新打开问题")
        with transaction.atomic():
            issue = self.locked(issue_id)
            if issue.status != "已闭环":
                self.conflict(issue, "只有已闭环的问题可以重新打开")
            closed_on = issue.closed_on
            issue.status = "处理中"
            issue.closed_on = None
            issue.save(update_fields=["status", "closed_on"])
            issue_event(issue, request.user, "reopened", before="已闭环", after="处理中")
            audit.log(request.user, "issue.reopen", "issue", issue.id, issue.code,
                      {"status": "已闭环", "closedOn": d(closed_on)}, {"status": "处理中", "closedOn": None}, project=self.project)
        return self.done(issue)


class Void(IssueAction):
    """AC-F08-07：问题不能删除，只能填写理由作废；作废后不计入统计，仍可在筛选中查看。"""

    def post(self, request, project_id, issue_id):
        self.require("issue.void")
        reason = str(request.data.get("reason") or "").strip()
        if not reason:
            raise ApiError(400, "VALIDATION_FAILED", "请填写作废理由", fields=[{"field": "reason", "message": "请填写作废理由"}])
        if len(reason) > 200:
            raise ApiError(400, "VALIDATION_FAILED", "作废理由不超过 200 字", fields=[{"field": "reason", "message": "作废理由不超过 200 字"}])
        with transaction.atomic():
            issue = self.locked(issue_id)
            if issue.status == "已作废":
                self.conflict(issue, "问题已作废")
            before = issue.status
            issue.status = "已作废"
            issue.void_reason = reason
            issue.save(update_fields=["status", "void_reason"])
            issue_event(issue, request.user, "voided", before=before, after="已作废", reason=reason)
            audit.log(request.user, "issue.void", "issue", issue.id, issue.code, {"status": before},
                      {"status": "已作废", "reason": reason}, project=self.project)
        return self.done(issue)


class ChangeDraft(IssueAction):
    """AC-F08-02 / DEC-083：从问题一键生成变更单草稿（立即分配编号，DEC-071）。已有未驳回的关联变更单时直接返回它。"""

    def post(self, request, project_id, issue_id):
        self.require("change.create", "只有项目经理可以生成变更单草稿")
        with transaction.atomic():
            issue = self.locked(issue_id)
            if issue.status == "已作废":
                self.conflict(issue, "问题已作废")
            existing = ChangeOrder.objects.filter(source_issue=issue).exclude(status="已驳回").order_by("-id").first()
            if existing:
                return Response({"id": existing.id, "code": existing.code, "status": existing.status, "existing": True})
            label = f"问题 {issue.code}" + (f"（检查点 {issue.checkpoint.code} 核对不一致）" if issue.checkpoint_id else "")
            file_ids = list(issue.source_check.photos.values_list("file_id", flat=True)) if issue.source_check_id else []
            co = create_change_draft(self.project, request.user, title=issue.description,
                                     content=f"{issue.description}\n来源：{label}",
                                     work_item_ids=[issue.work_item_id] if issue.work_item_id else [],
                                     file_ids=file_ids, source_issue=issue)
            issue_event(issue, request.user, "change_draft", after=co.code)
            audit.log(request.user, "change.draft", "change_order", co.id, co.code, None,
                      {"status": "草稿", "sourceIssue": issue.code}, project=self.project)
        return Response({"id": co.id, "code": co.code, "status": co.status, "existing": False}, status=201)


urlpatterns = [
    path("projects/<int:project_id>/issues", Issues.as_view()),
    path("projects/<int:project_id>/issues/options", IssueOptions.as_view()),
    path("projects/<int:project_id>/issues/<int:issue_id>", IssueDetail.as_view()),
    path("projects/<int:project_id>/issues/<int:issue_id>/cause", SetCause.as_view()),
    path("projects/<int:project_id>/issues/<int:issue_id>/assign", Assign.as_view()),
    path("projects/<int:project_id>/issues/<int:issue_id>/close", Close.as_view()),
    path("projects/<int:project_id>/issues/<int:issue_id>/reopen", Reopen.as_view()),
    path("projects/<int:project_id>/issues/<int:issue_id>/void", Void.as_view()),
    path("projects/<int:project_id>/issues/<int:issue_id>/change-order-draft", ChangeDraft.as_view()),
]
