"""公告栏（API-F13-02，REQ-F13-02）：留言按发布者角色归入板块、回复挂在原留言下、只能删自己的留言（软删除留占位）。

板块归属（AC-F13-03 + DEC-133）：一人兼多个角色时按「业主 > 设计经理 > 其他」确定；其他角色一律归入工地经理板块。
"""
from django.db import transaction
from django.urls import path
from django.utils import timezone
from rest_framework.response import Response

from core import perms
from core.api.base import ProjectView, iso
from core.errors import ApiError, validation
from core.models import Notice, ProjectMemberRole
from core.services import audit

BOARDS = {"owner": "业主", "site": "工地经理", "design": "设计师"}
LABEL_ORDER = ["owner", "design_manager", "pm", "qc", "budget", "owner_agent", "owner_member", "admin"]
MAX_LEN = 500


def board_of(roles):
    if "owner" in roles:
        return "owner"
    if "design_manager" in roles:
        return "design"
    return "site"


def role_label(roles):
    for r in LABEL_ORDER:
        if r in roles:
            return perms.ROLE_LABELS[r]
    return ""


def _body(request):
    text = str((request.data or {}).get("body", "")).strip()
    if not text:
        validation([("body", "请填写留言内容")])
    if len(text) > MAX_LEN:
        validation([("body", f"留言内容不能超过 {MAX_LEN} 字")])
    return text


def _excerpt(text):
    return text if len(text) <= 40 else text[:40] + "…"


class NoticeMixin:
    def roles_by_user(self):
        out = {}
        for uid, role in ProjectMemberRole.objects.filter(project=self.project).values_list("user_id", "role"):
            out.setdefault(uid, set()).add(role)
        return out

    def ser(self, n, roles_map, uid, replies=()):
        roles = roles_map.get(n.author_id, set())
        if not roles and n.author and n.author.is_company_admin:
            roles = {"admin"}
        deleted = n.deleted_at is not None
        return {"id": n.id, "board": n.board, "authorId": n.author_id, "authorName": n.author_name, "roleLabel": role_label(roles),
                "createdAt": iso(n.created_at), "body": "" if deleted else n.body, "deleted": deleted,
                "deletedAt": iso(n.deleted_at), "deletedBy": n.author_name if deleted else None,
                "canDelete": not deleted and n.author_id == uid,
                "replies": [self.ser(r, roles_map, uid) for r in replies]}


class Notices(NoticeMixin, ProjectView):
    def get(self, request, project_id):
        qs = Notice.objects.filter(project=self.project).select_related("author")
        top = [n for n in qs if n.parent_id is None]
        replies = {}
        for n in sorted((n for n in qs if n.parent_id), key=lambda x: (x.created_at, x.id)):
            replies.setdefault(n.parent_id, []).append(n)
        roles_map = self.roles_by_user()
        boards = {k: [] for k in BOARDS}
        for n in sorted(top, key=lambda x: (x.created_at, x.id), reverse=True):
            boards.setdefault(n.board, []).append(self.ser(n, roles_map, request.user.id, replies.get(n.id, [])))
        b = board_of(self.roles)
        return Response({"boards": boards, "boardNames": BOARDS,
                         "me": {"name": request.user.name, "roleLabel": role_label(self.roles), "board": b, "boardName": BOARDS[b]}})

    @transaction.atomic
    def post(self, request, project_id):
        self.require("notice.post")
        text = _body(request)
        b = board_of(self.roles)
        n = Notice.objects.create(project=self.project, board=b, author=request.user, author_name=request.user.name, body=text)
        audit.log(request.user, "新增", "公告栏留言", n.id, f"{BOARDS[b]}板块 · {_excerpt(text)}", None, {"body": text},
                  project=self.project)
        return Response(self.ser(n, self.roles_by_user(), request.user.id), status=201)


class Replies(NoticeMixin, ProjectView):
    @transaction.atomic
    def post(self, request, project_id, nid):
        self.require("notice.post")
        parent = self.obj(Notice, nid)
        if parent.parent_id:
            raise ApiError(409, "REPLY_TO_REPLY", "只能回复主留言")
        if parent.deleted_at:
            raise ApiError(409, "NOTICE_DELETED", "该留言已删除，不能回复")
        text = _body(request)
        n = Notice.objects.create(project=self.project, board=parent.board, author=request.user, author_name=request.user.name,
                                  parent=parent, body=text)
        audit.log(request.user, "新增", "公告栏留言", n.id, f"回复 {parent.author_name} · {_excerpt(text)}", None, {"body": text},
                  project=self.project)
        return Response(self.ser(n, self.roles_by_user(), request.user.id), status=201)


class NoticeDetail(NoticeMixin, ProjectView):
    http_method_names = ["delete"]

    @transaction.atomic
    def delete(self, request, project_id, nid):
        n = Notice.objects.select_for_update().filter(pk=nid, project=self.project).first()
        if n is None:
            raise ApiError(404, "NOT_FOUND", "留言不存在")
        if n.author_id != request.user.id:
            raise ApiError(403, "FORBIDDEN", "只能删除自己的留言")
        if n.deleted_at:
            raise ApiError(409, "ALREADY_DELETED", f"该留言已于 {iso(n.deleted_at)} 删除", details={"at": iso(n.deleted_at)})
        n.deleted_at = timezone.now()
        n.save(update_fields=["deleted_at"])
        audit.log(request.user, "删除", "公告栏留言", n.id, _excerpt(n.body), {"body": n.body}, {"body": "该留言已删除"},
                  project=self.project)
        return Response(self.ser(n, self.roles_by_user(), request.user.id))


urlpatterns = [
    path("projects/<int:project_id>/notices", Notices.as_view()),
    path("projects/<int:project_id>/notices/<int:nid>", NoticeDetail.as_view()),
    path("projects/<int:project_id>/notices/<int:nid>/replies", Replies.as_view()),
]
