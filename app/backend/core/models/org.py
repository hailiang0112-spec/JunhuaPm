"""组织、账号、项目与成员角色（DATA-F01-01 ~ DATA-F02-04）。"""
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models


class Company(models.Model):
    """DATA-F01-01 公司。单公司部署时只有 1 行。"""
    name = models.CharField(max_length=100)


class UserManager(BaseUserManager):
    def create_user(self, phone, name, password=None, **extra):
        user = self.model(phone=phone, name=name, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, phone, name, password=None, **extra):
        extra.setdefault("is_company_admin", True)
        return self.create_user(phone, name, password, **extra)


class User(AbstractBaseUser):
    """DATA-F02-01 用户。手机号唯一，姓名用于全站署名。"""
    phone = models.CharField(max_length=11, unique=True)
    name = models.CharField(max_length=40)
    is_company_admin = models.BooleanField(default=False)
    must_change_password = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    USERNAME_FIELD = "phone"
    REQUIRED_FIELDS = ["name"]
    objects = UserManager()

    class Meta:
        db_table = "user"


class Template(models.Model):
    """DATA-F03-01 公司模板；结构保存在 content（工段、楼层、房间、工作项、检查点模板）。"""
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    name = models.CharField(max_length=60)
    content = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)


class ProcessRule(models.Model):
    """DATA-F03-02 工序说明规则：按 order_no 取首个命中的关键词规则。"""
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    order_no = models.IntegerField()
    keywords = models.JSONField(default=list)  # 名称包含任一关键词即命中（DEC-112）
    work_description = models.TextField()
    acceptance_criteria = models.TextField()
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order_no", "id"]


class Project(models.Model):
    """DATA-F01-02 项目。"""
    STATUS = ["筹备", "施工中", "已交房"]
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    name = models.CharField(max_length=100)
    address = models.CharField(max_length=200)
    planned_start = models.DateField()
    planned_handover = models.DateField()
    actual_handover = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=10, default="筹备")
    release_timeout_hours = models.IntegerField(default=24)
    change_order_seq = models.IntegerField(default=0)
    template = models.ForeignKey(Template, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(planned_handover__gte=models.F("planned_start")), name="project_dates"),
            models.CheckConstraint(condition=models.Q(release_timeout_hours__gte=1, release_timeout_hours__lte=72), name="project_timeout_range"),
        ]


class ProjectMemberRole(models.Model):
    """DATA-F01-03 项目成员角色。"""
    ROLES = ["owner", "owner_member", "owner_agent", "pm", "design_manager", "qc", "budget"]
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="member_roles")
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="project_roles")
    role = models.CharField(max_length=20)
    granted_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    granted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "user", "role"], name="pmr_unique"),
            models.UniqueConstraint(fields=["project"], condition=models.Q(role="owner_agent"), name="pmr_one_agent"),
        ]


class Invitation(models.Model):
    """DATA-F02-02 邀请。只存令牌的 SHA-256。"""
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    phone = models.CharField(max_length=11)
    roles = models.JSONField(default=list)
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True)
    revoked_at = models.DateTimeField(null=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)


class LoginThrottle(models.Model):
    """DATA-F02-03 登录限流，按手机号计数。"""
    phone = models.CharField(max_length=11, unique=True)
    fail_count = models.IntegerField(default=0)
    window_start = models.DateTimeField(null=True)
    locked_until = models.DateTimeField(null=True)
