"""customers 服务包。"""

from apps.customers.services.customers import (
    assign_tags,
    create_customer,
    find_duplicates,
    restore_customer,
    soft_delete_customer,
    update_customer,
)

__all__ = [
    "assign_tags",
    "create_customer",
    "find_duplicates",
    "restore_customer",
    "soft_delete_customer",
    "update_customer",
]
