"""SavedView：通用保存视图（core 数据模型，T9.3 使用）。"""

from django.db import models

from apps.accounts.models import User
from apps.core.models.base import TimeStampedModel, UUIDModel


class SavedView(UUIDModel, TimeStampedModel):
    """保存的列表视图：记录过滤/排序等查询参数，按 owner 隔离。"""

    name = models.CharField(max_length=200, verbose_name="视图名")
    app_label = models.CharField(max_length=100, verbose_name="应用标识")
    model_name = models.CharField(max_length=100, verbose_name="模型名")
    filters = models.JSONField(default=dict, blank=True, verbose_name="过滤条件")
    sorts = models.JSONField(default=list, blank=True, verbose_name="排序条件")
    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="saved_views",
        verbose_name="所有者",
    )
    is_default = models.BooleanField(default=False, verbose_name="默认视图")
    is_shared = models.BooleanField(default=False, verbose_name="共享")

    class Meta:
        verbose_name = "保存视图"
        verbose_name_plural = "保存视图"
        indexes = [
            models.Index(fields=["owner", "app_label", "model_name"]),
        ]

    def __str__(self) -> str:
        return str(self.name)
