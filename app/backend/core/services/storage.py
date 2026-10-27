"""文件存储抽象（技术方案 §7.5.2）：local 或 s3。存储键带 SHA-256，只写不覆盖、不删除。"""
import hashlib
import io
import mimetypes
from pathlib import Path

from django.conf import settings

from core.errors import ApiError
from core.models import StoredFile

ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv",
               ".dwg", ".dxf", ".json", ".zip"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic"}


def _s3():
    import boto3
    from botocore.config import Config
    return boto3.client("s3", endpoint_url=settings.S3_ENDPOINT, aws_access_key_id=settings.S3_ACCESS_KEY,
                        aws_secret_access_key=settings.S3_SECRET_KEY,
                        config=Config(request_checksum_calculation="when_required"))


def put_bytes(key, data):
    if settings.FILE_STORAGE == "s3":
        try:
            _s3().put_object(Bucket=settings.S3_BUCKET, Key=key, Body=data)
        except Exception as e:  # noqa: BLE001 — 存储不可用时明确报错，不静默降级
            raise ApiError(503, "STORAGE_UNAVAILABLE", "文件存储暂不可用，请稍后重传") from e
        return
    path = Path(settings.FILE_ROOT) / key
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(data)


def put_file(key, fobj):
    """大文件（证据包）从文件对象写入存储，不整体读入内存。"""
    fobj.seek(0)
    if settings.FILE_STORAGE == "s3":
        try:
            _s3().upload_fileobj(fobj, settings.S3_BUCKET, key)
        except Exception as e:  # noqa: BLE001
            raise ApiError(503, "STORAGE_UNAVAILABLE", "文件存储暂不可用，请稍后重试") from e
        return
    import shutil
    path = Path(settings.FILE_ROOT) / key
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        tmp = path.with_name(path.name + ".part")
        with open(tmp, "wb") as out:
            shutil.copyfileobj(fobj, out, 1024 * 1024)
        tmp.replace(path)


def open_file(key):
    """以流的方式读取（下载大文件用）。"""
    if settings.FILE_STORAGE == "s3":
        return _s3().get_object(Bucket=settings.S3_BUCKET, Key=key)["Body"]
    return open(Path(settings.FILE_ROOT) / key, "rb")


def get_bytes(key):
    if settings.FILE_STORAGE == "s3":
        return _s3().get_object(Bucket=settings.S3_BUCKET, Key=key)["Body"].read()
    return (Path(settings.FILE_ROOT) / key).read_bytes()


def _thumbnail(data):
    try:
        from PIL import Image, ImageOps
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
        img.thumbnail((360, 360))
        out = io.BytesIO()
        img.convert("RGB").save(out, "JPEG", quality=78)
        return out.getvalue()
    except Exception:  # noqa: BLE001 — 非图片或损坏图片不生成缩略图
        return None


def save_upload(upload, user, project=None, allowed_ext=None):
    """校验大小与格式后保存；返回 StoredFile。不合格时抛出带文件名与原因的 413/415。"""
    name = upload.name
    ext = Path(name).suffix.lower()
    if upload.size > settings.MAX_UPLOAD_BYTES:
        raise ApiError(413, "FILE_TOO_LARGE", f"{name}：超过 50MB，未上传", details={"file": name})
    if ext not in (allowed_ext or ALLOWED_EXT):
        raise ApiError(415, "FILE_TYPE", f"{name}：格式不支持，未上传", details={"file": name})
    data = upload.read()
    return save_bytes(data, name, user, project)


def save_bytes(data, name, user, project=None, mime=None):
    sha = hashlib.sha256(data).hexdigest()
    ext = Path(name).suffix.lower()
    key = f"{sha[:2]}/{sha}{ext}"
    put_bytes(key, data)
    thumb_key = ""
    if ext in IMAGE_EXT:
        t = _thumbnail(data)
        if t:
            thumb_key = f"thumb/{sha}.jpg"
            put_bytes(thumb_key, t)
    return StoredFile.objects.create(project=project, storage_key=key, sha256=sha, size=len(data),
                                     mime=mime or mimetypes.guess_type(name)[0] or "application/octet-stream",
                                     original_name=name, uploader=user if getattr(user, "pk", None) else None,
                                     thumb_key=thumb_key)


def file_dict(f):
    if f is None:
        return None
    return {"id": f.id, "name": f.original_name, "size": f.size, "mime": f.mime, "sha256": f.sha256,
            "status": f.status, "isImage": bool(f.thumb_key) or f.mime.startswith("image/"),
            "url": f"/api/files/{f.id}/content", "thumbUrl": f"/api/files/{f.id}/thumb" if f.thumb_key else None,
            "uploadedAt": f.created_at.isoformat() if f.created_at else None}
