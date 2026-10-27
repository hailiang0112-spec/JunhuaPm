"""证据链：图纸、基线、检查点、核对、放行、变更单、问题、经验库（DATA-F04 ~ DATA-F09）。

带 KEY_RECORD 标记的模型是只追加的关键记录：运行账号只有 INSERT/SELECT，写入时进入摘要链。
"""
from django.db import models

from .org import Company, Project, User
from .structure import Phase, StoredFile, WorkItem


class DrawingSet(models.Model):
    """DATA-F04-01 图纸分册（投影：当前签认版）。"""
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="drawing_sets")
    name = models.CharField(max_length=40)
    current_signed_version = models.ForeignKey("DrawingVersion", null=True, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)


class DrawingVersion(models.Model):
    """DATA-F04-02 图纸版本（关键记录）。"""
    KEY_RECORD = True
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    drawing_set = models.ForeignKey(DrawingSet, on_delete=models.PROTECT, related_name="versions")
    version_no = models.IntegerField()
    file = models.ForeignKey(StoredFile, on_delete=models.PROTECT, related_name="+")
    cad_file = models.ForeignKey(StoredFile, null=True, on_delete=models.PROTECT, related_name="+")
    change_note = models.TextField(blank=True)
    affected_work_item_ids = models.JSONField(default=list)
    change_order = models.ForeignKey("ChangeOrder", null=True, on_delete=models.PROTECT, related_name="+")
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["drawing_set", "version_no"], name="dv_unique")]


class DrawingSignoff(models.Model):
    """DATA-F04-03 图纸签认（关键记录）。"""
    KEY_RECORD = True
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    version = models.OneToOneField(DrawingVersion, on_delete=models.PROTECT, related_name="signoff")
    signer = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    signed_at = models.DateTimeField(auto_now_add=True)
    file_sha256 = models.CharField(max_length=64)


class DrawingPage(models.Model):
    """DATA-F04-04 图纸页位图（派生，可重建）。"""
    version = models.ForeignKey(DrawingVersion, on_delete=models.CASCADE, related_name="pages")
    page_no = models.IntegerField()
    image = models.ForeignKey(StoredFile, on_delete=models.PROTECT, related_name="+")
    width_px = models.IntegerField()
    height_px = models.IntegerField()


class Baseline(models.Model):
    """DATA-F05-01 基线（投影）。status ∈ 草稿/待签认/已签认/已退回/待重签。"""
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    work_item = models.OneToOneField(WorkItem, on_delete=models.CASCADE, related_name="baseline")
    status = models.CharField(max_length=10, default="草稿")
    current_revision = models.ForeignKey("BaselineRevision", null=True, on_delete=models.PROTECT, related_name="+")
    signed_revision = models.ForeignKey("BaselineRevision", null=True, on_delete=models.PROTECT, related_name="+")
    return_reason = models.CharField(max_length=200, blank=True)
    submitted_at = models.DateTimeField(null=True)


class BaselineRevision(models.Model):
    """DATA-F05-02 基线修订（关键记录）。content 为完整快照。"""
    KEY_RECORD = True
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    baseline = models.ForeignKey(Baseline, on_delete=models.PROTECT, related_name="revisions")
    rev_no = models.IntegerField()
    kind = models.CharField(max_length=20)  # submit / change_order
    content = models.JSONField()
    change_order = models.ForeignKey("ChangeOrder", null=True, on_delete=models.PROTECT, related_name="+")
    actor = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["baseline", "rev_no"], name="br_unique")]


class BaselineSignoff(models.Model):
    """DATA-F05-03 基线签认（关键记录）。"""
    KEY_RECORD = True
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    revision = models.OneToOneField(BaselineRevision, on_delete=models.PROTECT, related_name="signoff")
    signer = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    signed_at = models.DateTimeField(auto_now_add=True)
    content_snapshot = models.JSONField()


class BaselineEvent(models.Model):
    """DATA-F05-04 基线事件（关键记录）：submitted / returned / resign_required / checkpoint_added。"""
    KEY_RECORD = True
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    baseline = models.ForeignKey(Baseline, on_delete=models.PROTECT, related_name="events")
    kind = models.CharField(max_length=20)
    reason = models.CharField(max_length=200, blank=True)
    drawing_version = models.ForeignKey(DrawingVersion, null=True, on_delete=models.PROTECT, related_name="+")
    checkpoint = models.ForeignKey("Checkpoint", null=True, on_delete=models.PROTECT, related_name="+")
    actor = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    at = models.DateTimeField(auto_now_add=True)


class Checkpoint(models.Model):
    """DATA-F06-01 检查点（投影）。status ∈ 未核对/不一致/待放行/已放行/放行后发现不一致。"""
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    work_item = models.ForeignKey(WorkItem, on_delete=models.PROTECT, related_name="checkpoints")
    code = models.CharField(max_length=10)  # CK-001
    point = models.CharField(max_length=200)  # 检查要点
    is_concealed = models.BooleanField(default=True)
    drawing_version = models.ForeignKey(DrawingVersion, on_delete=models.PROTECT, related_name="+")
    page_no = models.IntegerField(default=1)
    x = models.FloatField()
    y = models.FloatField()
    status = models.CharField(max_length=12, default="未核对")
    latest_check = models.ForeignKey("CheckRecord", null=True, on_delete=models.PROTECT, related_name="+")
    awaiting_release_since = models.DateTimeField(null=True)
    released_at = models.DateTimeField(null=True)
    covered_at = models.DateTimeField(null=True)
    unreleased_cover = models.BooleanField(default=False)
    is_draft = models.BooleanField(default=False)  # 基线草稿 / 已退回期间新建，随基线提交
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "code"], name="ck_code"),
            models.CheckConstraint(condition=models.Q(x__gte=0, x__lte=1, y__gte=0, y__lte=1), name="ck_xy"),
        ]


class CheckRecord(models.Model):
    """DATA-F06-02 核对记录（关键记录）。"""
    KEY_RECORD = True
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    checkpoint = models.ForeignKey(Checkpoint, on_delete=models.PROTECT, related_name="checks")
    checker = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    checked_at = models.DateTimeField(auto_now_add=True)
    drawing_version = models.ForeignKey(DrawingVersion, on_delete=models.PROTECT, related_name="+")
    was_latest_signed = models.BooleanField()
    conclusion = models.CharField(max_length=4)  # 一致 / 不一致 / 已变更
    was_covered = models.BooleanField()
    change_order = models.ForeignKey("ChangeOrder", null=True, on_delete=models.PROTECT, related_name="+")
    discovery_phase = models.CharField(max_length=4, blank=True)  # 覆盖前 / 覆盖后 / 交房后（仅不一致）
    note = models.CharField(max_length=300, blank=True)


class CheckPhoto(models.Model):
    """DATA-F06-03 核对照片（随核对入链）。"""
    KEY_RECORD = True
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    check_record = models.ForeignKey(CheckRecord, on_delete=models.PROTECT, related_name="photos")
    file = models.ForeignKey(StoredFile, on_delete=models.PROTECT, related_name="+")
    file_sha256 = models.CharField(max_length=64)
    pin_x = models.FloatField()
    pin_y = models.FloatField()


class ReleaseRecord(models.Model):
    """DATA-F06-04 放行记录（关键记录）。"""
    KEY_RECORD = True
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    checkpoint = models.ForeignKey(Checkpoint, on_delete=models.PROTECT, related_name="releases")
    releaser = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    is_proxy = models.BooleanField()
    released_at = models.DateTimeField(auto_now_add=True)
    basis_check = models.ForeignKey(CheckRecord, on_delete=models.PROTECT, related_name="+")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["checkpoint", "basis_check"], name="rr_unique")]


class CoverEvent(models.Model):
    """DATA-F06-05 覆盖事件（关键记录）。was_unreleased=true 即「未放行先覆盖」。"""
    KEY_RECORD = True
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    checkpoint = models.ForeignKey(Checkpoint, on_delete=models.PROTECT, related_name="cover_events")
    source = models.CharField(max_length=10)  # pm_mark / qc_check
    recorder = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    at = models.DateTimeField(auto_now_add=True)
    was_unreleased = models.BooleanField()


class DiscoveryCorrection(models.Model):
    """DATA-F06-06 发现时点修正（关键记录）。"""
    KEY_RECORD = True
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    check_record = models.ForeignKey(CheckRecord, on_delete=models.PROTECT, related_name="corrections")
    before = models.CharField(max_length=4)
    after = models.CharField(max_length=4)
    reason = models.CharField(max_length=200)
    actor = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    at = models.DateTimeField(auto_now_add=True)


class ChangeOrder(models.Model):
    """DATA-F07-01 变更单（投影）。status ∈ 草稿/待预算定价/待业主签认/已生效/已驳回。"""
    REASONS = ["业主要求", "设计深化", "现场条件", "施工纠偏"]
    BEARERS = ["业主", "装修公司", "设计方"]
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    seq_no = models.IntegerField()
    round_no = models.IntegerField(default=1)
    title = models.CharField(max_length=100, blank=True)
    reason_category = models.CharField(max_length=10, blank=True)
    content = models.TextField(blank=True)
    needs_new_drawing = models.BooleanField(null=True)
    built_before_sign = models.BooleanField(null=True)  # True = 后补变更
    status = models.CharField(max_length=10, default="草稿")
    price_delta = models.DecimalField(max_digits=12, decimal_places=2, null=True)
    schedule_delta_days = models.IntegerField(null=True)
    cost_bearer = models.CharField(max_length=10, blank=True)
    reject_reason = models.CharField(max_length=300, blank=True)
    work_items = models.ManyToManyField(WorkItem, related_name="change_orders", blank=True)
    files = models.ManyToManyField(StoredFile, related_name="+", blank=True)
    source_issue = models.ForeignKey("Issue", null=True, on_delete=models.SET_NULL, related_name="+")
    source_supplement = models.ForeignKey("Supplement", null=True, on_delete=models.SET_NULL, related_name="+")
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["project", "seq_no"], name="co_seq")]

    @property
    def code(self):
        return f"BG-{self.seq_no:03d}"


class ChangeOrderEvent(models.Model):
    """DATA-F07-02 变更单事件（关键记录）：created/priced/signed/rejected/resubmitted。"""
    KEY_RECORD = True
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    change_order = models.ForeignKey(ChangeOrder, on_delete=models.PROTECT, related_name="events")
    round_no = models.IntegerField()
    kind = models.CharField(max_length=12)
    payload = models.JSONField(default=dict)
    actor = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["change_order", "round_no", "kind"], name="coe_unique")]


class Issue(models.Model):
    """DATA-F08-01 问题（投影）。status ∈ 未闭环/处理中/已闭环/已作废。"""
    LEVELS = ["一般", "重要", "严重"]
    CAUSES = ["设计已改但未签变更单", "施工偏离签认图", "图纸本身未表达清楚"]
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    seq_no = models.IntegerField()
    source_check = models.ForeignKey(CheckRecord, null=True, on_delete=models.PROTECT, related_name="+")
    checkpoint = models.ForeignKey(Checkpoint, null=True, on_delete=models.PROTECT, related_name="issues")
    work_item = models.ForeignKey(WorkItem, null=True, on_delete=models.PROTECT, related_name="+")
    phase = models.ForeignKey(Phase, null=True, on_delete=models.PROTECT, related_name="+")
    floor = models.ForeignKey("Floor", null=True, on_delete=models.PROTECT, related_name="+")
    room = models.ForeignKey("Room", null=True, on_delete=models.PROTECT, related_name="+")
    description = models.TextField()
    level = models.CharField(max_length=4, default="一般")
    countermeasure = models.TextField(default="待补充对策")
    owner_name = models.CharField(max_length=40, default="待指派")
    found_on = models.DateField()
    due_date = models.DateField(null=True)
    cause = models.CharField(max_length=20, blank=True)
    status = models.CharField(max_length=6, default="未闭环")
    closed_on = models.DateField(null=True)
    void_reason = models.CharField(max_length=200, blank=True)
    source = models.CharField(max_length=20, default="manual")
    created_by = models.ForeignKey(User, null=True, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["project", "seq_no"], name="issue_seq")]

    @property
    def code(self):
        return f"WT-{self.seq_no:03d}"


class IssueEvent(models.Model):
    """DATA-F08-02 问题状态变化（关键记录）：created/cause_set/closed/reopened/voided。"""
    KEY_RECORD = True
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    issue = models.ForeignKey(Issue, on_delete=models.PROTECT, related_name="events")
    kind = models.CharField(max_length=12)
    before = models.CharField(max_length=40, blank=True)
    after = models.CharField(max_length=40, blank=True)
    reason = models.CharField(max_length=300, blank=True)
    actor = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    at = models.DateTimeField(auto_now_add=True)


class ExperienceEntry(models.Model):
    """DATA-F09-01 经验条目（公司级）。status ∈ 待审核/未验证经验/历史观察/已验证。"""
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    current_version = models.ForeignKey("ExperienceVersion", null=True, on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=6, default="待审核")
    reviewer = models.ForeignKey(User, null=True, on_delete=models.PROTECT, related_name="+")
    reviewed_at = models.DateTimeField(null=True)
    source_issue = models.ForeignKey(Issue, null=True, on_delete=models.SET_NULL, related_name="+")
    submitter = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)


class ExperienceVersion(models.Model):
    """DATA-F09-02 经验条目版本（只追加）。"""
    entry = models.ForeignKey(ExperienceEntry, on_delete=models.PROTECT, related_name="versions")
    ver_no = models.IntegerField()
    phase_name = models.CharField(max_length=20)
    process = models.CharField(max_length=60)
    issue_type = models.CharField(max_length=60)
    check_point = models.TextField()
    countermeasure = models.TextField()
    photo_file_ids = models.JSONField(default=list)
    status = models.CharField(max_length=6)
    change_note = models.CharField(max_length=200, blank=True)
    author = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["entry", "ver_no"], name="ev_unique")]
