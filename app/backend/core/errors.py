"""统一错误体（技术方案 §4.4）：{code, message, fields, details}。"""
import logging
import uuid

from django.http import Http404
from rest_framework import status
from rest_framework.exceptions import APIException, MethodNotAllowed, NotAuthenticated, PermissionDenied, ValidationError
from rest_framework.response import Response

log = logging.getLogger(__name__)


class ApiError(APIException):
    def __init__(self, http_status, code, message, fields=None, details=None):
        self.status_code = http_status
        self.code = code
        self.message = message
        self.fields = fields or []
        self.details = details or {}
        super().__init__(message)


def fail(code, message, http_status=400, **details):
    raise ApiError(http_status, code, message, details=details)


def validation(fields):
    """fields: [(field, message)]；一次返回全部错误字段。"""
    if fields:
        raise ApiError(400, "VALIDATION_FAILED", "请补全或修正以下字段：" + "、".join(m for _, m in fields),
                       fields=[{"field": f, "message": m} for f, m in fields])


def forbidden(message="无权执行该操作", code="FORBIDDEN"):
    raise ApiError(403, code, message)


def body(code, message, fields=None, details=None):
    return {"code": code, "message": message, "fields": fields or [], "details": details or {}}


def exception_handler(exc, context):
    if isinstance(exc, ApiError):
        return Response(body(exc.code, exc.message, exc.fields, exc.details), status=exc.status_code)
    if isinstance(exc, NotAuthenticated):
        return Response(body("UNAUTHENTICATED", "请先登录"), status=401)
    if isinstance(exc, PermissionDenied):
        return Response(body("FORBIDDEN", str(exc.detail)), status=403)
    if isinstance(exc, MethodNotAllowed):
        return Response(body("KEY_RECORD_IMMUTABLE", "关键记录不可修改，更正请追加新记录"), status=405)
    if isinstance(exc, Http404):
        return Response(body("NOT_FOUND", "记录不存在"), status=404)
    if isinstance(exc, ValidationError):
        detail = exc.detail if isinstance(exc.detail, dict) else {"_": exc.detail}
        fields = [{"field": k, "message": str(v[0] if isinstance(v, list) else v)} for k, v in detail.items()]
        return Response(body("VALIDATION_FAILED", "；".join(f["message"] for f in fields), fields), status=400)
    if isinstance(exc, APIException):
        return Response(body("ERROR", str(exc.detail)), status=exc.status_code)
    rid = uuid.uuid4().hex[:12]
    log.exception("unhandled error request_id=%s", rid)
    return Response(body("INTERNAL_ERROR", "服务器内部错误", details={"requestId": rid}), status=status.HTTP_500_INTERNAL_SERVER_ERROR)
