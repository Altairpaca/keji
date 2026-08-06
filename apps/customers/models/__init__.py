"""customers 模型包：CustomerStatus、Tag、Customer、CustomerRelation（规格 §6/§7）。"""

from apps.customers.models.customer import Customer
from apps.customers.models.relation import CustomerRelation
from apps.customers.models.status import CustomerStatus
from apps.customers.models.tag import Tag

__all__ = ["Customer", "CustomerRelation", "CustomerStatus", "Tag"]
