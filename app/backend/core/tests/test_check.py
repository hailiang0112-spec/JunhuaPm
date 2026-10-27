"""F06 检查点、对图核对与放行：FLOW-09、FLOW-10、FLOW-11（API 集成测试）。

前置数据（图纸、基线、变更单）直接用模型构造；超时通过把 awaiting_release_since 往前拨模拟时间推进。
"""
import datetime
import io

import pytest
from django.utils import timezone
from PIL import Image

from core.models import (Baseline, BaselineEvent, ChangeOrder, Checkpoint, CheckPhoto, CheckRecord, CoverEvent,
                         DiscoveryCorrection, DrawingSet, DrawingSignoff, DrawingVersion, Issue, LedgerEntry,
                         ProjectMemberRole, ReleaseRecord, WorkItem)
from core.services import ledger, storage


def _png(color):
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), color).save(buf, "PNG")
    buf.seek(0)
    buf.name = "现场照片.png"
    return buf


@pytest.fixture
def ev(project, users):
    """二楼书房 B「墙内线管预埋」：水电点位图 V1 已签认，基线已签认。"""
    pm = users["design_manager"]
    f1 = storage.save_bytes(b"%PDF-1.4 sd-v1", "水电点位图V1.pdf", pm, project)
    ds = DrawingSet.objects.create(project=project, name="水电点位图")
    v1 = DrawingVersion.objects.create(project=project, drawing_set=ds, version_no=1, file=f1, change_note="首版",
                                       created_by=pm)
    DrawingSignoff.objects.create(project=project, version=v1, signer=users["owner"], file_sha256=f1.sha256)
    ds.current_signed_version = v1
    ds.save()
    floor = project.floors.get(name="二楼")
    wis = list(WorkItem.objects.filter(project=project, floor=floor)[:4])
    for wi in wis:
        wi.drawing_version = v1
        wi.qc_user = users["qc"]
        wi.save()
    for wi, st in zip(wis, ["已签认", "待签认", "草稿"]):
        Baseline.objects.update_or_create(work_item=wi, defaults={"project": project, "status": st})
    signed = Baseline.objects.get(work_item=wis[0])
    return {"ds": ds, "v1": v1, "wi": wis[0], "wi_pending": wis[1], "wi_draft": wis[2], "baseline": signed}


def url(project, tail):
    return f"/api/projects/{project.id}/{tail}"


def make_cp(client, project, wi, point="墙内线管预埋走向", concealed=True, x=0.925, y=0.75):
    r = client.post(url(project, f"work-items/{wi.id}/checkpoints"),
                    {"point": point, "isConcealed": concealed, "x": x, "y": y, "pageNo": 1}, format="json")
    assert r.status_code == 201, r.json()
    return r.json()


def upload(client, project, color="red"):
    r = client.post(url(project, "files"), {"file": _png(color)}, format="multipart")
    assert r.status_code == 201, r.json()
    return r.json()["id"]


def check(client, project, cp_id, conclusion, covered=False, photos=None, **extra):
    if photos is None:
        photos = [{"fileId": upload(client, project)}]
    body = {"conclusion": conclusion, "wasCovered": covered, "photos": photos, **extra}
    return client.post(url(project, f"checkpoints/{cp_id}/checks"), body, format="json")


# ---------------------------------------------------------------- FLOW-09
def test_flow09_create_checkpoint_on_signed_baseline(client_for, project, ev):
    qc = client_for("qc")
    before_chain = LedgerEntry.objects.filter(project=project).count()
    cp = make_cp(qc, project, ev["wi"])
    assert cp["code"] == "CK-001" and cp["isDraft"] is False and cp["status"] == "未核对"
    assert cp["drawingVersionId"] == ev["v1"].id and (cp["x"], cp["y"], cp["pageNo"]) == (0.925, 0.75, 1)
    assert cp["labels"] == ["不得覆盖"]
    # 基线签认状态不变；追加 checkpoint_added 留痕并入链（给业主的知会待办由待办模块从该事件派生）
    assert Baseline.objects.get(pk=ev["baseline"].pk).status == "已签认"
    e = BaselineEvent.objects.get(baseline=ev["baseline"], kind="checkpoint_added")
    assert e.checkpoint_id == cp["id"] and e.actor.name == "王工"
    assert LedgerEntry.objects.filter(project=project, record_type="core_baselineevent", record_id=e.id).exists()
    assert LedgerEntry.objects.filter(project=project).count() == before_chain + 1
    # 编号项目内递增；工作项检查点列表含钉点
    cp2 = make_cp(client_for("pm"), project, ev["wi"], point="插座底盒中心距地 300mm")
    assert cp2["code"] == "CK-002"
    items = qc.get(url(project, f"work-items/{ev['wi'].id}/checkpoints")).json()["items"]
    assert [i["code"] for i in items] == ["CK-001", "CK-002"] and items[0]["x"] == 0.925
    # 待签认 → 409；草稿 → 编辑稿；坐标越界 → 400；业主方成员无权新建
    r = qc.post(url(project, f"work-items/{ev['wi_pending'].id}/checkpoints"),
                {"point": "门洞净宽 900mm", "isConcealed": False, "x": 0.5, "y": 0.5}, format="json")
    assert r.status_code == 409 and r.json()["message"] == "基线待业主签认，需业主退回后才能修改"
    d = make_cp(qc, project, ev["wi_draft"], point="给水管走向")
    assert d["isDraft"] is True and not BaselineEvent.objects.filter(checkpoint_id=d["id"]).exists()
    r = qc.post(url(project, f"work-items/{ev['wi'].id}/checkpoints"), {"point": "过梁", "x": 1.2, "y": 0.5}, format="json")
    assert r.status_code == 400
    r = client_for("owner_member").post(url(project, f"work-items/{ev['wi'].id}/checkpoints"),
                                        {"point": "过梁", "x": 0.2, "y": 0.5}, format="json")
    assert r.status_code == 403
    # 已有检查点没有修改 / 删除接口
    assert qc.patch(url(project, f"checkpoints/{cp['id']}"), {"point": "改"}, format="json").status_code == 405
    assert qc.delete(url(project, f"checkpoints/{cp['id']}")).status_code == 405


def test_flow09_check_photos_record_changed_and_recheck(client_for, project, ev, users):
    qc = client_for("qc")
    cp = make_cp(qc, project, ev["wi"])
    # 不上传照片提交 → 拒绝，不生成记录
    r = check(qc, project, cp["id"], "一致", photos=[])
    assert r.status_code == 400 and r.json()["message"] == "至少上传 1 张现场照片"
    assert not CheckRecord.objects.filter(checkpoint_id=cp["id"]).exists()
    # 2 张照片：第 1 张上传成功；第 2 张「失败」后单张重传成功（失败的那次没有文件 ID，不能引用）
    p1 = upload(qc, project, "red")
    r = check(qc, project, cp["id"], "一致", photos=[{"fileId": p1}, {"fileId": 999999}])
    assert r.status_code == 400 and not CheckRecord.objects.filter(checkpoint_id=cp["id"]).exists()
    p2 = upload(qc, project, "blue")
    r = check(qc, project, cp["id"], "一致", photos=[{"fileId": p1, "x": 0.9, "y": 0.7}, {"fileId": p2}])
    assert r.status_code == 201, r.json()
    rec = r.json()["check"]
    assert rec["no"] == 1 and rec["conclusion"] == "一致" and rec["checker"]["name"] == "王工"
    assert rec["drawingVersionId"] == ev["v1"].id and rec["drawingLabel"] == "水电点位图 V1"
    assert rec["wasCovered"] is False and rec["wasLatestSigned"] is True and rec["checkedAt"].endswith("+08:00")
    assert [(p["pinX"], p["pinY"]) for p in rec["photos"]] == [(0.9, 0.7), (0.925, 0.75)]
    assert r.json()["status"] == "待放行"
    ck = CheckRecord.objects.get(pk=rec["id"])
    assert LedgerEntry.objects.filter(record_type="core_checkrecord", record_id=ck.id).exists()
    assert LedgerEntry.objects.filter(record_type="core_checkphoto").count() == 2
    assert CheckPhoto.objects.filter(check_record=ck).count() == 2
    # 核对记录不可修改
    assert qc.put(url(project, f"checkpoints/{cp['id']}/checks"), {}, format="json").status_code == 405
    # 「已变更」不关联 / 关联未生效变更单 → 422
    cp2 = make_cp(qc, project, ev["wi"], point="插座底盒中心距地 300mm")
    r = check(qc, project, cp2["id"], "已变更")
    assert r.status_code == 422 and r.json()["message"] == "请关联已生效的变更单"
    pending = ChangeOrder.objects.create(project=project, seq_no=3, title="烟道洞口位置调整", status="待业主签认",
                                         created_by=users["pm"])
    r = check(qc, project, cp2["id"], "已变更", changeOrderId=pending.id)
    assert r.status_code == 422 and r.json()["message"] == "请关联已生效的变更单"
    done = ChangeOrder.objects.create(project=project, seq_no=1, title="二楼书房 B 新增 2 个五孔插座", status="已生效",
                                      created_by=users["pm"])
    r = check(qc, project, cp2["id"], "已变更", changeOrderId=done.id)
    assert r.status_code == 201 and r.json()["check"]["changeOrder"]["code"] == "BG-001"
    # 非质检不能核对
    assert check(client_for("pm"), project, cp2["id"], "一致", photos=[{"fileId": p1}]).status_code == 403
    # 复核：追加新记录，当前结论取最新，旧记录可查
    r = check(qc, project, cp["id"], "不一致", note="线管距门洞边仅 80mm")
    assert r.status_code == 201 and r.json()["check"]["no"] == 2
    det = qc.get(url(project, f"checkpoints/{cp['id']}")).json()
    assert det["latestCheck"]["no"] == 2 and det["latestCheck"]["conclusion"] == "不一致"
    assert [c["no"] for c in det["checks"]] == [2, 1] and det["checks"][1]["conclusion"] == "一致"
    assert det["status"] == "不一致" and det["nextCheckNo"] == 3


def test_flow09_was_latest_signed_after_new_version(client_for, project, ev, users):
    """新版签认后基线待重签：核对仍用原签认版，记录「当时不是最新签认版」。"""
    qc = client_for("qc")
    cp = make_cp(qc, project, ev["wi"])
    f2 = storage.save_bytes(b"%PDF-1.4 sd-v2", "水电点位图V2.pdf", users["design_manager"], project)
    v2 = DrawingVersion.objects.create(project=project, drawing_set=ev["ds"], version_no=2, file=f2, change_note="插座上移",
                                       created_by=users["design_manager"])
    DrawingSignoff.objects.create(project=project, version=v2, signer=users["owner"], file_sha256=f2.sha256)
    DrawingSet.objects.filter(pk=ev["ds"].pk).update(current_signed_version=v2)
    Baseline.objects.filter(pk=ev["baseline"].pk).update(status="待重签")
    det = qc.get(url(project, f"checkpoints/{cp['id']}")).json()
    assert det["baseDrawing"]["id"] == ev["v1"].id and det["resign"]["newLabel"] == "水电点位图 V2"
    rec = check(qc, project, cp["id"], "一致").json()["check"]
    assert rec["drawingVersionId"] == ev["v1"].id and rec["wasLatestSigned"] is False
    # 待重签期间新增检查点直接生效
    cp2 = make_cp(qc, project, ev["wi"], point="开关面板高度")
    assert cp2["isDraft"] is False and Baseline.objects.get(pk=ev["baseline"].pk).status == "待重签"


# ---------------------------------------------------------------- FLOW-10
def test_flow10_release_rules(client_for, project, ev, users):
    qc = client_for("qc")
    ck012 = make_cp(qc, project, ev["wi"], point="管道井封堵")
    ck031 = make_cp(qc, project, ev["wi"], point="门洞净宽 900mm", concealed=False)
    todo = make_cp(qc, project, ev["wi"], point="强电底盒高度")
    assert check(qc, project, ck012["id"], "一致").status_code == 201
    assert check(qc, project, ck031["id"], "不一致", note="实测 860mm").status_code == 201
    # 业主方成员（钱工）指定为代理人
    ProjectMemberRole.objects.create(project=project, user=users["owner_member"], role="owner_agent", granted_by=users["owner"])
    rel = lambda who, cid: client_for(who).post(url(project, f"checkpoints/{cid}/release"), {},  # noqa: E731
                                                format="json", HTTP_IDEMPOTENCY_KEY=f"k-{who}-{cid}")
    # 非业主方被拒
    for who in ("pm", "design_manager", "qc", "budget", "admin"):
        r = rel(who, ck012["id"])
        assert r.status_code == 403 and r.json()["message"] == "只有业主或业主代理人可以放行", who
    # 业主放行
    r = rel("owner", ck012["id"])
    assert r.status_code == 200 and r.json()["status"] == "已放行"
    rr = ReleaseRecord.objects.get(checkpoint_id=ck012["id"])
    basis = CheckRecord.objects.get(checkpoint_id=ck012["id"])
    assert rr.releaser.name == "刘先生" and rr.is_proxy is False and rr.basis_check_id == basis.id
    assert LedgerEntry.objects.filter(record_type="core_releaserecord", record_id=rr.id).exists()
    det = client_for("owner").get(url(project, f"checkpoints/{ck012['id']}")).json()
    assert det["seal"] == "已放行" and det["sealKind"] == "pass" and det["releases"][0]["basisNo"] == 1
    # 代理人再次放行：不新增记录，提示谁何时已放行
    r = rel("owner_member", ck012["id"])
    assert r.status_code == 409 and r.json()["code"] == "ALREADY_RELEASED"
    assert r.json()["message"].startswith("已由刘先生于 ") and "放行" in r.json()["message"]
    assert ReleaseRecord.objects.filter(checkpoint_id=ck012["id"]).count() == 1
    # 不一致与未核对被拒并说明原因
    r = rel("owner", ck031["id"])
    assert r.status_code == 422 and r.json()["code"] == "CANNOT_RELEASE" and "当前结论为「不一致」" in r.json()["message"]
    r = rel("owner", todo["id"])
    assert r.status_code == 422 and "尚未核对" in r.json()["message"]
    assert not ReleaseRecord.objects.filter(checkpoint_id__in=[ck031["id"], todo["id"]]).exists()
    # 代理放行标注 is_proxy；撤销代理后被拒，原记录不变
    proxy_cp = make_cp(qc, project, ev["wi"], point="床头插座点位")
    check(qc, project, proxy_cp["id"], "一致")
    assert rel("owner_member", proxy_cp["id"]).status_code == 200
    assert ReleaseRecord.objects.get(checkpoint_id=proxy_cp["id"]).is_proxy is True
    det = client_for("owner").get(url(project, f"checkpoints/{proxy_cp['id']}")).json()
    assert det["seal"] == "代理放行" and det["releases"][0]["isProxy"] is True
    ProjectMemberRole.objects.filter(project=project, role="owner_agent").delete()
    again = make_cp(qc, project, ev["wi"], point="砌体顶部斜砌")
    check(qc, project, again["id"], "一致")
    assert rel("owner_member", again["id"]).status_code == 403
    assert ReleaseRecord.objects.get(checkpoint_id=proxy_cp["id"]).is_proxy is True
    # 已放行的 CK-012 追加「不一致」→ 放行后发现不一致，原放行记录保留，自动生成问题
    r = check(qc, project, ck012["id"], "不一致", note="封堵不密实")
    assert r.status_code == 201 and r.json()["status"] == "放行后发现不一致"
    assert ReleaseRecord.objects.filter(checkpoint_id=ck012["id"]).count() == 1
    issue = Issue.objects.get(source_check_id=r.json()["check"]["id"])
    assert issue.status == "未闭环" and issue.checkpoint_id == ck012["id"] and issue.work_item_id == ev["wi"].id
    assert issue.floor.name == "二楼"
    # 再次放行依据新的核对：复核一致后可再放行，唯一约束按 (检查点, 依据核对) 计
    check(qc, project, ck012["id"], "一致")
    assert rel("owner", ck012["id"]).status_code == 200
    assert ReleaseRecord.objects.filter(checkpoint_id=ck012["id"]).count() == 2
    assert ledger.verify(project.id)["ok"]


# ---------------------------------------------------------------- FLOW-11
def test_flow11_timeout_nocover_cover_discovery(client_for, project, ev, users):
    qc, pm = client_for("qc"), client_for("pm")
    late = make_cp(qc, project, ev["wi"], point="墙内线管预埋走向")
    fresh = make_cp(qc, project, ev["wi"], point="新砌墙体垂直度", concealed=False)
    early = make_cp(qc, project, ev["wi"], point="隔墙底部防潮层")
    nocover = make_cp(qc, project, ev["wi"], point="隔墙拉结筋间距")
    check(qc, project, late["id"], "一致")
    check(qc, project, fresh["id"], "一致")
    Checkpoint.objects.filter(pk=late["id"]).update(awaiting_release_since=timezone.now() - datetime.timedelta(hours=25))
    Checkpoint.objects.filter(pk=fresh["id"]).update(awaiting_release_since=timezone.now() - datetime.timedelta(hours=5))
    lst = client_for("owner").get(url(project, "checkpoints")).json()
    by = {i["code"]: i for i in lst["items"]}
    assert "超时" in by[late["code"]]["labels"] and by[late["code"]]["status"] == "待放行"
    assert by[late["code"]]["seal"] == "超时" and "已等 25 小时（时限 24 小时）" in by[late["code"]]["situation"]
    assert "超时" not in by[fresh["code"]]["labels"] and by[fresh["code"]]["seal"] == "待放行"
    assert by[nocover["code"]]["seal"] == "不得覆盖" and by[nocover["code"]]["sealKind"] == "stop"
    assert lst["counts"]["超时"] == 1 and lst["summary"]["timeout"] == 1
    assert lst["items"][0]["code"] == late["code"]  # 紧急程度排序：超时在不得覆盖、待放行之前
    t = client_for("owner").get(url(project, "checkpoints"), {"status": "超时"}).json()
    assert [i["code"] for i in t["items"]] == [late["code"]]
    # 时限改为 12（项目经理）后，5 小时的仍不超时；预算专员改时限被拒
    assert pm.put(url(project, "settings"), {"releaseTimeoutHours": 4}, format="json").status_code == 200
    by = {i["code"]: i for i in pm.get(url(project, "checkpoints")).json()["items"]}
    assert "超时" in by[fresh["code"]]["labels"]
    assert pm.put(url(project, "settings"), {"releaseTimeoutHours": 12}, format="json").status_code == 200
    assert client_for("budget").put(url(project, "settings"), {"releaseTimeoutHours": 6}, format="json").status_code == 403
    # 项目经理标记未放行隐蔽检查点已覆盖 → 未放行先覆盖事件
    assert client_for("qc").post(url(project, f"checkpoints/{early['id']}/cover")).status_code == 403
    r = pm.post(url(project, f"checkpoints/{early['id']}/cover"))
    assert r.status_code == 201 and r.json()["coverEvent"]["wasUnreleased"] is True
    ce = CoverEvent.objects.get(checkpoint_id=early["id"])
    assert ce.source == "pm_mark" and ce.recorder.name == "张工"
    assert LedgerEntry.objects.filter(record_type="core_coverevent", record_id=ce.id).exists()
    assert pm.post(url(project, f"checkpoints/{early['id']}/cover")).status_code == 409
    item = [i for i in pm.get(url(project, "checkpoints"), {"status": "未放行先覆盖"}).json()["items"]]
    assert [i["code"] for i in item] == [early["code"]] and item[0]["seal"] == "未放行先覆盖"
    assert "未放行先覆盖" in item[0]["labels"]
    # 发现时点：未覆盖 → 覆盖前；已覆盖 → 覆盖后；交房日后 → 交房后
    r1 = check(qc, project, nocover["id"], "不一致")
    assert r1.json()["check"]["discoveryPhase"] == "覆盖前"
    r2 = check(qc, project, early["id"], "不一致", covered=True)
    assert r2.json()["check"]["discoveryPhase"] == "覆盖后"
    project.actual_handover = timezone.localdate() - datetime.timedelta(days=1)
    project.save()
    after = make_cp(qc, project, ev["wi"], point="空调预留孔")
    r3 = check(qc, project, after["id"], "不一致")
    assert r3.json()["check"]["discoveryPhase"] == "交房后"
    assert Issue.objects.filter(checkpoint_id__in=[nocover["id"], early["id"], after["id"]], status="未闭环").count() == 3
    # 修正发现时点：缺理由被拒；修正保存前后值、修正人、时间与理由
    cid = r1.json()["check"]["id"]
    r = qc.post(url(project, f"checks/{cid}/discovery-corrections"), {"after": "覆盖后", "reason": ""}, format="json")
    assert r.status_code == 400 and r.json()["message"] == "请填写修正理由"
    assert client_for("owner").post(url(project, f"checks/{cid}/discovery-corrections"),
                                    {"after": "覆盖后", "reason": "x"}, format="json").status_code == 403
    r = qc.post(url(project, f"checks/{cid}/discovery-corrections"),
                {"after": "覆盖后", "reason": "现场复看发现东墙已先行抹灰，核对时实际已被覆盖"}, format="json")
    assert r.status_code == 201
    dc = DiscoveryCorrection.objects.get(check_record_id=cid)
    assert (dc.before, dc.after, dc.actor.name) == ("覆盖前", "覆盖后", "王工") and dc.at is not None
    assert LedgerEntry.objects.filter(record_type="core_discoverycorrection", record_id=dc.id).exists()
    det = qc.get(url(project, f"checkpoints/{nocover['id']}")).json()
    assert det["checks"][0]["discoveryPhase"] == "覆盖后" and det["checks"][0]["inferredDiscoveryPhase"] == "覆盖前"
    assert det["checks"][0]["corrections"][0]["reason"].startswith("现场复看")
    assert ledger.verify(project.id)["ok"]


def test_flow11_qc_covered_check_records_unreleased_cover(client_for, project, ev):
    """质检核对时选「已被覆盖」且此前未放行 → 未放行先覆盖事件；覆盖时间取较早值。"""
    qc = client_for("qc")
    cp = make_cp(qc, project, ev["wi"], point="给水管走向")
    r = check(qc, project, cp["id"], "一致", covered=True)
    assert r.status_code == 201
    ce = CoverEvent.objects.get(checkpoint_id=cp["id"])
    assert ce.source == "qc_check" and ce.was_unreleased is True
    c = Checkpoint.objects.get(pk=cp["id"])
    assert c.unreleased_cover and c.covered_at == ce.at
    first = c.covered_at
    check(qc, project, cp["id"], "一致", covered=True)
    assert Checkpoint.objects.get(pk=cp["id"]).covered_at == first and CoverEvent.objects.filter(checkpoint_id=cp["id"]).count() == 1
    r = client_for("pm").post(url(project, f"checkpoints/{cp['id']}/cover"))
    assert r.status_code == 409 and r.json()["message"].startswith("已由王工于 ")


def test_list_filters_and_isolation(client_for, project, ev):
    qc = client_for("qc")
    make_cp(qc, project, ev["wi"])
    lst = qc.get(url(project, "checkpoints"), {"floor": ev["wi"].floor_id, "phase": ev["wi"].phase_id}).json()
    assert lst["total"] == 1 and lst["counts"]["不得覆盖"] == 1 and lst["items"][0]["floorName"] == "二楼"
    other = qc.get(url(project, "checkpoints"), {"floor": project.floors.get(name="一楼").id}).json()
    assert other["total"] == 0 and other["counts"]["全部"] == 0
    assert client_for("outsider").get(url(project, "checkpoints")).status_code == 403
