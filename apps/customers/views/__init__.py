"""customers 视图包。

T4.3 关系视图见 apps.customers.views.relations；客户主视图由 T4.2 追加。
"""

from apps.customers.views.customers import (
    customer_create,
    customer_delete,
    customer_detail,
    customer_edit,
    customer_list,
    customer_restore,
)

__all__ = [
    "customer_create",
    "customer_delete",
    "customer_detail",
    "customer_edit",
    "customer_list",
    "customer_restore",
]
