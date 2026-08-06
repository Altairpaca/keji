"""工作事件模型（规格 §4.3 / REQ-ACT-001、REQ-ACT-002）。

- event_type 九种类型（REQ-ACT-001 验收：九种全部可选）；
- customer 必填，CASCADE（事件从属于客户档案）；
- occurred_at 默认当前时间并加索引（时间线排序字段）；
- related_policy / related_claim 字段 T7 / T8 再加迁移，本任务不连；
- created_by / owner 记录创建人与负责人（REQ-ACT-002「负责人」）。
"""

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models.base import SoftDeleteModel, TimeStampedModel, UUIDModel


class WorkEvent(TimeStampedModel, UUIDModel, SoftDeleteModel):
    """工作事件：一次跟进、拜访、沟通等客户工作过程的时间点记录。"""

    class EventType(models.TextChoices):
        FIRST_MEETING = "first_meeting", "第一次见面"
        PHONE_CALL = "phone_call", "电话沟通"
        WECHAT = "wechat", "微信沟通"
        POLICY_ORGANIZE = "policy_organize", "保单整理"
        MATERIAL_COLLECTION = "material_collection", "资料收集"
        CLAIM_PROCESS = "claim_process", "理赔处理"
        CUSTOMER_ACTIVITY = "customer_activity", "客户活动"
        HOME_VISIT = "home_visit", "上门服务"
        OTHER = "other", "其他工作过程"

    event_type = models.CharField(
        max_length=32,
        choices=EventType.choices,
        verbose_name="事件类型",
    )
    title = models.CharField(max_length=200, verbose_name="标题")
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.CASCADE,
        related_name="work_events",
        verbose_name="客户",
    )
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True, verbose_name="发生时间")
    summary = models.TextField(blank=True, verbose_name="结论/主要内容")
    # related_policy 占位：T7 连保单后加迁移
    outcome = models.TextField(blank=True, verbose_name="结果")
    next_step = models.TextField(blank=True, verbose_name="下一步")
    next_followup_date = models.DateField(null=True, blank=True, verbose_name="下次跟进日期")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_work_events",
        verbose_name="创建者",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="owned_work_events",
        verbose_name="负责人",
    )

    class Meta:
        ordering = ["-occurred_at"]
        verbose_name = "工作事件"
        verbose_name_plural = "工作事件"

    def __str__(self) -> str:
        return str(self.title)
