"""压测造数（RULE-05，NFR-002/009）：单项目 1000 工作项、5000 检查点、20000 张核对照片，另建 20 个压测账号。

照片为真实 JPEG（每张内容不同），核对记录与照片照常写入摘要链。仅用于压测环境。
"""
import datetime
import io
import random

from django.core.management.base import BaseCommand
from django.db import transaction
from PIL import Image

from core.models import (Baseline, Checkpoint, CheckPhoto, CheckRecord, DrawingSet, DrawingSignoff, DrawingVersion,
                         Project, ProjectMemberRole, User, WorkItem)
from core.services import ledger, storage
from core.services.projects import create_from_template, default_company, ensure_company_template

NAME = "压测工地 · 翡翠湾独栋"
POINTS = ["墙内线管预埋走向", "强电底盒高度", "给水管打压", "防水上翻高度", "管道井封堵", "门洞净宽", "地漏坡度",
          "吊顶龙骨间距", "开关面板定位", "排水管坡度"]


def jpeg(seed, big=False):
    if big:  # 接近手机实拍体积（约 2–3MB）的照片，用于证据包导出耗时
        img = Image.frombytes("RGB", (1600, 1200), random.Random(seed).randbytes(1600 * 1200 * 3))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=80)
        return buf.getvalue()
    rnd = random.Random(seed)
    img = Image.new("RGB", (160, 120), (rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)))
    for _ in range(40):
        x, y = rnd.randrange(160), rnd.randrange(120)
        img.putpixel((x, y), (rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


class Command(BaseCommand):
    help = "生成压测数据"

    def add_arguments(self, parser):
        parser.add_argument("--work-items", type=int, default=1000)
        parser.add_argument("--checkpoints", type=int, default=5000)
        parser.add_argument("--photos", type=int, default=20000)
        parser.add_argument("--name", default=NAME)
        parser.add_argument("--big-photos", action="store_true")

    def handle(self, *args, **o):
        company = default_company()
        tpl = ensure_company_template(company)
        admin = User.objects.filter(is_company_admin=True).first()
        if Project.objects.filter(name=o["name"]).exists():
            self.stdout.write("压测项目已存在")
            return
        with transaction.atomic():
            p = create_from_template(company, tpl, o["name"], "翡翠湾 C 区 8 栋", datetime.date(2026, 9, 1),
                                     datetime.date(2027, 8, 31), admin)
            p.status = "施工中"
            p.save()
            users = []
            roles = ["owner", "pm", "qc", "design_manager", "budget"]
            for i in range(20):
                phone = f"1370000{i:04d}"
                u = User.objects.filter(phone=phone).first() or User.objects.create_user(
                    phone=phone, name=f"压测{roles[i % 5]}{i:02d}", password="Jh123456")
                ProjectMemberRole.objects.get_or_create(project=p, user=u, role=roles[i % 5])
                users.append(u)
            owner, qc = users[0], users[2]
            pdf = storage.save_bytes(b"%PDF-1.4\n% perf drawing\n%%EOF", "压测水电图.pdf", admin, p)
            ds = DrawingSet.objects.create(project=p, name="压测水电图")
            v = DrawingVersion.objects.create(project=p, drawing_set=ds, version_no=1, file=pdf, change_note="首版",
                                              created_by=admin)
            ledger.append(p.id, v)
            so = DrawingSignoff.objects.create(project=p, version=v, signer=owner, file_sha256=pdf.sha256)
            ledger.append(p.id, so)
            ds.current_signed_version = v
            ds.save()
            base = list(p.work_items.all())
            phases = list(p.phases.all())
            extra = [WorkItem(project=p, phase=phases[i % len(phases)], name=f"压测工作项 {i + 1:04d}",
                              description="按图施工", acceptance_criteria="与签认图纸一致", drawing_version=v,
                              qc_user=qc) for i in range(max(0, o["work_items"] - len(base)))]
            WorkItem.objects.bulk_create(extra, batch_size=500)
            wis = list(p.work_items.order_by("id"))[: o["work_items"]]
            WorkItem.objects.filter(project=p).update(drawing_version=v, qc_user=qc)
            Baseline.objects.bulk_create([Baseline(project=p, work_item=w, status="已签认") for w in wis
                                          if not Baseline.objects.filter(work_item=w).exists()], batch_size=500)
            Baseline.objects.filter(project=p).update(status="已签认")
            cps = [Checkpoint(project=p, work_item=wis[i % len(wis)], code=f"CK-{i + 1:04d}",
                              point=POINTS[i % len(POINTS)], is_concealed=i % 3 != 0, drawing_version=v,
                              x=round(random.random(), 3), y=round(random.random(), 3), created_by=qc)
                   for i in range(o["checkpoints"])]
            Checkpoint.objects.bulk_create(cps, batch_size=1000)
        cps = list(Checkpoint.objects.filter(project=p).order_by("id"))
        per = 5
        n_checks = o["photos"] // per
        for start in range(0, n_checks, 200):
            with transaction.atomic():
                for i in range(start, min(start + 200, n_checks)):
                    cp = cps[i % len(cps)]
                    ck = CheckRecord.objects.create(project=p, checkpoint=cp, checker=qc, drawing_version=v,
                                                    was_latest_signed=True, conclusion="一致", was_covered=False)
                    ledger.append(p.id, ck)
                    for k in range(per):
                        sf = storage.save_bytes(jpeg(i * per + k, o["big_photos"]), f"现场照片-{i * per + k + 1:05d}.jpg", qc, p)
                        ph = CheckPhoto.objects.create(project=p, check_record=ck, file=sf, file_sha256=sf.sha256,
                                                       pin_x=0.5, pin_y=0.5)
                        ledger.append(p.id, ph)
                    Checkpoint.objects.filter(pk=cp.pk).update(latest_check=ck, status="待放行",
                                                               awaiting_release_since=ck.checked_at)
            self.stdout.write(f"核对 {min(start + 200, n_checks)}/{n_checks}")
        self.stdout.write(f"完成：项目 {p.id}，工作项 {len(wis)}，检查点 {len(cps)}，照片 {o['photos']}")
