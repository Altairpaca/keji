"""客户档案（规格 §6 / REQ-CUST-001）。

字段以规格 §6 为准：基本信息、联系信息、跟进日期、状态/优先级/沟通偏好、
备注、创建者/负责人、标签 M2M。业务校验（birth_date/age_note 至少其一、
状态缺省取值）在服务层，见 apps/customers/services/customers.py。
"""

from django.conf import settings
from django.db import models

from apps.core.models.base import SoftDeleteModel, TimeStampedModel, UUIDModel
from apps.customers.models.status import CustomerStatus
from apps.customers.models.tag import Tag


class Customer(TimeStampedModel, UUIDModel, SoftDeleteModel):
    """客户档案。"""

    class Gender(models.TextChoices):
        MALE = "男", "男"
        FEMALE = "女", "女"
        UNKNOWN = "未知", "未知"

    class Priority(models.TextChoices):
        LOW = "低", "低"
        MEDIUM = "中", "中"
        HIGH = "高", "高"

    # 基本信息
    name = models.CharField(max_length=100, db_index=True, verbose_name="姓名")
    gender = models.CharField(
        max_length=10, choices=Gender.choices, default=Gender.UNKNOWN, verbose_name="性别"
    )
    birth_date = models.DateField(null=True, blank=True, verbose_name="出生日期")
    age_note = models.CharField(max_length=100, blank=True, verbose_name="年龄说明")
    # 联系信息
    phone = models.CharField(max_length=32, blank=True, db_index=True, verbose_name="手机号")
    wechat_nickname = models.CharField(
        max_length=100, blank=True, db_index=True, verbose_name="微信昵称"
    )
    # 背景信息
    region = models.CharField(max_length=100, blank=True, verbose_name="地区")
    occupation = models.CharField(max_length=100, blank=True, verbose_name="职业")
    marital_family_note = models.TextField(blank=True, verbose_name="婚姻和家庭说明")
    source = models.CharField(max_length=100, blank=True, verbose_name="客户来源")
    previous_agent = models.CharField(max_length=100, blank=True, verbose_name="原服务人员")
    # 跟进日期
    first_contact_date = models.DateField(null=True, blank=True, verbose_name="首次接触日期")
    last_contact_date = models.DateField(null=True, blank=True, verbose_name="最后联系日期")
    next_followup_date = models.DateField(
        null=True, blank=True, db_index=True, verbose_name="下次跟进日期"
    )
    # 状态与偏好
    status = models.ForeignKey(
        CustomerStatus,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="customers",
        verbose_name="客户状态",
    )
    priority = models.CharField(
        max_length=10, choices=Priority.choices, default=Priority.MEDIUM, verbose_name="优先级"
    )
    communication_preference = models.CharField(max_length=50, blank=True, verbose_name="沟通偏好")
    notes = models.TextField(blank=True, verbose_name="一般备注")
    # 归属
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="创建者",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="owned_customers",
        verbose_name="负责人",
    )
    # 标签
    tags = models.ManyToManyField(Tag, blank=True, related_name="customers", verbose_name="标签")

    class Meta:
        ordering = ["name"]
        verbose_name = "客户"
        verbose_name_plural = "客户"

    def __str__(self) -> str:
        return str(self.name)
