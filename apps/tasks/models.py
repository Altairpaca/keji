"""tasks 待办模型（规格 §13 / REQ-TASK-001）。

字段以规格 §13 为准：类型、标题、内容、关联客户、截止日期时间、优先级、
状态、完成/取消时间戳、负责人/创建者、备注。业务流转（complete/cancel）
在服务层，见 apps/tasks/services/tasks.py。
"""

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models.base import SoftDeleteModel, TimeStampedModel, UUIDModel

# 快速跟进可选项：天数 → 下次跟进截止日期偏移（规格 §13）。
QUICK_FOLLOWUP_DAYS: dict[str, int] = {"7": 7, "15": 15, "30": 30, "90": 90}


class Task(TimeStampedModel, UUIDModel, SoftDeleteModel):
    """待办事项。"""

    class TaskType(models.TextChoices):
        CALL = "call", "打电话"
        WECHAT = "wechat", "发微信"
        MEETING = "meeting", "约见"
        PREPARE_MATERIALS = "prepare_materials", "准备资料"
        FOLLOWUP = "followup", "客户回访"
        POLICY_ORGANIZE = "policy_organize", "保单整理"
        CLAIM_MATERIAL = "claim_material", "理赔补件"
        EVENT = "event", "参加活动"
        DELIVER_MATERIALS = "deliver_materials", "送资料"
        CONFIRM_PAYMENT = "confirm_payment", "确认缴费"
        OTHER = "other", "其他"

    class Priority(models.TextChoices):
        LOW = "低", "低"
        MEDIUM = "中", "中"
        HIGH = "高", "高"

    class Status(models.TextChoices):
        OPEN = "open", "未开始"
        IN_PROGRESS = "in_progress", "进行中"
        DONE = "done", "已完成"
        CANCELLED = "cancelled", "已取消"

    task_type = models.CharField(
        max_length=32, choices=TaskType.choices, default=TaskType.FOLLOWUP, verbose_name="类型"
    )
    title = models.CharField(max_length=200, verbose_name="标题")
    content = models.TextField(blank=True, verbose_name="内容")
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tasks",
        verbose_name="关联客户",
    )
    due_date = models.DateField(db_index=True, verbose_name="截止日期")
    due_time = models.TimeField(null=True, blank=True, verbose_name="截止时间")
    priority = models.CharField(
        max_length=10, choices=Priority.choices, default=Priority.MEDIUM, verbose_name="优先级"
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.OPEN,
        db_index=True,
        verbose_name="状态",
    )
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name="完成时间")
    cancelled_at = models.DateTimeField(null=True, blank=True, verbose_name="取消时间")
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_tasks",
        verbose_name="负责人",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_tasks",
        verbose_name="创建者",
    )
    remark = models.TextField(blank=True, verbose_name="备注")
    source_key = models.CharField(
        max_length=100, blank=True, default="", db_index=True, verbose_name="来源键"
    )

    class Meta:
        ordering = ["due_date", "created_at"]
        verbose_name = "待办"
        verbose_name_plural = "待办"

    def __str__(self) -> str:
        return str(self.title)

    @property
    def is_overdue(self) -> bool:
        """是否逾期：未完成/未取消且截止日期早于今天。"""
        if str(self.status) in ("done", "cancelled"):
            return False
        return bool(self.due_date < timezone.localdate())
