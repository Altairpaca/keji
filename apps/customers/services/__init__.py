"""customers 服务包。"""

from apps.customers.services.customers import (
    assign_tags,
    create_customer,
    find_duplicates,
    restore_customer,
    soft_delete_customer,
    update_customer,
)
from apps.customers.services.relations import (
    create_relation,
    delete_relation,
    get_relations,
    related_customers,
    restore_relation,
)

__all__ = [
    "assign_tags",
    "create_customer",
    "create_relation",
    "delete_relation",
    "find_duplicates",
    "get_relations",
    "related_customers",
    "restore_customer",
    "restore_relation",
    "soft_delete_customer",
    "update_customer",
]
