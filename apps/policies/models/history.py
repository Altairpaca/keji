"""保单状态历史模型（规格 §4.5 / REQ-POL-001）。

append-only 记录：不继承软删除，任何一次状态变更都留下不可变痕迹，
用于时间线聚合（REQ-ACT-003）。
"""

from django.conf import settings
from django.db import models

from apps.core.models.base import TimeStampedModel, UUIDModel


class PolicyStatusHistory(TimeStampedModel, UUIDModel):
    """保单状态变更历史。"""

    policy = models.ForeignKey(
        "policies.Policy",
        on_delete=models.CASCADE,
        related_name="status_history",
        verbose_name="保单",
    )
    from_status = models.CharField(max_length=30, blank=True, verbose_name="原状态")
    to_status = models.CharField(max_length=30, verbose_name="新状态")
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="操作人",
    )
    note = models.CharField(max_length=200, blank=True, verbose_name="备注")

    class Meta:
        verbose_name = "保单状态历史"
        verbose_name_plural = "保单状态历史"

    def __str__(self) -> str:
        return f"{self.policy_id}: {self.from_status}→{self.to_status}"
