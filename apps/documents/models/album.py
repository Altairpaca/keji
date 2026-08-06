"""相册（规格 §9 / REQ-DOC-002）：按类别归置文件，可自定义类别扩展。

``category`` 使用默认 10 类下拉；超出默认类别时用 ``custom_category``
自由填写。``customer`` 可空——空表示全局相册（未分类文件的归置处）。
"""

from django.db import models

from apps.core.models.base import SoftDeleteModel, TimeStampedModel, UUIDModel

# 默认类别常量（十种，REQ-DOC-002）：上传时可选项，也供模板与筛选复用。
ALBUM_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("id_docs", "客户证件"),
    ("policy_docs", "保单资料"),
    ("claim_docs", "理赔资料"),
    ("hospital_docs", "医院资料"),
    ("chat_screenshots", "沟通截图"),
    ("meeting_photos", "见面照片"),
    ("event_photos", "活动照片"),
    ("signature_docs", "签字资料"),
    ("payment_receipts", "缴费凭证"),
    ("other", "其他资料"),
)


class Album(TimeStampedModel, UUIDModel, SoftDeleteModel):
    """相册：按类别把文件归置成组，可关联单个客户或作为全局相册。"""

    name = models.CharField(max_length=100, verbose_name="相册名")
    category = models.CharField(
        max_length=32,
        choices=ALBUM_CATEGORIES,
        default="other",
        verbose_name="类别",
    )
    custom_category = models.CharField(max_length=100, blank=True, verbose_name="自定义类别")
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="albums",
        verbose_name="关联客户",
    )
    description = models.TextField(blank=True, verbose_name="说明")

    class Meta:
        ordering = ["name"]
        verbose_name = "相册"
        verbose_name_plural = "相册"

    def __str__(self) -> str:
        return str(self.name)
