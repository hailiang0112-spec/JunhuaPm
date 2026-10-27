"""公司检查经验库（F09，API-F09-01）。

- 提交：质检从已闭环的不一致问题提交，服务端按白名单字段生成条目并脱敏（AC-F09-01）。
- 审核：公司内任一质检（在任一项目担任质检即视为公司级质检）审核并选择状态（AC-F09-02）。
- 修改：每次修改追加新版本，旧版本可查（AC-F09-03）；版本表只追加。
- 推荐：按工段列出已审核条目，按「已验证、历史观察、未验证经验」排序（AC-F09-04）。
"""
import re

from django.db import transaction
from django.db.models import Case, IntegerField, Q, Value, When
from django.urls import path
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api.base import ProjectView, iso, paginate
from core.errors import fail, forbidden, validation
from core.models import (CheckPhoto, ExperienceEntry, ExperienceVersion, Issue, Phase, ProjectMemberRole, Template)
from core.services import audit
from core.services.projects import default_company

REVIEWED = ["已验证", "历史观察", "未验证经验"]  # 同时也是推荐与列表排序
PENDING = "待审核"
ISSUE_TYPES = Issue.CAUSES
STATUS_RANK = Case(*[When(status=s, then=Value(i)) for i, s in enumerate(REVIEWED)], default=Value(9),
                   output_field=IntegerField())
PHONE_RE = re.compile(r"1\d{10}")


def is_company_qc(user):
    """公司级质检身份：在任一项目担任质检（AC-F09-02「公司内任一质检」）。"""
    return ProjectMemberRole.objects.filter(user=user, role="qc").exists()


def require_qc(user, message):
    if not is_company_qc(user):
        forbidden(message)


def scrubber(project):
    """脱敏：去掉业主方姓名、项目名称与地址、手机号（AC-F09-01）。"""
    names = set(ProjectMemberRole.objects.filter(project=project, role__in=["owner", "owner_member", "owner_agent"])
                .values_list("user__name", flat=True))
    words = sorted({w for w in [project.name, project.address, *names] if w}, key=len, reverse=True)

    def clean(text):
        text = str(text or "")
        for w in words:
            text = text.replace(w, "业主" if w in names else "")
        return PHONE_RE.sub("***", text).strip()
    return clean


def phase_colors():
    tpl = Template.objects.filter(company=default_company()).order_by("id").first()
    phases = (tpl.content or {}).get("phases", []) if tpl else []
    return {p["name"]: f"--phase-{i % 6 + 1}" for i, p in enumerate(phases)}


def version_dict(v):
    return {"verNo": v.ver_no, "phaseName": v.phase_name, "process": v.process, "issueType": v.issue_type,
            "checkPoint": v.check_point, "countermeasure": v.countermeasure, "photoCount": len(v.photo_file_ids or []),
            "status": v.status, "changeNote": v.change_note, "author": v.author.name, "at": iso(v.at)}


def entry_dict(e, colors, can_edit=False):
    v = e.current_version
    return {"id": e.id, "status": e.status, **{k: x for k, x in version_dict(v).items() if k != "status"},
            "colorVar": colors.get(v.phase_name, "--phase-1"),
            "reviewer": e.reviewer.name if e.reviewer else None, "reviewedAt": iso(e.reviewed_at),
            "submitter": e.submitter.name, "createdAt": iso(e.created_at), "fromIssue": bool(e.source_issue_id),
            "canEdit": can_edit and e.status != PENDING, "canReview": can_edit and e.status == PENDING}


def _clean_fields(data, clean, require_note=False, require_status=False):
    errs = []
    process = clean(data.get("process"))
    issue_type = str(data.get("issueType") or "").strip()
    check_point = clean(data.get("checkPoint"))
    countermeasure = clean(data.get("countermeasure"))
    if not process:
        errs.append(("process", "请填写工序"))
    if not issue_type:
        errs.append(("issueType", "请选择问题类型"))
    if not check_point:
        errs.append(("checkPoint", "请填写检查要点"))
    if not countermeasure:
        errs.append(("countermeasure", "请填写对策"))
    status = data.get("status")
    if require_status and status not in REVIEWED:
        errs.append(("status", "请选择状态"))
    note = str(data.get("changeNote") or "").strip()
    if require_note and not note:
        errs.append(("changeNote", "请填写修改说明"))
    validation(errs)
    return {"process": process[:60], "issue_type": issue_type[:60], "check_point": check_point,
            "countermeasure": countermeasure, "status": status, "change_note": note[:200]}


def _append_version(entry, actor, **fields):
    last = entry.current_version
    v = ExperienceVersion.objects.create(
        entry=entry, ver_no=(last.ver_no + 1) if last else 1, author=actor,
        phase_name=fields.get("phase_name", last.phase_name if last else ""),
        process=fields.get("process", last.process if last else ""),
        issue_type=fields.get("issue_type", last.issue_type if last else ""),
        check_point=fields.get("check_point", last.check_point if last else ""),
        countermeasure=fields.get("countermeasure", last.countermeasure if last else ""),
        photo_file_ids=fields.get("photo_file_ids", last.photo_file_ids if last else []),
        status=fields["status"], change_note=fields.get("change_note", ""))
    entry.current_version = v
    entry.status = fields["status"]
    return v


class SubmitFromIssue(ProjectView):
    """POST /api/projects/{pid}/issues/{iid}/experience：从已闭环的不一致问题提交（AC-F09-01）。"""

    def get(self, request, project_id, issue_id):
        """提交前的预填（已脱敏）与可选照片。"""
        self.require("experience.submit", "只有质检可以提交经验条目")
        issue = self.obj(Issue, issue_id)
        clean = scrubber(self.project)
        wi = issue.work_item
        photos = []
        if issue.source_check_id:
            photos = [{"id": ph.file_id, "thumbUrl": f"/api/files/{ph.file_id}/thumb"}
                      for ph in CheckPhoto.objects.filter(check_record_id=issue.source_check_id)]
        return Response({"phaseName": issue.phase.name if issue.phase else (wi.phase.name if wi else ""),
                         "process": clean(wi.name if wi else ""), "issueType": issue.cause,
                         "checkPoint": clean(issue.checkpoint.point if issue.checkpoint else ""),
                         "countermeasure": clean(issue.countermeasure if issue.countermeasure != "待补充对策" else ""),
                         "issueTypes": ISSUE_TYPES, "photos": photos,
                         "submitted": ExperienceEntry.objects.filter(source_issue=issue).exists()})

    def post(self, request, project_id, issue_id):
        self.require("experience.submit", "只有质检可以提交经验条目")
        clean = scrubber(self.project)
        with transaction.atomic():
            issue = Issue.objects.select_for_update().filter(pk=issue_id, project=self.project).first()
            if issue is None:
                fail("NOT_FOUND", "记录不存在", 404)
            if issue.status != "已闭环" or not (issue.source_check_id or issue.checkpoint_id):
                fail("EXPERIENCE_SOURCE", "只有已闭环的不一致问题可以提交到经验库", 422)
            if ExperienceEntry.objects.filter(source_issue=issue).exists():
                fail("EXPERIENCE_EXISTS", "该问题已提交到经验库", 409)
            wi = issue.work_item
            data = {"process": request.data.get("process") or (wi.name if wi else ""),
                    "issueType": request.data.get("issueType") or issue.cause,
                    "checkPoint": request.data.get("checkPoint") or (issue.checkpoint.point if issue.checkpoint else ""),
                    "countermeasure": request.data.get("countermeasure")
                    or (issue.countermeasure if issue.countermeasure != "待补充对策" else "")}
            f = _clean_fields(data, clean)
            # 照片默认不带；质检可另行选择附带该问题核对记录中的照片
            allowed = set(CheckPhoto.objects.filter(check_record_id=issue.source_check_id).values_list("file_id", flat=True)) \
                if issue.source_check_id else set()
            photo_ids = [int(x) for x in request.data.get("photoFileIds") or [] if str(x).isdigit()]
            if any(x not in allowed for x in photo_ids):
                validation([("photoFileIds", "只能附带该问题核对记录中的照片")])
            phase_name = issue.phase.name if issue.phase else (wi.phase.name if wi else "")
            entry = ExperienceEntry.objects.create(company=self.project.company, status=PENDING, source_issue=issue,
                                                   submitter=request.user)
            _append_version(entry, request.user, phase_name=phase_name, process=f["process"], issue_type=f["issue_type"],
                            check_point=f["check_point"], countermeasure=f["countermeasure"], photo_file_ids=photo_ids,
                            status=PENDING, change_note="从已闭环的不一致问题提交")
            entry.save()
            audit.log(request.user, "experience.submit", "experience", entry.id, f"{phase_name} · {f['process']}",
                      None, {"issue": issue.code}, project=self.project)
        return Response(entry_dict(entry, phase_colors(), True), status=201)


class Experiences(APIView):
    """GET /api/experience?tab=reviewed|pending&phase=&status=&q=&page="""

    def get(self, request):
        qc = is_company_qc(request.user)
        tab = request.GET.get("tab", "reviewed")
        base = ExperienceEntry.objects.filter(company=default_company()).select_related(
            "current_version__author", "reviewer", "submitter")
        if tab == "pending":
            if not qc:
                forbidden("只有质检可以查看待审核条目")
            qs = base.filter(status=PENDING).order_by("-created_at", "-id")
        else:
            qs = base.filter(status__in=REVIEWED)
            phase = request.GET.get("phase")
            if phase:
                qs = qs.filter(current_version__phase_name=phase)
            status = request.GET.get("status")
            if status:
                qs = qs.filter(status=status)
            q = request.GET.get("q", "").strip()
            if q:
                qs = qs.filter(Q(current_version__process__icontains=q) | Q(current_version__check_point__icontains=q)
                               | Q(current_version__countermeasure__icontains=q)
                               | Q(current_version__issue_type__icontains=q))
            qs = qs.annotate(rank=STATUS_RANK).order_by("rank", "-reviewed_at", "-id")
        colors = phase_colors()
        page = paginate(request, qs, lambda e: entry_dict(e, colors, qc))
        page.update({
            "reviewedTotal": base.filter(status__in=REVIEWED).count(),
            "pendingCount": base.filter(status=PENDING).count() if qc else None,
            "isQc": qc, "phases": [{"name": n, "colorVar": c} for n, c in colors.items()],
            "statuses": REVIEWED, "issueTypes": ISSUE_TYPES,
        })
        return Response(page)


def _entry(pk):
    e = (ExperienceEntry.objects.filter(pk=pk, company=default_company())
         .select_related("current_version__author", "reviewer", "submitter").first())
    if e is None:
        fail("NOT_FOUND", "记录不存在", 404)
    return e


class Review(APIView):
    """POST /api/experience/{id}/review {status}：审核通过即对公司全部项目可见（AC-F09-02）。"""

    def post(self, request, pk):
        require_qc(request.user, "只有质检可以审核经验条目")
        status = request.data.get("status")
        if status not in REVIEWED:
            validation([("status", "请选择状态")])
        with transaction.atomic():
            e = ExperienceEntry.objects.select_for_update().filter(pk=pk, company=default_company()).first()
            if e is None:
                fail("NOT_FOUND", "记录不存在", 404)
            if e.status != PENDING:
                fail("ALREADY_REVIEWED", f"该条目已由 {e.reviewer.name if e.reviewer else '其他质检'} 审核", 409,
                     by=e.reviewer.name if e.reviewer else None, at=iso(e.reviewed_at))
            e.reviewer, e.reviewed_at = request.user, timezone.now()
            _append_version(e, request.user, status=status, change_note=f"审核通过，状态：{status}")
            e.save()
            audit.log(request.user, "experience.review", "experience", e.id, e.current_version.process,
                      {"status": PENDING}, {"status": status})
        e = _entry(pk)
        return Response(entry_dict(e, phase_colors(), True))


class Versions(APIView):
    def get(self, request, pk):
        e = _entry(pk)
        if e.status == PENDING and not is_company_qc(request.user):
            fail("NOT_FOUND", "记录不存在", 404)  # 审核前不对其他人可见（DEC-114）
        vs = e.versions.select_related("author").order_by("-ver_no")
        return Response({"items": [version_dict(v) for v in vs], "current": e.current_version.ver_no})

    def post(self, request, pk):
        """修改已审核条目：内容与状态一起保存为新版本，必须填写修改说明（AC-F09-03、DEC-114）。"""
        require_qc(request.user, "只有质检可以修改经验条目")
        with transaction.atomic():
            e = ExperienceEntry.objects.select_for_update().filter(pk=pk, company=default_company()).first()
            if e is None:
                fail("NOT_FOUND", "记录不存在", 404)
            if e.status == PENDING:
                fail("EXPERIENCE_PENDING", "待审核条目请先审核", 409)
            clean = scrubber(e.source_issue.project) if e.source_issue_id else (lambda t: str(t or "").strip())
            data = dict(request.data)
            data.setdefault("status", e.status)
            f = _clean_fields(data, clean, require_note=True, require_status=True)
            before = e.current_version.ver_no
            v = _append_version(e, request.user, process=f["process"], issue_type=f["issue_type"],
                                check_point=f["check_point"], countermeasure=f["countermeasure"], status=f["status"],
                                change_note=f["change_note"])
            e.save()
            audit.log(request.user, "experience.revise", "experience", e.id, v.process, {"verNo": before},
                      {"verNo": v.ver_no, "status": v.status})
        e = _entry(pk)
        return Response(entry_dict(e, phase_colors(), True))


class Suggestions(ProjectView):
    """GET /api/projects/{pid}/experience/suggestions?phaseId=：新建检查点时按工段推荐（AC-F09-04）。"""

    def get(self, request, project_id):
        raw = str(request.GET.get("phaseId") or "")
        phase = self.obj(Phase, int(raw) if raw.isdigit() else 0)
        qs = (ExperienceEntry.objects.filter(company=self.project.company, status__in=REVIEWED,
                                             current_version__phase_name=phase.name)
              .select_related("current_version__author", "reviewer", "submitter")
              .annotate(rank=STATUS_RANK).order_by("rank", "-reviewed_at", "-id"))
        colors = phase_colors()
        return Response({"phaseName": phase.name, "items": [entry_dict(e, colors) for e in qs]})


urlpatterns = [
    path("experience", Experiences.as_view()),
    path("experience/<int:pk>/review", Review.as_view()),
    path("experience/<int:pk>/versions", Versions.as_view()),
    path("projects/<int:project_id>/issues/<int:issue_id>/experience", SubmitFromIssue.as_view()),
    path("projects/<int:project_id>/experience/suggestions", Suggestions.as_view()),
]
