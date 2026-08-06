"""沟通记录模型（规格 §4.7 / REQ-COM-001）。

- channel 九种沟通方式，quick_result 十种快捷结果（REQ-COM-001 验收）；
- quick_result 可留空（不是每次沟通都有明确快捷结果）；
- recorded_by 记录登记人；
- 待办联动（REQ-COM-002）由 T5.3 并行任务实现，本任务只记录字段。
"""

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models.base import SoftDeleteModel, TimeStampedModel, UUIDModel


class CommunicationRecord(TimeStampedModel, UUIDModel, SoftDeleteModel):
    """一次沟通记录：电话 / 微信 / 见面等，含快捷结果与下一步计划。"""

    class Channel(models.TextChoices):
        PHONE = "phone", "电话"
        WECHAT = "wechat", "微信"
        MEETING = "meeting", "见面"
        COMPANY_ACTIVITY = "company_activity", "公司活动"
        HOME_VISIT = "home_visit", "上门服务"
        CUSTOMER_VISIT = "customer_visit", "客户来访"
        VIDEO_CALL = "video_call", "视频通话"
        SMS = "sms", "短信"
        OTHER = "other", "其他"

    class QuickResult(models.TextChoices):
        MISSED = "missed", "未接"
        HUNG_UP = "hung_up", "挂断"
        POWER_OFF = "power_off", "关机"
        EMPTY_NUMBER = "empty_number", "空号"
        DECLINED = "declined", "接听但拒绝"
        WANTS_WECHAT = "wants_wechat", "愿意微信联系"
        WANTS_MEETING = "wants_meeting", "愿意见面"
        TIME_UNCERTAIN = "time_uncertain", "时间不确定"
        CALL_LATER = "call_later", "要求稍后联系"
        NOT_NEEDED = "not_needed", "明确不需要"

    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.CASCADE,
        related_name="communications",
        verbose_name="客户",
    )
    channel = models.CharField(max_length=32, choices=Channel.choices, verbose_name="沟通方式")
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True, verbose_name="发生时间")
    quick_result = models.CharField(
        max_length=32,
        choices=QuickResult.choices,
        blank=True,
        default="",
        verbose_name="快捷结果",
    )
    content = models.TextField(blank=True, verbose_name="主要内容")
    customer_feedback = models.TextField(blank=True, verbose_name="客户反馈")
    next_plan = models.TextField(blank=True, verbose_name="下一步计划")
    next_followup_date = models.DateField(null=True, blank=True, verbose_name="下次跟进日期")
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recorded_communications",
        verbose_name="记录人",
    )

    class Meta:
        ordering = ["-occurred_at"]
        verbose_name = "沟通记录"
        verbose_name_plural = "沟通记录"

    def __str__(self) -> str:
        return f"{self.customer} {self.get_channel_display()}"
