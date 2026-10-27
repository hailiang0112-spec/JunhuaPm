"""项目、成员与角色、代理人、邀请、项目状态与放行时限（F01、REQ-F02-01、AC-F06-17）。"""
import datetime
import hashlib
import secrets

from django.db import transaction
from django.db.models import F, Sum
from django.urls import path
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from core import perms
from core.api.base import ProjectView, d, iso
from core.errors import ApiError, fail, forbidden, validation
from core.models import (AuditLog, Checkpoint, Invitation, ProcessRule, Project, ProjectMemberRole, ReleaseRecord,
                         Template, User, WorkItem)
from core.services import audit
from core.services.projects import create_from_template, default_company, ensure_company_template


def parse_date(v):
    try:
        return datetime.date.fromisoformat(str(v))
    except (TypeError, ValueError):
        return None


def project_dict(p, roles=None):
    out = {"id": p.id, "name": p.name, "address": p.address, "status": p.status,
           "plannedStart": d(p.planned_start), "plannedHandover": d(p.planned_handover),
           "actualHandover": d(p.actual_handover), "releaseTimeoutHours": p.release_timeout_hours}
    if roles is not None:
        out["roles"] = sorted(roles)
        out["roleLabels"] = [perms.ROLE_LABELS[r] for r in sorted(roles)]
        out["permissions"] = perms.permissions_for(roles)
    return out


def progress_of(p):
    """总体完成度 = Σ(工段权重 × 工段进度) / Σ工段权重；工段进度 = Σ(w×p)/Σw（AC-F03-05），保留 1 位小数。"""
    rows = (WorkItem.objects.filter(project=p, is_disabled=False, phase__is_disabled=False)
            .values("phase_id").annotate(wp=Sum(F("weight") * F("progress")), w=Sum("weight")))
    by_phase = {r["phase_id"]: (r["wp"] / r["w"] if r["w"] else 0) for r in rows}
    phases = list(p.phases.filter(is_disabled=False).order_by("order_no", "id"))
    total_w = sum(ph.weight for ph in phases)
    overall = round(sum(ph.weight * by_phase.get(ph.id, 0) for ph in phases) / total_w, 1) if total_w else 0
    today = timezone.localdate()
    current = next((ph for ph in phases if ph.planned_start <= today <= ph.planned_end), None)
    if current is None:
        current = next((ph for ph in phases if by_phase.get(ph.id, 0) < 99.95), phases[-1] if phases else None)
    return overall, current


def project_summary(p, roles=None):
    """项目列表 / 我的工地卡片用的汇总：项目经理、业主、成员数、进度、当前工段、未放行检查点数。"""
    names = {}
    for r in ProjectMemberRole.objects.filter(project=p).select_related("user").order_by("id"):
        names.setdefault(r.role, []).append(r.user.name)
    overall, current = progress_of(p)
    out = project_dict(p, roles)
    out.update({
        "pmNames": names.get("pm", []), "ownerNames": names.get("owner", []),
        "memberCount": ProjectMemberRole.objects.filter(project=p).values("user_id").distinct().count(),
        "progress": overall,
        "currentPhase": {"id": current.id, "name": current.name, "colorVar": current.color_var} if current else None,
        "unreleasedCheckpoints": Checkpoint.objects.filter(project=p, is_draft=False).exclude(status="已放行").count(),
    })
    return out


class Projects(APIView):
    def get(self, request):
        """公司管理员看到全部项目；其他成员只看到自己有角色的项目（AC-F01-04）。"""
        u = request.user
        qs = Project.objects.all() if u.is_company_admin else Project.objects.filter(member_roles__user=u).distinct()
        return Response({"items": [project_summary(p, perms.roles_of(u, p)) for p in qs.order_by("-id")]})

    def post(self, request):
        if not request.user.is_company_admin:
            forbidden("只有公司管理员可以新建项目")
        data = request.data
        errs = []
        name = str(data.get("name", "")).strip()
        address = str(data.get("address", "")).strip()
        ps, ph = parse_date(data.get("plannedStart")), parse_date(data.get("plannedHandover"))
        if not name:
            errs.append(("name", "请填写项目名称"))
        if not address:
            errs.append(("address", "请填写项目地址"))
        if not ps:
            errs.append(("plannedStart", "请选择计划开工日期"))
        if not ph:
            errs.append(("plannedHandover", "请选择计划交房日期"))
        if ps and ph and ph < ps:
            errs.append(("plannedHandover", "计划交房日期不能早于计划开工日期"))
        company = default_company()
        ensure_company_template(company)
        tpl = Template.objects.filter(pk=data.get("templateId"), company=company).first()
        if not tpl:
            errs.append(("templateId", "请选择公司模板"))
        validation(errs)
        p = create_from_template(company, tpl, name, address, ps, ph, request.user)
        audit.log(request.user, "project.create", "project", p.id, p.name, project=p, after={"template": tpl.name})
        return Response(project_dict(p, perms.roles_of(request.user, p)), status=201)


class ProjectDetail(ProjectView):
    def get(self, request, project_id):
        p = self.project
        stats = {"floors": p.floors.count(), "rooms": p.rooms.count(), "phases": p.phases.count(),
                 "workItems": p.work_items.count()}
        phases = [{"id": ph.id, "code": ph.code, "name": ph.name, "colorVar": ph.color_var}
                  for ph in p.phases.filter(is_disabled=False).order_by("order_no", "id")]
        return Response({**project_dict(p, self.roles), "stats": stats, "phases": phases})


class ProjectStatus(ProjectView):
    """项目状态只前进：筹备 → 施工中 → 已交房（必填实际交房日期，AC-F01-11）。"""

    def post(self, request, project_id):
        self.require("project.status", "只有项目经理可以推进项目状态")
        target = request.data.get("status")
        order = Project.STATUS
        cur = self.project.status
        if target not in order or order.index(target) != order.index(cur) + 1:
            fail("PROJECT_STATUS", f"项目状态只能从「{cur}」推进到下一状态")
        actual = parse_date(request.data.get("actualHandover"))
        if target == "已交房" and not actual:
            validation([("actualHandover", "请填写实际交房日期")])
        before = {"status": cur}
        self.project.status = target
        if actual:
            self.project.actual_handover = actual
        self.project.save()
        audit.log(request.user, "project.status", "project", self.project.id, self.project.name, before,
                  {"status": target, "actualHandover": d(actual)}, project=self.project)
        return Response(project_dict(self.project, self.roles))


class ProjectSettings(ProjectView):
    def patch(self, request, project_id):
        return self.put(request, project_id)

    def put(self, request, project_id):
        self.require("release_timeout.set")  # AC-F06-17
        raw = request.data.get("releaseTimeoutHours")
        try:
            hours = int(raw) if str(raw).strip().lstrip("-").isdigit() else 0
        except (TypeError, ValueError):
            hours = 0
        if not 1 <= hours <= 72:
            validation([("releaseTimeoutHours", "请输入 1–72 之间的整数")])
        before = {"releaseTimeoutHours": self.project.release_timeout_hours}
        self.project.release_timeout_hours = hours
        self.project.save()
        audit.log(request.user, "project.release_timeout", "project", self.project.id, self.project.name, before,
                  {"releaseTimeoutHours": hours}, project=self.project)
        return Response(project_dict(self.project, self.roles))


def mask(phone):
    return phone[:3] + "****" + phone[-4:]


def _history(project, actions):
    qs = AuditLog.objects.filter(project=project, action__in=actions).select_related("actor").order_by("at", "id")
    return [{"action": a.action, "actor": a.actor.name if a.actor else "系统", "at": iso(a.at), "label": a.object_label,
             "before": a.before, "after": a.after} for a in qs]


class Members(ProjectView):
    def get(self, request, project_id):
        """成员（手机号仅公司管理员看完整）、当前代理人与代理变更记录、项目状态记录。"""
        full = request.user.is_company_admin
        users = {}
        order = {r: i for i, r in enumerate(ProjectMemberRole.ROLES)}
        for r in ProjectMemberRole.objects.filter(project=self.project).select_related("user").order_by("granted_at", "id"):
            u = users.setdefault(r.user_id, {"id": r.user.id, "name": r.user.name,
                                             "phone": r.user.phone if full else mask(r.user.phone), "roles": [],
                                             "joinedAt": d(timezone.localtime(r.granted_at).date())})
            u["roles"].append(r.role)
        for u in users.values():
            u["roles"].sort(key=lambda x: order.get(x, 99))
            u["roleLabels"] = [perms.ROLE_LABELS[x] for x in u["roles"]]
            u["isAgent"] = "owner_agent" in u["roles"]
        agent_row = (ProjectMemberRole.objects.filter(project=self.project, role="owner_agent")
                     .select_related("user", "granted_by").first())
        agent = None
        if agent_row:
            agent = {"id": agent_row.user.id, "name": agent_row.user.name, "grantedAt": iso(agent_row.granted_at),
                     "grantedBy": agent_row.granted_by.name if agent_row.granted_by else None,
                     "proxyReleases": ReleaseRecord.objects.filter(project=self.project, releaser=agent_row.user,
                                                                   is_proxy=True).count()}
        return Response({"items": list(users.values()), "phoneFull": full, "agent": agent,
                         "agentHistory": _history(self.project, ["agent.assign", "agent.revoke"]),
                         "statusHistory": _history(self.project, ["project.create", "project.status"])})


class MemberRoles(ProjectView):
    def put(self, request, project_id, user_id):
        self.require("member.manage", "只有公司管理员可以分配角色")
        roles = [r for r in request.data.get("roles", []) if r in perms.PROJECT_ROLES]
        if not roles:
            validation([("roles", "请至少保留一个角色；如需移出项目请使用「移除」")])
        user = User.objects.filter(pk=user_id).first() or fail("NOT_FOUND", "成员不存在", 404)
        with transaction.atomic():
            before = list(ProjectMemberRole.objects.filter(project=self.project, user=user).exclude(role="owner_agent")
                          .values_list("role", flat=True))
            ProjectMemberRole.objects.filter(project=self.project, user=user).exclude(role="owner_agent").exclude(role__in=roles).delete()
            for r in roles:
                ProjectMemberRole.objects.get_or_create(project=self.project, user=user, role=r,
                                                        defaults={"granted_by": request.user})
            audit.log(request.user, "member.roles", "user", user.id, user.name, {"roles": before}, {"roles": roles},
                      project=self.project)
        return Response({"ok": True})

    def delete(self, request, project_id, user_id):
        """移除成员：下一次请求起无权访问；历史记录署名不变（AC-F01-06）。"""
        self.require("member.manage", "只有公司管理员可以移除成员")
        user = User.objects.filter(pk=user_id).first() or fail("NOT_FOUND", "成员不存在", 404)
        before = list(ProjectMemberRole.objects.filter(project=self.project, user=user).values_list("role", flat=True))
        if not before:
            fail("NOT_FOUND", "成员不存在", 404)
        ProjectMemberRole.objects.filter(project=self.project, user=user).delete()
        audit.log(request.user, "member.remove", "user", user.id, user.name, {"roles": before}, None, project=self.project)
        return Response({"ok": True})


class Agent(ProjectView):
    """业主指定 / 撤销业主代理人；每个项目最多一名（AC-F01-07 ~ AC-F01-09、AC-F01-12）。"""

    def post(self, request, project_id):
        self.require("agent.assign", "只有业主可以指定代理人")
        user = User.objects.filter(pk=request.data.get("userId")).first()
        if user is None or not ProjectMemberRole.objects.filter(project=self.project, user=user).exclude(role="owner_agent").exists():
            validation([("userId", "代理人必须是已加入本项目的成员")])
        if ProjectMemberRole.objects.filter(project=self.project, user=user, role="owner").exists():
            validation([("userId", "业主本人已有放行权限，请选择业主以外的成员")])
        with transaction.atomic():
            old = ProjectMemberRole.objects.select_for_update().filter(project=self.project, role="owner_agent").first()
            before = {"agent": old.user.name} if old else None
            ProjectMemberRole.objects.filter(project=self.project, role="owner_agent").delete()
            ProjectMemberRole.objects.create(project=self.project, user=user, role="owner_agent", granted_by=request.user)
            audit.log(request.user, "agent.assign", "user", user.id, user.name, before, {"agent": user.name},
                      project=self.project)
        return Response({"ok": True, "agent": {"id": user.id, "name": user.name}})

    def put(self, request, project_id):
        return self.post(request, project_id)

    def delete(self, request, project_id):
        self.require("agent.assign", "只有业主可以撤销代理人")
        old = ProjectMemberRole.objects.filter(project=self.project, role="owner_agent").select_related("user").first()
        if old:
            ProjectMemberRole.objects.filter(pk=old.pk).delete()
            audit.log(request.user, "agent.revoke", "user", old.user.id, old.user.name, {"agent": old.user.name}, None,
                      project=self.project)
        return Response({"ok": True})


def invitation_dict(inv, full=False):
    now = timezone.now()
    state = "已使用" if inv.used_at else "已撤销" if inv.revoked_at else "已过期" if inv.expires_at <= now else "有效"
    return {"id": inv.id, "phone": inv.phone if full else mask(inv.phone), "roles": inv.roles,
            "roleLabels": [perms.ROLE_LABELS[r] for r in inv.roles], "state": state,
            "createdBy": inv.created_by.name, "createdById": inv.created_by_id, "createdAt": iso(inv.created_at),
            "expiresAt": iso(inv.expires_at)}


def _owner_only(roles):
    """业主身份发邀请：只有业主（无项目经理、公司管理员身份）时受「只能邀请业主方成员」约束（AC-F02-09）。"""
    return "owner" in roles and not (roles & {"pm", "admin"})


class Invitations(ProjectView):
    def get(self, request, project_id):
        full = request.user.is_company_admin
        qs = Invitation.objects.filter(project=self.project).select_related("created_by").order_by("-id")
        items = []
        for i in qs:
            x = invitation_dict(i, full)
            x["canRevoke"] = (x["state"] == "有效" and self.can("invitation.create")
                              and (not _owner_only(self.roles) or i.created_by_id == request.user.id))
            items.append(x)
        return Response({"items": items})

    def post(self, request, project_id):
        self.require("invitation.create")
        phone = str(request.data.get("phone", "")).strip()
        roles = list(dict.fromkeys(request.data.get("roles", [])))
        is_admin = request.user.is_company_admin
        if ("admin" in roles or "company_admin" in roles) and not is_admin:
            forbidden("只有公司管理员可以设置该角色")  # AC-F02-04
        roles = ["admin" if r == "company_admin" else r for r in roles]
        allowed = perms.PROJECT_ROLES + (["admin"] if is_admin else [])
        errs = []
        if len(phone) != 11 or not phone.isdigit():
            errs.append(("phone", "请输入 11 位手机号"))
        if not roles:
            errs.append(("roles", "请至少选择一个角色"))
        elif any(r not in allowed for r in roles):
            errs.append(("roles", "请选择有效角色"))
        validation(errs)
        if _owner_only(self.roles) and roles != ["owner_member"]:
            forbidden("业主只能邀请业主方成员")  # AC-F02-09
        token = secrets.token_urlsafe(24)
        inv = Invitation.objects.create(project=self.project, phone=phone, roles=roles,
                                        token_hash=hashlib.sha256(token.encode()).hexdigest(),
                                        expires_at=timezone.now() + datetime.timedelta(days=7), created_by=request.user)
        audit.log(request.user, "invitation.create", "invitation", inv.id, mask(phone), None, {"roles": roles},
                  project=self.project)
        return Response({**invitation_dict(inv), "canRevoke": True, "link": f"/invite/{token}"}, status=201)


class InvitationRevoke(ProjectView):
    def post(self, request, project_id, inv_id):
        self.require("invitation.create")
        with transaction.atomic():
            inv = Invitation.objects.select_for_update().filter(pk=inv_id, project=self.project).first()
            if inv is None:
                fail("NOT_FOUND", "邀请不存在", 404)
            if _owner_only(self.roles) and inv.created_by_id != request.user.id:
                forbidden("业主只能撤销自己发出的邀请")
            if inv.used_at or inv.revoked_at:
                fail("INVITATION_STATE", "该邀请已使用或已撤销", 409)
            inv.revoked_at = timezone.now()
            inv.save(update_fields=["revoked_at"])
            audit.log(request.user, "invitation.revoke", "invitation", inv.id, mask(inv.phone), project=self.project)
        return Response(invitation_dict(inv))


def template_stats(t, rule_count=None):
    c = t.content or {}
    phases = c.get("phases", [])
    return {"phases": len(phases), "floors": len(c.get("floors", [])), "rooms": len(c.get("rooms", [])),
            "workItems": sum(len(p.get("tasks", [])) for p in phases),
            "rules": rule_count if rule_count is not None else ProcessRule.objects.filter(company_id=t.company_id, is_active=True).count()}


class Templates(APIView):
    def get(self, request):
        company = default_company()
        ensure_company_template(company)
        rules = ProcessRule.objects.filter(company=company, is_active=True).count()
        return Response({"items": [{"id": t.id, "name": t.name, "stats": template_stats(t, rules)}
                                   for t in Template.objects.filter(company=company).order_by("id")]})


urlpatterns = [
    path("projects", Projects.as_view()),
    path("templates", Templates.as_view()),
    path("projects/<int:project_id>", ProjectDetail.as_view()),
    path("projects/<int:project_id>/status", ProjectStatus.as_view()),
    path("projects/<int:project_id>/settings", ProjectSettings.as_view()),
    path("projects/<int:project_id>/members", Members.as_view()),
    path("projects/<int:project_id>/members/<int:user_id>", MemberRoles.as_view()),
    path("projects/<int:project_id>/members/<int:user_id>/roles", MemberRoles.as_view()),
    path("projects/<int:project_id>/agent", Agent.as_view()),
    path("projects/<int:project_id>/owner-agent", Agent.as_view()),
    path("projects/<int:project_id>/invitations", Invitations.as_view()),
    path("projects/<int:project_id>/invitations/<int:inv_id>/revoke", InvitationRevoke.as_view()),
]

# 公司模板与工序说明库（API-F03-01）放在独立文件，随本模块一起注册
from core.api.templates_admin import urlpatterns as _template_admin_urls  # noqa: E402

urlpatterns += _template_admin_urls
