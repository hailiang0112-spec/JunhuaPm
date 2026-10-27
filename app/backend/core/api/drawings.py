"""图纸分册与版本、页面渲染、业主签认、两版对比（API-F04-01、API-F04-02；SEQ-F04-01）。

图纸版本与签认是关键记录：只注册 GET / POST，PUT / PATCH / DELETE 一律 405（AC-F04-04）。
PDF 在服务端用 pypdfium2 渲染成 PNG 页面图（技术方案 §7.5.3），前端只显示图片。
"""
import io
import json
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.urls import path
from rest_framework.response import Response

from core.api.base import ProjectView, iso
from core.errors import ApiError, fail
from core.models import (Baseline, BaselineEvent, ChangeOrder, Checkpoint, DrawingPage, DrawingSet, DrawingSignoff, DrawingVersion,
                         ReleaseRecord, WorkItem)
from core.services import audit, ledger, storage
from core.services.shared import checkpoint_labels

DRAWING_EXT = {".pdf", ".jpg", ".jpeg", ".png"}
CAD_EXT = {".dwg", ".dxf"}
RENDER_LONG_SIDE = 3000  # 渲染长边像素：覆盖电脑端 300% 缩放，手机端流量可控
SIGNED, PENDING, SUPERSEDED = "已签认", "待业主签认", "已被新版取代"


def version_status(v, so):
    """未签认的版本只有分册最新版可签认；更早的未签认版本已被新版取代（只读留档）。"""
    if so:
        return SIGNED
    latest = v.drawing_set.versions.order_by("-version_no").values_list("version_no", flat=True).first()
    return PENDING if v.version_no == latest else SUPERSEDED


# ───────────── 序列化 ─────────────

def signoff_of(v):
    return v.signoff if hasattr(v, "signoff") else None


def version_label(v):
    return f"{v.drawing_set.name} V{v.version_no}" if v else ""


def version_brief(v):
    """供基线、检查点等引用处使用的简要信息。"""
    if v is None:
        return None
    so = signoff_of(v)
    return {"id": v.id, "setId": v.drawing_set_id, "setName": v.drawing_set.name, "versionNo": v.version_no,
            "status": version_status(v, so), "isSigned": bool(so), "signedAt": iso(so.signed_at) if so else None,
            "isCurrentSigned": v.drawing_set.current_signed_version_id == v.id}


def work_item_brief(wi):
    bl = wi.baseline if hasattr(wi, "baseline") else None
    return {"id": wi.id, "name": wi.name, "floorName": wi.floor.name if wi.floor else "全楼通用",
            "roomName": wi.room.name if wi.room else "", "phaseName": wi.phase.name,
            "baselineStatus": bl.status if bl else "草稿"}


def version_dict(v, pages=False):
    so = signoff_of(v)
    affected = [work_item_brief(w) for w in WorkItem.objects.filter(project_id=v.project_id, pk__in=v.affected_work_item_ids)
                .select_related("floor", "room", "phase", "baseline").order_by("phase__order_no", "id")]
    first = v.pages.order_by("page_no").select_related("image").first()
    out = {
        "id": v.id, "setId": v.drawing_set_id, "setName": v.drawing_set.name, "versionNo": v.version_no,
        "status": version_status(v, so), "changeNote": v.change_note,
        "file": storage.file_dict(v.file), "cadFile": storage.file_dict(v.cad_file),
        "createdBy": v.created_by.name, "createdAt": iso(v.created_at),
        "signedBy": so.signer.name if so else None, "signedAt": iso(so.signed_at) if so else None,
        "signSha256": so.file_sha256 if so else None,
        "isCurrentSigned": v.drawing_set.current_signed_version_id == v.id,
        "affectedWorkItems": affected,
        "affectedCount": len(affected),
        "affectedSignedCount": sum(1 for w in affected if w["baselineStatus"] == "已签认"),
        "changeOrderId": v.change_order_id,
        "thumbUrl": f"/api/files/{first.image_id}/thumb" if first else None,
        "pageCount": v.pages.count(),
    }
    if pages:
        out["pages"] = [{"pageNo": p.page_no, "imageUrl": f"/api/files/{p.image_id}/content", "width": p.width_px,
                         "height": p.height_px} for p in v.pages.order_by("page_no")]
    return out


def versions_qs(drawing_set):
    return (drawing_set.versions.select_related("drawing_set", "file", "cad_file", "created_by", "signoff__signer")
            .order_by("-version_no"))


def set_dict(s):
    versions = [version_dict(v) for v in versions_qs(s)]
    cur = next((v for v in versions if v["isCurrentSigned"]), None)
    return {"id": s.id, "name": s.name, "currentSignedVersion": cur,
            "hasPending": any(v["status"] == PENDING for v in versions),
            "nextVersionNo": (versions[0]["versionNo"] + 1) if versions else 1, "versions": versions}


# ───────────── 渲染 ─────────────

def render_pages(data, name, ext):
    """返回 [(png_bytes | None, width, height)]；None 表示图片原件直接作为页面图。"""
    try:
        if ext == ".pdf":
            import pypdfium2 as pdfium
            pdf = pdfium.PdfDocument(data)
            out = []
            for i in range(len(pdf)):
                page = pdf[i]
                w, h = page.get_size()
                scale = min(RENDER_LONG_SIDE / max(w, h), 8.0)
                img = page.render(scale=scale).to_pil().convert("RGB")
                buf = io.BytesIO()
                img.save(buf, "PNG", optimize=True)
                out.append((buf.getvalue(), img.width, img.height))
            pdf.close()
            if not out:
                raise ValueError("empty pdf")
            return out
        from PIL import Image, ImageOps
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
        return [(None, img.width, img.height)]
    except Exception as e:  # noqa: BLE001 — 损坏文件明确拒绝，不生成版本
        raise ApiError(400, "DRAWING_UNREADABLE", f"{name}：无法读取该图纸文件，请检查后重传",
                       fields=[{"field": "file", "message": f"{name}：无法读取该图纸文件，请检查后重传"}]) from e


def _fields_error(errs, http_status=400, code="VALIDATION_FAILED"):
    """errs: [(field, msg)]。只有一项时 message 原样等于该项文案（AC 文案原样返回）。"""
    if errs:
        raise ApiError(http_status, code, "；".join(m for _, m in errs),
                       fields=[{"field": f, "message": m} for f, m in errs])


def _parse_ids(raw):
    if raw in (None, ""):
        return []
    if isinstance(raw, list):
        vals = raw
    else:
        try:
            vals = json.loads(raw)
        except (TypeError, ValueError):
            vals = str(raw).split(",")
        if not isinstance(vals, list):
            vals = [vals]
    try:
        return sorted({int(x) for x in vals if str(x).strip()})
    except (TypeError, ValueError):
        fail("VALIDATION_FAILED", "受影响工作项格式不正确")


# ───────────── 视图 ─────────────

class DrawingSets(ProjectView):
    http_method_names = ["get", "post"]

    def get(self, request, project_id):
        sets = DrawingSet.objects.filter(project=self.project).order_by("id")
        return Response({"items": [set_dict(s) for s in sets]})

    def post(self, request, project_id):
        self.require("drawing.upload", "只有设计经理可以新建图纸分册")
        name = str(request.data.get("name", "")).strip()
        if not name:
            _fields_error([("name", "请填写分册名称")])
        if len(name) > 40:
            _fields_error([("name", "分册名称不超过 40 个字")])
        if DrawingSet.objects.filter(project=self.project, name=name).exists():
            fail("DRAWING_SET_EXISTS", "分册名称已存在", 409)
        s = DrawingSet.objects.create(project=self.project, name=name)
        audit.log(request.user, "drawing_set.create", "drawing_set", s.id, name, project=self.project, after={"name": name})
        return Response(set_dict(s), status=201)


class DrawingSetVersions(ProjectView):
    http_method_names = ["get", "post"]

    def get(self, request, project_id, set_id):
        s = self.obj(DrawingSet, set_id)
        return Response({"items": [version_dict(v) for v in versions_qs(s)]})

    def post(self, request, project_id, set_id):
        """上传新版本（AC-F04-01~03）：锁分册行后取上一版 +1。"""
        self.require("drawing.upload", "只有设计经理可以上传图纸")
        s = self.obj(DrawingSet, set_id)
        f = request.FILES.get("file")
        cad = request.FILES.get("cadFile")
        note = str(request.data.get("changeNote", "")).strip()
        wids = _parse_ids(request.data.get("affectedWorkItemIds"))
        errs = []
        if f is None:
            errs.append(("file", "请同时上传 PDF 或图片版，CAD 仅作为附件" if cad else "请上传 PDF 或图片版图纸"))
        else:
            ext = Path(f.name).suffix.lower()
            if ext not in DRAWING_EXT:
                errs.append(("file", f"{f.name}：格式不支持，仅支持 PDF、JPG、PNG"))
            elif f.size > settings.MAX_UPLOAD_BYTES:
                errs.append(("file", f"{f.name}：超过 50MB，未上传"))
        if cad is not None:
            if Path(cad.name).suffix.lower() not in CAD_EXT:
                errs.append(("cadFile", f"{cad.name}：格式不支持，CAD 附件仅支持 DWG、DXF"))
            elif cad.size > settings.MAX_UPLOAD_BYTES:
                errs.append(("cadFile", f"{cad.name}：超过 50MB，未上传"))
        last_no = s.versions.aggregate(m=Max("version_no"))["m"] or 0
        if last_no >= 1 and not note:
            errs.append(("changeNote", "请说明本版改了什么"))
        co = None
        if request.data.get("changeOrderId"):
            co = ChangeOrder.objects.filter(project=self.project, pk=request.data.get("changeOrderId")).first()
            if co is None:
                errs.append(("changeOrderId", "关联的变更单不存在"))
        if wids and WorkItem.objects.filter(project=self.project, pk__in=wids).count() != len(wids):
            errs.append(("affectedWorkItemIds", "受影响工作项不属于本项目"))
        status = 413 if any("超过 50MB" in m for _, m in errs) and len(errs) == 1 else 400
        _fields_error(errs, status, "FILE_TOO_LARGE" if status == 413 else "VALIDATION_FAILED")

        data = f.read()
        ext = Path(f.name).suffix.lower()
        rendered = render_pages(data, f.name, ext)
        with transaction.atomic():
            s = DrawingSet.objects.select_for_update().get(pk=s.pk)
            no = (s.versions.aggregate(m=Max("version_no"))["m"] or 0) + 1
            if no >= 2 and not note:
                _fields_error([("changeNote", "请说明本版改了什么")])
            sf = storage.save_bytes(data, f.name, request.user, self.project)
            cad_sf = storage.save_upload(cad, request.user, self.project, CAD_EXT) if cad else None
            v = DrawingVersion.objects.create(project=self.project, drawing_set=s, version_no=no, file=sf, cad_file=cad_sf,
                                              change_note=note, affected_work_item_ids=wids, change_order=co,
                                              created_by=request.user)
            ledger.append(self.project.id, v, extra={"file_sha256": sf.sha256,
                                                      "cad_sha256": cad_sf.sha256 if cad_sf else None})
            stem = Path(f.name).stem
            for i, (png, w, h) in enumerate(rendered, start=1):
                img = sf if png is None else storage.save_bytes(png, f"{stem}-第{i}页.png", request.user, self.project,
                                                                mime="image/png")
                DrawingPage.objects.create(version=v, page_no=i, image=img, width_px=w, height_px=h)
            audit.log(request.user, "drawing_version.create", "drawing_version", v.id, version_label(v),
                      project=self.project, after={"versionNo": no, "changeNote": v.change_note, "affected": wids})
        return Response(version_dict(v, pages=True), status=201)


class DrawingVersionDetail(ProjectView):
    http_method_names = ["get"]  # 已发布版本不可删除或替换（AC-F04-04）：其余方法 405

    def get(self, request, project_id, version_id):
        v = self.obj(DrawingVersion, version_id)
        return Response(version_dict(v, pages=True))


class DrawingVersionPages(ProjectView):
    http_method_names = ["get"]

    def get(self, request, project_id, version_id):
        v = self.obj(DrawingVersion, version_id)
        return Response({"status": "完成", "items": version_dict(v, pages=True)["pages"]})


class DrawingVersionSign(ProjectView):
    http_method_names = ["post"]

    def post(self, request, project_id, version_id):
        """业主签认（AC-F04-06、AC-F04-07、AC-F01-10）。"""
        self.require("drawing.sign", "只有业主可以签认图纸")
        v0 = self.obj(DrawingVersion, version_id)
        with transaction.atomic():
            s = DrawingSet.objects.select_for_update().get(pk=v0.drawing_set_id)
            v = DrawingVersion.objects.select_related("file", "drawing_set").get(pk=v0.pk)
            so = DrawingSignoff.objects.filter(version=v).select_related("signer").first()
            if so:
                raise ApiError(409, "ALREADY_SIGNED", f"已由{so.signer.name}于{iso(so.signed_at)[:16].replace('T', ' ')}签认",
                               details={"signer": so.signer.name, "signedAt": iso(so.signed_at)})
            if version_status(v, None) == SUPERSEDED:
                fail("SUPERSEDED", f"{version_label(v)} 已被新版取代，请签认最新版本", 409)
            cur = s.current_signed_version
            if cur and cur.version_no > v.version_no:
                fail("NEWER_SIGNED", f"已有更新的签认版 V{cur.version_no}，该版本不能再签认", 409)
            so = DrawingSignoff.objects.create(project=self.project, version=v, signer=request.user,
                                               file_sha256=v.file.sha256)
            ledger.append(self.project.id, so, extra={"version_no": v.version_no})
            s.current_signed_version = v
            s.save(update_fields=["current_signed_version"])
            resign = []
            for bl in (Baseline.objects.select_for_update()
                       .filter(project=self.project, work_item_id__in=v.affected_work_item_ids).order_by("id")):
                if bl.status != "已签认":
                    continue
                ev = BaselineEvent.objects.create(project=self.project, baseline=bl, kind="resign_required",
                                                  drawing_version=v, actor=request.user,
                                                  reason=f"{version_label(v)} 已签认，本项受影响")
                ledger.append(self.project.id, ev)
                bl.status = "待重签"
                bl.save(update_fields=["status"])
                resign.append(bl.work_item_id)
            audit.log(request.user, "drawing_version.sign", "drawing_version", v.id, version_label(v), project=self.project,
                      before={"currentSigned": cur.version_no if cur else None},
                      after={"currentSigned": v.version_no, "resignWorkItems": resign})
        out = version_dict(v, pages=False)
        out["resignCount"] = len(resign)
        out["resignWorkItemIds"] = resign
        return Response(out)


class DrawingCompare(ProjectView):
    http_method_names = ["get"]

    def get(self, request, project_id, set_id):
        """两版对比（AC-F04-05）：两版信息 + 较早版本（不含）到较晚版本（含）之间全部版本的改动说明。"""
        s = self.obj(DrawingSet, set_id)
        try:
            a = s.versions.get(pk=int(request.GET.get("from", 0)))
            b = s.versions.get(pk=int(request.GET.get("to", 0)))
        except (ValueError, DrawingVersion.DoesNotExist):
            fail("NOT_FOUND", "版本不存在", 404)
        if a.pk == b.pk:
            fail("VALIDATION_FAILED", "请选择两个不同的版本")
        lo, hi = sorted([a, b], key=lambda x: x.version_no)
        between = [version_dict(v) for v in versions_qs(s).filter(version_no__gt=lo.version_no, version_no__lte=hi.version_no)
                   .order_by("version_no")]
        return Response({"left": version_dict(a, pages=True), "right": version_dict(b, pages=True),
                         "range": f"V{lo.version_no} → V{hi.version_no} · 共 {len(between)} 版", "notes": between})


class DrawingVersionPins(ProjectView):
    http_method_names = ["get"]

    def get(self, request, project_id, version_id):
        """钉点图层：绑定在该版本上的检查点（PAGE-F04-02，DEC-209）。草稿检查点不显示。"""
        v = self.obj(DrawingVersion, version_id)
        cps = (Checkpoint.objects.filter(project=self.project, drawing_version=v, is_draft=False)
               .select_related("work_item__floor", "work_item__room", "latest_check").order_by("code"))
        proxy = set(ReleaseRecord.objects.filter(checkpoint__in=cps, is_proxy=True).values_list("checkpoint_id", flat=True))
        items = []
        for cp in cps:
            wi = cp.work_item
            items.append({"id": cp.id, "code": cp.code, "point": cp.point, "isConcealed": cp.is_concealed,
                          "status": cp.status, "pageNo": cp.page_no, "x": cp.x, "y": cp.y,
                          "labels": checkpoint_labels(cp, self.project),
                          "isProxyReleased": cp.status == "已放行" and cp.id in proxy,
                          "workItemId": wi.id, "workItemName": wi.name,
                          "floorName": wi.floor.name if wi.floor else "全楼通用", "roomName": wi.room.name if wi.room else "",
                          "awaitingReleaseSince": iso(cp.awaiting_release_since)})
        return Response({"items": items})


urlpatterns = [
    path("projects/<int:project_id>/drawing-sets", DrawingSets.as_view()),
    path("projects/<int:project_id>/drawing-sets/<int:set_id>/versions", DrawingSetVersions.as_view()),
    path("projects/<int:project_id>/drawing-sets/<int:set_id>/compare", DrawingCompare.as_view()),
    path("projects/<int:project_id>/drawing-versions/<int:version_id>", DrawingVersionDetail.as_view()),
    path("projects/<int:project_id>/drawing-versions/<int:version_id>/pages", DrawingVersionPages.as_view()),
    path("projects/<int:project_id>/drawing-versions/<int:version_id>/sign", DrawingVersionSign.as_view()),
    path("projects/<int:project_id>/drawing-versions/<int:version_id>/checkpoints", DrawingVersionPins.as_view()),
]
