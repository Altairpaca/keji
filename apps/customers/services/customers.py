"""customers 服务层：客户创建、更新、软删、标签、重复检测（T4.1）。

视图保持薄，业务逻辑全部经本模块进出；多写操作在服务层声明
transaction.atomic 事务边界。
"""

from django.db import transaction
from django.db.models import QuerySet

from apps.accounts.models import User
from apps.audit.services import record_audit
from apps.customers.models import Customer, CustomerStatus, Tag


def _default_status() -> CustomerStatus | None:
    """取 sort_order 最小且激活的状态作为新建客户默认状态。"""
    status: CustomerStatus | None = (
        CustomerStatus.objects.filter(is_active=True).order_by("sort_order", "name").first()
    )
    return status


def create_customer(
    *,
    name: str,
    owner: User,
    created_by: User,
    **kwargs: object,
) -> Customer:
    """创建客户：校验 name 非空、birth_date/age_note 至少其一；status 缺省取默认。"""
    cleaned_name = name.strip()
    if not cleaned_name:
        raise ValueError("客户姓名不能为空")
    if kwargs.get("birth_date") is None and not kwargs.get("age_note"):
        raise ValueError("出生日期与年龄说明至少填写其一")

    status = kwargs.pop("status", None)
    if status is None:
        status = _default_status()

    with transaction.atomic():
        customer: Customer = Customer.objects.create(
            name=cleaned_name,
            owner=owner,
            created_by=created_by,
            status=status,
            **kwargs,
        )
    return customer


def update_customer(customer: Customer, **fields: object) -> Customer:
    """部分更新并保存；未知字段拒绝，避免拼写错误静默失效。"""
    for field, value in fields.items():
        if not hasattr(customer, field):
            raise ValueError(f"未知字段：{field}")
        setattr(customer, field, value)
    customer.save()
    return customer


def soft_delete_customer(customer: Customer, *, actor: User | None = None) -> Customer:
    """软删除客户（ADR-006 第 1 级）；传入 actor 时落审计（规格 §17 / T10.2）。"""
    deleted = customer.soft_delete()
    record_audit(
        actor=actor,
        action="customer.soft_delete",
        object_type=customer._meta.label_lower,
        object_pk=str(customer.pk),
        target_label=customer.name,
    )
    return deleted


def restore_customer(customer: Customer, *, actor: User | None = None) -> Customer:
    """恢复软删除的客户；传入 actor 时落审计（规格 §17 / T10.2）。"""
    restored = customer.restore()
    record_audit(
        actor=actor,
        action="customer.restore",
        object_type=customer._meta.label_lower,
        object_pk=str(customer.pk),
        target_label=customer.name,
    )
    return restored


def assign_tags(customer: Customer, tag_names: list[str]) -> Customer:
    """按名称 get_or_create 标签并整体替换客户标签集。

    空名与纯空白跳过；多写操作包在事务中。
    """
    with transaction.atomic():
        tags: list[Tag] = []
        for raw in tag_names:
            name = raw.strip()
            if not name:
                continue
            tag, _created = Tag.objects.get_or_create(name=name)
            tags.append(tag)
        customer.tags.set(tags)
    return customer


def find_duplicates(phone: str) -> QuerySet:
    """按手机号找未删除的重复客户（重复检测基础，T4.4 完善）。"""
    cleaned = phone.strip()
    if not cleaned:
        return Customer.objects.none()
    return Customer.objects.filter(phone=cleaned)
