"""worker 进程（技术方案 §3.6）：轮询 Job 表，用 SELECT … FOR UPDATE SKIP LOCKED 领取排队任务并执行。"""
import logging
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections, transaction
from django.utils import timezone

from core.models import Job

log = logging.getLogger("worker")


def handlers():
    from core.api.audit import run_evidence_job
    return {"evidence_export": run_evidence_job}


class Command(BaseCommand):
    help = "后台任务 worker"

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="处理完当前队列后退出")

    def handle(self, *args, **opts):
        hs = handlers()
        while True:
            close_old_connections()
            with transaction.atomic():
                job = (Job.objects.select_for_update(skip_locked=True)
                       .filter(status="排队", kind__in=list(hs)).order_by("id").first())
                if job:
                    job.status = "进行中"
                    job.save(update_fields=["status"])
            if job is None:
                if opts["once"]:
                    return
                time.sleep(2)
                continue
            try:
                hs[job.kind](job)
                log.info("任务 %s（%s）完成", job.id, job.kind)
            except Exception as e:  # noqa: BLE001 — 失败写入任务状态，页面显示原因，worker 继续处理后续任务
                log.exception("任务 %s 失败", job.id)
                Job.objects.filter(pk=job.pk).update(status="失败", error=str(e)[:500], finished_at=timezone.now())
