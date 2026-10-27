"""补充事项、公告栏、付款节点、待办确认、摘要链、操作日志、后台任务（DATA-F13 ~ DATA-F17）。"""
from django.db import models

from .org import Project, User
from .structure import Phase


class Supplement(models.Model):
    """DATA-F13-01 补充事项。"""
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    title = models.CharField(max_length=100)
    note = models.TextField(blank=True)
    raised_on = models.DateField()
    due_on = models.DateField()
    owner_name = models.CharField(max_length=40)
    status = models.CharField(max_length=4, default="待处理")
    change_order = models.ForeignKey("ChangeOrder", null=True, on_delete=models.SET_NULL, related_name="+")
    files = models.ManyToManyField("StoredFile", related_name="+", blank=True)
    source = models.CharField(max_length=20, default="manual")
    created_at = models.DateTimeField(auto_now_add=True)


class Notice(models.Model):
    """DATA-F13-02 留言。board ∈ owner / site / design；删除 = 软删除。"""
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    board = models.CharField(max_length=10)
    author = models.ForeignKey(User, null=True, on_delete=models.PROTECT, related_name="+")
    author_name = models.CharField(max_length=40)
    parent = models.ForeignKey("self", null=True, on_delete=models.PROTECT, related_name="replies")
    body = models.TextField()
    deleted_at = models.DateTimeField(null=True)
    source = models.CharField(max_length=20, default="manual")
    created_at = models.DateTimeField(auto_now_add=True)


class PaymentMilestone(models.Model):
    """DATA-F15-01 付款节点。"""
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    name = models.CharField(max_length=60)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    planned_on = models.DateField()
    phase = models.ForeignKey(Phase, on_delete=models.PROTECT)  # 首个关联工段
    phases = models.ManyToManyField(Phase, related_name="+")  # 全部关联工段（PAGE-F15-01：可多选）
    status = models.CharField(max_length=4, default="未付")
    paid_at = models.DateTimeField(null=True)
    paid_by = models.ForeignKey(User, null=True, on_delete=models.PROTECT, related_name="+")
    paid_confirmed_unreleased = models.IntegerField(null=True)


class TodoAck(models.Model):
    """DATA-F16-01 知会确认。"""
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    kind = models.CharField(max_length=20)
    object_id = models.IntegerField()
    acked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "kind", "object_id"], name="ack_unique")]


class LedgerEntry(models.Model):
    """DATA-F17-01 摘要链：hash = SHA-256(content ‖ prev_hash)。"""
    project = models.ForeignKey(Project, on_delete=models.PROTECT)
    seq = models.IntegerField()
    record_type = models.CharField(max_length=40)
    record_id = models.IntegerField()
    content = models.TextField()
    prev_hash = models.CharField(max_length=64)
    hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "seq"], name="ledger_seq"),
            models.UniqueConstraint(fields=["record_type", "record_id"], name="ledger_record"),
        ]


class AuditLog(models.Model):
    """DATA-F17-02 操作日志（只追加，不入链）。"""
    project = models.ForeignKey(Project, null=True, on_delete=models.PROTECT)
    actor = models.ForeignKey(User, null=True, on_delete=models.PROTECT, related_name="+")
    at = models.DateTimeField(auto_now_add=True)
    action = models.CharField(max_length=40)
    object_type = models.CharField(max_length=40)
    object_id = models.CharField(max_length=40, blank=True)
    object_label = models.CharField(max_length=120, blank=True)
    before = models.JSONField(null=True)
    after = models.JSONField(null=True)

    class Meta:
        indexes = [models.Index(fields=["project", "at"]), models.Index(fields=["object_type", "object_id"])]


class Job(models.Model):
    """DATA-F17-03 后台任务（证据包、校验、渲染）。"""
    kind = models.CharField(max_length=20)
    project = models.ForeignKey(Project, null=True, on_delete=models.CASCADE)
    params = models.JSONField(default=dict)
    status = models.CharField(max_length=6, default="排队")
    progress = models.IntegerField(default=0)
    result = models.JSONField(default=dict)
    error = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True)
