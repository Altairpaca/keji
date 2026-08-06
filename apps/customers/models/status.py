"""客户状态枚举（规格 §6 / REQ-CUST-002）。

独立模型而非硬编码 choices：管理员可新增、重命名、排序、停用。
is_system 标记系统默认值，防止误删（删除保护由后续管理/服务层实施）。
"""

from django.db import models

from apps.core.models.base import SoftDeleteModel, TimeStampedModel, UUIDModel


class CustomerStatus(TimeStampedModel, UUIDModel, SoftDeleteModel):
    """客户状态：名称唯一，按 sort_order 排序，is_active 控制是否可选。"""

    name = models.CharField(max_length=50, unique=True, verbose_name="状态名称")
    is_active = models.BooleanField(default=True, verbose_name="启用")
    sort_order = models.PositiveSmallIntegerField(default=0, verbose_name="排序")
    is_system = models.BooleanField(default=False, verbose_name="系统默认值")

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name = "客户状态"
        verbose_name_plural = "客户状态"

    def __str__(self) -> str:
        return str(self.name)
