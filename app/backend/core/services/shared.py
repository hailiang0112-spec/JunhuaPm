"""跨模块共用的业务服务（多个功能模块都会调用，统一放在这里，避免各自实现出两套口径）。"""
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from core.models import ChangeOrder, ChangeOrderEvent, Issue, IssueEvent
from core.services import ledger


def next_issue_seq(project):
    return (Issue.objects.filter(project=project).aggregate(m=Max("seq_no"))["m"] or 0) + 1


def issue_event(issue, actor, kind, before="", after="", reason=""):
    """问题状态变化（关键记录，入链）。调用方需在事务内。"""
    ev = IssueEvent.objects.create(project=issue.project, issue=issue, kind=kind, before=before, after=after,
                                   reason=reason, actor=actor)
    ledger.append(issue.project_id, ev)
    return ev


@transaction.atomic
def create_issue_from_check(check, actor):
    """核对结论为「不一致」时自动生成问题（AC-F08-01）：带检查点、工作项、楼层、房间、照片与发现时点。"""
    cp = check.checkpoint
    wi = cp.work_item
    issue = Issue.objects.create(
        project=check.project, seq_no=next_issue_seq(check.project), source_check=check, checkpoint=cp, work_item=wi,
        phase=wi.phase, floor=wi.floor, room=wi.room,
        description=f"{cp.code} {cp.point}：现场与签认图纸不一致" + (f"（{check.note}）" if check.note else ""),
        level="重要", found_on=timezone.localdate(), status="未闭环", created_by=actor, source="check")
    issue_event(issue, actor, "created", after="未闭环")
    return issue


def checkpoint_labels(cp, project, now=None):
    """派生标签（技术方案 §5.1.5）：隐蔽且未放行 → 不得覆盖；待放行超过放行时限 → 超时。"""
    now = now or timezone.now()
    labels = []
    if cp.is_concealed and cp.status != "已放行":
        labels.append("不得覆盖")
    if (cp.status == "待放行" and cp.awaiting_release_since
            and (now - cp.awaiting_release_since).total_seconds() > project.release_timeout_hours * 3600):
        labels.append("超时")
    if cp.unreleased_cover:
        labels.append("未放行先覆盖")
    return labels


@transaction.atomic
def create_change_draft(project, actor, title, content="", work_item_ids=(), file_ids=(), source_issue=None,
                        source_supplement=None):
    """从问题「补签变更单」或补充事项「转为变更单」生成草稿：立即保存并分配编号（DEC-071）。"""
    from core.models import Project
    p = Project.objects.select_for_update().get(pk=project.pk)
    p.change_order_seq += 1
    p.save(update_fields=["change_order_seq"])
    co = ChangeOrder.objects.create(project=project, seq_no=p.change_order_seq, title=title[:100], content=content,
                                    status="草稿", created_by=actor, source_issue=source_issue,
                                    source_supplement=source_supplement)
    if work_item_ids:
        co.work_items.set(list(work_item_ids))
    if file_ids:
        co.files.set(list(file_ids))
    return co


def change_event(co, actor, kind, payload=None):
    """变更单事件（关键记录，入链）。调用方需在事务内。"""
    ev = ChangeOrderEvent.objects.create(project=co.project, change_order=co, round_no=co.round_no, kind=kind,
                                         payload=payload or {}, actor=actor)
    ledger.append(co.project_id, ev)
    return ev
