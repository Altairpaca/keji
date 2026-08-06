"""customers 重复检测与合并服务（T4.4 / 规格 §16）。

- find_phone_duplicates：按非空手机号分组，同号 ≥2 的组视为重复（排除软删）；
- find_name_duplicates：按「去空格 + 小写」后的姓名分组；
- merge_customers：事务内把 source 合并进 target——标签并集、关系改指
  （CustomerRelation 的 from/to 含 source 的全部替换）、归属空则继承、
  notes 合并注明来源，最后 soft_delete(source)。

返回组形状统一为 ``(组代表, [其余成员])``，组代表即合并时的目标客户。
"""

from collections.abc import Callable

from django.apps import apps
from django.db import transaction
from django.db.models import QuerySet

from apps.customers.models import Customer

# 关系模型由 T4.3 里程碑提供，字段见 data-model.md（from_customer / to_customer）。
_RELATION_MODEL = "CustomerRelation"


def _group_over_duplicates(
    customers: QuerySet[Customer], key_of: Callable[[Customer], str]
) -> list[tuple[Customer, list[Customer]]]:
    """按 key_of(customer) 分组，返回 (代表, [其余])，仅保留成员 ≥2 的组。

    组内顺序即传入 queryset 的顺序（Meta.ordering），代表取首个成员。
    """
    groups: dict[str, list[Customer]] = {}
    for customer in customers:
        key = key_of(customer)
        if not key:
            continue
        groups.setdefault(key, []).append(customer)
    return [(group[0], group[1:]) for group in groups.values() if len(group) > 1]


def find_phone_duplicates(
    queryset: QuerySet[Customer] | None = None,
) -> list[tuple[Customer, list[Customer]]]:
    """按非空手机号找重复客户（默认全库，排除软删）。

    queryset 可选：传入后只在该范围内检测（默认 manager 已排除软删）。
    """
    qs = queryset if queryset is not None else Customer.objects.all()
    customers = qs.filter(phone__gt="").exclude(is_deleted=True).order_by("created_at", "pk")
    return _group_over_duplicates(customers, lambda c: c.phone)


def find_name_duplicates() -> list[tuple[Customer, list[Customer]]]:
    """按「去空格 + 小写」后的姓名找重复客户（排除软删）。"""
    customers = Customer.objects.exclude(is_deleted=True).order_by("created_at", "pk")
    return _group_over_duplicates(
        customers,
        lambda c: "".join(c.name.split()).lower(),
    )


def _merge_tags(target: Customer, source: Customer) -> None:
    """把 source 的标签并入 target（天然去重，M2M 集合语义）。"""
    for tag in source.tags.all():
        target.tags.add(tag)


def _repoint_relations(source: Customer, target: Customer) -> None:
    """把 CustomerRelation 中 from/to 引用 source 的记录全部改指 target。

    独立成函数作为事务回滚测试的桩点；模型由 T4.3 提供，字段
    from_customer / to_customer 见 data-model.md。
    """
    relation_model = apps.get_model("customers", _RELATION_MODEL)
    if relation_model is None:
        return
    relation_model.objects.filter(from_customer=source).update(from_customer=target)
    relation_model.objects.filter(to_customer=source).update(to_customer=target)


def _merge_notes(target: Customer, source: Customer) -> None:
    """把 source 的备注并入 target，以分隔注释标明来源。"""
    source_note = source.notes.strip()
    if not source_note:
        return
    marker = f"（合并自源客户「{source.name}」）"
    if target.notes.strip():
        target.notes = f"{target.notes.rstrip()}\n\n{marker}\n{source_note}"
    else:
        target.notes = f"{marker}\n{source_note}"


def merge_customers(target: Customer, source: Customer) -> Customer:
    """把 source 合并进 target，返回 target。

    事务内依次：标签并集 → 关系改指 → 归属空则继承 → notes 合并 → 软删 source。
    中途任何一步失败整体回滚（source 不会被删）。
    """
    if target.pk == source.pk:
        raise ValueError("目标客户与源客户不能是同一个")
    if target.is_deleted or source.is_deleted:
        raise ValueError("不能合并已删除的客户")

    with transaction.atomic():
        _merge_tags(target, source)
        _repoint_relations(source, target)
        if target.owner is None and source.owner is not None:
            target.owner = source.owner
        if target.created_by is None and source.created_by is not None:
            target.created_by = source.created_by
        _merge_notes(target, source)
        target.save()
        source.soft_delete()
    return target
