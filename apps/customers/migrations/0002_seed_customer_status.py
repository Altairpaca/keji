"""客户状态种子（规格 §6 / REQ-CUST-002 的 15 个默认值）。

幂等：已存在的同名状态跳过；可回滚。顺序即 sort_order（0-14）。
"""

from typing import Any

from django.db import migrations

DEFAULT_CUSTOMER_STATUSES = [
    "待首次联系",
    "电话未接",
    "已加微信",
    "已联系",
    "等待回复",
    "已预约",
    "已见面",
    "多次失约",
    "暂时无需求",
    "保单服务中",
    "理赔处理中",
    "长期维护",
    "明确拒绝",
    "暂停联系",
    "已结案",
]


def seed_customer_statuses(apps: Any, schema_editor: Any) -> None:
    """插入 15 个默认状态；已存在（同 name）则跳过。

    历史模型不含抽象基类的自定义 manager（SoftDeleteManager），
    ``objects`` 为普通 Manager，不叠加软删过滤。
    """
    customer_status = apps.get_model("customers", "CustomerStatus")
    for sort_order, name in enumerate(DEFAULT_CUSTOMER_STATUSES):
        customer_status.objects.get_or_create(
            name=name,
            defaults={
                "sort_order": sort_order,
                "is_active": True,
                "is_system": True,
            },
        )


def unseed_customer_statuses(apps: Any, schema_editor: Any) -> None:
    """回滚：仅删除 is_system 标记的默认状态，保留管理员自定义。"""
    customer_status = apps.get_model("customers", "CustomerStatus")
    customer_status.objects.filter(
        name__in=DEFAULT_CUSTOMER_STATUSES, is_system=True
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("customers", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_customer_statuses, unseed_customer_statuses),
    ]
