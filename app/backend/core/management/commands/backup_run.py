"""执行一次每日备份（技术方案 §7.6）。失败（含异地同步失败）时退出码非 0。"""
import json
import logging

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.services import ops

log = logging.getLogger("backup")


class Command(BaseCommand):
    help = "每日备份：数据库 + 文件清单核对 + 异地同步 + 保留 30 天"

    def handle(self, *args, **opts):
        report = ops.run_backup(log)
        self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
        if settings.OFFSITE_TARGET and not report["offsite_synced"]:
            raise CommandError("异地同步失败")
        if report["manifestCheck"]["missing"] or report["manifestCheck"]["sizeMismatch"]:
            raise CommandError("文件清单核对不一致")
