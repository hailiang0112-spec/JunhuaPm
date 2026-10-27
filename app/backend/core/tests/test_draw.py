"""图纸版本、基线签认、工作项资料（FLOW-06、FLOW-07、FLOW-08、FLOW-17 工作项资料部分）。"""
import datetime
import hashlib
import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from core.models import (AuditLog, Baseline, BaselineEvent, BaselineSignoff, CheckPhoto, Checkpoint, CheckRecord,
                         DrawingSignoff, DrawingVersion, LedgerEntry, StoredFile, WorkItem)


def plan_pdf(label):
    """简化的「二楼水电点位图」：Pillow 画线稿后存为 PDF。"""
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (800, 520), "white")
    g = ImageDraw.Draw(im)
    g.rectangle((40, 40, 760, 480), outline="black", width=6)
    g.line((380, 40, 380, 240), fill="black", width=3)
    g.line((40, 240, 760, 240), fill="black", width=3)
    g.text((60, 490), label, fill="black")
    buf = io.BytesIO()
    im.save(buf, "PDF", resolution=100)
    return buf.getvalue()


def png_bytes(color):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), color).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture(autouse=True)
def file_root(settings, tmp_path):
    settings.FILE_ROOT = tmp_path


@pytest.fixture
def P(project):
    return f"/api/projects/{project.id}"


def upload_version(client, P, set_id, pdf, note="", wids=(), cad=None):
    data = {"changeNote": note, "affectedWorkItemIds": ",".join(str(w) for w in wids)}
    if pdf is not None:
        data["file"] = SimpleUploadedFile("二楼水电点位图.pdf", pdf, content_type="application/pdf")
    if cad is not None:
        data["cadFile"] = SimpleUploadedFile("二楼水电点位图.dwg", cad, content_type="application/octet-stream")
    return client.post(f"{P}/drawing-sets/{set_id}/versions", data, format="multipart")


@pytest.fixture
def water_set(client_for, P):
    """「水电点位图」分册，V1 已由刘先生签认。"""
    dm = client_for("design_manager")
    s = dm.post(f"{P}/drawing-sets", {"name": "水电点位图"}, format="json").json()
    v1 = upload_version(dm, P, s["id"], plan_pdf("V1"))
    assert v1.status_code == 201, v1.json()
    r = client_for("owner").post(f"{P}/drawing-versions/{v1.json()['id']}/sign", {}, format="json")
    assert r.status_code == 200
    return {"id": s["id"], "v1": v1.json()["id"]}


def make_item(project, users, name, phase_code="p1", floor="f2", room=None, finish=None, dv=None, fill=True):
    phase = project.phases.get(code=phase_code)
    fl = project.floors.get(code=floor)
    rm = project.rooms.filter(floor=fl, name=room).first() if room else None
    wi = WorkItem.objects.create(project=project, phase=phase, floor=fl, room=rm, name=name, weight=2)
    Baseline.objects.create(project=project, work_item=wi)
    if fill:
        wi.description = "随砌筑在东墙与南墙预埋 PVC 线管及 4 个插座底盒"
        wi.acceptance_criteria = "管中距门洞边 ≥ 150mm；底盒中心距地 300mm，偏差 ±5mm"
        wi.cost = 1280
        wi.planned_finish = finish or datetime.date(2026, 11, 3)
        wi.qc_user = users["qc"]
        wi.drawing_version_id = dv
        wi.save()
    return wi


_ck = {"n": 0}


def add_checkpoint(project, users, wi, dv_id, point="墙内线管预埋走向", draft=True):
    _ck["n"] += 1
    return Checkpoint.objects.create(project=project, work_item=wi, code=f"CK-{_ck['n'] + 100:03d}", point=point,
                                     is_concealed=True, drawing_version_id=dv_id, x=0.82, y=0.85,
                                     created_by=users["pm"], is_draft=draft)


def sign_baseline(client_for, P, wi):
    r = client_for("pm").post(f"{P}/work-items/{wi.id}/baseline/submit", {}, format="json")
    assert r.status_code == 201, r.json()
    s = client_for("owner").post(f"{P}/baselines/sign", {"revisionIds": [r.json()["revisionId"]]}, format="json")
    assert s.status_code == 200, s.json()
    return r.json()["revisionId"]


# ───────────── FLOW-06 图纸版本 ─────────────

@pytest.mark.django_db
def test_flow06_drawing_versions(project, users, client_for, P, water_set):
    dm, owner = client_for("design_manager"), client_for("owner")
    sid, v1 = water_set["id"], water_set["v1"]
    items = [make_item(project, users, f"二楼受影响工作项 {i + 1}", dv=v1) for i in range(12)]
    for wi in items[:3]:
        add_checkpoint(project, users, wi, v1)
        sign_baseline(client_for, P, wi)

    # 只有 CAD
    r = upload_version(dm, P, sid, None, note="改了插座", cad=b"AC1027 fake dwg")
    assert r.status_code == 400 and r.json()["message"] == "请同时上传 PDF 或图片版，CAD 仅作为附件"
    # 第 2 版不写改动说明
    r = upload_version(dm, P, sid, plan_pdf("V2"))
    assert r.status_code == 400 and r.json()["message"] == "请说明本版改了什么"
    # 非设计经理不能上传
    assert upload_version(client_for("qc"), P, sid, plan_pdf("V2"), note="x").status_code == 403
    assert DrawingVersion.objects.filter(drawing_set_id=sid).count() == 1

    pdf2 = plan_pdf("V2")
    r = upload_version(dm, P, sid, pdf2, note="二楼书房 B 南墙新增 2 个五孔插座", wids=[w.id for w in items],
                       cad=b"AC1027 fake dwg")
    assert r.status_code == 201, r.json()
    v2 = r.json()
    assert v2["versionNo"] == 2 and v2["status"] == "待业主签认" and v2["affectedCount"] == 12
    assert v2["affectedSignedCount"] == 3 and v2["cadFile"]["name"] == "二楼水电点位图.dwg"
    assert len(v2["pages"]) == 1 and v2["pages"][0]["width"] > 0
    img = dm.get(v2["pages"][0]["imageUrl"])
    assert img.status_code == 200 and img.content[:8] == b"\x89PNG\r\n\x1a\n"
    old = owner.get(f"{P}/drawing-versions/{v1}").json()
    assert old["status"] == "已签认" and old["isCurrentSigned"] is True
    assert LedgerEntry.objects.filter(record_type="core_drawingversion", record_id=v2["id"]).exists()

    # 已发布版本不可删除或替换（含公司管理员）
    for who in ("admin", "design_manager", "pm", "owner"):
        c = client_for(who)
        assert c.delete(f"{P}/drawing-versions/{v1}").status_code == 405
        r = c.put(f"{P}/drawing-versions/{v1}", {"changeNote": "改写"}, format="json")
        assert r.status_code == 405 and r.json()["code"] == "KEY_RECORD_IMMUTABLE"
        assert c.patch(f"{P}/drawing-versions/{v1}", {"changeNote": "改写"}, format="json").status_code == 405
    assert DrawingVersion.objects.get(pk=v1).change_note == ""

    # 签认权限：业主方成员、公司管理员、设计经理都不能签
    for who in ("owner_member", "admin", "design_manager"):
        assert client_for(who).post(f"{P}/drawing-versions/{v2['id']}/sign", {}, format="json").status_code == 403

    r = owner.post(f"{P}/drawing-versions/{v2['id']}/sign", {}, format="json")
    assert r.status_code == 200 and r.json()["resignCount"] == 3
    so = DrawingSignoff.objects.get(version_id=v2["id"])
    assert so.signer.name == "刘先生" and so.file_sha256 == hashlib.sha256(pdf2).hexdigest()
    assert LedgerEntry.objects.filter(record_type="core_drawingsignoff", record_id=so.id).exists()
    sets = owner.get(f"{P}/drawing-sets").json()["items"]
    cur = sets[0]["currentSignedVersion"]
    assert cur["versionNo"] == 2 and cur["signedBy"] == "刘先生" and cur["signSha256"] == so.file_sha256
    statuses = {w.id: Baseline.objects.get(work_item=w).status for w in items}
    assert [statuses[w.id] for w in items[:3]] == ["待重签"] * 3
    assert set(statuses[w.id] for w in items[3:]) == {"草稿"}
    assert BaselineEvent.objects.filter(kind="resign_required", drawing_version_id=v2["id"]).count() == 3

    # 另一位业主重复签认：409，带签认人
    r = client_for("owner2").post(f"{P}/drawing-versions/{v2['id']}/sign", {}, format="json")
    assert r.status_code == 409 and r.json()["message"].startswith("已由刘先生于")
    assert DrawingSignoff.objects.filter(version_id=v2["id"]).count() == 1

    # 两版对比：并排两版 + 期间改动说明
    r = owner.get(f"{P}/drawing-sets/{sid}/compare?from={v1}&to={v2['id']}").json()
    assert r["range"] == "V1 → V2 · 共 1 版"
    assert [n["changeNote"] for n in r["notes"]] == ["二楼书房 B 南墙新增 2 个五孔插座"]
    assert r["left"]["pages"] and r["right"]["pages"]
    assert owner.get(f"{P}/drawing-sets/{sid}/compare?from={v1}&to={v1}").json()["message"] == "请选择两个不同的版本"

    # 现场打开受影响工作项：基线引用版本 V1 + 待重签提示所需数据
    d = client_for("qc").get(f"{P}/work-items/{items[0].id}/detail").json()
    assert d["baseline"]["status"] == "待重签"
    assert d["baseline"]["baseDrawingVersion"]["versionNo"] == 1
    assert d["baseline"]["resign"]["newVersion"]["versionNo"] == 2


@pytest.mark.django_db
def test_flow06_image_drawing_and_bad_format(project, users, client_for, P, water_set):
    dm = client_for("design_manager")
    r = dm.post(f"{P}/drawing-sets/{water_set['id']}/versions",
                {"file": SimpleUploadedFile("点位.docx", b"x"), "changeNote": "说明"}, format="multipart")
    assert r.status_code == 400 and r.json()["message"] == "点位.docx：格式不支持，仅支持 PDF、JPG、PNG"
    r = dm.post(f"{P}/drawing-sets/{water_set['id']}/versions",
                {"file": SimpleUploadedFile("点位.png", png_bytes("white"), content_type="image/png"),
                 "changeNote": "改为图片版"}, format="multipart")
    assert r.status_code == 201 and r.json()["pages"][0]["width"] == 64
    assert dm.post(f"{P}/drawing-sets", {"name": "水电点位图"}, format="json").status_code == 409


# ───────────── FLOW-07 提交与签认 ─────────────

@pytest.mark.django_db
def test_flow07_submit_sign_return(project, users, client_for, P, water_set):
    pm, owner = client_for("pm"), client_for("owner")
    v1 = water_set["v1"]
    dm = client_for("design_manager")
    v_pending = upload_version(dm, P, water_set["id"], plan_pdf("V2"), note="三楼主卧床头插座下移 150mm").json()["id"]

    # 缺费用和质检人：一次列出全部缺失
    a = make_item(project, users, "三楼主卧隔墙砌筑", floor="f3", dv=v1)
    a.cost = None
    a.qc_user = None
    a.save()
    add_checkpoint(project, users, a, v1, "拉结筋间距与伸入长度")
    r = pm.post(f"{P}/work-items/{a.id}/baseline/submit", {}, format="json")
    assert r.status_code == 400
    assert {f["field"] for f in r.json()["fields"]} == {"cost", "qcUserId"}
    assert r.json()["message"] == "以下字段缺失，无法提交：费用（元）、质检人"
    # 全空：7 项全部列出
    empty = make_item(project, users, "三楼次卧隔墙砌筑", floor="f3", fill=False)
    r = pm.post(f"{P}/work-items/{empty.id}/baseline/submit", {}, format="json")
    assert len(r.json()["fields"]) == 7

    # 选了待业主签认的版本
    b = make_item(project, users, "三楼卫生间防水反坎浇筑", floor="f3", dv=v_pending)
    add_checkpoint(project, users, b, v1)
    r = pm.post(f"{P}/work-items/{b.id}/baseline/submit", {}, format="json")
    assert r.status_code == 422 and r.json()["message"] == "该版本尚未签认"
    assert Baseline.objects.get(work_item=b).status == "草稿"

    # 两条完整基线（砌墙工段）；提交时可直接带字段
    c = make_item(project, users, "二楼书房 B 隔墙砌筑", dv=v1)
    d = make_item(project, users, "二楼卧室 B 隔墙砌筑", dv=v1)
    ck_c = add_checkpoint(project, users, c, v1, "门洞位置与净宽")
    add_checkpoint(project, users, d, v1, "拉结筋间距")
    rc = pm.post(f"{P}/work-items/{c.id}/baseline/submit", {"cost": "4980", "qcUserId": users["qc"].id}, format="json")
    rd = pm.post(f"{P}/work-items/{d.id}/baseline/submit", {}, format="json")
    assert rc.status_code == 201 and rd.status_code == 201
    assert rc.json()["status"] == "待签认" and rc.json()["content"]["cost"] == "4980.00"
    ck_c.refresh_from_db()
    assert ck_c.is_draft is False  # 草稿检查点随提交生效
    # 预算专员、质检不能提交
    assert client_for("budget").post(f"{P}/work-items/{a.id}/baseline/submit", {}, format="json").status_code == 403

    # 待签认期间修改被拒
    r = pm.post(f"{P}/work-items/{c.id}/baseline/submit", {"cost": "5000"}, format="json")
    assert r.status_code == 409 and r.json()["message"] == "基线待业主签认，需业主退回后才能修改"
    assert WorkItem.objects.get(pk=c.id).cost == 4980

    # 待签列表按工段分组，含完整内容
    pend = owner.get(f"{P}/baselines/pending?group=phase").json()
    g = next(x for x in pend["groups"] if x["name"] == "砌墙")
    it = next(x for x in g["items"] if x["workItemId"] == c.id)
    assert it["drawing"] == "水电点位图 V1" and it["qcUserName"] == "王工" and it["cost"] == "4980.00"
    assert it["description"] and it["acceptanceCriteria"] and it["checkpoints"][0]["point"] == "门洞位置与净宽"
    assert {x["name"] for x in owner.get(f"{P}/baselines/pending?group=floor").json()["groups"]} == {"二楼"}

    # 批量签认 2 条：2 条独立签认记录，各带签认人、时间、完整快照
    revs = [rc.json()["revisionId"], rd.json()["revisionId"]]
    for who in ("owner_member", "admin", "pm"):
        assert client_for(who).post(f"{P}/baselines/sign", {"revisionIds": revs}, format="json").status_code == 403
    r = owner.post(f"{P}/baselines/sign", {"revisionIds": revs}, format="json")
    assert r.status_code == 200 and r.json()["count"] == 2
    sos = BaselineSignoff.objects.filter(revision_id__in=revs).order_by("id")
    assert len(sos) == 2 and {s.signer.name for s in sos} == {"刘先生"} and all(s.signed_at for s in sos)
    snap = sos[0].content_snapshot
    assert snap["description"] and snap["acceptanceCriteria"] and snap["qcUserName"] == "王工"
    assert snap["drawingVersionNo"] == 1 and snap["checkpoints"]
    assert LedgerEntry.objects.filter(record_type="core_baselinesignoff").count() == 2
    assert set(Baseline.objects.filter(work_item__in=[c, d]).values_list("status", flat=True)) == {"已签认"}
    # 刘太太随后签认同一条：409「已由刘先生于…签认」
    r = client_for("owner2").post(f"{P}/baselines/sign", {"revisionIds": revs[:1]}, format="json")
    assert r.status_code == 409 and "已由刘先生于" in r.json()["message"]
    assert BaselineSignoff.objects.filter(revision_id__in=revs).count() == 2

    # 跨工段且跨楼层不能批量
    e = make_item(project, users, "一楼厨房给排水管道敷设", phase_code="p2", floor="f1", dv=v1)
    f = make_item(project, users, "三楼主卫给水管道敷设", phase_code="p1", floor="f3", dv=v1)
    for w in (e, f):
        add_checkpoint(project, users, w, v1)
    re_ = pm.post(f"{P}/work-items/{e.id}/baseline/submit", {}, format="json").json()
    rf = pm.post(f"{P}/work-items/{f.id}/baseline/submit", {}, format="json").json()
    r = owner.post(f"{P}/baselines/sign", {"revisionIds": [re_["revisionId"], rf["revisionId"]]}, format="json")
    assert r.status_code == 400 and r.json()["message"] == "批量签认只能在同一工段或同一楼层内勾选"

    # 退回：无理由被拒；有理由后「已退回」，事件入链
    bl = Baseline.objects.get(work_item=e)
    r = owner.post(f"{P}/baselines/{bl.id}/return", {"reason": " "}, format="json")
    assert r.status_code == 400 and r.json()["message"] == "请填写退回理由"
    r = owner.post(f"{P}/baselines/{bl.id}/return", {"reason": "费用含 2 道拉结筋，请核对后重新提交"}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "已退回"
    bl.refresh_from_db()
    assert bl.return_reason == "费用含 2 道拉结筋，请核对后重新提交"
    ev = BaselineEvent.objects.get(baseline=bl, kind="returned")
    assert ev.actor.name == "刘先生" and LedgerEntry.objects.filter(record_type="core_baselineevent", record_id=ev.id).exists()
    # 退回后可修改再提交
    r = pm.post(f"{P}/work-items/{e.id}/baseline/submit", {"cost": "3850"}, format="json")
    assert r.status_code == 201 and r.json()["revNo"] == 2


# ───────────── FLOW-08 锁定与重签 ─────────────

@pytest.mark.django_db
def test_flow08_lock_resign_and_soon(project, users, client_for, P, water_set):
    pm, owner, dm = client_for("pm"), client_for("owner"), client_for("design_manager")
    v1 = water_set["v1"]
    wi = make_item(project, users, "二楼书房 B 墙内线管预埋", room="书房 B", dv=v1)
    add_checkpoint(project, users, wi, v1, "墙内线管预埋走向")
    r1 = sign_baseline(client_for, P, wi)

    # 已签认后改锁定字段被拒
    r = pm.post(f"{P}/work-items/{wi.id}/baseline/submit", {"cost": "1640"}, format="json")
    assert r.status_code == 409 and r.json()["message"] == "已签认，请发起变更单或等待新版图纸重签"
    assert WorkItem.objects.get(pk=wi.id).cost == 1280

    # 新版签认 → 待重签；重签前基线引用仍是原签认版 V1
    v2 = upload_version(dm, P, water_set["id"], plan_pdf("V2"), note="书房 B 新增插座", wids=[wi.id]).json()["id"]
    owner.post(f"{P}/drawing-versions/{v2}/sign", {}, format="json")
    v3 = upload_version(dm, P, water_set["id"], plan_pdf("V3"), note="主卫给水改走顶面").json()["id"]
    d = pm.get(f"{P}/work-items/{wi.id}/detail").json()
    assert d["baseline"]["status"] == "待重签" and d["baseline"]["baseDrawingVersion"]["id"] == v1
    assert d["baseline"]["effectiveRevision"]["content"]["drawingVersionNo"] == 1
    assert any("待重签" in h["text"] for h in d["history"])

    # 选未签认的 V3 被拒；选 V2 重新提交
    r = pm.post(f"{P}/work-items/{wi.id}/baseline/submit", {"drawingVersionId": v3}, format="json")
    assert r.status_code == 422 and r.json()["message"] == "该版本尚未签认"
    assert WorkItem.objects.get(pk=wi.id).drawing_version_id == v1
    r = pm.post(f"{P}/work-items/{wi.id}/baseline/submit", {"drawingVersionId": v2, "cost": "1640"}, format="json")
    assert r.status_code == 201
    pend = owner.get(f"{P}/baselines/pending").json()
    item = pend["groups"][0]["items"][0]
    assert item["isResign"] is True and item["drawing"] == "水电点位图 V2"
    r = owner.post(f"{P}/baselines/sign", {"revisionIds": [r.json()["revisionId"]]}, format="json")
    assert r.status_code == 200
    bl = Baseline.objects.get(work_item=wi)
    assert bl.status == "已签认" and bl.signed_revision.content["drawingVersionId"] == v2
    # 旧签认记录保留
    assert BaselineSignoff.objects.filter(revision__baseline=bl).count() == 2
    assert BaselineSignoff.objects.filter(revision_id=r1).exists()
    hist = pm.get(f"{P}/work-items/{wi.id}/detail").json()["history"]
    assert sum(1 for h in hist if h["kind"] == "signoff") == 2

    # 计划完成日期为今天 +5 天、基线未签认 → 即将施工
    soon = make_item(project, users, "二楼书房 B 强电插座布线", room="书房 B", dv=v2,
                     finish=timezone.localdate() + datetime.timedelta(days=5))
    assert pm.get(f"{P}/work-items/{soon.id}/detail").json()["baseline"]["soon"] is True
    add_checkpoint(project, users, soon, v2)
    pm.post(f"{P}/work-items/{soon.id}/baseline/submit", {}, format="json")
    item = next(i for g in owner.get(f"{P}/baselines/pending").json()["groups"] for i in g["items"]
                if i["workItemId"] == soon.id)
    assert item["soon"] is True
    later = make_item(project, users, "二楼书房 A 强电插座布线", dv=v2, finish=timezone.localdate() + datetime.timedelta(days=8))
    assert pm.get(f"{P}/work-items/{later.id}/detail").json()["baseline"]["soon"] is False


# ───────────── FLOW-17 工作项资料 ─────────────

@pytest.mark.django_db
def test_flow17_attachments(project, users, client_for, P, water_set, settings):
    qc, pm = client_for("qc"), client_for("pm")
    wi = make_item(project, users, "二楼书房 B 墙内线管预埋", room="书房 B", dv=water_set["v1"])
    url = f"{P}/work-items/{wi.id}/attachments"
    files = [SimpleUploadedFile("线管走向.jpg", png_bytes("gray"), content_type="image/jpeg"),
             SimpleUploadedFile("底盒高度.png", png_bytes("white"), content_type="image/png"),
             SimpleUploadedFile("PVC线管合格证.pdf", plan_pdf("合格证"), content_type="application/pdf"),
             SimpleUploadedFile("现场视频.pdf", b"0" * (60 * 1024 * 1024), content_type="application/pdf")]
    res = [qc.post(url, {"file": f}, format="multipart") for f in files]
    assert [r.status_code for r in res] == [201, 201, 201, 413]
    assert res[3].json()["message"] == "现场视频.pdf：超过 50MB，未上传"
    r = qc.post(url, {"file": SimpleUploadedFile("脚本.exe", b"MZ")}, format="multipart")
    assert r.status_code == 415 and r.json()["message"] == "脚本.exe：格式不支持，未上传"
    lst = pm.get(url).json()
    assert lst["count"] == 3
    by = {a["name"]: a for a in lst["items"]}
    assert by["线管走向.jpg"]["thumbUrl"] and by["PVC线管合格证.pdf"]["thumbUrl"] is None
    assert pm.get(by["PVC线管合格证.pdf"]["url"]).status_code == 200
    assert client_for("owner_member").post(url, {"file": SimpleUploadedFile("a.png", png_bytes("red"))},
                                           format="multipart").status_code == 403

    # 被核对记录引用的照片不能作废
    cp = add_checkpoint(project, users, wi, water_set["v1"], draft=False)
    cr = CheckRecord.objects.create(project=project, checkpoint=cp, checker=users["qc"], drawing_version_id=water_set["v1"],
                                    was_latest_signed=True, conclusion="一致", was_covered=False)
    CheckPhoto.objects.create(project=project, check_record=cr, file_id=by["底盒高度.png"]["id"],
                              file_sha256=by["底盒高度.png"]["sha256"], pin_x=0.5, pin_y=0.5)
    r = qc.post(f"{P}/attachments/{by['底盒高度.png']['attachmentId']}/void", {}, format="json")
    assert r.status_code == 409 and r.json()["message"] == "该文件已被核对、签认或变更单引用，不能作废"
    assert r.json()["details"]["refs"][0]["label"] == f"{cp.code} 核对 #1"
    # 非上传者不能作废
    assert pm.post(f"{P}/attachments/{by['线管走向.jpg']['attachmentId']}/void", {}, format="json").status_code == 403
    # 上传者作废普通资料：标记作废、记录作废人与时间、留痕
    r = qc.post(f"{P}/attachments/{by['线管走向.jpg']['attachmentId']}/void", {}, format="json")
    assert r.status_code == 200 and r.json()["isVoided"] and r.json()["voidedBy"] == "王工" and r.json()["voidedAt"]
    sf = StoredFile.objects.get(pk=by["线管走向.jpg"]["id"])
    assert sf.status == "voided" and sf.voided_by == users["qc"]
    assert AuditLog.objects.filter(action="attachment.void", object_label="线管走向.jpg").exists()
    d = pm.get(f"{P}/work-items/{wi.id}/detail").json()
    assert d["attachmentCount"] == 2 and d["voidedCount"] == 1
    assert qc.post(f"{P}/attachments/{by['线管走向.jpg']['attachmentId']}/void", {}, format="json").status_code == 409
