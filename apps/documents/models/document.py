"""文件元数据模型（规格 §9 / REQ-DOC-001，data-model.md documents 节）。

DB 只存元数据：存储键、原始文件名、SHA-256、MIME、大小等；二进制内容
经 storage 层（ADR-002）落盘。原始文件名仅用于展示与下载还原，绝不进入
存储键（ADR-005）。一份文件可同时关联多个客户与相册（M2M，只存一份）。
"""

from django.conf import settings
from django.db import models

from apps.core.models.base import SoftDeleteModel, TimeStampedModel, UUIDModel
from apps.customers.models import Customer
from apps.documents.models.album import Album


class Document(TimeStampedModel, UUIDModel, SoftDeleteModel):
    """文件实体：物理文件经 storage 层管理，本表保存全量元数据。"""

    class Sensitivity(models.TextChoices):
        NORMAL = "normal", "普通"
        SENSITIVE = "sensitive", "敏感"
        HIGHLY_SENSITIVE = "highly_sensitive", "高敏感"

    class CheckStatus(models.TextChoices):
        UNCHECKED = "unchecked", "未核对"
        CHECKED = "checked", "已核对"
        NEEDS_SUPPLEMENT = "needs_supplement", "需要补充"

    original_name = models.CharField(max_length=255, verbose_name="原始文件名")
    storage_key = models.CharField(max_length=255, unique=True, verbose_name="存储键")
    mime_type = models.CharField(max_length=100, verbose_name="MIME 类型")
    size = models.BigIntegerField(verbose_name="文件大小")
    sha256 = models.CharField(max_length=64, db_index=True, verbose_name="SHA-256")
    taken_at = models.DateTimeField(null=True, blank=True, verbose_name="拍摄时间")
    title = models.CharField(max_length=255, blank=True, verbose_name="标题")
    note = models.TextField(blank=True, verbose_name="备注")
    sensitivity = models.CharField(
        max_length=20,
        choices=Sensitivity.choices,
        default=Sensitivity.NORMAL,
        verbose_name="敏感级别",
    )
    is_important = models.BooleanField(default=False, verbose_name="重要标记")
    check_status = models.CharField(
        max_length=20,
        choices=CheckStatus.choices,
        default=CheckStatus.UNCHECKED,
        verbose_name="核对状态",
    )
    source = models.CharField(max_length=50, blank=True, verbose_name="来源")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documents",
        verbose_name="上传者",
    )
    customers = models.ManyToManyField(
        Customer, blank=True, related_name="documents", verbose_name="关联客户"
    )
    albums = models.ManyToManyField(
        Album, blank=True, related_name="documents", verbose_name="关联相册"
    )
    policies = models.ManyToManyField(
        "policies.Policy",
        blank=True,
        related_name="documents",
        verbose_name="关联保单",
    )
    thumb_storage_key = models.CharField(max_length=255, blank=True, verbose_name="缩略图存储键")
    thumb_mime = models.CharField(max_length=50, blank=True, verbose_name="缩略图 MIME")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "文件"
        verbose_name_plural = "文件"
        # 注意：sha256 不加唯一约束——重复文件分组功能（T6.3）依赖多个活动
        # 记录共享同一 sha256；并发去重由上传服务经 advisory 锁串行化保障。

    def __str__(self) -> str:
        return str(self.original_name)
