"""理赔材料模型（规格 §12 / REQ-CLAIM-002）。

材料挂靠在理赔案件下，按材料项逐项核对是否齐备；状态迁移图由
apps/claims/services/claims.py 的 MATERIAL_STATUS_TRANSITIONS 统一定义。
"""

from django.conf import settings
from django.db import models

from apps.core.models.base import SoftDeleteModel, TimeStampedModel, UUIDModel

#: 材料状态 6 态（规格 §12），default not_submitted 未提交。
MATERIAL_STATUS_CHOICES: list[tuple[str, str]] = [
    ("not_submitted", "未提交"),
    ("submitted", "已提交"),
    ("pending_review", "待核对"),
    ("checked", "已核对"),
    ("needs_supplement", "需要补充"),
    ("not_applicable", "不适用"),
]


class ClaimMaterial(TimeStampedModel, UUIDModel, SoftDeleteModel):
    """理赔材料：一案件多材料，逐项核对。"""

    claim = models.ForeignKey(
        "claims.ClaimCase",
        on_delete=models.CASCADE,
        related_name="materials",
        verbose_name="理赔案件",
    )
    name = models.CharField(max_length=200, verbose_name="材料名称")
    is_required = models.BooleanField(default=True, verbose_name="必需材料")
    status = models.CharField(
        max_length=20,
        choices=MATERIAL_STATUS_CHOICES,
        default="not_submitted",
        verbose_name="状态",
    )
    document = models.ForeignKey(
        "documents.Document",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="claim_materials",
        verbose_name="关联文件",
    )
    note = models.CharField(max_length=200, blank=True, verbose_name="备注")
    checked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="checked_materials",
        verbose_name="核对人",
    )
    checked_at = models.DateTimeField(null=True, blank=True, verbose_name="核对时间")

    class Meta:
        ordering = ["created_at"]
        verbose_name = "理赔材料"
        verbose_name_plural = "理赔材料"

    def __str__(self) -> str:
        return f"{self.claim}: {self.name}"
