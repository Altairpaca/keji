"""保单模型（规格 §4.5 / REQ-POL-001）。

保单为高价值业务对象，继承软删除（ADR-006）；状态字段的合法迁移图由
apps/policies/services/policies.py 的 STATUS_TRANSITIONS 统一定义。
"""

from decimal import Decimal

from django.conf import settings
from django.db import models

from apps.core.models.base import SoftDeleteModel, TimeStampedModel, UUIDModel
from apps.customers.models import Customer


class Policy(TimeStampedModel, UUIDModel, SoftDeleteModel):
    """保单。"""

    class Status(models.TextChoices):
        ACTIVE = "active", "正常有效"
        PAYING = "paying", "缴费中"
        PAID_UP = "paid_up", "已缴清"
        LAPSED = "lapsed", "失效"
        REINSTATING = "reinstating", "复效处理中"
        SURRENDERED = "surrendered", "退保"
        TERMINATED = "terminated", "解约"
        MATURED = "matured", "满期"
        CLAIM_CLOSED = "claim_closed", "理赔结案"
        STATUS_PENDING = "status_pending", "状态待核实"

    class PaymentFrequency(models.TextChoices):
        MONTHLY = "monthly", "月缴"
        QUARTERLY = "quarterly", "季缴"
        SEMI_ANNUAL = "semi_annual", "半年缴"
        ANNUAL = "annual", "年缴"
        ONCE = "once", "趸缴"

    # 保单信息
    insurer = models.CharField(max_length=100, verbose_name="保险公司")
    name = models.CharField(max_length=200, verbose_name="保单名称")
    policy_no = models.CharField(max_length=100, db_index=True, unique=True, verbose_name="保单号")
    policyholder = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name="held_policies",
        verbose_name="投保人",
    )
    insured = models.ForeignKey(
        Customer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="insured_policies",
        verbose_name="被保险人",
    )
    # 险种与保障
    insurance_type = models.CharField(max_length=100, blank=True, verbose_name="险种")
    main_coverage = models.CharField(max_length=200, blank=True, verbose_name="主险")
    rider_note = models.TextField(blank=True, verbose_name="附加险说明")
    application_date = models.DateField(null=True, blank=True, verbose_name="投保日期")
    effective_date = models.DateField(null=True, blank=True, verbose_name="生效日期")
    # 缴费与保障期
    payment_term = models.CharField(max_length=50, blank=True, verbose_name="缴费期限")
    coverage_term = models.CharField(max_length=50, blank=True, verbose_name="保障期限")
    payment_frequency = models.CharField(
        max_length=20,
        choices=PaymentFrequency.choices,
        default=PaymentFrequency.ANNUAL,
        blank=True,
        verbose_name="缴费频率",
    )
    premium_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0"), verbose_name="每期保费"
    )
    last_paid_batch = models.DateField(null=True, blank=True, verbose_name="最后已缴批次")
    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_index=True,
        verbose_name="状态",
    )
    remark = models.TextField(blank=True, verbose_name="备注")
    # 归属
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="policies",
        verbose_name="负责人",
    )

    class Meta:
        verbose_name = "保单"
        verbose_name_plural = "保单"

    def __str__(self) -> str:
        return f"{self.insurer} {self.name}"
