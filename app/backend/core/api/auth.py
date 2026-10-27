"""账号与登录（F02）：登录锁定、本人信息、改密、邀请接受、管理员重置密码。"""
import datetime
import hashlib
import re
import secrets

from django.contrib.auth import login, logout, update_session_auth_hash
from django.db import transaction
from django.urls import path
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from core import perms
from core.errors import ApiError, fail, forbidden, validation
from core.models import Invitation, LoginThrottle, Project, ProjectMemberRole, User
from core.services import audit

LOCK_FAILS = 5
LOCK_MINUTES = 15


def check_password_rule(pw, field="newPassword"):
    """NFR-006：至少 8 位，同时包含字母和数字。"""
    if not pw or len(pw) < 8 or not re.search(r"[A-Za-z]", pw) or not re.search(r"\d", pw):
        validation([(field, "密码至少 8 位，且必须同时包含字母和数字")])


def me_payload(user):
    projects = []
    qs = Project.objects.all() if user.is_company_admin else Project.objects.filter(member_roles__user=user).distinct()
    for p in qs.order_by("id"):
        roles = perms.roles_of(user, p)
        projects.append({"id": p.id, "name": p.name, "status": p.status, "roles": sorted(roles),
                         "roleLabels": [perms.ROLE_LABELS[r] for r in sorted(roles)],
                         "permissions": perms.permissions_for(roles)})
    return {"id": user.id, "name": user.name, "phone": user.phone, "isCompanyAdmin": user.is_company_admin,
            "mustChangePassword": user.must_change_password,
            "createdAt": timezone.localtime(user.created_at).date().isoformat(), "projects": projects}


class Csrf(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        # 前端启动时先问是否已登录，未登录就不再请求 /me，避免控制台出现 401
        return Response({"ok": True, "authenticated": bool(request.user and request.user.is_authenticated)})

    @classmethod
    def as_view(cls, **kw):
        return ensure_csrf_cookie(super().as_view(**kw))


class Login(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        phone = str(request.data.get("phone", "")).strip()
        password = str(request.data.get("password", ""))
        now = timezone.now()
        error = None
        with transaction.atomic():  # 失败计数必须提交，所以错误在事务外抛出
            th, _ = LoginThrottle.objects.select_for_update().get_or_create(phone=phone)
            user = User.objects.filter(phone=phone, is_active=True).first()
            if th.locked_until and th.locked_until > now:
                remaining = int((th.locked_until - now).total_seconds())
                error = ApiError(423, "ACCOUNT_LOCKED", f"账号已锁定，请 {remaining // 60 + 1} 分钟后再试",
                                 details={"remainingSeconds": remaining})
            elif user is None or not user.check_password(password):
                if not th.window_start or now - th.window_start > datetime.timedelta(minutes=LOCK_MINUTES):
                    th.window_start, th.fail_count = now, 0
                th.fail_count += 1
                if th.fail_count >= LOCK_FAILS:
                    th.locked_until = now + datetime.timedelta(minutes=LOCK_MINUTES)
                    th.fail_count = 0
                    error = ApiError(423, "ACCOUNT_LOCKED", "连续输错 5 次，账号已锁定 15 分钟",
                                     details={"remainingSeconds": LOCK_MINUTES * 60})
                else:
                    error = ApiError(400, "LOGIN_FAILED", "手机号或密码错误")  # DEC-101：不提示剩余次数
                th.save()
            else:
                th.fail_count, th.window_start, th.locked_until = 0, None, None
                th.save()
        if error:
            raise error
        login(request, user)
        return Response(me_payload(user))


class Logout(APIView):
    def post(self, request):
        logout(request)
        return Response({"ok": True})


class Me(APIView):
    def get(self, request):
        return Response(me_payload(request.user))


class MyPassword(APIView):
    def post(self, request):
        user = request.user
        new = str(request.data.get("newPassword", ""))
        if not user.must_change_password and not user.check_password(str(request.data.get("oldPassword", ""))):
            validation([("oldPassword", "原密码不正确")])  # 强制改密时不要求原密码（DEC-104）
        check_password_rule(new)
        user.set_password(new)
        user.must_change_password = False
        user.save()
        update_session_auth_hash(request, user)  # 本设备保持登录，其他设备会话失效（AC-F02-08）
        audit.log(user, "password.change", "user", user.id, user.name)
        return Response(me_payload(user))


def _invitation(token):
    inv = Invitation.objects.filter(token_hash=hashlib.sha256(token.encode()).hexdigest()).select_related("project", "created_by").first()
    if inv is None or inv.used_at or inv.revoked_at or inv.expires_at <= timezone.now():
        raise ApiError(410, "INVITATION_INVALID", "邀请已失效，请联系邀请人重新发送")
    return inv


class InvitationInfo(APIView):
    permission_classes = [AllowAny]

    def get(self, request, token):
        inv = _invitation(token)
        account = User.objects.filter(phone=inv.phone).first()
        inviter_roles = sorted(perms.roles_of(inv.created_by, inv.project) - {"owner_agent"},
                               key=lambda r: list(perms.ROLE_LABELS).index(r))
        return Response({"projectName": inv.project.name, "inviter": inv.created_by.name,
                         "inviterRole": perms.ROLE_LABELS[inviter_roles[0]] if inviter_roles else "",
                         "roles": inv.roles, "roleLabels": [perms.ROLE_LABELS[r] for r in inv.roles],
                         "phoneMasked": inv.phone[:3] + "****" + inv.phone[-4:],
                         "hasAccount": account is not None, "accountName": account.name if account else None,
                         "expiresAt": timezone.localtime(inv.expires_at).isoformat(timespec="seconds")})


class InvitationAccept(APIView):
    permission_classes = [AllowAny]

    def post(self, request, token):
        phone = str(request.data.get("phone", "")).strip()
        name = str(request.data.get("name", "")).strip()
        password = str(request.data.get("password", ""))
        with transaction.atomic():
            inv = _invitation(token)
            if phone != inv.phone:
                validation([("phone", "手机号与邀请不一致，请使用收到邀请的手机号")])
            user = User.objects.filter(phone=phone).first()
            if user:
                if not user.check_password(password):
                    validation([("password", "原密码不正确")])  # 已有账号用原密码加入，不重置（AC-F02-02）
            else:
                errs = []
                if not name:
                    errs.append(("name", "请填写姓名，将作为签认署名"))
                if len(password) < 8 or not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
                    errs.append(("password", "密码至少 8 位，且必须同时包含字母和数字"))
                validation(errs)
                user = User.objects.create_user(phone=phone, name=name, password=password)
            claimed = Invitation.objects.filter(pk=inv.pk, used_at__isnull=True).update(used_at=timezone.now())
            if not claimed:
                raise ApiError(410, "INVITATION_INVALID", "邀请已失效，请联系邀请人重新发送")
            for role in inv.roles:
                if role == "admin":  # 公司管理员不是项目角色，只能由公司管理员发出（AC-F02-04）
                    if inv.created_by.is_company_admin and not user.is_company_admin:
                        user.is_company_admin = True
                        user.save(update_fields=["is_company_admin"])
                    continue
                ProjectMemberRole.objects.get_or_create(project=inv.project, user=user, role=role,
                                                        defaults={"granted_by": inv.created_by})
            audit.log(user, "invitation.accept", "invitation", inv.id, f"{user.name} 加入", project=inv.project,
                      after={"roles": inv.roles})
        login(request, user)
        return Response(me_payload(user))


class ResetPassword(APIView):
    def post(self, request, user_id):
        if not request.user.is_company_admin:
            forbidden("只有公司管理员可以重置密码")
        user = User.objects.filter(pk=user_id).first()
        if user is None:
            fail("NOT_FOUND", "成员不存在", 404)
        temp = "Jh" + secrets.token_hex(3) + str(secrets.randbelow(90) + 10)
        user.set_password(temp)
        user.must_change_password = True
        user.save()
        audit.log(request.user, "password.reset", "user", user.id, user.name)  # 临时密码不落日志（NFR-006）
        resp = Response({"tempPassword": temp, "userName": user.name})
        resp["Cache-Control"] = "no-store"
        return resp


urlpatterns = [
    path("auth/csrf", Csrf.as_view()),
    path("auth/login", Login.as_view()),
    path("auth/logout", Logout.as_view()),
    path("me", Me.as_view()),
    path("me/password", MyPassword.as_view()),
    path("invitations/<str:token>", InvitationInfo.as_view()),
    path("invitations/<str:token>/accept", InvitationAccept.as_view()),
    path("admin/users/<int:user_id>/reset-password", ResetPassword.as_view()),
]
