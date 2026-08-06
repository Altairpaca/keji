"""理赔案件模型（规格 §12 / REQ-CLAIM-001）。

理赔案件聚合理赔全生命周期：客户咨询 → 资料收集 → 报案 → 审核 → 结案。
状态迁移图由 apps/claims/services/claims.py 的 CLAIM_STATUS_TRANSITIONS
统一定义；此处仅声明 choices 常量与字段。
"""

from django.conf import settings
from django.db import models

from apps.core.models.base import SoftDeleteModel, TimeStampedModel, UUIDModel
from apps.customers.models import Customer
from apps.policies.models import Policy

#: 理赔类型常量（规格 §12）：medical 医疗 / accident 意外 / critical_illness 重疾 /
#: death 身故 / annuity 年金 / other 其他。claim_type 与材料模板共用。
CLAIM_TYPES: list[tuple[str, str]] = [
    ("medical", "医疗"),
    ("accident", "意外"),
    ("critical_illness", "重疾"),
    ("death", "身故"),
    ("annuity", "年金"),
    ("other", "其他"),
]

#: 理赔状态 14 态（规格 §12），default consultation 客户咨询。
CLAIM_STATUS_CHOICES: list[tuple[str, str]] = [
    ("consultation", "客户咨询"),
    ("waiting_materials", "等待客户资料"),
    ("collecting_materials", "资料收集中"),
    ("materials_pending_review", "资料待核对"),
    ("materials_incomplete", "资料不完整"),
    ("reported", "已报案"),
    ("submitted", "已提交"),
    ("insurer_reviewing", "保险公司审核中"),
    ("requested_supplement", "要求补充材料"),
    ("approved", "理赔通过"),
    ("partial_paid", "部分赔付"),
    ("rejected", "拒赔"),
    ("disputing", "客户申诉"),
    ("closed", "已结案"),
]


class ClaimCase(TimeStampedModel, UUIDModel, SoftDeleteModel):
    """理赔案件。"""

    name = models.CharField(max_length=200, verbose_name="案件名称")
    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name="claims",
        verbose_name="客户",
    )
    # 可空：客户咨询阶段可能尚无对应保单。
    policy = models.ForeignKey(
        Policy,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="claims",
        verbose_name="关联保单",
    )
    claim_type = models.CharField(
        max_length=100,
        choices=CLAIM_TYPES,
        default="other",
        blank=True,
        verbose_name="理赔类型",
    )
    incident_date = models.DateField(null=True, blank=True, verbose_name="出险日期")
    report_date = models.DateField(null=True, blank=True, verbose_name="报案日期")
    status = models.CharField(
        max_length=30,
        choices=CLAIM_STATUS_CHOICES,
        default="consultation",
        verbose_name="状态",
    )
    estimated_amount = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, verbose_name="预估金额"
    )
    actual_paid_amount = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, verbose_name="实际赔付金额"
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="claims",
        verbose_name="负责人",
    )
    description = models.TextField(blank=True, verbose_name="案件说明")
    closed_at = models.DateTimeField(null=True, blank=True, verbose_name="结案时间")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "理赔案件"
        verbose_name_plural = "理赔案件"

    def __str__(self) -> str:
        return str(self.name)
