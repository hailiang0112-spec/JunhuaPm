"""强制改密：must_change_password 时只放行本人信息、改密和退出（AC-F02-07）。"""
from django.http import JsonResponse

from .errors import body

ALLOWED = {("GET", "/api/me"), ("POST", "/api/me/password"), ("POST", "/api/auth/logout")}


class PasswordChangeRequiredMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (request.path.startswith("/api/") and user is not None and user.is_authenticated
                and user.must_change_password and (request.method, request.path.rstrip("/")) not in ALLOWED):
            return JsonResponse(body("PASSWORD_CHANGE_REQUIRED", "请先修改密码"), status=403)
        return self.get_response(request)
