"""总览与指标（F10）：项目总览、证据链四项指标、楼层 / 房间视图与详情、工段详情（API-F10-01）。

口径（技术方案 §5.1.6）：
- 总体完成度 / 计划基准 = Σ(工段权重×工段进度或计划进度)÷Σ工段权重（AC-F10-01）
- 工期按自然日含首尾；已用天数限制在 0 ~ 总工期（AC-F10-02）
- 四项指标分母为 0 时返回 null，前端显示「暂无数据」（AC-F10-08）
"""
import datetime
from collections import defaultdict

from django.db.models import Exists, OuterRef, Q
from django.urls import path
from rest_framework.response import Response

from core.api import structure as st
from core.api.base import ProjectView, d
from core.errors import fail
from core.models import (AcceptancePhoto, Attendance, ChangeOrder, Checkpoint, CheckRecord, DiscoveryCorrection,
                         DrawingSignoff, Floor, Issue, Phase, PlanChangeLog, ProjectMemberRole, Room, WorkItem)
from core.services import storage

TARGETS = {"coverBefore": 90, "concealedCompliance": 100, "latestSigned": 100, "signBeforeBuild": 100}
LABELS = {"coverBefore": "覆盖前发现比例", "concealedCompliance": "隐蔽检查点合规率",
          "latestSigned": "最新签认版使用率", "signBeforeBuild": "变更先签后做比例"}


def ratio(m, n):
    return st.r1(m / n * 100) if n else None


# ---------------------------------------------------------------- 证据链四项指标

def evidence(project, phase_id=None):
    cps = Checkpoint.objects.filter(project=project, is_draft=False)
    checks = CheckRecord.objects.filter(project=project)
    cos = ChangeOrder.objects.filter(project=project, status="已生效")
    if phase_id:
        cps = cps.filter(work_item__phase_id=phase_id)
        checks = checks.filter(checkpoint__work_item__phase_id=phase_id)
        cos = cos.filter(work_items__phase_id=phase_id).distinct()

    # 1 覆盖前发现比例：未作废问题对应的不一致核对，取修正后的发现时点（AC-F10-04）
    live_issue = Issue.objects.filter(source_check=OuterRef("pk")).exclude(status="已作废")
    inc = list(checks.filter(conclusion="不一致").filter(Exists(live_issue)).values("id", "discovery_phase"))
    fixed = {}
    for c in DiscoveryCorrection.objects.filter(check_record_id__in=[x["id"] for x in inc]).order_by("at", "id"):
        fixed[c.check_record_id] = c.after
    m1 = sum(1 for x in inc if fixed.get(x["id"], x["discovery_phase"]) == "覆盖前")

    # 2 隐蔽检查点合规率：已放行或已覆盖的隐蔽检查点；覆盖前同时具备签认版核对 + ≥1 张照片 + 放行记录（AC-F10-05）
    conc = (cps.filter(is_concealed=True)
            .filter(Q(released_at__isnull=False) | Q(covered_at__isnull=False) | Q(releases__isnull=False))
            .distinct().prefetch_related("releases", "checks__photos"))
    signed_at = {s.version_id: s.signed_at for s in DrawingSignoff.objects.filter(project=project)}
    n2 = m2 = 0
    for cp in conc:
        n2 += 1
        rel = sorted(r.released_at for r in cp.releases.all())
        cover = cp.covered_at or (rel[0] if rel else cp.released_at)
        ok_release = any(r <= cover for r in rel)
        ok_check = any(c.checked_at <= cover and len(c.photos.all()) > 0
                       and c.drawing_version_id in signed_at and signed_at[c.drawing_version_id] <= c.checked_at
                       for c in cp.checks.all())
        m2 += 1 if (ok_release and ok_check) else 0

    # 3 最新签认版使用率（AC-F10-06）
    n3 = checks.count()
    m3 = checks.filter(was_latest_signed=True).count()
    # 4 变更先签后做比例（AC-F10-07）
    n4 = cos.count()
    m4 = cos.exclude(built_before_sign=True).count()

    out = []
    for key, m, n in (("coverBefore", m1, len(inc)), ("concealedCompliance", m2, n2), ("latestSigned", m3, n3),
                      ("signBeforeBuild", m4, n4)):
        out.append({"key": key, "label": LABELS[key], "numerator": m, "denominator": n, "value": ratio(m, n),
                    "target": TARGETS[key]})
    return out


# ---------------------------------------------------------------- 快照

class Snap:
    """一次性取齐总览类页面所需数据（单项目规模下几十毫秒）。"""

    def __init__(self, project):
        self.project = project
        self.today = st.today()
        self.phases = list(Phase.objects.filter(project=project, is_disabled=False).order_by("order_no", "id"))
        self.floors = list(Floor.objects.filter(project=project, is_disabled=False).order_by("order_no", "id"))
        fids = {f.id for f in self.floors}
        self.rooms = [r for r in Room.objects.filter(project=project, is_disabled=False).order_by("order_no", "id")
                      if r.floor_id in fids]
        self.rooms.sort(key=lambda r: ([f.id for f in self.floors].index(r.floor_id), r.order_no, r.id))
        pids = {p.id for p in self.phases}
        self.items = [w for w in WorkItem.objects.filter(project=project, is_disabled=False).values(
            "id", "phase_id", "floor_id", "room_id", "weight", "progress") if w["phase_id"] in pids]
        self.issues = list(Issue.objects.filter(project=project).exclude(status="已作废")
                           .select_related("phase", "floor", "room", "checkpoint").order_by("seq_no"))
        self.floor_name = {f.id: f.name for f in Floor.objects.filter(project=project)}
        self.room_name = {r.id: r.name for r in Room.objects.filter(project=project)}
        self.prog = {}
        by_phase = defaultdict(list)
        for w in self.items:
            by_phase[w["phase_id"]].append((w["weight"], w["progress"]))
        for p in self.phases:
            self.prog[p.id] = st.weighted(by_phase[p.id]) or 0.0
        self.att = defaultdict(dict)  # phase_id -> {date: n}
        for a in Attendance.objects.filter(project=project).values("phase_id", "date", "headcount"):
            self.att[a["phase_id"]][a["date"]] = a["headcount"]

    def planned(self, p):
        return st.planned_pct(p.planned_start, p.planned_end, self.today)

    def cell(self, phase_id, test):
        v = st.weighted([(w["weight"], w["progress"]) for w in self.items if w["phase_id"] == phase_id and test(w)])
        return st.r1(v)

    def overdue(self, i):
        if i.status in ("已闭环", "已作废") or not i.due_date:
            return 0
        return max(0, (self.today - i.due_date).days)

    def phase_brief(self, p):
        return {"id": p.id, "code": p.code, "name": p.name, "colorVar": p.color_var,
                "plannedStart": d(p.planned_start), "plannedEnd": d(p.planned_end)}

    def floor_matrix(self):
        rows = [{"id": f.id, "name": f.name,
                 "cells": [self.cell(p.id, lambda w, f=f: w["floor_id"] == f.id) for p in self.phases]}
                for f in self.floors]
        rows.append({"id": "all", "name": "全楼通用",
                     "cells": [self.cell(p.id, lambda w: w["floor_id"] is None) for p in self.phases]})
        return rows

    def room_matrix(self):
        return [{"id": r.id, "floorId": r.floor_id, "floorName": self.floor_name.get(r.floor_id, ""), "name": r.name,
                 "cells": [self.cell(p.id, lambda w, r=r: w["room_id"] == r.id) for p in self.phases]}
                for r in self.rooms]

    def issue_brief(self, i):
        return {"id": i.id, "code": i.code, "phaseId": i.phase_id, "phaseName": i.phase.name if i.phase else "",
                "phaseColor": i.phase.color_var if i.phase else "--muted",
                "floorId": i.floor_id, "roomId": i.room_id,
                "floorName": i.floor.name if i.floor else "全楼通用",
                "roomName": i.room.name if i.room else ("本层通用" if i.floor else ""),
                "description": i.description, "level": i.level, "status": i.status, "ownerName": i.owner_name,
                "foundOn": d(i.found_on), "dueDate": d(i.due_date), "closedOn": d(i.closed_on),
                "overdueDays": self.overdue(i), "countermeasure": i.countermeasure, "source": i.source,
                "checkpointId": i.checkpoint_id, "checkpointCode": i.checkpoint.code if i.checkpoint_id else None}

    def rooms_stats(self):
        out = []
        for r in self.rooms:
            ws = [(w["weight"], w["progress"]) for w in self.items if w["room_id"] == r.id]
            iss = [i for i in self.issues if i.room_id == r.id]
            closed = sum(1 for i in iss if i.status == "已闭环")
            out.append({"id": r.id, "floorId": r.floor_id, "floorName": self.floor_name.get(r.floor_id, ""),
                        "name": r.name, "itemCount": len(ws), "progress": st.r1(st.weighted(ws) or 0.0),
                        "issues": len(iss), "closed": closed, "legacy": len(iss) - closed,
                        "issueSummary": [{"code": i.code, "description": i.description} for i in iss]})
        return out

    def att_stats(self, p, upto=None):
        """工段工期内截至今天：累计、峰值、施工天数、未登记天数、首末施工日（AC-F11-01、AC-F11-03）。"""
        att = self.att.get(p.id, {})
        end = min(p.planned_end, upto or self.today)
        unreg = sum(1 for k in range((end - p.planned_start).days + 1)
                    if p.planned_start + datetime.timedelta(days=k) not in att)
        tot = sum(att.values())
        worked = sorted(day for day, v in att.items() if v > 0)
        return {"total": tot, "peak": max(att.values(), default=0), "workDays": len(worked), "unregistered": unreg,
                "firstDay": d(worked[0]) if worked else None, "lastDay": d(worked[-1]) if worked else None,
                "avg": st.r1(tot / len(worked)) if worked else 0.0}

    def phase_card(self, p):
        v = self.prog[p.id]
        iss = [i for i in self.issues if i.phase_id == p.id]
        a = self.att_stats(p)
        return {**self.phase_brief(p), "teamLead": p.team_lead, "scopeNote": p.scope_note, "weight": p.weight,
                "progress": st.r1(v), "planned": st.r1(self.planned(p)), "status": st.status_of(v),
                "itemCount": sum(1 for w in self.items if w["phase_id"] == p.id),
                "doneCount": sum(1 for w in self.items if w["phase_id"] == p.id and w["progress"] >= 100),
                "manDays": a["total"], "peak": a["peak"], "workDays": a["workDays"],
                "issues": len(iss), "closed": sum(1 for i in iss if i.status == "已闭环"),
                "mid": sum(1 for i in iss if i.status == "处理中"), "open": sum(1 for i in iss if i.status == "未闭环")}


def plan_logs(project, phase_id=None):
    qs = PlanChangeLog.objects.filter(project=project).select_related("phase", "actor").order_by("-at", "-id")
    if phase_id:
        qs = qs.filter(phase_id=phase_id)
    return [st.plan_log_dict(x) for x in qs]


def member_names(project, role):
    return list(ProjectMemberRole.objects.filter(project=project, role=role).select_related("user")
                .order_by("id").values_list("user__name", flat=True))


# ---------------------------------------------------------------- 项目总览

class Overview(ProjectView):
    def get(self, request, project_id):
        s = Snap(self.project)
        phase_id = request.GET.get("phaseId") or None
        if phase_id and not Phase.objects.filter(project=self.project, pk=phase_id).exists():
            fail("NOT_FOUND", "工段不存在", 404)
        sw = sum(p.weight for p in s.phases)
        overall = sum(p.weight * s.prog[p.id] for p in s.phases) / sw if sw else 0.0
        plan = sum(p.weight * s.planned(p) for p in s.phases) / sw if sw else 0.0
        start = min((p.planned_start for p in s.phases), default=self.project.planned_start)
        end = max((p.planned_end for p in s.phases), default=self.project.planned_handover)
        duration = (end - start).days + 1
        used = min(max((s.today - start).days + 1, 0), duration)
        today_att = [v.get(s.today) for v in s.att.values() if s.today in v]
        closed = sum(1 for i in s.issues if i.status == "已闭环")
        mid = sum(1 for i in s.issues if i.status == "处理中")
        open_ = sum(1 for i in s.issues if i.status == "未闭环")
        legacy = sorted([i for i in s.issues if i.status in ("未闭环", "处理中")],
                        key=lambda i: (-s.overdue(i), i.due_date or datetime.date.max))
        return Response({
            "today": d(s.today),
            "project": {"name": self.project.name, "status": self.project.status,
                        "owners": member_names(self.project, "owner"), "pms": member_names(self.project, "pm")},
            "kpi": {
                "overall": st.r1(overall), "planned": st.r1(plan), "gap": st.r1(overall - plan),
                "periodStart": d(start), "periodEnd": d(end), "duration": duration, "used": used,
                "timeProgress": st.r1(used / duration * 100) if duration else 0.0,
                "todayAttendance": sum(today_att) if today_att else None,
                "runningPhases": sum(1 for p in s.phases if st.status_of(s.prog[p.id]) == "进行中"),
                "manDays": sum(sum(v.values()) for v in s.att.values()),
                "issues": len(s.issues), "overdueOpen": sum(1 for i in s.issues if s.overdue(i) > 0),
                "closed": closed, "closeRate": st.r1(closed / len(s.issues) * 100) if s.issues else None,
                "legacy": mid + open_, "mid": mid, "open": open_,
            },
            "evidence": evidence(self.project, phase_id), "evidencePhaseId": int(phase_id) if phase_id else None,
            "phases": [s.phase_card(p) for p in s.phases],
            "floorMatrix": s.floor_matrix(),
            "rooms": s.rooms_stats(),
            "legacy": [s.issue_brief(i) for i in legacy],
            "planLogs": plan_logs(self.project),
        })


# ---------------------------------------------------------------- 楼层 / 房间视图

class FloorView(ProjectView):
    def get(self, request, project_id):
        s = Snap(self.project)
        floors = []
        for f in s.floors + [None]:
            fid = f.id if f else None
            ws = [w for w in s.items if w["floor_id"] == fid]
            iss = [i for i in s.issues if i.floor_id == fid]
            floors.append({
                "id": fid or "all", "name": f.name if f else "全楼通用",
                "roomCount": sum(1 for r in s.rooms if r.floor_id == fid) if f else None,
                "itemCount": len(ws), "doneCount": sum(1 for w in ws if w["progress"] >= 100),
                "progress": st.r1(st.weighted([(w["weight"], w["progress"]) for w in ws]) or 0.0),
                "weightByPhase": [sum(w["weight"] for w in ws if w["phase_id"] == p.id) for p in s.phases],
                "weightTotal": sum(w["weight"] for w in ws),
                "issues": len(iss), "closed": sum(1 for i in iss if i.status == "已闭环"),
                "mid": sum(1 for i in iss if i.status == "处理中"), "open": sum(1 for i in iss if i.status == "未闭环"),
            })
        return Response({
            "phases": [s.phase_brief(p) for p in s.phases], "floors": floors, "rooms": s.rooms_stats(),
            "floorMatrix": s.floor_matrix(), "roomMatrix": s.room_matrix(),
            "workItems": {"total": len(s.items), "done": sum(1 for w in s.items if w["progress"] >= 100),
                          "common": sum(1 for w in s.items if w["floor_id"] is None)},
        })


class ScopeDetail(ProjectView):
    """楼层 / 房间详情抽屉：?floor=<id|all> 或 ?room=<id>。"""

    def get(self, request, project_id):
        s = Snap(self.project)
        room_id, floor_id = request.GET.get("room"), request.GET.get("floor")
        if room_id:
            room = self.obj(Room, room_id)
            title, kind = f"{s.floor_name.get(room.floor_id, '')} · {room.name}", "room"
            qs = WorkItem.objects.filter(project=self.project, room=room)
            iss = [i for i in s.issues if i.room_id == room.id]
            fid, rid = room.floor_id, room.id
        elif floor_id == "all":
            title, kind = "全楼通用", "floor"
            qs = WorkItem.objects.filter(project=self.project, floor__isnull=True)
            iss = [i for i in s.issues if i.floor_id is None]
            fid, rid = "all", None
        elif floor_id:
            floor = self.obj(Floor, floor_id)
            title, kind = floor.name, "floor"
            qs = WorkItem.objects.filter(project=self.project, floor=floor)
            iss = [i for i in s.issues if i.floor_id == floor.id]
            fid, rid = floor.id, None
        else:
            fail("NOT_FOUND", "请指定楼层或房间", 404)
        pids = [p.id for p in s.phases]
        items = list(qs.filter(is_disabled=False, phase_id__in=pids).select_related("baseline", "qc_user")
                     .order_by("phase__order_no", "id"))
        ctx = st.ItemContext(self.project, [w.id for w in items])
        groups = []
        for p in s.phases:
            ws = [st.wi_dict(w, ctx) for w in items if w.phase_id == p.id]
            if ws:
                groups.append({**s.phase_brief(p), "status": st.status_of(s.prog[p.id]), "items": ws})
        legacy = sum(1 for i in iss if i.status != "已闭环")
        return Response({
            "kind": kind, "title": title, "floorId": fid, "roomId": rid,
            "stats": {"progress": st.r1(st.weighted([(w.weight, w.progress) for w in items]) or 0.0),
                      "itemCount": len(items), "doneCount": sum(1 for w in items if w.progress >= 100),
                      "legacy": legacy},
            "groups": groups, "issues": [s.issue_brief(i) for i in iss],
        })


# ---------------------------------------------------------------- 工段详情

def photo_dict(ph):
    return {"id": ph.id, "phaseId": ph.phase_id, "caption": ph.caption, "status": ph.status, "source": ph.source,
            "file": storage.file_dict(ph.file) if ph.file_id else None,
            "uploaderName": ph.file.uploader.name if ph.file_id and ph.file.uploader_id else "",
            "createdAt": d(ph.created_at.date()) if ph.created_at else None}


class PhaseDetail(ProjectView):
    def get(self, request, project_id, pk):
        p = self.obj(Phase, pk)
        s = Snap(self.project)
        v = s.prog.get(p.id)
        if v is None:  # 已停用的工段也允许查看历史
            v = st.weighted([(w.weight, w.progress) for w in WorkItem.objects.filter(phase=p, is_disabled=False)]) or 0.0
        items = list(WorkItem.objects.filter(phase=p, is_disabled=False).select_related("baseline", "qc_user")
                     .order_by("id"))
        ctx = st.ItemContext(self.project, [w.id for w in items])
        att = Attendance.objects.filter(phase=p).order_by("date")
        a = s.att_stats(p)
        iss = [i for i in s.issues if i.phase_id == p.id]
        photos = AcceptancePhoto.objects.filter(phase=p).select_related("file", "file__uploader").order_by("id")
        return Response({
            "today": d(s.today),
            "phase": {**s.phase_brief(p), "teamLead": p.team_lead, "scopeNote": p.scope_note, "weight": p.weight,
                      "isDisabled": p.is_disabled, "progress": st.r1(v), "planned": st.r1(s.planned(p)),
                      "status": st.status_of(v), "duration": (p.planned_end - p.planned_start).days + 1},
            "phases": [s.phase_brief(x) for x in s.phases],
            "attendanceStats": a,
            "attendance": [{"date": d(x.date), "headcount": x.headcount, "source": x.source} for x in att],
            "items": [st.wi_dict(w, ctx) for w in items],
            "floors": [{"id": f.id, "name": f.name} for f in s.floors],
            "rooms": [{"id": r.id, "floorId": r.floor_id, "name": r.name} for r in s.rooms],
            "issues": sorted([s.issue_brief(i) for i in iss], key=lambda x: -x["overdueDays"]),
            "photos": [photo_dict(x) for x in photos],
            "planLogs": plan_logs(self.project, p.id),
        })


P = "projects/<int:project_id>/"
urlpatterns = [
    path(P + "overview", Overview.as_view()),
    path(P + "floor-view", FloorView.as_view()),
    path(P + "scope-detail", ScopeDetail.as_view()),
    path(P + "phases/<int:pk>/detail", PhaseDetail.as_view()),
]
