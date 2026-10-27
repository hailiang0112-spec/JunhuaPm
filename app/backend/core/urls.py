"""API 路由汇总：每个功能模块在 core/api/<模块>.py 中定义 urlpatterns。"""
from django.urls import include, path

urlpatterns = [
    path("", include("core.api.auth")),
    path("", include("core.api.projects")),
    path("", include("core.api.structure")),
    path("", include("core.api.plan_import")),
    path("", include("core.api.drawings")),
    path("", include("core.api.baselines")),
    path("", include("core.api.checkpoints")),
    path("", include("core.api.changes")),
    path("", include("core.api.issues")),
    path("", include("core.api.experience")),
    path("", include("core.api.overview")),
    path("", include("core.api.attendance")),
    path("", include("core.api.files")),
    path("", include("core.api.archive")),
    path("", include("core.api.supplements")),
    path("", include("core.api.notices")),
    path("", include("core.api.payments")),
    path("", include("core.api.todos")),
    path("", include("core.api.audit")),
]
