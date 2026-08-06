"""审计日志模型（规格 §17 / §18，T10.2，蓝图参考 mp-crm SecurityAuditLog）。

记录「谁在何时对哪个对象做了什么动作、结果与上下文」，不随业务对象删除而消失：
本模型不继承 SoftDeleteModel，delete() 即物理删除；审计记录本身的保留与清理
由独立的清理命令承担（本任务不实现）。

detail 上下文绝不记录完整敏感数据：密码 / 密钥 / 身份证 / 银行卡等一律经
``apps.audit.services.record_audit`` 脱敏后再落库。
"""

from django.conf import settings
from django.db import models

from apps.core.models.base import TimeStampedModel, UUIDModel


class AuditLog(UUIDModel, TimeStampedModel):
    """审计日志条目。"""

    class Result(models.TextChoices):
        SUCCESS = "success", "成功"
        FAILURE = "failure", "失败"
        PARTIAL = "partial", "部分成功"

    #: 动作命名约定：`<domain>.<verb>`，如 customer.soft_delete /
    #: document.permanent_delete / policy.change_status / claim.change_status /
    #: claim.material_status / user.create / user.update / user.toggle_active /
    #: export / backup。
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
        verbose_name="操作用户",
    )
    action = models.CharField(max_length=50, db_index=True, verbose_name="动作")
    object_type = models.CharField(
        max_length=100, blank=True, verbose_name="对象类型（模型 label）"
    )
    object_pk = models.CharField(max_length=64, blank=True, verbose_name="对象 ID")
    target_label = models.CharField(max_length=200, blank=True, verbose_name="对象名称（人类可读）")
    result = models.CharField(
        max_length=20,
        choices=Result.choices,
        default=Result.SUCCESS,
        verbose_name="结果",
    )
    detail = models.JSONField(default=dict, blank=True, verbose_name="上下文")
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name="IP 地址")
    user_agent = models.CharField(max_length=255, blank=True, verbose_name="User-Agent")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "审计日志"
        verbose_name_plural = "审计日志"
        indexes = [
            models.Index(fields=["actor", "created_at"]),
            models.Index(fields=["action", "created_at"]),
            models.Index(fields=["object_type", "object_pk"]),
        ]

    def __str__(self) -> str:
        return f"{self.actor} {self.action} @ {self.created_at}"
