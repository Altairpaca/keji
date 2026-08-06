"""客户标签（规格 §6）。

Tag 为独立软删除模型，颜色以 hex 值存储；标签管理视图在后续里程碑实现。
"""

from django.db import models

from apps.core.models.base import SoftDeleteModel, TimeStampedModel, UUIDModel


class Tag(TimeStampedModel, UUIDModel, SoftDeleteModel):
    """标签：名称唯一，颜色 hex，描述可选。"""

    name = models.CharField(max_length=50, unique=True, verbose_name="标签名称")
    color = models.CharField(max_length=7, default="#64748b", verbose_name="颜色")
    description = models.CharField(max_length=200, blank=True, verbose_name="描述")

    class Meta:
        ordering = ["name"]
        verbose_name = "标签"
        verbose_name_plural = "标签"

    def __str__(self) -> str:
        return str(self.name)
