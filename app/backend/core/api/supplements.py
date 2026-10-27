"""补充事项（API-F13-01，REQ-F13-01）：登记、状态流转（待处理 / 处理中 / 已完成，未完成在前）、转为变更单。

必填范围 DEC-131：标题、提出日期、约定完成日期、责任人；说明与附件可空；约定完成日期不得早于提出日期。
DEC-132：已完成或已关联变更单的事项不能再转为变更单。
"""
import datetime

from django.db import transaction
from django.urls import path
from django.utils import timezone
from rest_framework.response import Response

from core.api.base import ProjectView, d
from core.errors import ApiError, validation
from core.models import StoredFile, Supplement, User
from core.services import audit, shared, storage

STATUSES = ["待处理", "处理中", "已完成"]


def _date(v):
    try:
        return datetime.date.fromisoformat(str(v)) if v else None
    except ValueError:
        return None


def codes(project):
    """BC-nnn：按项目内登记顺序编号（补充事项不能删除，编号稳定）。"""
    ids = Supplement.objects.filter(project=project).order_by("id").values_list("id", flat=True)
    return {sid: f"BC-{i:03d}" for i, sid in enumerate(ids, start=1)}


class SupplementMixin:
    def ser(self, s, code):
        co = s.change_order
        return {"id": s.id, "code": code, "title": s.title, "note": s.note, "raisedOn": d(s.raised_on), "dueOn": d(s.due_on),
                "ownerName": s.owner_name, "status": s.status, "files": [storage.file_dict(f) for f in s.files.all().order_by("id")],
                "changeOrder": {"id": co.id, "code": co.code} if co else None,
                "canConvert": self.can("supplement.to_change") and co is None and s.status != "已完成"}

    def one(self, s):
        return self.ser(s, codes(self.project)[s.id])

    def parse(self, request, partial=None):
        data = request.data or {}
        title = str(data.get("title", partial.title if partial else "")).strip()
        note = str(data.get("note", partial.note if partial else "")).strip()
        raised = _date(data.get("raisedOn")) if "raisedOn" in data or not partial else partial.raised_on
        due = _date(data.get("dueOn")) if "dueOn" in data or not partial else partial.due_on
        owner = str(data.get("ownerName", partial.owner_name if partial else "")).strip()
        errs = []
        if not title:
            errs.append(("title", "请填写标题"))
        elif len(title) > 100:
            errs.append(("title", "标题不能超过 100 字"))
        if not raised:
            errs.append(("raisedOn", "请选择提出日期"))
        if not due:
            errs.append(("dueOn", "请选择约定完成日期"))
        elif raised and due < raised:
            errs.append(("dueOn", "约定完成日期不能早于提出日期"))
        if not owner:
            errs.append(("ownerName", "请选择责任人"))
        files = None
        if "fileIds" in data:
            ids = [int(x) for x in (data.get("fileIds") or [])]
            files = list(StoredFile.objects.filter(project=self.project, pk__in=ids).exclude(status="voided"))
            if len(files) != len(set(ids)):
                errs.append(("fileIds", "附件不存在或未上传完成，请重新上传"))
        validation(errs)
        return {"title": title, "note": note, "raised_on": raised, "due_on": due, "owner_name": owner}, files


class Supplements(SupplementMixin, ProjectView):
    def get(self, request, project_id):
        cmap = codes(self.project)
        qs = Supplement.objects.filter(project=self.project).select_related("change_order").prefetch_related("files")
        items = sorted(qs, key=lambda s: (s.status == "已完成", s.due_on, s.id))
        members = (User.objects.filter(project_roles__project=self.project).distinct().order_by("id").values_list("name", flat=True))
        undone = sum(1 for s in items if s.status != "已完成")
        return Response({"items": [self.ser(s, cmap[s.id]) for s in items], "counts": {"undone": undone, "done": len(items) - undone},
                         "members": list(dict.fromkeys(members)), "today": d(timezone.localdate())})

    @transaction.atomic
    def post(self, request, project_id):
        self.require("supplement.edit")
        fields, files = self.parse(request)
        s = Supplement.objects.create(project=self.project, status="待处理", **fields)
        if files:
            s.files.set(files)
        out = self.one(s)
        audit.log(request.user, "新增", "补充事项", s.id, f"{out['code']} {s.title}", None,
                  {"title": s.title, "status": s.status, "ownerName": s.owner_name, "dueOn": d(s.due_on)}, project=self.project)
        return Response(out, status=201)


class SupplementDetail(SupplementMixin, ProjectView):
    http_method_names = ["get", "patch"]

    def get(self, request, project_id, sid):
        return Response(self.one(self.obj(Supplement, sid)))

    @transaction.atomic
    def patch(self, request, project_id, sid):
        self.require("supplement.edit")
        s = Supplement.objects.select_for_update().filter(pk=sid, project=self.project).first()
        if s is None:
            raise ApiError(404, "NOT_FOUND", "补充事项不存在")
        fields, files = self.parse(request, partial=s)
        before = {k: (d(getattr(s, k)) if k.endswith("_on") else getattr(s, k)) for k in fields}
        for k, v in fields.items():
            setattr(s, k, v)
        s.save()
        if files is not None:
            s.files.set(files)
        after = {k: (d(getattr(s, k)) if k.endswith("_on") else getattr(s, k)) for k in fields}
        changed = {k for k in fields if before[k] != after[k]}
        out = self.one(s)
        if changed or files is not None:
            audit.log(request.user, "修改", "补充事项", s.id, f"{out['code']} {s.title}", {k: before[k] for k in changed},
                      {k: after[k] for k in changed}, project=self.project)
        return Response(out)


class SupplementStatus(SupplementMixin, ProjectView):
    @transaction.atomic
    def post(self, request, project_id, sid):
        self.require("supplement.edit")
        st = (request.data or {}).get("status")
        if st not in STATUSES:
            validation([("status", "状态只能是待处理、处理中或已完成")])
        s = Supplement.objects.select_for_update().filter(pk=sid, project=self.project).first()
        if s is None:
            raise ApiError(404, "NOT_FOUND", "补充事项不存在")
        before = s.status
        if before != st:
            s.status = st
            s.save(update_fields=["status"])
        out = self.one(s)
        if before != st:
            audit.log(request.user, "状态变更", "补充事项", s.id, f"{out['code']} {s.title}", {"status": before}, {"status": st},
                      project=self.project)
        return Response(out)


class SupplementToChange(SupplementMixin, ProjectView):
    @transaction.atomic
    def post(self, request, project_id, sid):
        self.require("supplement.to_change", "只有项目经理可以转为变更单")
        s = Supplement.objects.select_for_update().filter(pk=sid, project=self.project).first()
        if s is None:
            raise ApiError(404, "NOT_FOUND", "补充事项不存在")
        code = codes(self.project)[s.id]
        if s.change_order_id:
            raise ApiError(409, "ALREADY_CONVERTED", f"{code} 已转为变更单 {s.change_order.code}",
                           details={"changeOrder": {"id": s.change_order_id, "code": s.change_order.code}})
        if s.status == "已完成":
            raise ApiError(409, "SUPPLEMENT_DONE", "已完成的补充事项不能转为变更单")
        content = (s.note + "\n\n" if s.note else "") + \
            f"来源：补充事项 {code}（提出 {d(s.raised_on)}，约定完成 {d(s.due_on)}，责任人 {s.owner_name}）"
        co = shared.create_change_draft(self.project, request.user, title=s.title, content=content,
                                        file_ids=list(s.files.values_list("id", flat=True)), source_supplement=s)
        s.change_order = co
        s.save(update_fields=["change_order"])
        audit.log(request.user, "新增", "变更单", co.id, f"{co.code} {co.title}", None,
                  {"status": co.status, "source": f"补充事项 {code}"}, project=self.project)
        audit.log(request.user, "修改", "补充事项", s.id, f"{code} {s.title}", {"changeOrder": None}, {"changeOrder": co.code},
                  project=self.project)
        return Response(self.one(s), status=201)


urlpatterns = [
    path("projects/<int:project_id>/supplements", Supplements.as_view()),
    path("projects/<int:project_id>/supplements/<int:sid>", SupplementDetail.as_view()),
    path("projects/<int:project_id>/supplements/<int:sid>/status", SupplementStatus.as_view()),
    path("projects/<int:project_id>/supplements/<int:sid>/to-change", SupplementToChange.as_view()),
]
