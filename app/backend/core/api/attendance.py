"""出勤（F11）与阶段验收图片（REQ-F12-02）。

- 出勤只存人工登记；未登记日期不存行、不推算（AC-F11-03）。
- 验收图片新上传为「待复验」，按 施工中 → 待复验 → 已验收 → 施工中 循环切换（AC-F12-04、DEC-307）。
"""
import calendar
import datetime

from django.db import transaction
from django.urls import path
from rest_framework.response import Response

from core.api import structure as st
from core.api.base import ProjectView, d
from core.api.overview import photo_dict
from core.errors import ApiError, fail, validation
from core.models import AcceptancePhoto, Attendance, Phase, StoredFile
from core.services import audit

PHOTO_CYCLE = ["施工中", "待复验", "已验收"]
MODES = {"all": "每天", "workdays": "仅工作日（跳过周日）", "untilToday": "仅至今日"}


def _headcount(v, field="headcount"):
    s = str(v if v is not None else "").strip()
    if not s.isdigit() or int(s) > 40:
        return None, (field, "请填写 0–40 的整数")
    return int(s), None


def _in_phase(p, day):
    return p.planned_start <= day <= p.planned_end


class AttendanceDay(ProjectView):
    """PUT …/phases/{id}/attendance/{date}：单日登记（AC-F11-01）。"""

    def put(self, request, project_id, pk, date):
        self.require("attendance.edit", "只有项目经理可以登记出勤")
        p = self.obj(Phase, pk)
        errs = []
        day = st.parse_date(date)
        if day is None or not _in_phase(p, day):
            errs.append(("date", f"日期须在工段工期 {d(p.planned_start)} ~ {d(p.planned_end)} 内"))
        n, e = _headcount(request.data.get("headcount"))
        if e:
            errs.append(e)
        validation(errs)
        with transaction.atomic():
            old = Attendance.objects.select_for_update().filter(phase=p, date=day).first()
            before = {"headcount": old.headcount} if old else None
            Attendance.objects.update_or_create(project=self.project, phase=p, date=day,
                                                defaults={"headcount": n, "source": "manual"})
            audit.log(request.user, "attendance.set", "phase", p.id, f"{p.name} {d(day)}", before,
                      {"headcount": n}, project=self.project)
        return Response({"date": d(day), "headcount": n})


class AttendanceBatch(ProjectView):
    """POST …/phases/{id}/attendance/batch：按范围逐日写入（AC-F11-02）。"""

    def post(self, request, project_id, pk):
        self.require("attendance.edit", "只有项目经理可以登记出勤")
        p = self.obj(Phase, pk)
        data = request.data
        errs = []
        s, e = st.parse_date(data.get("start")), st.parse_date(data.get("end"))
        if s is None or not _in_phase(p, s):
            errs.append(("start", "开始日期须在工段工期内"))
        if e is None or not _in_phase(p, e):
            errs.append(("end", "结束日期须在工段工期内"))
        if s and e and s > e:
            errs.append(("start", "开始日期不能晚于结束日期"))
        n, he = _headcount(data.get("headcount"))
        if he:
            errs.append(he)
        mode = data.get("mode") or "workdays"
        if mode not in MODES:
            errs.append(("mode", "请选择写入范围"))
        validation(errs)
        today = st.today()
        days = []
        day = s
        while day <= e:
            if not (mode == "workdays" and day.weekday() == 6) and not (mode == "untilToday" and day > today):
                days.append(day)
            day += datetime.timedelta(days=1)
        if not days:
            validation([("end", "所选范围内没有可写入的日期")])
        with transaction.atomic():
            overwritten = Attendance.objects.filter(phase=p, date__in=days).count()
            for day in days:
                Attendance.objects.update_or_create(project=self.project, phase=p, date=day,
                                                    defaults={"headcount": n, "source": "manual"})
            audit.log(request.user, "attendance.batch", "phase", p.id, p.name, None,
                      {"start": d(s), "end": d(e), "mode": mode, "headcount": n, "written": len(days)},
                      project=self.project)
        return Response({"written": len(days), "overwritten": overwritten, "headcount": n,
                         "first": d(days[0]), "last": d(days[-1])})


class AttendanceMonth(ProjectView):
    """GET …/attendance?month=YYYY-MM：全项目每日出勤之和（AC-F11-04）。未登记日期不出现在 days 中。"""

    def get(self, request, project_id):
        today = st.today()
        month = request.GET.get("month") or today.strftime("%Y-%m")
        try:
            y, m = (int(x) for x in month.split("-"))
            first = datetime.date(y, m, 1)
        except ValueError:
            fail("VALIDATION_FAILED", "月份格式应为 YYYY-MM")
        last = datetime.date(y, m, calendar.monthrange(y, m)[1])
        phases = Phase.objects.filter(project=self.project)
        start = min((p.planned_start for p in phases), default=self.project.planned_start)
        end = max((p.planned_end for p in phases), default=self.project.planned_handover)
        days = {}
        for a in Attendance.objects.filter(project=self.project, date__gte=first, date__lte=last):
            days[d(a.date)] = days.get(d(a.date), 0) + a.headcount
        total = sum(days.values())
        peak_day = max(days.items(), key=lambda kv: (kv[1], -int(kv[0].replace("-", ""))), default=(None, 0))
        unreg = 0
        day = max(first, start)
        while day <= min(last, today, end):
            if d(day) not in days:
                unreg += 1
            day += datetime.timedelta(days=1)
        return Response({"month": f"{y:04d}-{m:02d}", "periodStart": d(start), "periodEnd": d(end), "today": d(today),
                         "days": days, "total": total, "workDays": sum(1 for v in days.values() if v > 0),
                         "peak": peak_day[1], "peakDate": peak_day[0] if peak_day[1] else None,
                         "unregistered": unreg})


class AcceptancePhotos(ProjectView):
    def get(self, request, project_id, pk):
        p = self.obj(Phase, pk)
        qs = AcceptancePhoto.objects.filter(phase=p).select_related("file", "file__uploader").order_by("id")
        return Response({"items": [photo_dict(x) for x in qs]})

    def post(self, request, project_id, pk):
        """body {fileIds:[…], caption?}：文件先经 …/files 上传；新图片一律「待复验」。"""
        self.require("acceptance_photo.edit", "无权上传验收图片")
        p = self.obj(Phase, pk)
        ids = request.data.get("fileIds") or ([request.data["fileId"]] if request.data.get("fileId") else [])
        files = list(StoredFile.objects.filter(project=self.project, pk__in=ids, status="normal"))
        if not ids or len(files) != len(set(ids)):
            validation([("fileIds", "请先上传图片")])
        bad = [f.original_name for f in files if not f.mime.startswith("image/")]
        if bad:
            raise ApiError(415, "FILE_TYPE", f"{bad[0]}：不是图片，未上传", details={"file": bad[0]})
        caption = str(request.data.get("caption") or "").strip()[:100]
        out = []
        with transaction.atomic():
            for f in files:
                cap = caption or f.original_name.rsplit(".", 1)[0][:100]
                ph = AcceptancePhoto.objects.create(project=self.project, phase=p, file=f, caption=cap, status="待复验")
                out.append(ph)
            audit.log(request.user, "acceptance_photo.upload", "phase", p.id, p.name, None,
                      {"count": len(out), "files": [f.original_name for f in files]}, project=self.project)
        return Response({"items": [photo_dict(AcceptancePhoto.objects.select_related("file", "file__uploader").get(pk=x.pk))
                                   for x in out]}, status=201)


class AcceptancePhotoStatus(ProjectView):
    """POST …/acceptance-photos/{id}/status：不带 status 时切到下一状态。"""

    def post(self, request, project_id, pk):
        self.require("acceptance_photo.edit", "无权切换验收图片状态")
        with transaction.atomic():
            ph = AcceptancePhoto.objects.select_for_update().get(pk=self.obj(AcceptancePhoto, pk).pk)
            target = request.data.get("status")
            if target is None:
                cur = PHOTO_CYCLE.index(ph.status) if ph.status in PHOTO_CYCLE else -1
                target = PHOTO_CYCLE[(cur + 1) % 3]
            if target not in PHOTO_CYCLE:
                validation([("status", "状态只能是施工中、待复验或已验收")])
            before = ph.status
            ph.status = target
            ph.save(update_fields=["status"])
            audit.log(request.user, "acceptance_photo.status", "acceptance_photo", ph.id, ph.caption,
                      {"status": before}, {"status": target}, project=self.project)
        ph = AcceptancePhoto.objects.select_related("file", "file__uploader").get(pk=ph.pk)
        return Response(photo_dict(ph))


P = "projects/<int:project_id>/"
urlpatterns = [
    path(P + "phases/<int:pk>/attendance/batch", AttendanceBatch.as_view()),
    path(P + "phases/<int:pk>/attendance/<str:date>", AttendanceDay.as_view()),
    path(P + "attendance", AttendanceMonth.as_view()),
    path(P + "phases/<int:pk>/acceptance-photos", AcceptancePhotos.as_view()),
    path(P + "acceptance-photos/<int:pk>/status", AcceptancePhotoStatus.as_view()),
]
