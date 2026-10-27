"""时间推进（唯一的 ORM 前置）：界面无法造出「核对一致后已等 25 小时」，把「防潮层」检查点的待放行起点前拨 25 小时。

用法：manage.py shell < advance_time.py（运行账号 app_runtime；Checkpoint 是投影表，允许 UPDATE）。
"""
import datetime
import json
import os

from django.utils import timezone

from core.models import Checkpoint

seed = json.load(open(os.environ["SEED_JSON"]))
n = Checkpoint.objects.filter(pk=seed["cps"]["damp"]["cp"], status="待放行").update(
    awaiting_release_since=timezone.now() - datetime.timedelta(hours=25))
print("已前拨待放行起点 25 小时：", n, "个检查点")
