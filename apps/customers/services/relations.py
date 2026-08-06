"""customers 关系服务层（规格 §7 / REQ-REL-001）。

视图保持薄，关系业务规则全部经本模块进出：
- create_relation：from≠to、custom 必填 label、重复活跃关系拒绝；
- get_relations / related_customers：双向可见查询（单向存储、反向靠查询，避免双写）；
- delete_relation / restore_relation：软删 / 恢复。

多写操作在服务层声明 transaction.atomic 事务边界。
"""

from django.db import transaction
from django.db.models import Q, QuerySet

from apps.customers.models import Customer, CustomerRelation


def create_relation(
    *,
    from_customer: Customer,
    to_customer: Customer,
    relation_type: str,
    custom_label: str = "",
    note: str = "",
) -> CustomerRelation:
    """创建客户关系并校验：自环、未知类型、custom 缺 label、重复活跃关系。

    重复校验先做存在性检查抛出 ValueError（可读消息），数据库层
    ``uniq_active_relation`` 唯一约束作为兜底（ADR-006 下不覆盖软删记录）。
    """
    if from_customer.pk == to_customer.pk:
        raise ValueError("关系双方不能是同一客户")
    if relation_type not in CustomerRelation.RelationType.values:
        raise ValueError(f"未知关系类型：{relation_type}")

    cleaned_label = custom_label.strip()
    # TextChoices 成员在 mypy 下会被推断为 tuple（无 django-stubs），故与字面值比较。
    if relation_type == "custom" and not cleaned_label:
        raise ValueError("自定义关系必须填写关系名称")

    # objects 自动排除已删除，存在即活跃重复。
    if CustomerRelation.objects.filter(
        from_customer=from_customer,
        to_customer=to_customer,
        relation_type=relation_type,
    ).exists():
        raise ValueError("该客户间已存在相同类型的关系")

    cleaned_note = note.strip() if note else ""
    with transaction.atomic():
        relation: CustomerRelation = CustomerRelation.objects.create(
            from_customer=from_customer,
            to_customer=to_customer,
            relation_type=relation_type,
            custom_label=cleaned_label,
            note=cleaned_note,
        )
    return relation


def get_relations(customer: Customer) -> QuerySet:
    """该客户的出 + 入关系（Q 合并，排除自己循环）。

    已删除记录由 ``objects`` 管理器自动过滤；不做反向复制，反向靠查询可见。
    """
    return CustomerRelation.objects.filter(
        Q(from_customer=customer) | Q(to_customer=customer)
    ).exclude(from_customer=customer, to_customer=customer)


def related_customers(customer: Customer) -> QuerySet:
    """去重后的关联客户（关系另一端；供关系图 / 摘要使用）。

    出向关系取 to_customer，入向关系取 from_customer；已删除客户由
    ``Customer.objects`` 自动过滤。
    """
    relations = get_relations(customer)
    outgoing_ids = relations.filter(from_customer=customer).values_list("to_customer_id", flat=True)
    incoming_ids = relations.filter(to_customer=customer).values_list("from_customer_id", flat=True)
    return Customer.objects.filter(Q(pk__in=outgoing_ids) | Q(pk__in=incoming_ids)).distinct()


def delete_relation(relation: CustomerRelation) -> CustomerRelation:
    """软删除关系（ADR-006 第 1 级）。"""
    return relation.soft_delete()


def restore_relation(relation: CustomerRelation) -> CustomerRelation:
    """恢复软删除的关系。"""
    return relation.restore()
