"""项目结构、出勤、计划留档、文件与资料（DATA-F03-03 ~ DATA-F03-06、DATA-F11/F12/F14）。"""
from django.db import models

from .org import Project, User

SOURCES = ["manual", "excel_import", "prototype_import"]


class Floor(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="floors")
    code = models.CharField(max_length=10)  # 如 b1 / f1，模板与 Excel 用于匹配
    name = models.CharField(max_length=20)
    order_no = models.IntegerField(default=0)
    is_disabled = models.BooleanField(default=False)

    class Meta:
        ordering = ["order_no", "id"]


class Room(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="rooms")
    floor = models.ForeignKey(Floor, on_delete=models.PROTECT, related_name="rooms")
    code = models.CharField(max_length=20)
    name = models.CharField(max_length=30)
    order_no = models.IntegerField(default=0)
    is_disabled = models.BooleanField(default=False)

    class Meta:
        ordering = ["order_no", "id"]


class Phase(models.Model):
    """DATA-F03-04 工段。状态与进度实时推导。"""
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="phases")
    code = models.CharField(max_length=10)  # p1 ~ p6
    name = models.CharField(max_length=20)
    color_var = models.CharField(max_length=20, default="--phase-1")
    order_no = models.IntegerField(default=0)
    planned_start = models.DateField()
    planned_end = models.DateField()
    team_lead = models.CharField(max_length=60, blank=True)
    weight = models.IntegerField(default=10)  # 百分比整数
    scope_note = models.TextField(blank=True)
    is_disabled = models.BooleanField(default=False)

    class Meta:
        ordering = ["order_no", "id"]
        constraints = [models.CheckConstraint(condition=models.Q(planned_end__gte=models.F("planned_start")), name="phase_dates")]


class WorkItem(models.Model):
    """DATA-F03-05 工作项。基线锁定字段由服务层控制。"""
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="work_items")
    phase = models.ForeignKey(Phase, on_delete=models.PROTECT, related_name="work_items")
    floor = models.ForeignKey(Floor, null=True, blank=True, on_delete=models.PROTECT)  # null = 全楼通用
    room = models.ForeignKey(Room, null=True, blank=True, on_delete=models.PROTECT)  # null = 本层通用
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    acceptance_criteria = models.TextField(blank=True)
    cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    planned_finish = models.DateField(null=True, blank=True)
    actual_finish = models.DateField(null=True, blank=True)
    owner_name = models.CharField(max_length=40, blank=True)
    qc_user = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    drawing_version = models.ForeignKey("DrawingVersion", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    weight = models.IntegerField(default=1)
    progress = models.IntegerField(default=0)
    source = models.CharField(max_length=20, default="manual")
    is_disabled = models.BooleanField(default=False)
    # 模板检查点（深拷贝自公司模板）：检查点必须钉在签认图纸上，建项目时无图，作为新建检查点时的一键填入项
    checkpoint_hints = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["phase__order_no", "id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(weight__gte=1, weight__lte=5), name="wi_weight"),
            models.CheckConstraint(condition=models.Q(progress__gte=0, progress__lte=100), name="wi_progress"),
        ]


class StoredFile(models.Model):
    """DATA-F12-01 文件对象。存储键带内容哈希，只写不覆盖。"""
    project = models.ForeignKey(Project, null=True, on_delete=models.CASCADE)
    storage_key = models.CharField(max_length=200)
    sha256 = models.CharField(max_length=64)
    size = models.BigIntegerField()
    mime = models.CharField(max_length=100)
    original_name = models.CharField(max_length=200)
    uploader = models.ForeignKey(User, null=True, on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=10, default="normal")  # normal / voided / missing
    thumb_key = models.CharField(max_length=200, blank=True)
    voided_by = models.ForeignKey(User, null=True, on_delete=models.PROTECT, related_name="+")
    voided_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)


class WorkItemAttachment(models.Model):
    """DATA-F12-02 工作项资料。"""
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    work_item = models.ForeignKey(WorkItem, on_delete=models.CASCADE, related_name="attachments")
    file = models.ForeignKey(StoredFile, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)


class AcceptancePhoto(models.Model):
    """DATA-F12-03 阶段验收图片。"""
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    phase = models.ForeignKey(Phase, on_delete=models.CASCADE, related_name="acceptance_photos")
    file = models.ForeignKey(StoredFile, null=True, on_delete=models.PROTECT)
    caption = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=10, default="待复验")
    source = models.CharField(max_length=20, default="manual")
    created_at = models.DateTimeField(auto_now_add=True)


class ArchiveFolder(models.Model):
    """DATA-F12-04 档案分类。zone ∈ layout / render / contract。"""
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    zone = models.CharField(max_length=10)
    name = models.CharField(max_length=40)
    order_no = models.IntegerField(default=0)

    class Meta:
        ordering = ["order_no", "id"]


class ArchiveFile(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    folder = models.ForeignKey(ArchiveFolder, on_delete=models.PROTECT, related_name="files")
    file = models.ForeignKey(StoredFile, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)


class Attendance(models.Model):
    """DATA-F11-01 出勤。未登记日期不存行。"""
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    phase = models.ForeignKey(Phase, on_delete=models.CASCADE, related_name="attendance")
    date = models.DateField()
    headcount = models.IntegerField()
    source = models.CharField(max_length=20, default="manual")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["phase", "date"], name="att_unique"),
            models.CheckConstraint(condition=models.Q(headcount__gte=0, headcount__lte=40), name="att_range"),
        ]


class PlanChangeLog(models.Model):
    """DATA-F14-01 计划留档（关键记录，只追加）。"""
    KEY_RECORD = True
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    phase = models.ForeignKey(Phase, on_delete=models.PROTECT)
    at = models.DateTimeField(auto_now_add=True)
    actor = models.ForeignKey(User, null=True, on_delete=models.PROTECT, related_name="+")
    changes = models.JSONField()  # [{field,label,before,after}]
    duration_delta_days = models.IntegerField(null=True)
    reason = models.CharField(max_length=200, blank=True)
    source = models.CharField(max_length=20, default="manual")


class ImportBatch(models.Model):
    """DATA-F03-06 导入批次。"""
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    kind = models.CharField(max_length=20)  # plan_xlsx / plan_csv / prototype_json
    file = models.ForeignKey(StoredFile, null=True, on_delete=models.PROTECT)
    parsed = models.JSONField(default=dict)
    errors = models.JSONField(default=list)
    result = models.JSONField(default=dict)
    status = models.CharField(max_length=10, default="校验中")
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
