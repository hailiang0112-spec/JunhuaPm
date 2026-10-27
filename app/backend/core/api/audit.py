"""审计与证据（REQ-F17-01 ~ 04、REQ-F14-02）。

- API-F17-01 完整性校验：调用 ledger.verify 逐条重算摘要链（SEQ-F17-03），结果「完整」或第一条不一致记录的编号与时间。
- API-F17-02 证据包导出：按工段 / 楼层 / 房间 / 时间范围生成 ZIP（SEQ-F17-02），本期在请求内同步生成并记入 job 表。
- API-F17-03 操作日志：按时间、对象、操作人筛选，显示前后值。
- API-F14-01 计划留档 CSV 导出。
- 关键记录兜底路由：对关键记录资源发 PUT / PATCH / DELETE 一律 405 KEY_RECORD_IMMUTABLE（技术方案 §4.4、AC-F17-01）。
"""
import csv
import datetime
import hashlib
import io
import json
import zipfile
from urllib.parse import quote

from django.apps import apps
from django.db.models import Q
from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse
from django.urls import path, re_path
from django.utils import timezone
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.response import Response
from rest_framework.views import APIView

from core import perms
from core.api.base import ProjectView, d, iso, paginate
from core.errors import ApiError, validation
from core.models import (AcceptancePhoto, AuditLog, DrawingVersion, Floor,
                         Job, LedgerEntry, Phase, PlanChangeLog, ProjectMemberRole, Room, User, WorkItem)
from core.services import audit, audit_labels, ledger, storage

TYPE_LABELS = {
    "core_drawingversion": "图纸版本", "core_drawingsignoff": "图纸签认", "core_baselinerevision": "基线修订",
    "core_baselinesignoff": "基线签认", "core_baselineevent": "基线事件", "core_checkrecord": "核对记录",
    "core_checkphoto": "核对照片", "core_releaserecord": "放行记录", "core_coverevent": "覆盖事件",
    "core_discoverycorrection": "发现时点修正", "core_changeorderevent": "变更单状态", "core_issueevent": "问题状态变化",
    "core_planchangelog": "计划留档",
}
OBJECT_TYPE_LABELS = audit_labels.OBJECT_TYPES
LABEL_ORDER = ["owner", "design_manager", "pm", "qc", "budget", "owner_agent", "owner_member"]
ZIP_ITEMS = ["记录清单.xlsx", "照片原件/", "图纸版本/", "签认快照/", "摘要清单.csv"]


def kr(seq):
    return f"KR-{seq:06d}"


def fmt_time(dt):
    return timezone.localtime(dt).strftime("%Y-%m-%d %H:%M:%S") if dt else ""


def short_name(project):
    return project.name.replace("·", "").replace(" ", "")


def stamp_date():
    return timezone.localdate().strftime("%Y%m%d")


def ledger_tail(project):
    last = LedgerEntry.objects.filter(project=project).order_by("-seq").first()
    return last


# ——————————————————— 关键记录的归属解析（证据包范围、记录说明） ———————————————————

def _models():
    return {m._meta.db_table: m for m in apps.get_app_config("core").get_models()}


class RecordInfo:
    """一条关键记录在证据包中的归属：工作项（可多个）、工段、时间、对象说明、操作人。"""

    def __init__(self, entry, obj):
        self.entry = entry
        self.obj = obj
        self.work_items = []
        self.phase_ids = set()
        self.at = entry.created_at
        self.subject = ""
        self.actor = ""
        self.summary = ""
        self.drawing_version_ids = set()
        self.photo = None
        self.snapshot = None
        self.structural = True  # False：无法归属到楼层 / 房间（如计划留档），仅在未选楼层与房间时纳入
        resolve(self)

    @property
    def type_label(self):
        return TYPE_LABELS.get(self.entry.record_type, self.entry.record_type)

    @property
    def label(self):
        return f"{self.subject} {self.type_label}".strip()


def _wi(info, wi):
    if wi is not None:
        info.work_items.append(wi)
        info.phase_ids.add(wi.phase_id)


def _name(u):
    return u.name if u else ""


def resolve(info):
    t, o = info.entry.record_type, info.obj
    if o is None:
        info.subject = f"#{info.entry.record_id}"
        info.summary = "记录不存在"
        return
    if t == "core_checkrecord":
        cp = o.checkpoint
        _wi(info, cp.work_item)
        info.at, info.actor, info.subject = o.checked_at, _name(o.checker), f"检查点 {cp.code}"
        info.summary = f"结论：{o.conclusion}" + (f"；发现时点：{o.discovery_phase}" if o.discovery_phase else "") + (f"；{o.note}" if o.note else "")
        info.drawing_version_ids.add(o.drawing_version_id)
    elif t == "core_checkphoto":
        cr = o.check_record
        _wi(info, cr.checkpoint.work_item)
        info.at, info.actor, info.subject = cr.checked_at, _name(cr.checker), f"检查点 {cr.checkpoint.code}"
        info.summary = f"照片 {o.file.original_name}（SHA-256 {o.file_sha256[:12]}…）"
        info.photo = o
    elif t == "core_releaserecord":
        _wi(info, o.checkpoint.work_item)
        info.at, info.actor, info.subject = o.released_at, _name(o.releaser), f"检查点 {o.checkpoint.code}"
        info.summary = "代理放行" if o.is_proxy else "业主放行"
        info.drawing_version_ids.add(o.checkpoint.drawing_version_id)
    elif t == "core_coverevent":
        _wi(info, o.checkpoint.work_item)
        info.at, info.actor, info.subject = o.at, _name(o.recorder), f"检查点 {o.checkpoint.code}"
        info.summary = "未放行先覆盖" if o.was_unreleased else "放行后覆盖"
    elif t == "core_discoverycorrection":
        _wi(info, o.check_record.checkpoint.work_item)
        info.at, info.actor, info.subject = o.at, _name(o.actor), f"检查点 {o.check_record.checkpoint.code}"
        info.summary = f"发现时点 {o.before} → {o.after}；原因：{o.reason}"
    elif t == "core_baselinerevision":
        _wi(info, o.baseline.work_item)
        info.at, info.actor, info.subject = o.created_at, _name(o.actor), f"工作项 {o.baseline.work_item.name}"
        info.summary = f"第 {o.rev_no} 版（{'变更单生效' if o.kind == 'change_order' else '提交'}）"
        dv = (o.content or {}).get("drawingVersionId") or (o.content or {}).get("drawing_version_id")
        if dv:
            info.drawing_version_ids.add(dv)
    elif t == "core_baselinesignoff":
        bl = o.revision.baseline
        _wi(info, bl.work_item)
        info.at, info.actor, info.subject = o.signed_at, _name(o.signer), f"工作项 {bl.work_item.name}"
        info.summary = f"签认基线第 {o.revision.rev_no} 版"
        info.snapshot = (f"签认快照/基线签认-{kr(info.entry.seq)}.json",
                         {"类型": "基线签认", "工作项": bl.work_item.name, "签认人": _name(o.signer), "签认时间": iso(o.signed_at),
                          "修订号": o.revision.rev_no, "内容快照": o.content_snapshot})
    elif t == "core_baselineevent":
        _wi(info, o.baseline.work_item)
        info.at, info.actor, info.subject = o.at, _name(o.actor), f"工作项 {o.baseline.work_item.name}"
        info.summary = o.kind + (f"：{o.reason}" if o.reason else "")
        if o.drawing_version_id:
            info.drawing_version_ids.add(o.drawing_version_id)
    elif t in ("core_drawingversion", "core_drawingsignoff"):
        dv = o if t == "core_drawingversion" else o.version
        for wi in WorkItem.objects.filter(pk__in=dv.affected_work_item_ids or []):
            _wi(info, wi)
        for wi in WorkItem.objects.filter(drawing_version=dv):
            if wi not in info.work_items:
                _wi(info, wi)
        info.drawing_version_ids.add(dv.id)
        info.subject = f"图纸 {dv.drawing_set.name} V{dv.version_no}"
        if t == "core_drawingversion":
            info.at, info.actor, info.summary = dv.created_at, _name(dv.created_by), dv.change_note or "新版本"
        else:
            info.at, info.actor, info.summary = o.signed_at, _name(o.signer), "业主签认"
            info.snapshot = (f"签认快照/图纸签认-{kr(info.entry.seq)}.json",
                             {"类型": "图纸签认", "图纸": info.subject, "签认人": _name(o.signer), "签认时间": iso(o.signed_at),
                              "文件": dv.file.original_name, "文件SHA-256": o.file_sha256})
        info.structural = bool(info.work_items)
    elif t == "core_changeorderevent":
        co = o.change_order
        for wi in co.work_items.all():
            _wi(info, wi)
        info.at, info.actor, info.subject = o.at, _name(o.actor), f"变更单 {co.code}"
        info.summary = f"{o.kind}（第 {o.round_no} 轮）"
        info.structural = bool(info.work_items)
        if o.kind == "signed":
            info.snapshot = (f"签认快照/变更单签认-{co.code}-{kr(info.entry.seq)}.json",
                             {"类型": "变更单签认", "变更单": co.code, "标题": co.title, "签认人": _name(o.actor), "签认时间": iso(o.at),
                              "轮次": o.round_no, "内容": o.payload})
    elif t == "core_issueevent":
        iss = o.issue
        if iss.work_item_id:
            _wi(info, iss.work_item)
        elif iss.phase_id:
            info.phase_ids.add(iss.phase_id)
        info.at, info.actor, info.subject = o.at, _name(o.actor), f"问题 {iss.code}"
        info.summary = f"{o.kind}：{o.before or '—'} → {o.after or '—'}" + (f"；{o.reason}" if o.reason else "")
        info.issue = iss
    elif t == "core_planchangelog":
        info.phase_ids.add(o.phase_id)
        info.at, info.actor, info.subject = o.at, _name(o.actor), f"工段 {o.phase.name}"
        info.summary = "；".join(f"{c.get('label', c.get('field'))} {c.get('before')} → {c.get('after')}" for c in (o.changes or []))
        info.structural = False
    else:
        info.subject = f"#{info.entry.record_id}"
        info.structural = False


def in_scope(info, phase_id, floor_id, room_id, date_from, date_to):
    day = timezone.localtime(info.at).date()
    if date_from and day < date_from or date_to and day > date_to:
        return False
    if phase_id and phase_id not in info.phase_ids:
        return False
    if floor_id or room_id:
        issue = getattr(info, "issue", None)
        if issue is not None and not info.work_items:
            return (not floor_id or issue.floor_id == floor_id) and (not room_id or issue.room_id == room_id)
        if not info.work_items:
            return False
        return any((not floor_id or wi.floor_id == floor_id) and (not room_id or wi.room_id == room_id) for wi in info.work_items)
    return True


# ——————————————————— 完整性校验（API-F17-01） ———————————————————

def first_bad_detail(project, bad):
    if not bad:
        return None
    e = LedgerEntry.objects.get(project=project, seq=bad["seq"])
    model = _models().get(e.record_type)
    obj = model.objects.filter(pk=e.record_id).first() if model else None
    info = RecordInfo(e, obj)
    return {"code": kr(e.seq), "seq": e.seq, "at": iso(e.created_at), "atText": fmt_time(e.created_at),
            "recordType": TYPE_LABELS.get(e.record_type, e.record_type), "recordLabel": info.label}


def job_dict(job):
    return {"id": job.id, "kind": job.kind, "status": job.status, "progress": job.progress, "params": job.params,
            "result": job.result, "error": job.error, "createdBy": job.created_by.name, "createdAt": iso(job.created_at),
            "finishedAt": iso(job.finished_at)}


class IntegrityChecks(ProjectView):
    def get(self, request, project_id):
        self.require("integrity.check")
        latest = Job.objects.filter(project=self.project, kind="integrity_check", status="完成").order_by("-id").first()
        tail = ledger_tail(self.project)
        return Response({"latest": job_dict(latest) if latest else None,
                         "ledgerCount": LedgerEntry.objects.filter(project=self.project).count(),
                         "tail": tail.hash if tail else ledger.GENESIS})

    def post(self, request, project_id):
        self.require("integrity.check")
        job = Job.objects.create(kind="integrity_check", project=self.project, status="进行中", created_by=request.user)
        res = ledger.verify(self.project.id)
        job.result = {"ok": res["ok"], "count": res["count"], "tail": res["tail"],
                      "firstBad": first_bad_detail(self.project, res["first_bad"]), "checkedAt": iso(timezone.now())}
        job.status, job.progress, job.finished_at = "完成", 100, timezone.now()
        job.save()
        audit.log(request.user, "校验", "完整性校验", job.id, "摘要链完整性校验", None,
                  {"结果": "完整" if res["ok"] else "不完整", "条数": res["count"]}, project=self.project)
        return Response(job_dict(job), status=201)


class IntegrityCheckDetail(ProjectView):
    def get(self, request, project_id, job_id):
        self.require("integrity.check")
        return Response(job_dict(self.obj(Job, job_id, kind="integrity_check")))


# ——————————————————— 证据包（API-F17-02，SEQ-F17-02） ———————————————————

def _parse_scope(project, data):
    def pick(model, key, **extra):
        v = data.get(key)
        if v in (None, "", 0, "0"):
            return None
        try:
            return model.objects.get(pk=int(v), project=project, **extra)
        except (ValueError, TypeError, model.DoesNotExist):
            validation([(key, "所选范围不存在")])

    phase = pick(Phase, "phaseId")
    floor = pick(Floor, "floorId")
    room = pick(Room, "roomId")
    if room and floor and room.floor_id != floor.id:
        validation([("roomId", "房间与楼层不匹配")])
    errs, dates = [], {}
    for key in ("from", "to"):
        v = data.get(key)
        if v:
            try:
                dates[key] = datetime.date.fromisoformat(str(v))
            except ValueError:
                errs.append((key, "日期格式不正确"))
    validation(errs)
    if dates.get("from") and dates.get("to") and dates["from"] > dates["to"]:
        validation([("from", "开始日期不能晚于结束日期")])
    return phase, floor, room, dates.get("from"), dates.get("to")


def _safe(name):
    return "".join("_" if c in '\\/:*?"<>|' else c for c in name)


def build_evidence(project, phase, floor, room, date_from, date_to, out):
    """把证据包 ZIP 写入文件对象 out，返回摘要信息。只纳入导出开始时链尾及以前的记录，保证清单与链尾一致。"""
    tail = ledger_tail(project)
    tail_seq = tail.seq if tail else 0
    tail_hash = tail.hash if tail else ledger.GENESIS
    models = _models()
    entries = list(LedgerEntry.objects.filter(project=project, seq__lte=tail_seq).order_by("seq"))
    infos = []
    for e in entries:
        model = models.get(e.record_type)
        obj = model.objects.filter(pk=e.record_id).first() if model else None
        info = RecordInfo(e, obj)
        info.in_scope = (obj is not None and in_scope(info, phase.id if phase else None, floor.id if floor else None,
                                                      room.id if room else None, date_from, date_to)
                         and (info.structural or not (floor or room)))
        infos.append(info)
    scoped = [i for i in infos if i.in_scope]

    anomalies = []
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
        # 1. 记录清单.xlsx
        import xlsxwriter
        xb = io.BytesIO()
        wb = xlsxwriter.Workbook(xb, {"in_memory": True})
        ws = wb.add_worksheet("记录清单")
        head = wb.add_format({"bold": True, "bg_color": "#F2EEE6"})
        cols = ["编号", "记录类型", "时间", "工段", "楼层", "房间", "工作项", "对象", "内容摘要", "操作人", "本条摘要"]
        ws.write_row(0, 0, cols, head)
        phase_names = dict(Phase.objects.filter(project=project).values_list("id", "name"))
        for r, i in enumerate(scoped, start=1):
            wis = i.work_items
            ws.write_row(r, 0, [kr(i.entry.seq), i.type_label, fmt_time(i.at),
                                "、".join(sorted({phase_names.get(p, "") for p in i.phase_ids})),
                                "、".join(dict.fromkeys(w.floor.name if w.floor else "全楼通用" for w in wis)),
                                "、".join(dict.fromkeys(w.room.name if w.room else "本层通用" for w in wis)),
                                "、".join(dict.fromkeys(w.name for w in wis)), i.subject, i.summary, i.actor, i.entry.hash])
        ws.set_column(0, 0, 12)
        ws.set_column(1, 6, 14)
        ws.set_column(7, 8, 36)
        ws.set_column(10, 10, 66)
        ws.freeze_panes(1, 0)
        wb.close()
        z.writestr("记录清单.xlsx", xb.getvalue())

        # 2. 照片原件（核对照片 + 范围内阶段验收图片），不压缩
        def put_file(sf, arcname, expect_sha):
            try:
                data = storage.get_bytes(sf.storage_key)
            except Exception as ex:  # noqa: BLE001 — 文件缺失写入「文件校验异常」清单，不中断整包导出（SEQ-F17-02）
                anomalies.append((arcname, sf.original_name, f"读取失败：{type(ex).__name__}"))
                return
            if hashlib.sha256(data).hexdigest() != expect_sha:
                anomalies.append((arcname, sf.original_name, "SHA-256 与入库值不符"))
            z.writestr(zipfile.ZipInfo(arcname, date_time=timezone.localtime(sf.created_at).timetuple()[:6]), data,
                       compress_type=zipfile.ZIP_STORED)

        photo_count = 0
        for i in scoped:
            if i.photo is not None:
                ph = i.photo
                put_file(ph.file, f"照片原件/{ph.check_record.checkpoint.code}-{kr(i.entry.seq)}-{_safe(ph.file.original_name)}",
                         ph.file_sha256)
                photo_count += 1
        if not (floor or room):
            aps = AcceptancePhoto.objects.filter(project=project, file__isnull=False).select_related("file", "phase")
            if phase:
                aps = aps.filter(phase=phase)
            for ap in aps:
                day = timezone.localtime(ap.created_at).date()
                if date_from and day < date_from or date_to and day > date_to:
                    continue
                put_file(ap.file, f"照片原件/阶段验收-{_safe(ap.phase.name)}-{ap.id}-{_safe(ap.file.original_name)}", ap.file.sha256)
                photo_count += 1

        # 3. 相关图纸版本文件
        dv_ids = set()
        for i in scoped:
            dv_ids |= {x for x in i.drawing_version_ids if x}
            for wi in i.work_items:
                if wi.drawing_version_id:
                    dv_ids.add(wi.drawing_version_id)
        dvs = DrawingVersion.objects.filter(project=project, pk__in=dv_ids).select_related("drawing_set", "file", "cad_file")
        for dv in dvs:
            for sf in (dv.file, dv.cad_file):
                if sf is not None:
                    put_file(sf, f"图纸版本/{_safe(dv.drawing_set.name)}-V{dv.version_no}-{_safe(sf.original_name)}", sf.sha256)

        # 4. 签认内容快照
        snap_count = 0
        for i in scoped:
            if i.snapshot:
                name, content = i.snapshot
                z.writestr(name, json.dumps({**content, "编号": kr(i.entry.seq), "摘要": i.entry.hash}, ensure_ascii=False, indent=2))
                snap_count += 1

        # 5. 摘要清单（范围内记录的规范化内容 + 全链 seq/prev/hash，含导出时链尾摘要）
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["导出时链尾摘要", tail_hash])
        w.writerow(["链尾编号", kr(tail_seq) if tail_seq else "（空链）"])
        w.writerow(["导出时间", fmt_time(timezone.now())])
        w.writerow([])
        w.writerow(["编号", "记录类型", "记录ID", "时间", "上一条摘要", "本条摘要", "在导出范围内", "规范化内容"])
        for i in infos:
            e = i.entry
            w.writerow([kr(e.seq), TYPE_LABELS.get(e.record_type, e.record_type), e.record_id, fmt_time(e.created_at), e.prev_hash,
                        e.hash, "是" if i.in_scope else "否", e.content if i.in_scope else ""])
        z.writestr("摘要清单.csv", "﻿" + out.getvalue())

        if anomalies:
            out = io.StringIO()
            w = csv.writer(out)
            w.writerow(["包内路径", "原文件名", "异常"])
            w.writerows(anomalies)
            z.writestr("文件校验异常.csv", "﻿" + out.getvalue())

        z.writestr("核验说明.txt", (
            "本证据包由君华装修项目管理平台导出。\n"
            "摘要算法：hash = SHA-256(规范化内容的 UTF-8 字节 ‖ 上一条摘要的十六进制字符串)，首条的上一条摘要为 64 个 0。\n"
            "核验方法：按「摘要清单.csv」中的编号顺序，用任意 SHA-256 工具对「规范化内容 + 上一条摘要」重算，应与「本条摘要」一致；"
            "全链 seq / 摘要列表用来证明范围外记录没有被插入或删除；请自行保存导出时链尾摘要，用于发现末尾记录被整体截断。\n"
            f"导出时链尾摘要：{tail_hash}\n"))
    return {"count": len(scoped), "photoCount": photo_count, "drawingCount": len(dvs), "snapshotCount": snap_count,
                            "tail": tail_hash, "tailCode": kr(tail_seq) if tail_seq else None, "anomalies": len(anomalies)}


class EvidenceExports(ProjectView):
    def get(self, request, project_id):
        self.require("evidence.export")
        floors = [{"id": f.id, "name": f.name, "rooms": [{"id": r.id, "name": r.name} for r in f.rooms.filter(is_disabled=False)]}
                  for f in Floor.objects.filter(project=self.project, is_disabled=False).prefetch_related("rooms")]
        recent = Job.objects.filter(project=self.project, kind="evidence_export").order_by("-id")[:5]
        return Response({"options": {"phases": [{"id": p.id, "name": p.name} for p in Phase.objects.filter(project=self.project)],
                                     "floors": floors},
                         "defaultFrom": d(self.project.planned_start), "defaultTo": d(timezone.localdate()),
                         "zipItems": ZIP_ITEMS, "recent": [job_dict(j) for j in recent]})

    def post(self, request, project_id):
        self.require("evidence.export")
        data = request.data or {}
        phase, floor, room, date_from, date_to = _parse_scope(self.project, data)
        parts = [x.name for x in (phase, floor, room) if x]
        scope_label = " / ".join(parts) or "全部工段、楼层、房间"
        frm = date_from or self.project.planned_start
        to = date_to or timezone.localdate()
        file_name = f"{short_name(self.project)}-证据包-{'-'.join(parts) or '全项目'}-{stamp_date()}.zip"
        params = {"phaseId": phase.id if phase else None, "floorId": floor.id if floor else None, "roomId": room.id if room else None,
                  "from": d(date_from), "to": d(date_to)}
        params.update({"fileName": file_name, "scopeLabel": f"{scope_label}，{d(frm)} 至 {d(to)}"})
        job = Job.objects.create(kind="evidence_export", project=self.project, params=params, status="排队", created_by=request.user)
        if settings.JOBS_INLINE:
            run_evidence_job(job)
        return Response(job_dict(job), status=201)


def run_evidence_job(job):
    """生成证据包（worker 或开发环境内联调用）：ZIP 写临时文件，边写边不占内存，完成后存入文件存储。"""
    import tempfile

    pj = job.project
    pr = job.params
    get = lambda model, k: model.objects.filter(project=pj, pk=pr[k]).first() if pr.get(k) else None  # noqa: E731
    phase, floor, room = get(Phase, "phaseId"), get(Floor, "floorId"), get(Room, "roomId")
    date_from = datetime.date.fromisoformat(pr["from"]) if pr.get("from") else None
    date_to = datetime.date.fromisoformat(pr["to"]) if pr.get("to") else None
    job.status = "进行中"
    job.save(update_fields=["status"])
    with tempfile.TemporaryFile() as tmp:
        info = build_evidence(pj, phase, floor, room, date_from, date_to, tmp)
        size = tmp.tell()
        tmp.seek(0)
        h = hashlib.sha256()
        for chunk in iter(lambda: tmp.read(1024 * 1024), b""):
            h.update(chunk)
        sha = h.hexdigest()
        key = f"exports/{sha}.zip"
        storage.put_file(key, tmp)
    job.result = {**info, "fileName": pr["fileName"], "key": key, "size": size, "sha256": sha, "scopeLabel": pr["scopeLabel"]}
    job.status, job.progress, job.finished_at = "完成", 100, timezone.now()
    job.save()
    audit.log(job.created_by, "导出", "证据包", job.id, pr["fileName"], None, {"范围": pr["scopeLabel"], "记录数": info["count"]},
              project=pj)


class EvidenceExportDetail(ProjectView):
    def get(self, request, project_id, job_id):
        self.require("evidence.export")
        return Response(job_dict(self.obj(Job, job_id, kind="evidence_export")))


class EvidenceExportDownload(ProjectView):
    def get(self, request, project_id, job_id):
        self.require("evidence.export")
        job = self.obj(Job, job_id, kind="evidence_export")
        if job.status != "完成":
            raise ApiError(409, "JOB_NOT_READY", "证据包还在生成中，请稍后下载")
        resp = FileResponse(storage.open_file(job.result["key"]), content_type="application/zip")
        resp["Content-Length"] = str(job.result["size"])
        resp["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(job.result['fileName'])}"
        return resp


# ——————————————————— 操作日志（API-F17-03） ———————————————————

def _roles_by_user(project):
    out = {}
    for uid, role in ProjectMemberRole.objects.filter(project=project).values_list("user_id", "role"):
        out.setdefault(uid, set()).add(role)
    return out


def _role_label(roles, user):
    for r in LABEL_ORDER:
        if r in roles:
            return perms.ROLE_LABELS[r]
    return "公司管理员" if user and user.is_company_admin else ""


def _type_label(t):
    return OBJECT_TYPE_LABELS.get(t.lower(), t) if t else ""


class AuditLogs(ProjectView):
    def get(self, request, project_id):
        self.require("audit.read")
        base = AuditLog.objects.filter(project=self.project)
        qs = base.select_related("actor").order_by("-at", "-id")
        g = request.GET
        errs = []
        for key, op in (("from", "at__date__gte"), ("to", "at__date__lte")):
            if g.get(key):
                try:
                    qs = qs.filter(**{op: datetime.date.fromisoformat(g[key])})
                except ValueError:
                    errs.append((key, "日期格式不正确"))
        validation(errs)
        if g.get("objectType"):
            raw = [t for t in base.values_list("object_type", flat=True).distinct() if _type_label(t) == g["objectType"]]
            qs = qs.filter(object_type__in=raw or [g["objectType"]])
        if g.get("objectId"):
            kw = g["objectId"].strip()
            qs = qs.filter(Q(object_id=kw) | Q(object_label__icontains=kw))
        if g.get("actorId"):
            qs = qs.filter(actor_id=g["actorId"])
        roles = _roles_by_user(self.project)

        def ser(a):
            return {"id": a.id, "at": iso(a.at), "actorId": a.actor_id, "actorName": a.actor.name if a.actor else "系统",
                    "actorRole": _role_label(roles.get(a.actor_id, set()), a.actor), "action": audit_labels.action(a.action),
                    "objectType": _type_label(a.object_type), "objectId": a.object_id, "objectLabel": a.object_label,
                    "before": audit_labels.values(a.before), "after": audit_labels.values(a.after)}

        out = paginate(request, qs, ser)
        actor_ids = base.exclude(actor=None).values_list("actor_id", flat=True).distinct()
        out["facets"] = {"actors": [{"id": u.id, "name": u.name} for u in User.objects.filter(pk__in=actor_ids).order_by("id")],
                         "objectTypes": sorted({_type_label(t) for t in base.values_list("object_type", flat=True).distinct()})}
        return Response(out)


# ——————————————————— 计划留档 CSV（API-F14-01，AC-F14-04） ———————————————————

CSV_COLUMNS = ["记录时间", "工段", "变更项", "变更前", "变更后", "工期影响（天）", "变更原因备注"]


def _delta(v):
    if v is None:
        return ""
    return f"+{v}" if v > 0 else str(v)


def plan_log_rows(project):
    for log in PlanChangeLog.objects.filter(project=project).select_related("phase").order_by("at", "id"):
        changes = log.changes or [{}]
        for c in changes:
            yield [timezone.localtime(log.at).strftime("%Y-%m-%d %H:%M"), log.phase.name, c.get("label") or c.get("field") or "",
                   "" if c.get("before") is None else str(c.get("before")), "" if c.get("after") is None else str(c.get("after")),
                   _delta(log.duration_delta_days), log.reason]


class AuditSummary(ProjectView):
    def get(self, request, project_id):
        return Response({"planLogCount": PlanChangeLog.objects.filter(project=self.project).count(), "csvColumns": CSV_COLUMNS,
                         "csvFileName": f"{short_name(self.project)}-计划变更留档-{stamp_date()}.csv"})


class PlanLogCsv(ProjectView):
    http_method_names = ["get"]

    def get(self, request, project_id):
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(CSV_COLUMNS)
        w.writerows(plan_log_rows(self.project))
        name = f"{short_name(self.project)}-计划变更留档-{stamp_date()}.csv"
        resp = HttpResponse("﻿" + out.getvalue(), content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(name)}"
        return resp


# ——————————————————— 关键记录兜底：PUT / PATCH / DELETE → 405 ———————————————————

KEY_SEGMENTS = ["drawing-versions", "drawing-signoffs", "signoffs", "baseline-revisions", "baseline-signoffs", "revisions", "baseline-events",
                "checks", "check-records", "check-photos", "releases", "release-records", "cover-events",
                "discovery-corrections", "corrections", "change-order-events", "issue-events", "events", "plan-logs",
                "audit-logs", "ledger"]


class KeyRecordImmutable(APIView):
    """没有被具体模块匹配的关键记录路径：读取返回 404；任何修改或删除一律 405 KEY_RECORD_IMMUTABLE。"""

    def get(self, request, *args, **kwargs):
        raise Http404

    def post(self, request, *args, **kwargs):
        raise Http404

    def put(self, request, *args, **kwargs):
        raise MethodNotAllowed(request.method)

    patch = put
    delete = put


urlpatterns = [
    path("projects/<int:project_id>/integrity-checks", IntegrityChecks.as_view()),
    path("projects/<int:project_id>/integrity-checks/<int:job_id>", IntegrityCheckDetail.as_view()),
    path("projects/<int:project_id>/evidence-exports", EvidenceExports.as_view()),
    path("projects/<int:project_id>/evidence-exports/<int:job_id>", EvidenceExportDetail.as_view()),
    path("projects/<int:project_id>/evidence-exports/<int:job_id>/download", EvidenceExportDownload.as_view()),
    path("projects/<int:project_id>/audit-logs", AuditLogs.as_view()),
    path("projects/<int:project_id>/audit-summary", AuditSummary.as_view()),
    path("projects/<int:project_id>/plan-logs/export.csv", PlanLogCsv.as_view()),
    re_path(r"^projects/(?P<project_id>\d+)/(?:[\w-]+/)*(?:%s)(?:/[^/]+)*/?$" % "|".join(KEY_SEGMENTS), KeyRecordImmutable.as_view()),
]
