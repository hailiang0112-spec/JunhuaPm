"""备份容器常驻进程：每天北京时间 02:30 执行 backup_run（技术方案 §7.6）。"""
import datetime
import logging
import time

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone

log = logging.getLogger("backup")


class Command(BaseCommand):
    help = "每日 02:30 执行备份"

    def handle(self, *args, **opts):
        while True:
            now = timezone.localtime()
            nxt = now.replace(hour=2, minute=30, second=0, microsecond=0)
            if nxt <= now:
                nxt += datetime.timedelta(days=1)
            log.info("下次备份：%s", nxt.isoformat())
            time.sleep((nxt - now).total_seconds())
            try:
                call_command("backup_run")
            except Exception:  # noqa: BLE001 — 记录后等待次日重试，进程不退出
                log.exception("每日备份失败")
