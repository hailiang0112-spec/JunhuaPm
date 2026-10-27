"""检查点、对图核对、放行、覆盖登记与发现时点修正（F06，API-F06-01 ~ API-F06-03，SEQ-F06-01 ~ SEQ-F06-03）。"""
from types import SimpleNamespace

from django.db import IntegrityError, connection, transaction
from django.urls import path
from django.utils import timezone
from rest_framework.response import Response

from core.api.base import ProjectView, d, iso, user_brief
from core.errors import ApiError, fail
from core.models import (Baseline, BaselineEvent, ChangeOrder, Checkpoint, CheckPhoto, CheckRecord, CoverEvent,
                         DiscoveryCorrection, DrawingPage, DrawingSignoff, Issue, Project, ReleaseRecord, StoredFile,
                         WorkItem)
from core.services import audit, ledger, shared, storage

CONCLUSIONS = ["一致", "不一致", "已变更"]
PHASES = ["覆盖前", "覆盖后", "交房后"]
RELEASABLE = {"一致", "已变更"}
# DEC-201 印章优先级（同时是 DEC-202 默认排序）
SEAL_RANK = ["放行后发现不一致", "不一致", "未放行先覆盖", "超时", "不得覆盖", "待放行", "待核对", "已放行", "代理放行"]
SEAL_KIND = {"放行后发现不一致": "stop", "不一致": "stop", "未放行先覆盖": "stop", "超时": "stop", "不得覆盖": "stop",
             "待放行": "pend", "已放行": "pass", "代理放行": "proxy"}
CHIPS = ["全部", "不得覆盖", "待核对", "待放行", "超时", "不一致", "放行后发现不一致", "未放行先覆盖", "已放行"]


def fmt_dt(dt):
    return timezone.localtime(dt).strftime("%Y-%m-%d %H:%M") if dt else ""


def fmt_date(dt):
    return timezone.localtime(dt).strftime("%Y-%m-%d") if dt else ""


def handover_date(project):
    """交房日期口径（PRD §3.2.1）：有实际交房日期取实际，否则取计划。"""
    return project.actual_handover or project.planned_handover


def infer_discovery(project, checked_at, covered):
    """AC-F06-14：核对日期不早于交房日期 → 交房后；否则已覆盖 → 覆盖后，未覆盖 → 覆盖前。"""
    if timezone.localtime(checked_at).date() >= handover_date(project):
        return "交房后"
    return "覆盖后" if covered else "覆盖前"


def is_signed(version):
    return version is not None and DrawingSignoff.objects.filter(version=version).exists()


def base_version(cp):
    """核对底图 = 工作项基线引用的签认版（待重签期间仍为原签认版，AC-F05-07）。"""
    wv = cp.work_item.drawing_version
    return wv if wv is not None and is_signed(wv) else cp.drawing_version


def waiting_hours(cp, now=None):
    if cp.status != "待放行" or not cp.awaiting_release_since:
        return None
    return int(((now or timezone.now()) - cp.awaiting_release_since).total_seconds() // 3600)


def latest_release(cp):
    return cp.releases.select_related("releaser").order_by("-id").first()


def check_numbers(cp):
    return {cid: i + 1 for i, cid in enumerate(cp.checks.order_by("id").values_list("id", flat=True))}


def current_discovery(check):
    """发现时点取最新一次修正后的值（AC-F06-15）。"""
    last = check.corrections.order_by("-id").first()
    return last.after if last else check.discovery_phase


def seal_of(cp, labels, rel):
    """DEC-201：每个检查点只取一个印章；非隐蔽且未核对显示普通标签「待核对」。"""
    if cp.status == "放行后发现不一致":
        return "放行后发现不一致"
    if cp.status == "不一致":
        return "不一致"
    if cp.unreleased_cover:
        return "未放行先覆盖"
    if "超时" in labels:
        return "超时"
    if cp.is_concealed and cp.status != "已放行" and not cp.covered_at:
        return "不得覆盖"
    if cp.status == "待放行":
        return "待放行"
    if cp.status == "已放行":
        return "代理放行" if rel and rel.is_proxy else "已放行"
    return "待核对"


def chip_hits(cp, labels):
    hits = {"全部"}
    if cp.is_concealed and cp.status not in ("已放行", "放行后发现不一致") and not cp.covered_at:
        hits.add("不得覆盖")
    if cp.latest_check_id is None:
        hits.add("待核对")
    if cp.status == "待放行":
        hits.add("待放行")
    if "超时" in labels:
        hits.add("超时")
    if cp.status in ("不一致", "放行后发现不一致", "已放行"):
        hits.add(cp.status)
    if cp.unreleased_cover:
        hits.add("未放行先覆盖")
    return hits


def place(wi):
    floor = wi.floor.name if wi.floor else "全楼"
    return f"{floor} · {wi.room.name}" if wi.room else floor


def situation(cp, project, rel, now):
    """列表「当前情况」一句话。"""
    lc = cp.latest_check
    if cp.status == "已放行" and rel:
        s = f"{rel.releaser.name} {fmt_date(rel.released_at)} {'代理放行' if rel.is_proxy else '放行'}"
        return s + (" · 已覆盖" if cp.covered_at else "")
    if cp.status == "放行后发现不一致" and rel and lc:
        return f"{rel.releaser.name} {fmt_date(rel.released_at)} 放行；{lc.checker.name} {fmt_date(lc.checked_at)} 复核不一致"
    if cp.status == "不一致" and lc:
        parts = [lc.note or "现场与签认图纸不一致", f"{lc.checker.name} {fmt_dt(lc.checked_at)}", current_discovery(lc)]
        issue = Issue.objects.filter(source_check=lc).first()
        if issue:
            parts.append(f"问题 {issue.code}")
        return " · ".join(p for p in parts if p)
    if cp.unreleased_cover:
        ev = cp.cover_events.select_related("recorder").filter(was_unreleased=True).order_by("id").first()
        if ev:
            how = "标记已覆盖" if ev.source == "pm_mark" else "核对时记录已被覆盖"
            return f"{ev.recorder.name} {fmt_date(ev.at)} {how}，此前未放行"
    if cp.status == "待放行" and lc:
        h = waiting_hours(cp, now)
        s = f"结论{lc.conclusion} · 待放行已等 {h} 小时"
        return s + (f"（时限 {project.release_timeout_hours} 小时）" if h is not None and h >= project.release_timeout_hours else "")
    return "待质检核对"


def sort_time(cp):
    lc = cp.latest_check
    if cp.status == "待放行" and cp.awaiting_release_since:
        return cp.awaiting_release_since
    if cp.status in ("不一致", "放行后发现不一致") and lc:
        return lc.checked_at
    if cp.status == "已放行" and cp.released_at:
        return cp.released_at
    return cp.created_at


def latest_check_brief(cp, numbers=None):
    lc = cp.latest_check
    if lc is None:
        return None
    no = (numbers or check_numbers(cp)).get(lc.id)
    return {"id": lc.id, "no": no, "conclusion": lc.conclusion, "checkedAt": iso(lc.checked_at),
            "checker": user_brief(lc.checker), "wasCovered": lc.was_covered}


def version_label(v):
    return f"{v.drawing_set.name} V{v.version_no}" if v else ""


def base_qs(project):
    return (Checkpoint.objects.filter(project=project)
            .select_related("work_item__phase", "work_item__floor", "work_item__room", "latest_check__checker",
                            "drawing_version__drawing_set"))


class CheckpointList(ProjectView):
    """GET …/checkpoints?status=&phase=&floor=&page=：派生标签、chip 数量（随工段与楼层条件）、默认按紧急程度排序。"""

    def get(self, request, project_id):
        p = self.project
        now = timezone.now()
        # 第一遍只取派生标签、计数与排序需要的列（5000 个检查点规模下避免整行建模，NFR-002）；第二遍只为当前页取完整数据
        qs = Checkpoint.objects.filter(project=p, is_draft=False)
        phase, floor = request.GET.get("phase"), request.GET.get("floor")
        if phase:
            qs = qs.filter(work_item__phase_id=phase)
        if floor:
            qs = qs.filter(work_item__floor_id=floor)
        status = request.GET.get("status") or "全部"
        if status not in CHIPS:
            fail("VALIDATION_FAILED", "筛选条件无效")
        light = list(qs.values("id", "status", "is_concealed", "awaiting_release_since", "unreleased_cover",
                               "covered_at", "latest_check_id", "latest_check__checked_at", "released_at",
                               "created_at"))
        released_ids = [r["id"] for r in light if r["status"] in ("已放行", "放行后发现不一致")]
        if connection.vendor == "postgresql":
            proxy = dict(ReleaseRecord.objects.filter(checkpoint_id__in=released_ids)
                         .order_by("checkpoint_id", "-id").distinct("checkpoint_id")
                         .values_list("checkpoint_id", "is_proxy"))
        else:
            # SQLite has no DISTINCT ON. id order matches insertion; the last row
            # per checkpoint is the newest release (same row PostgreSQL DISTINCT ON -id keeps).
            proxy = {}
            for cid, is_proxy in (ReleaseRecord.objects.filter(checkpoint_id__in=released_ids)
                                  .order_by("id").values_list("checkpoint_id", "is_proxy")):
                proxy[cid] = is_proxy
        rows = []
        counts = {c: 0 for c in CHIPS}
        summary = {"noCover": 0, "pending": 0, "timeout": 0, "inconsistent": 0, "inconsistentAfter": 0,
                   "released": 0, "releasedProxy": 0}
        for r in light:
            cp = SimpleNamespace(**r, latest_check=SimpleNamespace(checked_at=r["latest_check__checked_at"])
                                 if r["latest_check_id"] else None)
            labels = shared.checkpoint_labels(cp, p, now)
            rel = SimpleNamespace(is_proxy=proxy[cp.id]) if cp.id in proxy else None
            hits = chip_hits(cp, labels)
            for c in hits:
                counts[c] += 1
            summary["noCover"] += "不得覆盖" in hits
            summary["pending"] += cp.status == "待放行"
            summary["timeout"] += "超时" in labels
            summary["inconsistent"] += cp.status in ("不一致", "放行后发现不一致")
            summary["inconsistentAfter"] += cp.status == "放行后发现不一致"
            summary["released"] += cp.status == "已放行"
            summary["releasedProxy"] += cp.status == "已放行" and bool(rel and rel.is_proxy)
            if status in hits:
                rows.append((cp, labels, rel))
        rows.sort(key=lambda r: (SEAL_RANK.index(seal_of(r[0], r[1], r[2])), sort_time(r[0]), r[0].id))
        try:
            page = max(1, int(request.GET.get("page", 1)))
        except ValueError:
            page = 1
        size = 50 if request.GET.get("pageSize") == "50" else 20
        page_rows = rows[(page - 1) * size: page * size]
        full = base_qs(p).in_bulk([r[0].id for r in page_rows])
        items = []
        for light_cp, labels, _ in page_rows:
            cp = full[light_cp.id]
            wi = cp.work_item
            rel = latest_release(cp) if cp.status in ("已放行", "放行后发现不一致") else None
            seal = seal_of(cp, labels, rel)
            items.append({
                "id": cp.id, "code": cp.code, "point": cp.point, "isConcealed": cp.is_concealed, "status": cp.status,
                "labels": labels, "seal": seal, "sealKind": SEAL_KIND.get(seal),
                "workItemId": wi.id, "workItemName": wi.name, "phaseName": wi.phase.name, "phaseColorVar": wi.phase.color_var,
                "floorName": wi.floor.name if wi.floor else "", "roomName": wi.room.name if wi.room else "",
                "place": place(wi), "situation": situation(cp, p, rel, now), "covered": bool(cp.covered_at),
            })
        return Response({"items": items, "total": len(rows), "page": page, "pageSize": size, "counts": counts,
                         "summary": summary, "totalAll": Checkpoint.objects.filter(project=p, is_draft=False).count(),
                         "releaseTimeoutHours": p.release_timeout_hours,
                         "phases": [{"id": x.id, "name": x.name, "colorVar": x.color_var}
                                    for x in p.phases.filter(is_disabled=False).order_by("order_no", "id")],
                         "floors": [{"id": x.id, "name": x.name}
                                    for x in p.floors.filter(is_disabled=False).order_by("order_no", "id")]})


def wi_checkpoint_dict(cp, project, now=None):
    return {"id": cp.id, "code": cp.code, "point": cp.point, "isConcealed": cp.is_concealed, "status": cp.status,
            "labels": shared.checkpoint_labels(cp, project, now), "drawingVersionId": cp.drawing_version_id,
            "pageNo": cp.page_no, "x": cp.x, "y": cp.y, "isDraft": cp.is_draft, "latestCheck": latest_check_brief(cp),
            "waitingHours": waiting_hours(cp, now)}


def _coord(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if 0 <= f <= 1 else None


class WorkItemCheckpoints(ProjectView):
    """GET/POST …/work-items/{wid}/checkpoints（DEV_GUIDE 跨模块约定；SEQ-F06-03，AC-F06-01、AC-F06-16、AC-F05-10）。"""

    def get(self, request, project_id, wid):
        wi = self.obj(WorkItem, wid)
        now = timezone.now()
        qs = base_qs(self.project).filter(work_item=wi).order_by("id")
        return Response({"items": [wi_checkpoint_dict(cp, self.project, now) for cp in qs]})

    def post(self, request, project_id, wid):
        self.require("checkpoint.create")
        wi = self.obj(WorkItem, wid)
        data = request.data
        errs = []
        point = str(data.get("point") or "").strip()
        if not point:
            errs.append(("point", "请填写检查要点"))
        elif len(point) > 200:
            errs.append(("point", "检查要点不超过 200 字"))
        x, y = _coord(data.get("x")), _coord(data.get("y"))
        if x is None or y is None:
            errs.append(("x", "请在图纸上点选检查点位置"))
        try:
            page_no = int(data.get("pageNo") or 1)
        except (TypeError, ValueError):
            page_no = 0
        if page_no < 1:
            errs.append(("pageNo", "图纸页码无效"))
        if errs:
            raise ApiError(400, "VALIDATION_FAILED", "；".join(m for _, m in errs),
                           fields=[{"field": f, "message": m} for f, m in errs])
        version = wi.drawing_version
        if version is None:
            fail("DRAWING_REQUIRED", "该工作项尚未引用签认版图纸，请先在基线中选择图纸版本", 422)
        if not is_signed(version):
            fail("DRAWING_NOT_SIGNED", "该版本尚未签认", 422)
        concealed = data.get("isConcealed", True)
        concealed = concealed if isinstance(concealed, bool) else str(concealed).lower() in ("1", "true", "是")
        with transaction.atomic():
            baseline = Baseline.objects.select_for_update().filter(work_item=wi).first()
            bstatus = baseline.status if baseline else "草稿"
            if bstatus == "待签认":
                fail("BASELINE_PENDING_SIGN", "基线待业主签认，需业主退回后才能修改", 409)
            Project.objects.select_for_update().filter(pk=self.project.pk).first()  # 串行化项目内编号
            codes = Checkpoint.objects.filter(project=self.project).values_list("code", flat=True)
            seq = max([int(c[3:]) for c in codes if c[3:].isdigit()] or [0]) + 1
            effective = bstatus in ("已签认", "待重签")
            cp = Checkpoint.objects.create(project=self.project, work_item=wi, code=f"CK-{seq:03d}", point=point,
                                           is_concealed=concealed, drawing_version=version, page_no=page_no, x=x, y=y,
                                           is_draft=not effective, created_by=request.user)
            if effective:
                ev = BaselineEvent.objects.create(project=self.project, baseline=baseline, kind="checkpoint_added",
                                                  drawing_version=version, checkpoint=cp, actor=request.user)
                ledger.append(self.project.id, ev)
            audit.log(request.user, "checkpoint.create", "checkpoint", cp.id, f"{cp.code} {cp.point}",
                      after={"workItemId": wi.id, "drawingVersionId": version.id, "pageNo": page_no, "x": x, "y": y,
                             "isConcealed": concealed, "isDraft": cp.is_draft, "baselineStatus": bstatus},
                      project=self.project)
        return Response(wi_checkpoint_dict(cp, self.project), status=201)


def check_dict(ck, no, project):
    issue = Issue.objects.filter(source_check=ck).first()
    corrections = [{"id": c.id, "before": c.before, "after": c.after, "reason": c.reason, "actor": user_brief(c.actor),
                    "at": iso(c.at)} for c in ck.corrections.select_related("actor").order_by("id")]
    out = {"id": ck.id, "no": no, "conclusion": ck.conclusion, "checker": user_brief(ck.checker),
           "checkedAt": iso(ck.checked_at), "drawingVersionId": ck.drawing_version_id,
           "drawingLabel": version_label(ck.drawing_version), "wasLatestSigned": ck.was_latest_signed,
           "wasCovered": ck.was_covered, "note": ck.note,
           "photos": [{"id": ph.id, "file": storage.file_dict(ph.file), "sha256": ph.file_sha256, "pinX": ph.pin_x,
                       "pinY": ph.pin_y} for ph in ck.photos.select_related("file").order_by("id")],
           "changeOrder": ({"id": ck.change_order.id, "code": ck.change_order.code, "title": ck.change_order.title,
                            "status": ck.change_order.status} if ck.change_order else None),
           "discoveryPhase": current_discovery(ck) if ck.conclusion == "不一致" else "",
           "inferredDiscoveryPhase": ck.discovery_phase, "corrections": corrections,
           "issue": ({"id": issue.id, "code": issue.code, "status": issue.status, "description": issue.description}
                     if issue else None)}
    if ck.conclusion == "不一致":
        hd = handover_date(project)
        cd = timezone.localtime(ck.checked_at).date()
        kind = "实际" if project.actual_handover else "计划"
        if ck.discovery_phase == "交房后":
            out["inferBasis"] = f"核对日期 {cd} 不早于{kind}交房日期 {hd}，记为「交房后」。"
        else:
            out["inferBasis"] = (f"核对日期 {cd} 早于{kind}交房日期 {hd}，核对时{'已覆盖' if ck.discovery_phase == '覆盖后' else '未覆盖'}，"
                                 f"记为「{ck.discovery_phase}」。")
    return out


def drawing_dict(v):
    if v is None:
        return None
    pages = [{"pageNo": pg.page_no, "imageUrl": f"/api/files/{pg.image_id}/content", "width": pg.width_px,
              "height": pg.height_px} for pg in DrawingPage.objects.filter(version=v).order_by("page_no")]
    cur = v.drawing_set.current_signed_version_id
    return {"id": v.id, "setId": v.drawing_set_id, "setName": v.drawing_set.name, "versionNo": v.version_no,
            "label": version_label(v), "file": storage.file_dict(v.file), "pages": pages,
            "isCurrentSigned": cur == v.id}


def detail_dict(cp, project):
    now = timezone.now()
    cp.refresh_from_db()
    labels = shared.checkpoint_labels(cp, project, now)
    rel = latest_release(cp)
    seal = seal_of(cp, labels, rel if cp.status == "已放行" else None)
    wi = cp.work_item
    baseline = Baseline.objects.filter(work_item=wi).first()
    bv = base_version(cp)
    numbers = check_numbers(cp)
    checks = list(cp.checks.select_related("checker", "drawing_version__drawing_set", "change_order").order_by("-id"))
    resign = None
    if baseline and baseline.status == "待重签" and bv:
        newer = bv.drawing_set.current_signed_version
        if newer and newer.id != bv.id:
            so = DrawingSignoff.objects.filter(version=newer).first()
            resign = {"newVersionId": newer.id, "newLabel": version_label(newer), "oldLabel": version_label(bv),
                      "oldVersionNo": bv.version_no, "signedOn": fmt_date(so.signed_at) if so else ""}
    cover_events = [{"id": e.id, "source": e.source, "recorder": user_brief(e.recorder), "at": iso(e.at),
                     "wasUnreleased": e.was_unreleased}
                    for e in cp.cover_events.select_related("recorder").order_by("id")]
    releases = [{"id": r.id, "releaser": user_brief(r.releaser), "isProxy": r.is_proxy, "releasedAt": iso(r.released_at),
                 "basisCheckId": r.basis_check_id, "basisNo": numbers.get(r.basis_check_id)}
                for r in cp.releases.select_related("releaser").order_by("id")]
    return {
        "id": cp.id, "code": cp.code, "point": cp.point, "isConcealed": cp.is_concealed, "status": cp.status,
        "isDraft": cp.is_draft, "labels": labels, "seal": seal, "sealKind": SEAL_KIND.get(seal),
        "pageNo": cp.page_no, "x": cp.x, "y": cp.y,
        "workItem": {"id": wi.id, "name": wi.name, "phaseName": wi.phase.name, "phaseColorVar": wi.phase.color_var,
                     "floorName": wi.floor.name if wi.floor else "", "roomName": wi.room.name if wi.room else "",
                     "qcUser": user_brief(wi.qc_user), "description": wi.description,
                     "baselineStatus": baseline.status if baseline else "草稿"},
        "pinDrawing": drawing_dict(cp.drawing_version), "baseDrawing": drawing_dict(bv), "resign": resign,
        "latestCheck": latest_check_brief(cp, numbers), "nextCheckNo": len(numbers) + 1,
        "checks": [check_dict(ck, numbers[ck.id], project) for ck in checks],
        "releases": releases, "coverEvents": cover_events,
        "coveredAt": iso(cp.covered_at), "unreleasedCover": cp.unreleased_cover,
        "awaitingReleaseSince": iso(cp.awaiting_release_since), "waitingHours": waiting_hours(cp, now),
        "releasedAt": iso(cp.released_at), "releaseTimeoutHours": project.release_timeout_hours,
        "handoverDate": d(handover_date(project)), "handoverKind": "实际" if project.actual_handover else "计划",
    }


class CheckpointDetail(ProjectView):
    def get(self, request, project_id, cid):
        cp = self.obj(Checkpoint, cid)
        return Response(detail_dict(cp, self.project))


def _bool(v):
    if isinstance(v, bool):
        return v
    if v in (None, ""):
        return None
    return str(v).lower() in ("1", "true", "已被覆盖", "是")


def _cover(cp, actor, source, project):
    """记录覆盖：覆盖时间取较早值（PRD §3.2.1）；隐蔽且未放行时为「未放行先覆盖」（AC-F06-12）。调用方需已锁 cp。"""
    unreleased = cp.is_concealed and cp.status != "已放行"
    ev = CoverEvent.objects.create(project=project, checkpoint=cp, source=source, recorder=actor, was_unreleased=unreleased)
    ledger.append(project.id, ev)
    cp.covered_at = min(cp.covered_at, ev.at) if cp.covered_at else ev.at
    if unreleased:
        cp.unreleased_cover = True
    return ev


class Checks(ProjectView):
    """POST …/checkpoints/{id}/checks：对图核对（关键记录，SEQ-F06-01）。GET 返回核对历史。"""
    http_method_names = ["get", "post"]

    def get(self, request, project_id, cid):
        cp = self.obj(Checkpoint, cid)
        numbers = check_numbers(cp)
        return Response({"items": [check_dict(ck, numbers[ck.id], self.project)
                                   for ck in cp.checks.select_related("checker", "drawing_version__drawing_set",
                                                                      "change_order").order_by("-id")]})

    def post(self, request, project_id, cid):
        self.require("checkpoint.check", "只有质检可以核对")
        cp = self.obj(Checkpoint, cid)
        data = request.data
        errs = []
        photos = data.get("photos") or []
        if not isinstance(photos, list):
            photos = []
        conclusion = data.get("conclusion")
        covered = _bool(data.get("wasCovered"))
        if not photos:
            errs.append(("photos", "至少上传 1 张现场照片"))
        if conclusion not in CONCLUSIONS:
            errs.append(("conclusion", "请选择结论"))
        if covered is None:
            errs.append(("wasCovered", "请选择核对时是否已被覆盖"))
        files = []
        if photos:
            ids = []
            for ph in photos:
                fid = ph.get("fileId") if isinstance(ph, dict) else ph
                try:
                    ids.append(int(fid))
                except (TypeError, ValueError):
                    ids.append(None)
            found = {f.id: f for f in StoredFile.objects.filter(pk__in=[i for i in ids if i], project=self.project,
                                                                  status="normal")}
            if any(i not in found for i in ids):
                errs.append(("photos", "照片未上传完成或不属于本项目，请重传后再提交"))
            elif any(not found[i].mime.startswith("image/") for i in ids):
                errs.append(("photos", "现场照片只能是图片文件"))
            else:
                for ph, i in zip(photos, ids):
                    px = _coord(ph.get("x")) if isinstance(ph, dict) and ph.get("x") is not None else cp.x
                    py = _coord(ph.get("y")) if isinstance(ph, dict) and ph.get("y") is not None else cp.y
                    if px is None or py is None:
                        errs.append(("photos", "照片钉点坐标无效"))
                        break
                    files.append((found[i], px, py))
        if errs:
            raise ApiError(400, "VALIDATION_FAILED", "；".join(m for _, m in errs),
                           fields=[{"field": f, "message": m} for f, m in errs])
        co = None
        if conclusion == "已变更":
            co = ChangeOrder.objects.filter(pk=data.get("changeOrderId") or 0, project=self.project, status="已生效").first() \
                if str(data.get("changeOrderId") or "").isdigit() else None
            if co is None:
                raise ApiError(422, "CHANGE_ORDER_REQUIRED", "请关联已生效的变更单",
                               fields=[{"field": "changeOrderId", "message": "请关联已生效的变更单"}])
        note = str(data.get("note") or "").strip()[:300]
        with transaction.atomic():
            cp = Checkpoint.objects.select_for_update().get(pk=cp.pk)
            before = cp.status
            version = base_version(cp)
            ck = CheckRecord(project=self.project, checkpoint=cp, checker=request.user, drawing_version=version,
                             was_latest_signed=version.drawing_set.current_signed_version_id == version.id,
                             conclusion=conclusion, was_covered=covered, change_order=co, note=note)
            ck.checked_at = timezone.now()  # auto_now_add 会覆盖为服务器时间；此处先取值用于推断发现时点
            if conclusion == "不一致":
                ck.discovery_phase = infer_discovery(self.project, ck.checked_at, covered or bool(cp.covered_at))
            ck.save()
            ledger.append(self.project.id, ck)
            for f, px, py in files:
                ph = CheckPhoto.objects.create(project=self.project, check_record=ck, file=f, file_sha256=f.sha256,
                                               pin_x=px, pin_y=py)
                ledger.append(self.project.id, ph)
            if covered and not cp.covered_at:
                _cover(cp, request.user, "qc_check", self.project)
            # 状态迁移（技术方案 §5.1.5）
            if conclusion == "不一致":
                cp.status = "放行后发现不一致" if before == "已放行" else "不一致"
                cp.awaiting_release_since = None
            elif before != "已放行":
                if before != "待放行":
                    cp.awaiting_release_since = timezone.now()
                cp.status = "待放行"
            cp.latest_check = ck
            cp.save()
            issue = shared.create_issue_from_check(ck, request.user) if conclusion == "不一致" else None
            audit.log(request.user, "checkpoint.check", "checkpoint", cp.id, f"{cp.code} {cp.point}",
                      before={"status": before},
                      after={"status": cp.status, "checkId": ck.id, "conclusion": conclusion, "wasCovered": covered,
                             "photos": len(files), "discoveryPhase": ck.discovery_phase,
                             "issue": issue.code if issue else None}, project=self.project)
        no = check_numbers(cp)[ck.id]
        ck.refresh_from_db()
        return Response({"check": check_dict(ck, no, self.project), "status": cp.status,
                         "issue": {"id": issue.id, "code": issue.code} if issue else None}, status=201)


class Release(ProjectView):
    """POST …/checkpoints/{id}/release：业主或代理人放行（关键记录，SEQ-F06-02）。"""

    def post(self, request, project_id, cid):
        self.require("checkpoint.release")
        cp = self.obj(Checkpoint, cid)
        is_proxy = "owner" not in self.roles
        try:
            with transaction.atomic():
                cp = Checkpoint.objects.select_for_update().get(pk=cp.pk)
                if cp.status == "已放行":
                    _already_released(cp)
                if cp.latest_check_id is None:
                    fail("CANNOT_RELEASE", "该检查点尚未核对，不能放行。质检核对为「一致」或「已变更」后才能放行。", 422)
                if cp.status != "待放行" or cp.latest_check.conclusion not in RELEASABLE:
                    fail("CANNOT_RELEASE", f"当前结论为「{cp.latest_check.conclusion}」，不能放行。质检复核为「一致」或「已变更」后才能放行。", 422)
                with transaction.atomic():
                    rr = ReleaseRecord.objects.create(project=self.project, checkpoint=cp, releaser=request.user,
                                                      is_proxy=is_proxy, basis_check=cp.latest_check)
                ledger.append(self.project.id, rr)
                cp.status = "已放行"
                cp.released_at = rr.released_at
                cp.awaiting_release_since = None
                cp.save()
                audit.log(request.user, "checkpoint.release", "checkpoint", cp.id, f"{cp.code} {cp.point}",
                          before={"status": "待放行"},
                          after={"status": "已放行", "releaseId": rr.id, "isProxy": is_proxy, "basisCheckId": rr.basis_check_id,
                                 "idempotencyKey": request.headers.get("Idempotency-Key", "")}, project=self.project)
        except IntegrityError:
            _already_released(Checkpoint.objects.get(pk=cp.pk))
        return Response({"release": {"id": rr.id, "releaser": user_brief(rr.releaser), "isProxy": rr.is_proxy,
                                     "releasedAt": iso(rr.released_at), "basisCheckId": rr.basis_check_id},
                         "status": cp.status})


def _already_released(cp):
    rel = latest_release(cp)
    who = rel.releaser.name if rel else "他人"
    when = fmt_dt(rel.released_at) if rel else ""
    raise ApiError(409, "ALREADY_RELEASED", f"已由{who}于 {when} 放行，未生成新的放行记录",
                   details={"releaser": who, "releasedAt": iso(rel.released_at) if rel else None,
                            "isProxy": rel.is_proxy if rel else None})


class Cover(ProjectView):
    """POST …/checkpoints/{id}/cover：项目经理标记已覆盖（关键记录 CoverEvent，AC-F06-12）。"""

    def post(self, request, project_id, cid):
        self.require("checkpoint.mark_covered", "只有项目经理可以标记已覆盖")
        cp = self.obj(Checkpoint, cid)
        with transaction.atomic():
            cp = Checkpoint.objects.select_for_update().get(pk=cp.pk)
            if cp.covered_at:
                first = cp.cover_events.select_related("recorder").order_by("at", "id").first()
                who = first.recorder.name if first else "他人"
                raise ApiError(409, "ALREADY_COVERED", f"已由{who}于 {fmt_dt(cp.covered_at)} 记录覆盖",
                               details={"recorder": who, "coveredAt": iso(cp.covered_at)})
            ev = _cover(cp, request.user, "pm_mark", self.project)
            cp.save()
            audit.log(request.user, "checkpoint.mark_covered", "checkpoint", cp.id, f"{cp.code} {cp.point}",
                      before={"covered": False}, after={"covered": True, "coverEventId": ev.id,
                                                        "wasUnreleased": ev.was_unreleased}, project=self.project)
        return Response({"coverEvent": {"id": ev.id, "wasUnreleased": ev.was_unreleased, "at": iso(ev.at)},
                         "coveredAt": iso(cp.covered_at), "unreleasedCover": cp.unreleased_cover}, status=201)


class Correct(ProjectView):
    """POST …/checks/{id}/discovery-corrections：修正发现时点（关键记录，AC-F06-15）。"""

    def post(self, request, project_id, chid):
        self.require("discovery.correct", "只有质检或项目经理可以修正发现时点")
        ck = self.obj(CheckRecord, chid)
        if ck.conclusion != "不一致":
            fail("NOT_INCONSISTENT", "只有结论为「不一致」的核对记录有发现时点", 422)
        after = request.data.get("after")
        reason = str(request.data.get("reason") or "").strip()
        errs = []
        if after not in PHASES:
            errs.append(("after", "请选择修正后的发现时点"))
        if not reason:
            errs.append(("reason", "请填写修正理由"))
        elif len(reason) > 200:
            errs.append(("reason", "修正理由不超过 200 字"))
        if errs:
            raise ApiError(400, "VALIDATION_FAILED", "；".join(m for _, m in errs),
                           fields=[{"field": f, "message": m} for f, m in errs])
        with transaction.atomic():
            Checkpoint.objects.select_for_update().get(pk=ck.checkpoint_id)  # 串行化同一检查点的修正
            before = current_discovery(ck)
            if before == after:
                fail("VALIDATION_FAILED", f"发现时点已是「{after}」，无需修正")
            dc = DiscoveryCorrection.objects.create(project=self.project, check_record=ck, before=before, after=after,
                                                    reason=reason, actor=request.user)
            ledger.append(self.project.id, dc)
            audit.log(request.user, "checkpoint.discovery_correct", "check_record", ck.id,
                      f"{ck.checkpoint.code} 核对记录", before={"discoveryPhase": before},
                      after={"discoveryPhase": after, "reason": reason}, project=self.project)
        return Response({"id": dc.id, "before": before, "after": after, "reason": reason,
                         "actor": user_brief(request.user), "at": iso(dc.at)}, status=201)


urlpatterns = [
    path("projects/<int:project_id>/checkpoints", CheckpointList.as_view()),
    path("projects/<int:project_id>/checkpoints/<int:cid>", CheckpointDetail.as_view()),
    path("projects/<int:project_id>/checkpoints/<int:cid>/checks", Checks.as_view()),
    path("projects/<int:project_id>/checkpoints/<int:cid>/release", Release.as_view()),
    path("projects/<int:project_id>/checkpoints/<int:cid>/cover", Cover.as_view()),
    path("projects/<int:project_id>/checks/<int:chid>/discovery-corrections", Correct.as_view()),
    path("projects/<int:project_id>/work-items/<int:wid>/checkpoints", WorkItemCheckpoints.as_view()),
]
