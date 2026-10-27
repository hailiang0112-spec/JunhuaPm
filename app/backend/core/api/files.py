"""文件上传与读取（API-F12-01）。读取时校验项目成员身份与合同专区可见性（AC-F12-06）。"""
from django.http import HttpResponse
from django.urls import path
from rest_framework.response import Response
from rest_framework.views import APIView

from core import perms
from core.api.base import ProjectView, project_for
from core.errors import ApiError
from core.models import ArchiveFile, StoredFile
from core.services import storage


class Upload(ProjectView):
    """单文件 multipart 上传；前端逐个上传，同批其他文件不受影响（AC-F12-02）。"""

    def post(self, request, project_id):
        if not (self.can("file.upload") or self.can("prototype.import") or self.can("checkpoint.check")):
            raise ApiError(403, "FORBIDDEN", "无权上传文件")
        f = request.FILES.get("file")
        if f is None:
            raise ApiError(400, "VALIDATION_FAILED", "请选择文件")
        sf = storage.save_upload(f, request.user, self.project)
        return Response(storage.file_dict(sf), status=201)


def _readable(request, sf):
    if sf.project_id is None:
        if not request.user.is_authenticated:
            raise ApiError(401, "UNAUTHENTICATED", "请先登录")
        return
    project_for(request, sf.project_id)
    if ArchiveFile.objects.filter(file=sf, folder__zone="contract").exists():
        perms.require(request.roles, "contract.read")


class Content(APIView):
    def get(self, request, file_id, kind="content"):
        sf = StoredFile.objects.filter(pk=file_id).first()
        if sf is None:
            raise ApiError(404, "NOT_FOUND", "文件不存在")
        _readable(request, sf)
        key = sf.thumb_key if kind == "thumb" and sf.thumb_key else sf.storage_key
        data = storage.get_bytes(key)
        resp = HttpResponse(data, content_type="image/jpeg" if key.startswith("thumb/") else sf.mime)
        disp = "inline" if sf.mime.startswith("image/") or sf.mime == "application/pdf" else "attachment"
        from urllib.parse import quote
        resp["Content-Disposition"] = f"{disp}; filename*=UTF-8''{quote(sf.original_name)}"
        resp["Cache-Control"] = "private, max-age=86400"
        return resp


urlpatterns = [
    path("projects/<int:project_id>/files", Upload.as_view()),
    path("files/<int:file_id>/content", Content.as_view()),
    path("files/<int:file_id>/thumb", Content.as_view(), {"kind": "thumb"}),
]
