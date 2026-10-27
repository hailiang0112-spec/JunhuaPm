"""权限点 → 角色集合（技术方案 §4.5，与 PRD §2.1 一一对应）。

项目角色：owner 业主、owner_member 业主方成员、owner_agent 业主代理人、pm 项目经理、
design_manager 设计经理、qc 质检、budget 预算专员；公司管理员用 admin 表示（user.is_company_admin）。
"""
from .errors import forbidden

ROLE_LABELS = {
    "owner": "业主", "owner_member": "业主方成员", "owner_agent": "业主代理人", "pm": "项目经理",
    "design_manager": "设计经理", "qc": "质检", "budget": "预算专员", "admin": "公司管理员",
}
PROJECT_ROLES = ["owner", "owner_member", "pm", "design_manager", "qc", "budget"]  # 可直接邀请 / 分配的角色
ALL_MEMBERS = {"owner", "owner_member", "owner_agent", "pm", "design_manager", "qc", "budget"}
STAFF = {"owner", "pm", "design_manager", "qc", "budget"}  # 有写权限的正式成员（不含业主方成员、代理人）

# 权限点：角色集合。「admin」= 公司管理员（只读 + 管理类，AC-F01-13）
POINTS = {
    # 读
    "project.read": ALL_MEMBERS | {"admin"},
    "contract.read": {"owner", "pm", "budget", "admin"},
    # 管理类
    "member.manage": {"admin"},
    "invitation.create": {"admin", "pm", "owner"},
    "agent.assign": {"owner"},
    "project.status": {"pm"},
    "release_timeout.set": {"pm", "admin"},
    "evidence.export": {"owner", "admin"},
    "integrity.check": {"owner", "admin"},
    "audit.read": {"owner", "admin"},
    "prototype.import": {"admin"},
    # 结构与计划
    "structure.edit": {"pm"},
    "plan.import": {"pm"},
    "phase.plan_edit": {"pm"},
    "attendance.edit": {"pm"},
    # 图纸
    "drawing.upload": {"design_manager"},
    "drawing.sign": {"owner"},
    # 基线与检查点
    "baseline.edit": {"pm", "budget"},
    "baseline.submit": {"pm"},
    "baseline.sign": {"owner"},
    "checkpoint.create": {"pm", "qc"},
    "checkpoint.check": {"qc"},
    "checkpoint.release": {"owner", "owner_agent"},
    "checkpoint.mark_covered": {"pm"},
    "discovery.correct": {"qc", "pm"},
    # 变更单
    "change.create": {"pm"},
    "change.price": {"budget"},
    "change.sign": {"owner"},
    # 问题
    "issue.create": STAFF,
    "issue.cause": {"qc"},
    "issue.close": {"pm", "qc"},
    "issue.void": STAFF,
    "issue.assign": {"pm", "qc"},
    # 经验库（公司级，按「在任一项目是质检」判定）
    "experience.submit": {"qc"},
    "experience.review": {"qc"},
    # 资料与档案
    "file.upload": STAFF,
    "acceptance_photo.edit": STAFF,
    "archive.folder_manage": {"pm", "admin"},
    "archive.upload": STAFF,
    # 补充事项、公告、付款
    "supplement.edit": STAFF,
    "supplement.to_change": {"pm"},
    "notice.post": ALL_MEMBERS,
    "payment.edit": {"budget"},
}

PERMISSION_MESSAGES = {
    "checkpoint.release": "只有业主或业主代理人可以放行",
    "evidence.export": "仅业主和公司管理员可导出证据包",
    "contract.read": "无权查看合同资料",
    "release_timeout.set": "无权修改放行时限",
}


def roles_of(user, project):
    """实时查库得到当前用户在项目中的角色集合（移除、撤销代理下一次请求即生效）。"""
    roles = set(project.member_roles.filter(user=user).values_list("role", flat=True))
    if user.is_company_admin and not roles:
        roles.add("admin")
    elif user.is_company_admin:
        roles.add("admin")
    return roles


def can(roles, point):
    allowed = POINTS[point]
    if "admin" in roles and "admin" not in allowed:
        # 公司管理员只在本人另有项目角色时，凭该角色获得业务写权限（AC-F01-13）
        return bool((roles - {"admin"}) & allowed)
    return bool(roles & allowed)


def require(roles, point, message=None):
    if not can(roles, point):
        forbidden(message or PERMISSION_MESSAGES.get(point, "无权执行该操作"))


def permissions_for(roles):
    return sorted(p for p in POINTS if can(roles, p))
