"""项目内接口公共底座：认证、项目隔离（防 IDOR）、权限点判定、分页与时间格式。"""
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.views import APIView

from core import perms
from core.errors import ApiError
from core.models import Project


def project_for(request, project_id):
    """取项目并实时计算角色；非成员且非公司管理员 → 403 PROJECT_FORBIDDEN（响应不含业务数据）。"""
    project = Project.objects.filter(pk=project_id).first()
    if project is None:
        raise ApiError(403, "PROJECT_FORBIDDEN", "无权访问该项目")
    roles = perms.roles_of(request.user, project)
    if not perms.can(roles, "project.read"):
        raise ApiError(403, "PROJECT_FORBIDDEN", "无权访问该项目")
    request.project = project
    request.roles = roles
    return project


class ProjectView(APIView):
    """URL 中带 project_id 的视图都继承它；self.project / self.roles 在 initial() 中就绪。"""

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        self.project = project_for(request, kwargs["project_id"])
        self.roles = request.roles

    def require(self, point, message=None):
        perms.require(self.roles, point, message)

    def can(self, point):
        return perms.can(self.roles, point)

    def obj(self, model, pk, **extra):
        """按 ID 取对象时固定带项目条件，防止拿别的项目的 ID 越权读取。"""
        return get_object_or_404(model, pk=pk, project=self.project, **extra)


def paginate(request, qs, serialize):
    try:
        page = max(1, int(request.GET.get("page", 1)))
    except ValueError:
        page = 1
    size = 50 if request.GET.get("pageSize") == "50" else 20
    total = qs.count()
    items = [serialize(x) for x in qs[(page - 1) * size: page * size]]
    return {"items": items, "total": total, "page": page, "pageSize": size}


def iso(dt):
    return timezone.localtime(dt).isoformat(timespec="seconds") if dt else None


def d(date):
    return date.isoformat() if date else None


def user_brief(u):
    return {"id": u.id, "name": u.name} if u else None
