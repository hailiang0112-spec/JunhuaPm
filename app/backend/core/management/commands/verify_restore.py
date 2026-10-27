"""恢复演练校验（技术方案 §7.6）：全部项目完整性校验为「完整」、文件清单缺失为 0、数据时间点与备份相差不超过 24 小时。"""
import datetime
import json

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.services import ops


class Command(BaseCommand):
    help = "在恢复出的库上执行完整性校验与文件清单核对"

    def add_arguments(self, parser):
        parser.add_argument("--file-root", help="恢复出的文件目录（本地模式为异地副本中的 files/）")
        parser.add_argument("--report", help="备份当日的 manifest.json，用于核对数据时间点")

    def handle(self, *args, **opts):
        projects = ops.verify_all_projects()
        manifest = ops.file_manifest_check(opts["file_root"])
        t = ops.latest_data_time()
        out = {"projects": projects, "manifestCheck": manifest,
               "dataTime": timezone.localtime(t).isoformat() if t else None}
        ok = all(p["result"] == "完整" for p in projects) and manifest["missing"] == 0 and manifest["sizeMismatch"] == 0
        if opts["report"]:
            rep = json.load(open(opts["report"], encoding="utf-8"))
            backup_at = datetime.datetime.fromisoformat(rep["startedAt"])
            out["backupAt"] = rep["startedAt"]
            out["lagHours"] = round((backup_at - t).total_seconds() / 3600, 2) if t else None
            ok = ok and out["lagHours"] is not None and out["lagHours"] <= 24
        self.stdout.write(json.dumps(out, ensure_ascii=False, indent=2))
        if not ok:
            raise CommandError("恢复演练未通过")
        self.stdout.write("恢复演练通过：完整性校验全部为「完整」，文件缺失 0")
