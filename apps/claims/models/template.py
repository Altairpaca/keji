"""材料清单模板模型（规格 §12 / REQ-CLAIM-002）。

按理赔类型预设常用材料，建案后可一键实例化出 ClaimMaterial 清单。
(claim_type, name) 唯一约束带 is_deleted=False 条件：软删除后同名可重建。
"""

from django.db import models

from apps.claims.models.case import CLAIM_TYPES
from apps.core.models.base import SoftDeleteModel, TimeStampedModel, UUIDModel


class ClaimMaterialTemplate(TimeStampedModel, UUIDModel, SoftDeleteModel):
    """材料清单模板：按理赔类型预设材料项。"""

    name = models.CharField(max_length=100, verbose_name="材料名称")
    claim_type = models.CharField(
        max_length=100,
        choices=CLAIM_TYPES,
        default="other",
        verbose_name="理赔类型",
    )
    is_required = models.BooleanField(default=True, verbose_name="必需材料")
    sort_order = models.IntegerField(default=0, verbose_name="排序")

    class Meta:
        ordering = ["claim_type", "sort_order", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["claim_type", "name"],
                condition=~models.Q(is_deleted=True),
                name="uniq_claim_material_template_type_name_active",
            )
        ]
        verbose_name = "材料清单模板"
        verbose_name_plural = "材料清单模板"

    def __str__(self) -> str:
        return str(self.name)
