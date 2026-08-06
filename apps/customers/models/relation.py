"""客户间关系模型（规格 §7 / REQ-REL-001）。

有向记录（from → to），但查询层面双向可见（get_relations 同时返回出向与
入向），不自动创建反向记录，避免双写。业务校验（from≠to、custom 必填
label、重复活跃关系拒绝）在服务层 relations.py，见 data-model 客户关系段。
"""

from django.db import models
from django.db.models import Q

from apps.core.models.base import SoftDeleteModel, TimeStampedModel, UUIDModel
from apps.customers.models.customer import Customer


class CustomerRelation(TimeStampedModel, UUIDModel, SoftDeleteModel):
    """客户间关系：方向（from_customer → to_customer）+ 类型 + 自定义名称 + 备注。"""

    class RelationType(models.TextChoices):
        SPOUSE = "spouse", "配偶"
        PARENT_CHILD = "parent_child", "父母子女"
        FAMILY = "family", "其他家庭成员"
        REFERRER = "referrer", "介绍人"
        SAME_HOUSEHOLD = "same_household", "同一家庭"
        CUSTOM = "custom", "其他自定义关系"

    from_customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name="outgoing_relations",
        verbose_name="关系发起方",
    )
    to_customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name="incoming_relations",
        verbose_name="关系对方",
    )
    relation_type = models.CharField(
        max_length=20, choices=RelationType.choices, verbose_name="关系类型"
    )
    custom_label = models.CharField(max_length=50, blank=True, verbose_name="自定义关系名称")
    note = models.TextField(blank=True, verbose_name="备注")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "客户关系"
        verbose_name_plural = "客户关系"
        constraints = [
            models.UniqueConstraint(
                fields=["from_customer", "to_customer", "relation_type"],
                condition=~Q(is_deleted=True),
                name="uniq_active_relation",
                violation_error_message="同方向同类型的关系已存在",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.from_customer} → {self.to_customer} ({self.get_relation_type_display()})"
