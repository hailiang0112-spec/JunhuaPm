"""FLOW-12（变更单：发起 → 定价 → 签认 / 驳回 → 重新提交、后补变更）与 FLOW-13（不一致处置与问题闭环）。

期望值来自 TDD 契约与 AC 原文中的已知业务数据，不由被测函数推算。
"""
import datetime

import pytest

from core.api import issues as issues_api
from core.models import (Baseline, BaselineRevision, ChangeOrder, ChangeOrderEvent, Checkpoint, CheckPhoto, CheckRecord,
                         DrawingSet, DrawingVersion, Issue, IssueEvent, LedgerEntry, StoredFile, WorkItem)
from core.services import ledger
from core.services.shared import create_issue_from_check

pytestmark = pytest.mark.django_db


def url(p, tail=""):
    return f"/api/projects/{p.id}/change-orders{tail}"


def iurl(p, tail=""):
    return f"/api/projects/{p.id}/issues{tail}"


def kitchen_items(project):
    """一楼 · 厨房的 3 个工作项（BG-003 的受影响工作项）。"""
    items = list(WorkItem.objects.filter(project=project, room__name="厨房", floor__name="一楼").order_by("id")[:3])
    if len(items) < 3:
        items += list(WorkItem.objects.filter(project=project, floor__name="一楼").exclude(id__in=[i.id for i in items])
                      .order_by("id")[: 3 - len(items)])
    return items


def form(items, **kw):
    body = {"reasonCategory": "设计深化", "content": "一楼厨房烟道预留位调整（纠正偏移 120mm）：按深化图将烟道包封位置西移 120mm。",
            "title": "一楼厨房烟道预留位调整（纠正偏移 120mm）", "workItemIds": [i.id for i in items],
            "needsNewDrawing": True, "builtBeforeSign": False}
    body.update(kw)
    return body


def make_co(client, project, items, **kw):
    r = client.post(url(project), form(items, **kw), format="json")
    assert r.status_code == 201, r.json()
    return r.json()


def test_flow12_change_order_lifecycle(project, client_for, users):
    pm, budget, owner, owner_member = client_for("pm"), client_for("budget"), client_for("owner"), client_for("owner_member")
    items = kitchen_items(project)

    # 缺 5 项一次列出（AC-F07-01）
    r = pm.post(url(project), {}, format="json")
    assert r.status_code == 400 and r.json()["code"] == "VALIDATION_FAILED"
    assert {f["field"] for f in r.json()["fields"]} == {"reasonCategory", "content", "workItemIds", "needsNewDrawing", "builtBeforeSign"}
    assert ChangeOrder.objects.filter(project=project).count() == 0

    # 只有项目经理可以发起
    assert owner.post(url(project), form(items), format="json").status_code == 403

    # 先有 BG-001、BG-002，再发起 BG-003（项目内序号）
    make_co(pm, project, items[:1], title="二楼主卧衣帽间隔墙后移 300mm", reasonCategory="业主要求",
            content="业主要求二楼主卧衣帽间隔墙整体后移 300mm。")
    make_co(pm, project, items[:1], title="负一楼卫生间地漏移位至淋浴区中心", reasonCategory="现场条件",
            content="负一楼卫生间地漏移至淋浴区中心。", needsNewDrawing=False)
    # 其中一个工作项的基线已签认：签认变更单后基线指针前移
    b0 = Baseline.objects.get(work_item=items[0])
    from django.db import transaction
    with transaction.atomic():
        sub = BaselineRevision.objects.create(project=project, baseline=b0, rev_no=1, kind="submit",
                                              content={"description": "烟道包封原做法"}, actor=users["pm"])
        ledger.append(project.id, sub)
    b0.status, b0.current_revision, b0.signed_revision = "已签认", sub, sub
    b0.save()

    co = make_co(pm, project, items)
    assert co["code"] == "BG-003" and co["status"] == "待预算定价" and co["isLate"] is False
    assert co["needsNewDrawing"] is True and len(co["workItems"]) == 3
    assert [e["kind"] for e in co["events"]] == ["created"]
    ev = ChangeOrderEvent.objects.get(change_order_id=co["id"], kind="created")
    assert LedgerEntry.objects.filter(project=project, record_type=ev._meta.db_table, record_id=ev.id).exists()
    # 预算专员待办由「待预算定价」状态派生
    r = budget.get(url(project), {"status": "待预算定价"})
    assert "BG-003" in [x["code"] for x in r.json()["items"]]

    # 定价：+1800 元、工期 1 天、承担方 设计方（AC-F07-03）
    assert pm.post(url(project, f"/{co['id']}/price"), {"priceDelta": 1800, "scheduleDeltaDays": 1, "costBearer": "设计方"}, format="json").status_code == 403
    r = budget.post(url(project, f"/{co['id']}/price"), {}, format="json")
    assert r.status_code == 400 and {f["field"] for f in r.json()["fields"]} == {"priceDelta", "scheduleDeltaDays", "costBearer"}
    r = budget.post(url(project, f"/{co['id']}/price"), {"priceDelta": 1800, "scheduleDeltaDays": 1, "costBearer": "设计方"}, format="json")
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "待业主签认" and d["priceDelta"] == 1800 and d["scheduleDeltaDays"] == 1 and d["costBearer"] == "设计方"
    assert d["pricedBy"]["name"] == "赵会计"
    # 重复定价 → 409，带谁、何时
    r = budget.post(url(project, f"/{co['id']}/price"), {"priceDelta": 1800, "scheduleDeltaDays": 1, "costBearer": "设计方"}, format="json")
    assert r.status_code == 409 and r.json()["details"]["by"] == "赵会计"
    # 业主待办由「待业主签认」派生
    assert "BG-003" in [x["code"] for x in owner.get(url(project), {"status": "待业主签认"}).json()["items"]]

    # 业主方成员不能签认
    assert owner_member.post(url(project, f"/{co['id']}/sign"), {}, format="json").status_code == 403
    # 签认（AC-F07-04）
    r = owner.post(url(project, f"/{co['id']}/sign"), {}, format="json")
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "已生效" and d["signedBy"]["name"] == "刘先生"
    assert all(w["revision"] is not None for w in d["workItems"])
    revs = BaselineRevision.objects.filter(change_order_id=co["id"])
    assert revs.count() == 3 and set(revs.values_list("kind", flat=True)) == {"change_order"}
    assert sorted(revs.values_list("baseline__work_item_id", flat=True)) == sorted(i.id for i in items)
    for rev in revs:
        assert rev.content["changeOrder"]["code"] == "BG-003"
        assert LedgerEntry.objects.filter(project=project, record_type=rev._meta.db_table, record_id=rev.id).exists()
    b0.refresh_from_db()
    rev0 = revs.get(baseline=b0)
    assert rev0.rev_no == 2 and rev0.content["description"] == "烟道包封原做法"
    assert b0.current_revision_id == rev0.id and b0.signed_revision_id == rev0.id
    signed = ChangeOrderEvent.objects.get(change_order_id=co["id"], kind="signed")
    assert signed.payload["priceDelta"] == "1800.00" and signed.payload["costBearer"] == "设计方"
    # 需要新版图纸 → 设计经理「按变更单出新版图纸」待办可查询（AC-F07-07）
    assert d["drawing"]["todoPending"] is True and d["drawing"]["designManagers"] == ["李工"]
    assert ChangeOrder.objects.filter(project=project, status="已生效", needs_new_drawing=True).count() == 1
    # 重复签认 → 409 ALREADY_SIGNED，带签认人
    r = owner.post(url(project, f"/{co['id']}/sign"), {}, format="json")
    assert r.status_code == 409 and r.json()["code"] == "ALREADY_SIGNED" and "刘先生" in r.json()["message"]
    assert BaselineRevision.objects.filter(change_order_id=co["id"]).count() == 3

    # 另一张：定价（费用可为负数）后业主无理由驳回被拒，填理由后驳回（AC-F07-05、AC-F07-06）
    co2 = make_co(pm, project, items[1:2], title="一楼客厅东墙砌筑线纠偏，向内移 40mm", reasonCategory="施工纠偏",
                  content="一楼客厅东墙放线偏差 40mm，拆除后按签认图向内移 40mm 重砌。", needsNewDrawing=False)
    assert co2["code"] == "BG-004"
    r = budget.post(url(project, f"/{co2['id']}/price"), {"priceDelta": -300, "scheduleDeltaDays": 0, "costBearer": "业主"}, format="json")
    assert r.status_code == 200 and r.json()["priceDelta"] == -300 and r.json()["scheduleDeltaDays"] == 0
    r = owner.post(url(project, f"/{co2['id']}/reject"), {"reason": "  "}, format="json")
    assert r.status_code == 400 and r.json()["message"] == "请填写驳回理由"
    assert ChangeOrder.objects.get(pk=co2["id"]).status == "待业主签认"
    reason = "放线偏差属于施工方问题，重砌费用应由装修公司承担，不同意由业主承担。"
    r = owner.post(url(project, f"/{co2['id']}/reject"), {"reason": reason}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "已驳回" and r.json()["rejectReason"] == reason
    # 项目经理待办由「已驳回」派生
    assert "BG-004" in [x["code"] for x in pm.get(url(project), {"status": "已驳回"}).json()["items"]]
    # 已驳回不能签认
    assert owner.post(url(project, f"/{co2['id']}/sign"), {}, format="json").status_code == 409

    # 修改后重新提交（AC-F07-09）：编号不变、回到待预算定价、清空定价、驳回记录保留
    r = pm.post(url(project, f"/{co2['id']}/resubmit"), {}, format="json")
    assert r.status_code == 400 and len(r.json()["fields"]) == 5
    body = form(items[1:2], reasonCategory="施工纠偏", content="一楼客厅东墙按签认图向内移 40mm 重砌，费用由装修公司承担。",
                title="一楼客厅东墙砌筑线纠偏，向内移 40mm", needsNewDrawing=False)
    r = pm.post(url(project, f"/{co2['id']}/resubmit"), body, format="json")
    assert r.status_code == 200
    d = r.json()
    assert d["code"] == "BG-004" and d["status"] == "待预算定价" and d["roundNo"] == 2
    assert d["priceDelta"] is None and d["scheduleDeltaDays"] is None and d["costBearer"] == ""
    assert [e["kind"] for e in d["events"]] == ["created", "priced", "rejected", "resubmitted"]
    assert d["rejects"] == [{"roundNo": 1, "by": {"id": users["owner"].id, "name": "刘先生"}, "at": d["rejects"][0]["at"], "reason": reason}]
    # 重复重新提交 → 409
    r = pm.post(url(project, f"/{co2['id']}/resubmit"), body, format="json")
    assert r.status_code == 409 and r.json()["code"] == "CHANGE_ORDER_STATE" and r.json()["message"] == "变更单状态已变化，请刷新"
    # 第二轮可以再次定价（每轮每种事件一条）
    r = budget.post(url(project, f"/{co2['id']}/price"), {"priceDelta": 0, "scheduleDeltaDays": 1, "costBearer": "装修公司"}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "待业主签认"

    # 第三张：现场已按此施工 → 后补变更（AC-F07-08）
    co3 = make_co(pm, project, items[2:3], title="夹层楼梯间增设检修门洞（600×1800mm）", reasonCategory="现场条件",
                  content="夹层楼梯间现场已预留 600×1800mm 检修门洞，补办变更单。", needsNewDrawing=False, builtBeforeSign=True)
    assert co3["code"] == "BG-005" and co3["isLate"] is True and co3["builtBeforeSign"] is True
    late = pm.get(url(project), {"late": "1"}).json()
    assert [x["code"] for x in late["items"]] == ["BG-005"]
    # 列表：编号倒序、搜索
    lst = owner_member.get(url(project)).json()
    assert [x["code"] for x in lst["items"]] == ["BG-005", "BG-004", "BG-003", "BG-002", "BG-001"] and lst["total"] == 5
    assert [x["code"] for x in pm.get(url(project), {"q": "烟道"}).json()["items"]] == ["BG-003"]
    assert [x["code"] for x in pm.get(url(project), {"q": "BG-004"}).json()["items"]] == ["BG-004"]
    # 关键记录事件全部入链，链完整
    assert ledger.verify(project.id)["ok"] is True


# ——— FLOW-13 ———

def make_mismatch(project, users):
    """CK-031（二楼书房 B 门洞 860mm）核对为不一致，并自动生成问题。"""
    from django.db import transaction
    wi = WorkItem.objects.filter(project=project, floor__name="二楼", room__name="书房 B").first() or \
        WorkItem.objects.filter(project=project, room__isnull=False).first()
    with transaction.atomic():
        f = StoredFile.objects.create(project=project, storage_key="ab/demo.pdf", sha256="a" * 64, size=10,
                                      mime="application/pdf", original_name="二楼平面布局图.pdf", uploader=users["design_manager"])
        ds = DrawingSet.objects.create(project=project, name="二楼平面布局图")
        dv = DrawingVersion.objects.create(project=project, drawing_set=ds, version_no=1, file=f, created_by=users["design_manager"])
        cp = Checkpoint.objects.create(project=project, work_item=wi, code="CK-031", point="二楼书房 B 门洞净宽 900mm",
                                       drawing_version=dv, x=0.4, y=0.5, created_by=users["qc"])
        chk = CheckRecord.objects.create(project=project, checkpoint=cp, checker=users["qc"], drawing_version=dv,
                                         was_latest_signed=True, conclusion="不一致", was_covered=False,
                                         discovery_phase="覆盖前", note="门洞净宽 860mm")
        ledger.append(project.id, chk)
        for n in range(3):
            pf = StoredFile.objects.create(project=project, storage_key=f"cd/p{n}.jpg", sha256=str(n) * 64, size=10,
                                           mime="image/jpeg", original_name=f"CK-031-{n + 1}.jpg", uploader=users["qc"])
            CheckPhoto.objects.create(project=project, check_record=chk, file=pf, file_sha256=pf.sha256, pin_x=0.4, pin_y=0.5)
        cp.status, cp.latest_check = "不一致", chk
        cp.save()
    issue = create_issue_from_check(chk, users["qc"])
    return wi, cp, dv, issue


def recheck(project, users, cp, dv, conclusion):
    from django.db import transaction
    with transaction.atomic():
        chk = CheckRecord.objects.create(project=project, checkpoint=cp, checker=users["qc"], drawing_version=dv,
                                         was_latest_signed=True, conclusion=conclusion, was_covered=False)
        ledger.append(project.id, chk)
    cp.latest_check = chk
    cp.status = "待放行" if conclusion != "不一致" else "不一致"
    cp.save()


def test_flow13_issue_lifecycle(project, client_for, users, monkeypatch):
    pm, qc, owner, member = client_for("pm"), client_for("qc"), client_for("owner"), client_for("owner_member")
    wi, cp, dv, issue = make_mismatch(project, users)

    # 自动生成的问题带检查点、工作项、楼层房间、照片、发现时点，状态未闭环（AC-F08-01）
    d = qc.get(iurl(project, f"/{issue.id}")).json()
    assert d["status"] == "未闭环" and d["checkpoint"]["code"] == "CK-031" and d["workItem"]["id"] == wi.id
    assert d["floor"]["name"] == wi.floor.name and d["room"]["name"] == wi.room.name
    assert len(d["sourceCheck"]["photos"]) == 3 and d["sourceCheck"]["discoveryPhase"] == "覆盖前"
    assert d["sourceLabel"] == "不一致 CK-031" and d["foundOn"]

    # 质检依次选三种原因 → 对应处置建议（AC-F08-02）
    assert pm.post(iurl(project, f"/{issue.id}/cause"), {"cause": "施工偏离签认图"}, format="json").status_code == 403
    expect = [("设计已改但未签变更单", "补签变更单（可一键生成变更单草稿）"), ("施工偏离签认图", "返工后复核"),
              ("图纸本身未表达清楚", "设计经理出新版或书面澄清")]
    for cause, sugg in expect:
        r = qc.post(iurl(project, f"/{issue.id}/cause"), {"cause": cause}, format="json")
        assert r.status_code == 200 and r.json()["cause"] == cause and r.json()["suggestion"] == sugg
    assert IssueEvent.objects.filter(issue=issue, kind="cause_set").count() == 3

    # 一键生成变更单草稿（项目经理）→ 草稿立即分配编号，补齐后提交进入待预算定价
    assert qc.post(iurl(project, f"/{issue.id}/change-order-draft"), {}, format="json").status_code == 403
    r = pm.post(iurl(project, f"/{issue.id}/change-order-draft"), {}, format="json")
    assert r.status_code == 201 and r.json()["code"] == "BG-001" and r.json()["status"] == "草稿"
    draft = pm.get(url(project, f"/{r.json()['id']}")).json()
    assert draft["source"]["code"] == issue.code and [w["id"] for w in draft["workItems"]] == [wi.id] and len(draft["files"]) == 3
    again = pm.post(iurl(project, f"/{issue.id}/change-order-draft"), {}, format="json")
    assert again.status_code == 200 and again.json()["existing"] is True and again.json()["code"] == "BG-001"
    r = pm.post(url(project, f"/{draft['id']}/submit"), form([wi], content=draft["content"], title=draft["title"]), format="json")
    assert r.status_code == 200 and r.json()["code"] == "BG-001" and r.json()["status"] == "待预算定价"
    assert [e["kind"] for e in r.json()["events"]] == ["created"]

    # 项目经理手工登记：空表单逐项提示（DEC-081）；不填对策和负责人 → 待补充对策 / 待指派（AC-F08-03）
    r = pm.post(iurl(project), {}, format="json")
    assert r.status_code == 400
    assert {f["field"]: f["message"] for f in r.json()["fields"]} == {
        "description": "请填写问题描述", "level": "请选择等级", "phaseId": "请选择所属工段", "dueDate": "请选择要求闭环日期",
        "floorId": "请选择楼层", "roomId": "请选择房间"}
    opts = pm.get(iurl(project, "/options")).json()
    mez = next(f for f in opts["floors"] if f["name"] == "夹层")
    one = next(f for f in opts["floors"] if f["name"] == "一楼")
    phase = opts["phases"][0]
    r = pm.post(iurl(project), {"description": "夹层楼梯间墙体砂浆饱满度不足", "level": "一般", "phaseId": phase["id"],
                                "dueDate": "2026-11-05", "floorId": one["id"], "roomId": mez["rooms"][0]["id"]}, format="json")
    assert r.status_code == 400 and r.json()["fields"] == [{"field": "roomId", "message": "房间与楼层不匹配"}]
    r = pm.post(iurl(project), {"description": "夹层楼梯间墙体砂浆饱满度不足", "level": "一般", "phaseId": phase["id"],
                                "dueDate": "2026-11-05", "floorId": mez["id"], "roomId": mez["rooms"][0]["id"],
                                "countermeasure": "", "ownerName": ""}, format="json")
    assert r.status_code == 201
    manual = r.json()
    assert manual["status"] == "未闭环" and manual["countermeasure"] == "待补充对策" and manual["ownerName"] == "待指派"
    assert manual["sourceLabel"] == "手工登记" and manual["code"] == "WT-002"
    # 补充对策、指派负责人也留痕
    r = qc.post(iurl(project, f"/{manual['id']}/assign"), {"countermeasure": "铲除重新勾缝", "ownerName": "张工"}, format="json")
    assert r.status_code == 200 and r.json()["ownerName"] == "张工"
    assert [e["kind"] for e in r.json()["events"]] == ["created", "measure", "assign"]
    assert owner.post(iurl(project, f"/{manual['id']}/assign"), {"ownerName": "李工"}, format="json").status_code == 403

    # 超期：今天 2026-10-27，要求闭环 2026-10-20 → 超期 7 天，按超期降序排在前面（AC-F08-04）
    monkeypatch.setattr(issues_api, "today", lambda: datetime.date(2026, 10, 27))
    Issue.objects.filter(pk=issue.id).update(due_date=datetime.date(2026, 10, 24))
    r = pm.post(iurl(project), {"description": "负一楼设备间砌体垂直度偏差 12mm", "level": "重要", "phaseId": phase["id"],
                                "dueDate": "2026-10-20", "floorId": mez["id"], "roomId": mez["rooms"][0]["id"]}, format="json")
    late = r.json()
    lst = member.get(iurl(project)).json()
    assert [x["code"] for x in lst["items"]][:2] == [late["code"], issue.code]
    assert lst["items"][0]["overdueDays"] == 7 and lst["items"][1]["overdueDays"] == 3
    assert next(x for x in lst["items"] if x["code"] == "WT-002")["overdueDays"] == 0
    assert lst["counts"] == {"open": 3, "overdue": 2, "closed": 0} and lst["today"] == "2026-10-27"

    # CK-031 仍为不一致时闭环被拒（AC-F08-06）
    r = pm.post(iurl(project, f"/{issue.id}/close"), {}, format="json")
    assert r.status_code == 422 and r.json()["message"] == "请先由质检复核为一致或已变更"
    assert Issue.objects.get(pk=issue.id).status == "未闭环"
    assert owner.post(iurl(project, f"/{issue.id}/close"), {}, format="json").status_code == 403
    # 质检复核为一致后闭环：闭环日期为当天（AC-F08-05）
    recheck(project, users, cp, dv, "一致")
    r = pm.post(iurl(project, f"/{issue.id}/close"), {}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "已闭环" and r.json()["closedOn"] == "2026-10-27"
    assert pm.post(iurl(project, f"/{issue.id}/close"), {}, format="json").status_code == 409
    # 重新打开：清除闭环日期，恢复处理中，留痕
    r = qc.post(iurl(project, f"/{issue.id}/reopen"), {}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "处理中" and r.json()["closedOn"] is None
    kinds = list(IssueEvent.objects.filter(issue=issue).order_by("id").values_list("kind", flat=True))
    assert kinds[-2:] == ["closed", "reopened"]
    reopened = IssueEvent.objects.filter(issue=issue, kind="reopened").get()
    assert LedgerEntry.objects.filter(project=project, record_type=reopened._meta.db_table, record_id=reopened.id).exists()
    # 手工问题（无检查点）直接可闭环
    assert pm.post(iurl(project, f"/{manual['id']}/close"), {}, format="json").json()["status"] == "已闭环"

    # 删除改为填理由作废：不计入统计，筛选可见（AC-F08-07）
    assert member.post(iurl(project, f"/{late['id']}/void"), {"reason": "重复"}, format="json").status_code == 403
    assert pm.delete(iurl(project, f"/{late['id']}")).status_code == 405
    r = owner.post(iurl(project, f"/{late['id']}/void"), {"reason": ""}, format="json")
    assert r.status_code == 400 and r.json()["message"] == "请填写作废理由"
    r = owner.post(iurl(project, f"/{late['id']}/void"), {"reason": "与 WT-001 重复登记"}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "已作废" and r.json()["voidReason"] == "与 WT-001 重复登记"
    assert Issue.objects.filter(pk=late["id"]).exists()
    lst = pm.get(iurl(project)).json()
    assert late["code"] not in [x["code"] for x in lst["items"]]
    assert lst["counts"] == {"open": 1, "overdue": 1, "closed": 1}
    assert [x["code"] for x in pm.get(iurl(project), {"status": "已作废"}).json()["items"]] == [late["code"]]
    assert owner.post(iurl(project, f"/{late['id']}/void"), {"reason": "再次作废"}, format="json").status_code == 409
    # 来源筛选
    assert [x["code"] for x in pm.get(iurl(project), {"source": "check"}).json()["items"]] == [issue.code]
    assert ledger.verify(project.id)["ok"] is True
