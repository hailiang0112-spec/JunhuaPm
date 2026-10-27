"""我的待办（F16，API-F16-01）：跨项目按角色实时派生，没有待办表（技术方案 §5.1.6）。

唯一的写入是知会类待办的「知道了」（DATA-F16-01 TodoAck）。
角色只取项目成员角色表；公司管理员身份不产生业务待办（AC-F01-13）。
"""
import datetime
import math
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from django.db import IntegrityError, transaction
from django.urls import path
from django.db.models import Max
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from core import perms
from core.api.base import iso
from core.api.projects import project_summary
from core.errors import fail, validation
from core.models import (Baseline, BaselineEvent, ChangeOrder, ChangeOrderEvent, Checkpoint, CoverEvent, DrawingVersion,
                         Project, ProjectMemberRole, TodoAck, WorkItem)
from core.services import audit
from core.services.shared import checkpoint_labels

UPCOMING_DAYS = 7  # 计划完成日期距今 ≤ 7 天且基线未签认（AC-F05-09）

# 类型（chip 与分组标题）按页面原型的展示顺序
T_RELEASE = "待放行检查点"
T_COVER = "未放行先覆盖"
T_BASELINE = "待签基线"
T_UPCOMING = "即将施工，基线未签认"
T_DRAWING = "待签图纸"
T_CHANGE = "待签变更单"
T_NOTIFY = "新增检查点（知会）"
T_RETURNED = "被退回基线"
T_RESIGN = "基线待重签"
T_REJECTED = "被驳回变更单"
T_CHECK = "待核对检查点"
T_PRICE = "待预算定价变更单"
T_MAKE = "待出新版图纸"
TYPE_ORDER = [T_RELEASE, T_COVER, T_BASELINE, T_UPCOMING, T_DRAWING, T_CHANGE, T_NOTIFY, T_RESIGN, T_RETURNED, T_REJECTED,
              T_CHECK, T_PRICE, T_MAKE]
CHECKPOINT_KINDS = {"release", "cover", "check"}
ACK_KINDS = {"checkpoint_added"}


TZ = ZoneInfo("Asia/Shanghai")  # 待办可能有上千条，直接换算时区，避免逐条走 timezone.localtime 的线程局部查找


def _dt(v):
    return f"{v.astimezone(TZ):%Y-%m-%d %H:%M}" if v else ""


def _day(v):
    if v is None:
        return ""
    if isinstance(v, datetime.datetime):
        v = v.astimezone(TZ).date()
    return v.isoformat()


def place(wi):
    """「夹层 · 设备间」：楼层 · 房间；全楼通用的工作项只显示楼层或「全楼」。"""
    if wi.floor_id is None:
        return "全楼"
    return f"{wi.floor.name} · {wi.room.name}" if wi.room_id else wi.floor.name


def cp_title(cp):
    return f"{cp.code} {place(cp.work_item)} {cp.point}" + ("（隐蔽）" if cp.is_concealed else "")


def wi_title(wi):
    """模板工作项名称多已含楼层或房间（如「负一楼车库隔墙砌筑」），此时不再重复位置。"""
    names = [x.name for x in (wi.floor, wi.room) if x is not None]
    return wi.name if any(n in wi.name for n in names) else f"{place(wi)} {wi.name}"


def money_text(v):
    if v is None:
        return ""
    sign = "+" if v >= 0 else "-"
    return f"{sign}{abs(v):,.0f} 元"


class Ctx:
    """单个项目的派生上下文：本人角色、各角色成员姓名。"""

    def __init__(self, project, roles, now):
        self.p, self.roles, self.now = project, roles, now
        self.names = {}
        for r in ProjectMemberRole.objects.filter(project=project).select_related("user").order_by("id"):
            self.names.setdefault(r.role, []).append(r.user.name)

    def who(self, *roles):
        parts = []
        label = {"owner": "业主", "owner_agent": "代理人", "pm": "项目经理", "qc": "质检", "budget": "预算专员",
                 "design_manager": "设计经理"}
        for r in roles:
            for n in self.names.get(r, []):
                parts.append(f"{n}（{label[r]}）")
        return "、".join(parts) or "待指派"

    def owners(self):
        names = self.names.get("owner", [])
        return f"{'、'.join(names)}（业主）" if names else "待指派"


def _item(ctx, kind, type_, seal, seal_text, obj_id, title, who, due, msg_due, path_, sort="", urgent=False,
          overdue_hours=0, bad=False, ack=None):
    return {"id": f"{kind}-{obj_id}", "kind": kind, "type": type_, "seal": seal, "sealText": seal_text,
            "projectId": ctx.p.id, "projectName": ctx.p.name, "objectId": obj_id, "title": title, "who": who,
            "due": due, "msgDue": msg_due, "path": path_, "sort": sort, "urgent": urgent,
            "overdueHours": overdue_hours, "bad": bad or urgent, "ack": ack}


def _release_items(ctx, for_pm_only):
    """待放行：业主、代理人看全部；项目经理只看超时（AC-F06-13）。"""
    out = []
    p = ctx.p
    # 只取生成待办需要的列（单项目可能有上千个待放行检查点，避免整行建模，NFR-002）
    rows = (Checkpoint.objects.filter(project=p, status="待放行", is_draft=False).order_by("awaiting_release_since", "id")
            .values("id", "code", "point", "is_concealed", "status", "awaiting_release_since", "created_at",
                    "unreleased_cover", "work_item__floor_id", "work_item__room_id", "work_item__floor__name",
                    "work_item__room__name"))
    for r in rows:
        wi = SimpleNamespace(floor_id=r["work_item__floor_id"], room_id=r["work_item__room_id"],
                             floor=SimpleNamespace(name=r["work_item__floor__name"]),
                             room=SimpleNamespace(name=r["work_item__room__name"]))
        cp = SimpleNamespace(id=r["id"], code=r["code"], point=r["point"], is_concealed=r["is_concealed"],
                             status=r["status"], awaiting_release_since=r["awaiting_release_since"],
                             created_at=r["created_at"], unreleased_cover=r["unreleased_cover"], work_item=wi)
        labels = checkpoint_labels(cp, p, ctx.now)
        overdue = "超时" in labels
        if for_pm_only and not overdue:
            continue
        since = cp.awaiting_release_since or cp.created_at
        due_at = since + datetime.timedelta(hours=p.release_timeout_hours)
        secs = (due_at - ctx.now).total_seconds()
        limit = f"放行时限 {p.release_timeout_hours} 小时"
        if overdue:
            hours = max(1, int(-secs // 3600))
            due = f"{_dt(due_at)} 到期 · 已超时 {hours} 小时（{limit}）"
            msg = f"已超时 {hours} 小时（{limit}），请尽快处理"
            out.append(_item(ctx, "release", T_RELEASE, "stop", "超时", cp.id, cp_title(cp), ctx.who("owner", "owner_agent"),
                             due, msg, f"/p/{p.id}/checkpoints/{cp.id}", _dt(due_at), urgent=True, overdue_hours=hours))
        else:
            left = max(1, math.ceil(secs / 3600))
            due = f"{_dt(due_at)} 到期 · 剩余 {left} 小时"
            msg = f"{_dt(due_at)} 前放行（剩余 {left} 小时）"
            out.append(_item(ctx, "release", T_RELEASE, "pend", "待放行", cp.id, cp_title(cp),
                             ctx.who("owner", "owner_agent"), due, msg, f"/p/{p.id}/checkpoints/{cp.id}", _dt(due_at)))
    return out


def _cover_items(ctx):
    """未放行先覆盖（AC-F06-12）：放行之前一直置顶提醒业主。"""
    out = []
    p = ctx.p
    events = (CoverEvent.objects.filter(project=p, was_unreleased=True).exclude(checkpoint__status="已放行")
              .select_related("checkpoint__work_item__floor", "checkpoint__work_item__room", "recorder").order_by("at", "id"))
    seen = set()
    for ev in events:
        if ev.checkpoint_id in seen:
            continue
        seen.add(ev.checkpoint_id)
        cp = ev.checkpoint
        rec_roles = perms.roles_of(ev.recorder, p) - {"admin", "owner_agent"}
        rec_label = perms.ROLE_LABELS[sorted(rec_roles)[0]] if rec_roles else ""
        who = f"记录人：{ev.recorder.name}" + (f"（{rec_label}）" if rec_label else "")
        due = f"{_dt(ev.at)} 被标记已覆盖，覆盖前未放行"
        out.append(_item(ctx, "cover", T_COVER, "stop", "未放行先覆盖", cp.id, cp_title(cp), who, due,
                         f"{due}，请查看核对照片", f"/p/{p.id}/checkpoints/{cp.id}", _dt(ev.at), urgent=True))
    return out


def _baseline_sign_items(ctx):
    """待签基线：按「楼层 + 工段」归组，避免几十项基线刷屏。"""
    p = ctx.p
    groups = {}
    qs = (Baseline.objects.filter(project=p, status="待签认", work_item__is_disabled=False)
          .select_related("work_item__phase", "work_item__floor", "work_item__room")
          .order_by("work_item__phase__order_no", "work_item__floor__order_no", "work_item__id"))
    for b in qs:
        wi = b.work_item
        groups.setdefault((wi.phase_id, wi.floor_id), []).append(b)
    out = []
    for (_, _), bl in groups.items():
        wi0 = bl[0].work_item
        floor = wi0.floor.name if wi0.floor_id else "全楼"
        if len(bl) == 1:
            title = wi_title(wi0)
        else:
            first = wi0.name if (not wi0.room_id or wi0.room.name in wi0.name) else f"{wi0.room.name} {wi0.name}"
            title = f"{floor}{wi0.phase.name}工作项基线 {len(bl)} 项（{first}等）"
        plans = [b.work_item.planned_finish for b in bl if b.work_item.planned_finish]
        earliest = min(plans) if plans else None
        ev = (BaselineEvent.objects.filter(baseline__in=bl, kind="submitted").select_related("actor").order_by("-at").first())
        sub = f"{ev.actor.name} {_day(ev.at)} 提交" if ev else (f"{_day(bl[0].submitted_at)} 提交" if bl[0].submitted_at else "已提交")
        due = sub + (f" · 最早计划完成 {_day(earliest)}" if earliest else "")
        msg = f"最早计划完成 {_day(earliest)}，请在开工前签认" if earliest else "请尽快签认"
        out.append(_item(ctx, "baseline_sign", T_BASELINE, "pend", "待签认", bl[0].id, title, ctx.owners(), due, msg,
                         f"/p/{p.id}/baselines", _day(earliest) or "9999"))
    return out


def _upcoming_items(ctx, skip_pending):
    p = ctx.p
    today = timezone.localdate()
    qs = (WorkItem.objects.filter(project=p, is_disabled=False, actual_finish__isnull=True,
                                  planned_finish__gte=today, planned_finish__lte=today + datetime.timedelta(days=UPCOMING_DAYS))
          .exclude(baseline__status="已签认").select_related("floor", "room", "baseline").order_by("planned_finish", "id"))
    out = []
    for wi in qs:
        if skip_pending and wi.baseline.status == "待签认":
            continue  # 业主已在「待签基线」里看到这一项
        days = (wi.planned_finish - today).days
        left = f"还有 {days} 天" if days else "今天到期"
        out.append(_item(ctx, "upcoming", T_UPCOMING, "pend", "基线未签认", wi.id, wi_title(wi), ctx.who("pm", "owner"),
                         f"计划完成 {_day(wi.planned_finish)} · {left}",
                         f"计划完成 {_day(wi.planned_finish)}（{left}），基线仍未签认",
                         f"/p/{p.id}/work-items/{wi.id}", _day(wi.planned_finish)))
    return out


def _drawing_items(ctx):
    p = ctx.p
    out = []
    qs = (DrawingVersion.objects.filter(project=p, signoff__isnull=True)
          .select_related("drawing_set__current_signed_version", "created_by").order_by("created_at", "id"))
    latest = dict(DrawingVersion.objects.filter(project=p).values("drawing_set_id").annotate(m=Max("version_no"))
                  .values_list("drawing_set_id", "m"))
    for v in qs:
        if v.version_no < latest[v.drawing_set_id]:
            continue  # 已被新版取代：只签分册最新版
        n = len(v.affected_work_item_ids or [])
        title = f"{v.drawing_set.name} V{v.version_no}" + (f"（影响 {n} 个工作项）" if n else "")
        due = f"{v.created_by.name} {_day(v.created_at)} 发布"
        out.append(_item(ctx, "drawing_sign", T_DRAWING, "pend", "待签认", v.id, title, ctx.owners(), due,
                         f"{due}，请签认", f"/p/{p.id}/drawings", _day(v.created_at)))
    return out


def _co_title(co, with_price=False):
    t = f"{co.code} {co.title}".strip()
    if with_price and co.price_delta is not None:
        t += f" · {money_text(co.price_delta)}"
        if co.cost_bearer:
            t += f" · {co.cost_bearer}承担"
    return t


def _co_event(co, kind):
    return (ChangeOrderEvent.objects.filter(change_order=co, kind=kind).select_related("actor").order_by("-at", "-id").first())


def _change_items(ctx, status, kind, type_, seal, seal_text, who):
    p = ctx.p
    out = []
    for co in ChangeOrder.objects.filter(project=p, status=status).select_related("created_by").order_by("seq_no"):
        if status == "待业主签认":
            ev = _co_event(co, "priced")
            due = f"{ev.actor.name} {_day(ev.at)} 定价" if ev else "已定价"
            msg = f"{due}，待业主签认"
            title = _co_title(co, True)
            sort_at = ev.at if ev else co.created_at
        elif status == "待预算定价":
            ev = _co_event(co, "resubmitted") or _co_event(co, "created")
            actor = ev.actor.name if ev else co.created_by.name
            at = ev.at if ev else co.created_at
            due = f"{actor} {_day(at)} " + ("重新提交" if ev and ev.kind == "resubmitted" else "发起")
            msg = f"{due}，待预算定价"
            title = _co_title(co)
            sort_at = at
        else:  # 已驳回
            ev = _co_event(co, "rejected")
            reason = co.reject_reason or (ev.payload.get("reason", "") if ev else "")
            due = (f"{ev.actor.name} {_day(ev.at)} 驳回" if ev else "已驳回") + (f"：「{reason}」" if reason else "")
            msg = (f"{ev.actor.name} {_day(ev.at)} 驳回" if ev else "已驳回") + "，请修改后重新提交"
            title = _co_title(co, True)
            sort_at = ev.at if ev else co.created_at
        out.append(_item(ctx, kind, type_, seal, seal_text, co.id, title, who, due, msg, f"/p/{p.id}/changes/{co.id}",
                         _dt(sort_at)))
    return out


def _notify_items(ctx, user):
    """已签认 / 待重签基线新增检查点的知会（AC-F06-16）；本人点「知道了」后消失（DEC-118）。"""
    p = ctx.p
    acked = set(TodoAck.objects.filter(user=user, project=p, kind="checkpoint_added").values_list("object_id", flat=True))
    out = []
    qs = (BaselineEvent.objects.filter(project=p, kind="checkpoint_added").exclude(id__in=acked)
          .select_related("actor", "baseline", "checkpoint__work_item__floor", "checkpoint__work_item__room")
          .order_by("at", "id"))
    for ev in qs:
        cp = ev.checkpoint
        title = cp_title(cp) if cp else wi_title(ev.baseline.work_item)
        wid = cp.work_item_id if cp else ev.baseline.work_item_id
        due = f"{ev.actor.name} {_dt(ev.at)} 新增 · 已直接生效，基线「{ev.baseline.status}」状态不变"
        msg = f"{ev.actor.name} {_day(ev.at)} 新增检查点，已直接生效，基线签认状态不变，请知悉"
        out.append(_item(ctx, "checkpoint_added", T_NOTIFY, "plain", "知会", ev.id, title, ctx.owners(), due, msg,
                         f"/p/{p.id}/work-items/{wid}", _dt(ev.at), ack={"kind": "checkpoint_added", "objectId": ev.id}))
    return out


def _check_items(ctx, user):
    """待核对：未核对；不一致与放行后发现不一致等待复核。工作项指定了质检时只给该质检。"""
    p = ctx.p
    out = []
    qs = (Checkpoint.objects.filter(project=p, is_draft=False, status__in=["未核对", "不一致", "放行后发现不一致"])
          .select_related("work_item__floor", "work_item__room", "latest_check").order_by("work_item__planned_finish", "id"))
    for cp in qs:
        wi = cp.work_item
        if wi.qc_user_id and wi.qc_user_id != user.id:
            continue
        if cp.status == "未核对":
            seal_text = "待核对"
            due = f"计划 {_day(wi.planned_finish)} 完成，覆盖前核对" if wi.planned_finish else "覆盖前核对"
            msg = due
        else:
            seal_text = "待复核"
            note = cp.latest_check.note if cp.latest_check else ""
            due = "原核对：不一致" + (f"（{note}）" if note else "") + "，整改后复核"
            msg = "原核对不一致，整改后请复核"
        out.append(_item(ctx, "check", T_CHECK, "pend", seal_text, cp.id, cp_title(cp), ctx.who("qc"), due, msg,
                         f"/p/{p.id}/checkpoints/{cp.id}", _day(wi.planned_finish) or "9999"))
    return out


def _make_drawing_items(ctx):
    p = ctx.p
    out = []
    done = set(DrawingVersion.objects.filter(project=p, change_order__isnull=False).values_list("change_order_id", flat=True))
    for co in ChangeOrder.objects.filter(project=p, status="已生效", needs_new_drawing=True).order_by("seq_no"):
        if co.id in done:
            continue
        ev = _co_event(co, "signed")
        due = f"变更单 {_day(ev.at)} 生效" if ev else "变更单已生效"
        out.append(_item(ctx, "drawing_make", T_MAKE, "pend", "待出图", co.id, f"{_co_title(co)} · 需出新版图纸",
                         ctx.who("design_manager"), due, f"{due}，请发布新版图纸", f"/p/{p.id}/drawings",
                         _dt(ev.at) if ev else ""))
    return out


def _returned_items(ctx):
    p = ctx.p
    out = []
    qs = (Baseline.objects.filter(project=p, status="已退回", work_item__is_disabled=False)
          .select_related("work_item__floor", "work_item__room").order_by("work_item__planned_finish", "id"))
    for b in qs:
        ev = BaselineEvent.objects.filter(baseline=b, kind="returned").select_related("actor").order_by("-at").first()
        reason = b.return_reason or (ev.reason if ev else "")
        head = f"{ev.actor.name} {_day(ev.at)} 退回" if ev else "已退回"
        out.append(_item(ctx, "baseline_returned", T_RETURNED, "stop", "已退回", b.id, wi_title(b.work_item), ctx.who("pm"),
                         head + (f"：「{reason}」" if reason else ""), f"{head}，请修改后重新提交",
                         f"/p/{p.id}/work-items/{b.work_item_id}", _day(b.work_item.planned_finish) or "9999"))
    return out


def _resign_items(ctx):
    """新版图纸签认后受影响的已签认基线进入「待重签」（AC-F04-07）：项目经理更新图纸版本重提，业主知悉。"""
    p = ctx.p
    out = []
    qs = (Baseline.objects.filter(project=p, status="待重签", work_item__is_disabled=False)
          .select_related("work_item__floor", "work_item__room").order_by("work_item__planned_finish", "id"))
    for b in qs:
        ev = (BaselineEvent.objects.filter(baseline=b, kind="resign_required")
              .select_related("drawing_version__drawing_set").order_by("-at").first())
        dv = ev.drawing_version if ev else None
        head = f"{dv.drawing_set.name} V{dv.version_no} 于 {_day(ev.at)} 签认" if dv else "图纸已更新"
        out.append(_item(ctx, "baseline_resign", T_RESIGN, "pend", "待重签", b.id, wi_title(b.work_item),
                         ctx.who("pm", "owner"), f"{head}，本工作项基线待重签；重签前现场仍按原签认版施工与核对",
                         f"{head}，请项目经理更新图纸版本后重新提交业主签认",
                         f"/p/{p.id}/work-items/{b.work_item_id}", _day(b.work_item.planned_finish) or "9999"))
    return out


def release_count(project, roles, now):
    """待放行待办条数（计数接口用数据库直接统计，与 _release_items 口径一致）。"""
    qs = Checkpoint.objects.filter(project=project, status="待放行", is_draft=False)
    if roles & {"owner", "owner_agent"}:
        return qs.count()
    if "pm" in roles:
        return qs.filter(awaiting_release_since__lt=now - datetime.timedelta(hours=project.release_timeout_hours)).count()
    return 0


def project_todos(project, roles, user, now, skip_release=False):
    ctx = Ctx(project, roles, now)
    items = []
    if skip_release:
        pass
    elif roles & {"owner", "owner_agent"}:
        items += _release_items(ctx, for_pm_only=False)
    elif "pm" in roles:
        items += _release_items(ctx, for_pm_only=True)
    if "owner" in roles:
        items += _cover_items(ctx)
        items += _baseline_sign_items(ctx)
        items += _drawing_items(ctx)
        items += _change_items(ctx, "待业主签认", "change_sign", T_CHANGE, "pend", "待签认", ctx.owners())
        items += _notify_items(ctx, user)
    if roles & {"owner", "pm"}:
        items += _upcoming_items(ctx, skip_pending="owner" in roles)
        items += _resign_items(ctx)
    if "pm" in roles:
        items += _returned_items(ctx)
        items += _change_items(ctx, "已驳回", "change_rejected", T_REJECTED, "stop", "已驳回", ctx.who("pm"))
    if "qc" in roles:
        items += _check_items(ctx, user)
    if "budget" in roles:
        items += _change_items(ctx, "待预算定价", "price", T_PRICE, "pend", "待预算定价", ctx.who("budget"))
    if "design_manager" in roles:
        items += _make_drawing_items(ctx)
    return items


def my_projects(user):
    """本人有项目角色的项目（公司管理员身份不产生待办）。"""
    rows = ProjectMemberRole.objects.filter(user=user).values_list("project_id", "role")
    by_project = {}
    for pid, role in rows:
        by_project.setdefault(pid, set()).add(role)
    return by_project


def collect(user):
    now = timezone.now()
    items = []
    by_project = my_projects(user)
    for p in Project.objects.filter(pk__in=by_project).order_by("id"):
        items += project_todos(p, by_project[p.id], user, now)
    urgent = sorted([x for x in items if x["urgent"]], key=lambda x: (-x["overdueHours"], x["kind"] != "release", x["sort"]))
    rest = sorted([x for x in items if not x["urgent"]], key=lambda x: (TYPE_ORDER.index(x["type"]), x["sort"]))
    return urgent + rest


class Todos(APIView):
    def get(self, request):
        items = collect(request.user)
        u = request.user
        qs = Project.objects.all() if u.is_company_admin else Project.objects.filter(member_roles__user=u).distinct()
        sites = []
        for p in qs.order_by("id"):
            roles = perms.roles_of(u, p)
            s = project_summary(p, roles)
            s["roleLabels"] = [perms.ROLE_LABELS[r] for r in sorted(roles, key=lambda r: list(perms.ROLE_LABELS).index(r))]
            sites.append(s)
        types = [t for t in TYPE_ORDER if any(x["type"] == t for x in items)]
        return Response({"items": items, "total": len(items), "urgent": sum(1 for x in items if x["urgent"]),
                         "types": types, "generatedAt": iso(timezone.now()), "sites": sites,
                         "isCompanyAdmin": u.is_company_admin})


class TodoCount(APIView):
    def get(self, request):
        now = timezone.now()
        by_project = my_projects(request.user)
        total = checkpoints = 0
        for p in Project.objects.filter(pk__in=by_project).order_by("id"):
            roles = by_project[p.id]
            items = project_todos(p, roles, request.user, now, skip_release=True)
            rel = release_count(p, roles, now)
            total += len(items) + rel
            checkpoints += rel + sum(1 for x in items if x["kind"] in CHECKPOINT_KINDS)
        return Response({"total": total, "checkpoints": checkpoints})


class TodoAckView(APIView):
    """知会类「知道了」（DATA-F16-01）：只影响本人，多名业主各自确认。"""

    def post(self, request):
        kind = request.data.get("kind")
        try:
            object_id = int(request.data.get("objectId"))
        except (TypeError, ValueError):
            object_id = None
        if kind not in ACK_KINDS or object_id is None:
            validation([("kind", "不支持的知会类型")])
        ev = BaselineEvent.objects.filter(pk=object_id, kind="checkpoint_added").select_related("project").first()
        if ev is None or not ProjectMemberRole.objects.filter(project=ev.project, user=request.user, role="owner").exists():
            fail("NOT_FOUND", "该知会不存在或已移除", 404)
        try:
            with transaction.atomic():
                TodoAck.objects.create(user=request.user, project=ev.project, kind=kind, object_id=object_id)
                audit.log(request.user, "todo.ack", "baseline_event", ev.id, "新增检查点知会", project=ev.project)
        except IntegrityError:
            pass  # 唯一约束：重复点击只记一次
        return Response({"ok": True})


urlpatterns = [
    path("todos", Todos.as_view()),
    path("todos/count", TodoCount.as_view()),
    path("todos/ack", TodoAckView.as_view()),
]
