"""房屋档案（API-F12-03，REQ-F12-03）：三个专区的分类管理、文件上传 / 移动 / 作废；合同专区按角色可见（AC-F12-06）。

上传与作废沿用工作项资料规则（DEC-121）：单个 ≤ 50MB、允许图片 / PDF / Word / Excel；删除改为作废并留痕，
被核对、签认或变更单引用的文件不能作废（AC-F12-03）；作废仅限上传者本人。
"""
from django.db import transaction
from django.urls import path
from django.utils import timezone
from rest_framework.response import Response

from core.api.base import ProjectView, d, iso
from core.errors import ApiError, fail, validation
from core.models import ArchiveFile, ArchiveFolder, ChangeOrder, CheckPhoto, DrawingVersion, StoredFile
from core.services import audit, storage

ZONES = {"layout": "平面布局图", "render": "三维效果图", "contract": "装修合同"}
UNVOIDABLE = "该文件已被核对、签认或变更单引用，不能作废"


def file_refs(sf):
    """文件被哪些关键记录引用（核对照片、图纸版本、变更单附件）。"""
    refs = []
    for ph in CheckPhoto.objects.filter(file=sf).select_related("check_record__checkpoint"):
        refs.append(f"核对记录 {ph.check_record.checkpoint.code}")
    for dv in DrawingVersion.objects.filter(project_id=sf.project_id).filter(file=sf).select_related("drawing_set"):
        refs.append(f"图纸 {dv.drawing_set.name} V{dv.version_no}")
    for dv in DrawingVersion.objects.filter(project_id=sf.project_id).filter(cad_file=sf).select_related("drawing_set"):
        refs.append(f"图纸 {dv.drawing_set.name} V{dv.version_no}")
    for co in ChangeOrder.objects.filter(files=sf):
        refs.append(f"变更单 {co.code}")
    return refs


class ZoneMixin:
    def zone_check(self, zone):
        if zone not in ZONES:
            raise ApiError(404, "NOT_FOUND", "专区不存在")
        if zone == "contract":
            self.require("contract.read")

    def folder(self, zone, folder_id):
        self.zone_check(zone)
        return self.obj(ArchiveFolder, folder_id, zone=zone)

    def folder_dict(self, f):
        return {"id": f.id, "zone": f.zone, "name": f.name, "orderNo": f.order_no,
                "fileCount": ArchiveFile.objects.filter(folder=f).exclude(file__status="voided").count()}

    def file_dict(self, af, user):
        sf = af.file
        refs = file_refs(sf)
        out = storage.file_dict(sf)
        out.update({"archiveFileId": af.id, "folderId": af.folder_id, "uploaderName": sf.uploader.name if sf.uploader else "",
                    "uploadedOn": d(timezone.localdate(sf.created_at)), "refs": refs,
                    "voidedByName": sf.voided_by.name if sf.voided_by else None, "voidedAt": iso(sf.voided_at),
                    "isMine": sf.uploader_id == user.id,
                    "canVoid": sf.status != "voided" and sf.uploader_id == user.id and not refs})
        return out


def _name(request):
    name = str((request.data or {}).get("name", "")).strip()
    if not name:
        validation([("name", "请填写分类名称")])
    if len(name) > 20:
        validation([("name", "分类名称不能超过 20 字")])
    return name


class Folders(ZoneMixin, ProjectView):
    def get(self, request, project_id, zone):
        self.zone_check(zone)
        qs = ArchiveFolder.objects.filter(project=self.project, zone=zone).order_by("order_no", "id")
        return Response({"zone": zone, "zoneName": ZONES[zone], "items": [self.folder_dict(f) for f in qs]})

    @transaction.atomic
    def post(self, request, project_id, zone):
        self.zone_check(zone)
        self.require("archive.folder_manage")
        name = _name(request)
        qs = ArchiveFolder.objects.filter(project=self.project, zone=zone)
        if qs.filter(name=name).exists():
            validation([("name", "已有同名分类")])
        last = qs.order_by("-order_no").first()
        f = ArchiveFolder.objects.create(project=self.project, zone=zone, name=name, order_no=(last.order_no + 1) if last else 0)
        audit.log(request.user, "新增", "档案分类", f.id, f"{ZONES[zone]} · {name}", None, {"name": name}, project=self.project)
        return Response(self.folder_dict(f), status=201)


class FolderDetail(ZoneMixin, ProjectView):
    http_method_names = ["patch", "delete"]

    @transaction.atomic
    def patch(self, request, project_id, zone, folder_id):
        f = self.folder(zone, folder_id)
        self.require("archive.folder_manage")
        name = _name(request)
        if ArchiveFolder.objects.filter(project=self.project, zone=zone, name=name).exclude(pk=f.pk).exists():
            validation([("name", "已有同名分类")])
        before = f.name
        f.name = name
        f.save(update_fields=["name"])
        audit.log(request.user, "修改", "档案分类", f.id, f"{ZONES[zone]} · {name}", {"name": before}, {"name": name}, project=self.project)
        return Response(self.folder_dict(f))

    @transaction.atomic
    def delete(self, request, project_id, zone, folder_id):
        self.zone_check(zone)
        self.require("archive.folder_manage")
        f = ArchiveFolder.objects.select_for_update().filter(pk=folder_id, project=self.project, zone=zone).first()
        if f is None:
            raise ApiError(404, "NOT_FOUND", "分类不存在")
        n = ArchiveFile.objects.filter(folder=f).count()
        if n:
            raise ApiError(409, "FOLDER_NOT_EMPTY", f"分类「{f.name}」下还有 {n} 个文件，请先移出文件", details={"fileCount": n})
        audit.log(request.user, "删除", "档案分类", f.id, f"{ZONES[zone]} · {f.name}", {"name": f.name}, None, project=self.project)
        f.delete()
        return Response(status=204)


class FolderFiles(ZoneMixin, ProjectView):
    def get(self, request, project_id, zone, folder_id):
        f = self.folder(zone, folder_id)
        qs = ArchiveFile.objects.filter(folder=f).select_related("file__uploader", "file__voided_by").order_by("-created_at", "-id")
        if request.GET.get("showVoided") not in ("1", "true"):
            qs = qs.exclude(file__status="voided")
        return Response({"folder": self.folder_dict(f), "items": [self.file_dict(a, request.user) for a in qs]})

    @transaction.atomic
    def post(self, request, project_id, zone, folder_id):
        """单文件 multipart 上传到分类；前端逐个上传，某个文件被拒不影响同批其他文件（AC-F12-02）。"""
        f = self.folder(zone, folder_id)
        self.require("archive.upload", "无权上传档案资料")
        up = request.FILES.get("file")
        if up is None:
            validation([("file", "请选择文件")])
        sf = storage.save_upload(up, request.user, self.project)
        af = ArchiveFile.objects.create(project=self.project, folder=f, file=sf)
        audit.log(request.user, "新增", "资料文件", sf.id, sf.original_name, None,
                  {"folder": f"{ZONES[zone]} · {f.name}", "size": sf.size}, project=self.project)
        return Response(self.file_dict(af, request.user), status=201)


class FileAction(ZoneMixin, ProjectView):
    def archive_file(self, file_id):
        af = ArchiveFile.objects.select_related("folder", "file").filter(pk=file_id, project=self.project).first()
        if af is None:
            raise ApiError(404, "NOT_FOUND", "文件不存在")
        self.zone_check(af.folder.zone)
        return af


class MoveFile(FileAction):
    @transaction.atomic
    def post(self, request, project_id, file_id):
        af = self.archive_file(file_id)
        self.require("archive.folder_manage", "无权移动文件")
        try:
            target_id = int((request.data or {}).get("folderId"))
        except (TypeError, ValueError):
            validation([("folderId", "请选择目标分类")])
        target = ArchiveFolder.objects.filter(pk=target_id, project=self.project, zone=af.folder.zone).first()
        if target is None:
            validation([("folderId", "请选择同一专区的目标分类")])
        if af.file.status == "voided":
            fail("FILE_VOIDED", "已作废的文件不能移动", 409)
        before = af.folder.name
        af.folder = target
        af.save(update_fields=["folder"])
        audit.log(request.user, "修改", "资料文件", af.file_id, af.file.original_name, {"folder": before}, {"folder": target.name},
                  project=self.project)
        return Response(self.file_dict(af, request.user))


class VoidFile(FileAction):
    @transaction.atomic
    def post(self, request, project_id, file_id):
        af = self.archive_file(file_id)
        sf = StoredFile.objects.select_for_update().get(pk=af.file_id)
        if sf.uploader_id != request.user.id:
            raise ApiError(403, "FORBIDDEN", "只有上传者可以作废该文件")
        if sf.status == "voided":
            raise ApiError(409, "ALREADY_VOIDED", f"已由{sf.voided_by.name if sf.voided_by else ''}于 {iso(sf.voided_at)} 作废",
                           details={"by": sf.voided_by.name if sf.voided_by else None, "at": iso(sf.voided_at)})
        refs = file_refs(sf)
        if refs:
            raise ApiError(409, "FILE_REFERENCED", UNVOIDABLE, details={"refs": refs})
        sf.status = "voided"
        sf.voided_by = request.user
        sf.voided_at = timezone.now()
        sf.save(update_fields=["status", "voided_by", "voided_at"])
        audit.log(request.user, "作废", "资料文件", sf.id, sf.original_name, {"status": "有效"}, {"status": "已作废"}, project=self.project)
        af.file = sf
        return Response(self.file_dict(af, request.user))


urlpatterns = [
    path("projects/<int:project_id>/archive/<str:zone>/folders", Folders.as_view()),
    path("projects/<int:project_id>/archive/<str:zone>/folders/<int:folder_id>", FolderDetail.as_view()),
    path("projects/<int:project_id>/archive/<str:zone>/folders/<int:folder_id>/files", FolderFiles.as_view()),
    path("projects/<int:project_id>/archive-files/<int:file_id>/move", MoveFile.as_view()),
    path("projects/<int:project_id>/archive-files/<int:file_id>/void", VoidFile.as_view()),
]
