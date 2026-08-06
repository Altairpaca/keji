"""SystemSetting：系统设置键值存储（core 数据模型）。"""

from django.db import models

from apps.accounts.models import User
from apps.core.models.base import TimeStampedModel, UUIDModel


class SystemSetting(UUIDModel, TimeStampedModel):
    """系统设置：key 唯一，value 存任意 JSON 结构（data-model core 表）。"""

    key = models.CharField(max_length=200, unique=True, verbose_name="设置键")
    value = models.JSONField(default=dict, verbose_name="设置值")
    label = models.CharField(max_length=200, blank=True, default="", verbose_name="显示名")
    description = models.TextField(blank=True, default="", verbose_name="说明")
    updated_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        verbose_name="最后更新人",
    )

    class Meta:
        verbose_name = "系统设置"
        verbose_name_plural = "系统设置"

    def __str__(self) -> str:
        return str(self.key)
